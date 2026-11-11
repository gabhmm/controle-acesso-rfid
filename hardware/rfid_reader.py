from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pika

from hardware import config
from server.config import (
    DB_PATH,
    RABBITMQ_DISPOSITIVO,
    RABBITMQ_EXCHANGE,
    RABBITMQ_HOST,
    RABBITMQ_PASS,
    RABBITMQ_PORT,
    RABBITMQ_USER,
    RABBITMQ_VHOST,
)
from server.database import DatabaseRepository
from server.redis_client import RedisClient, redis_client

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [Pi-Hardware] %(message)s",
)
logger = logging.getLogger("rfid.hardware")
logging.getLogger("pika").setLevel(logging.CRITICAL)

BASE_DIR = Path(__file__).resolve().parent
ESTADO_FILE = BASE_DIR / "estado.json"
PENDENTES_FILE = BASE_DIR / "pendentes.jsonl"

MSG_INVASAO = "Acesso negado, tag não cadastrada"

# leitor e atuadores só funcionam na Raspberry (dependem do GPIO e do SPI).
# Em qualquer outra máquina, cai no simulador de teclado.
try:
    from hardware import atuadores, leitor

    HARDWARE_REAL = True
except Exception as exc:
    HARDWARE_REAL = False
    MOTIVO_SEM_HARDWARE = str(exc)

CORES_SIMULADOR = {
    "ENTRADA": "\033[92m[LED VERDE]\033[0m 1 bip curto",
    "SAIDA": "\033[93m[LED AMARELO]\033[0m 2 bips curtos",
    "NEGADO": "\033[93m[LED AMARELO]\033[0m 1 bip longo",
    "INVASAO": "\033[91m[LED VERMELHO PISCANDO]\033[0m 3 bips",
}


class RaspberryPiClient:
    """Sistema embarcado: lê o cartão, decide, sinaliza e publica o evento no RabbitMQ."""

    def __init__(
        self,
        dispositivo: str = RABBITMQ_DISPOSITIVO,
        host: str = RABBITMQ_HOST,
        port: int = RABBITMQ_PORT,
        user: str = RABBITMQ_USER,
        password: str = RABBITMQ_PASS,
        vhost: str = RABBITMQ_VHOST,
        repo: DatabaseRepository | None = None,
        redis: RedisClient | None = None,
    ) -> None:
        self.dispositivo = dispositivo
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.vhost = vhost
        self.routing_key_evento = f"evento.{self.dispositivo}"
        self.is_real = HARDWARE_REAL
        self.repo = repo or DatabaseRepository(db_path=DB_PATH)
        self.redis = redis or redis_client
        self.estado_local: dict[str, Any] = {}
        self.ultima_origem = ""  # de onde veio o colaborador na última leitura: REDIS ou BANCO

        if ESTADO_FILE.exists():
            try:
                with open(ESTADO_FILE, "r", encoding="utf-8") as f:
                    self.estado_local = json.load(f)
            except Exception:
                self.estado_local = {}

        if self.is_real:
            logger.info("Leitor RC522, LED RGB e buzzer inicializados.")
        else:
            logger.info("Sem hardware (%s). Usando o simulador de teclado.", MOTIVO_SEM_HARDWARE)

    def _salvar_estado(self) -> None:
        with open(ESTADO_FILE, "w", encoding="utf-8") as f:
            json.dump(self.estado_local, f, ensure_ascii=False, indent=2)

    # -------------------------------------------------------------------------
    # CARTÃO → COLABORADOR (cache-aside: Redis primeiro, banco se não achar)
    # -------------------------------------------------------------------------

    def buscar_colaborador(self, tag_norm: str) -> tuple[dict[str, Any] | None, str]:
        """Devolve (colaborador, origem). origem é "REDIS" ou "BANCO"."""
        # Sem Redis, vai direto ao banco: a porta continua funcionando, só sem cache.
        usar_redis = self.redis.disponivel

        if usar_redis:
            em_cache = self.redis.obter_tag_cache(tag_norm)
            if em_cache is not None:
                return em_cache, "REDIS"

        encontrado = self.repo.obter_colaborador_por_tag(tag_norm)
        if encontrado is None:
            return None, "BANCO"

        colab = encontrado.to_dict()
        if usar_redis:
            # A API apaga esta chave quando o colaborador é editado ou excluído.
            self.redis.salvar_tag_cache(tag_norm, colab, ttl_segundos=config.TTL_CARTAO_SEGUNDOS)
        return colab, "BANCO"

    # -------------------------------------------------------------------------
    # DECISÃO DO ACESSO
    # -------------------------------------------------------------------------

    def decidir_acesso(self, tag_uid: str) -> dict[str, Any]:
        tag_norm = tag_uid.strip().upper()
        colab, self.ultima_origem = self.buscar_colaborador(tag_norm)

        def evento(resultado: str, mensagem: str) -> dict[str, Any]:
            return {
                "versao": 1,
                "evento_id": str(uuid.uuid4()),
                "dispositivo": self.dispositivo,
                "data_hora": datetime.now(timezone.utc).astimezone().isoformat(),
                "tag_uid": tag_norm,
                "colaborador_id": colab.get("id") if colab else None,
                "nome": colab.get("nome") if colab else None,
                "resultado": resultado,
                "mensagem": mensagem,
            }

        if colab is None:
            return evento("INVASAO", MSG_INVASAO)

        nome = colab.get("nome", "Colaborador")
        hoje_str = datetime.now().strftime("%Y-%m-%d")
        estado_colab = self.estado_local.get(tag_norm, {})
        # O estado só vale para o dia em que foi gravado; zera na virada do dia.
        estado_de_hoje = estado_colab.get("data") == hoje_str
        na_sala = estado_colab.get("na_sala", False) if estado_de_hoje else False
        entrou_hoje = estado_colab.get("entrou_hoje", False) if estado_de_hoje else False

        # A saída vem antes da checagem de permissão: quem perde o acesso
        # enquanto está na sala ainda consegue sair.
        if na_sala:
            resultado, mensagem = "SAIDA", f"Até logo, {nome}"
        elif not colab.get("ativo", True) or not colab.get("acesso_sala", True):
            return evento("NEGADO", f"Acesso negado, {nome}")
        elif entrou_hoje:
            resultado, mensagem = "ENTRADA", f"Bem-vindo de volta, {nome}"
        else:
            resultado, mensagem = "ENTRADA", f"Bem-vindo, {nome}"

        self.estado_local[tag_norm] = {
            "data": hoje_str,
            "na_sala": resultado == "ENTRADA",
            "entrou_hoje": True,
        }
        self._salvar_estado()
        return evento(resultado, mensagem)

    # -------------------------------------------------------------------------
    # SINALIZAÇÃO (LED RGB + buzzer na Pi; texto colorido no simulador)
    # -------------------------------------------------------------------------

    def sinalizar(self, evento: dict[str, Any]) -> None:
        resultado = evento["resultado"]
        logger.info("[%s] %s %s: %s", self.ultima_origem, evento["tag_uid"], resultado, evento["mensagem"])
        if self.is_real:
            atuadores.sinalizar(resultado)
        else:
            print(CORES_SIMULADOR[resultado])

    # -------------------------------------------------------------------------
    # PUBLICAÇÃO NO RABBITMQ (com confirmação; se falhar, guarda em pendentes.jsonl)
    # -------------------------------------------------------------------------

    def _salvar_pendente(self, evento: dict[str, Any]) -> None:
        with open(PENDENTES_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(evento, ensure_ascii=False) + "\n")
        logger.info("RabbitMQ indisponível. Evento salvo em 'pendentes.jsonl' para envio posterior.")

    def _enviar_evento_ao_broker(self, evento: dict[str, Any]) -> bool:
        try:
            credentials = pika.PlainCredentials(self.user, self.password)
            parameters = pika.ConnectionParameters(
                host=self.host,
                port=self.port,
                virtual_host=self.vhost,
                credentials=credentials,
                socket_timeout=1.0,
            )
            with pika.BlockingConnection(parameters) as connection:
                channel = connection.channel()
                channel.confirm_delivery()

                channel.basic_publish(
                    exchange=RABBITMQ_EXCHANGE,
                    routing_key=self.routing_key_evento,
                    body=json.dumps(evento, ensure_ascii=False).encode("utf-8"),
                    properties=pika.BasicProperties(
                        content_type="application/json",
                        delivery_mode=pika.DeliveryMode.Persistent,
                    ),
                    mandatory=True,
                )
                return True
        except Exception as exc:
            logger.debug("Não foi possível entregar evento ao broker (%s).", exc)
            return False

    def processar_leitura(self, tag_uid: str) -> dict[str, Any]:
        """Ciclo completo de uma leitura: decide → sinaliza → publica."""
        evento = self.decidir_acesso(tag_uid)

        # Sinaliza antes de publicar: a pessoa na porta não espera pelo histórico.
        self.sinalizar(evento)

        if self._enviar_evento_ao_broker(evento):
            self._reenviar_pendentes_se_houver()
        else:
            self._salvar_pendente(evento)

        return evento

    def _reenviar_pendentes_se_houver(self) -> None:
        if not PENDENTES_FILE.exists():
            return
        try:
            with open(PENDENTES_FILE, "r", encoding="utf-8") as f:
                linhas = [l.strip() for l in f if l.strip()]
            if not linhas:
                return

            restantes = []
            for linha in linhas:
                ev = json.loads(linha)
                if self._enviar_evento_ao_broker(ev):
                    logger.info("Pendente reenviado com sucesso: %s", ev.get("evento_id"))
                else:
                    restantes.append(linha)

            if restantes:
                with open(PENDENTES_FILE, "w", encoding="utf-8") as f:
                    for r in restantes:
                        f.write(r + "\n")
            else:
                PENDENTES_FILE.unlink(missing_ok=True)
        except Exception as exc:
            logger.error("Erro ao reenviar pendentes: %s", exc)

    # -------------------------------------------------------------------------
    # LOOP DE LEITURA
    # -------------------------------------------------------------------------

    def loop_leitura_continua(self) -> None:
        logger.info("Loop de leitura ativo (Dispositivo: %s)...", self.dispositivo)
        if self.is_real:
            self._loop_rc522()
        else:
            self._loop_simulador()

    def _loop_rc522(self) -> None:
        ultima_tag = None
        ultima_leitura = 0.0
        logger.info("Aguardando cartão...")
        try:
            while True:
                tag_hex = leitor.ler_tag()

                # Debounce: ignora o mesmo cartão enquanto ele continuar no leitor.
                mesmo_cartao = tag_hex == ultima_tag
                if mesmo_cartao and time.monotonic() - ultima_leitura < config.DEBOUNCE_SEGUNDOS:
                    ultima_leitura = time.monotonic()
                    continue

                self.processar_leitura(tag_hex)
                ultima_tag = tag_hex
                ultima_leitura = time.monotonic()
        except KeyboardInterrupt:
            pass
        finally:
            leitor.encerrar()

    def _loop_simulador(self) -> None:
        logger.info("=== SIMULADOR DE CARTÃO RFID ===")
        logger.info("Digite uma Tag (ex: A1B2C3D4, B2C3D4E5, FF998877) ou 'sair':")
        try:
            while True:
                tag = input("\n[LEITOR RFID] Aproxime o cartão: ").strip().upper()
                if not tag:
                    continue
                if tag.lower() in ("sair", "exit", "quit"):
                    break
                self.processar_leitura(tag)
        except (KeyboardInterrupt, EOFError):
            pass


HardwareController = RaspberryPiClient

if __name__ == "__main__":
    client = RaspberryPiClient()
    client.loop_leitura_continua()

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pika

from hardware import config

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [Pi-Hardware] %(message)s",
)
logger = logging.getLogger("rfid.hardware")
logging.getLogger("pika").setLevel(logging.CRITICAL)

BASE_DIR = Path(__file__).resolve().parent

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
    """Sistema embarcado: lê o cartão, decide sozinho, sinaliza e publica o evento no RabbitMQ.

    A Pi não acessa o banco nem o Redis do servidor. A lista de colaboradores chega
    pela fila 'pi.<dispositivo>.colaboradores' e fica guardada em cache.json, então a
    porta continua funcionando mesmo com o servidor fora do ar.
    """

    def __init__(
        self,
        dispositivo: str = config.DISPOSITIVO,
        host: str = config.RABBITMQ_HOST,
        port: int = config.RABBITMQ_PORT,
        user: str = config.RABBITMQ_USER,
        password: str = config.RABBITMQ_PASS,
        vhost: str = config.RABBITMQ_VHOST,
        pasta_dados: Path | str = BASE_DIR,
    ) -> None:
        self.dispositivo = dispositivo
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.vhost = vhost
        self.routing_key_evento = f"evento.{self.dispositivo}"
        self.fila_colaboradores = f"pi.{self.dispositivo}.colaboradores"
        self.is_real = HARDWARE_REAL

        pasta = Path(pasta_dados)
        self.cache_file = pasta / "cache.json"
        self.estado_file = pasta / "estado.json"
        self.pendentes_file = pasta / "pendentes.jsonl"
        # Protege pendentes.jsonl: o loop de leitura grava e a thread de reenvio reescreve.
        self._trava_pendentes = threading.Lock()

        self.colaboradores_cache: list[dict[str, Any]] = self._ler_json(self.cache_file).get("colaboradores", [])
        self.estado_local: dict[str, Any] = self._ler_json(self.estado_file)

        if self.is_real:
            logger.info("Leitor RC522, LED RGB e buzzer inicializados.")
        else:
            logger.info("Sem hardware (%s). Usando o simulador de teclado.", MOTIVO_SEM_HARDWARE)

        if self.colaboradores_cache:
            logger.info("cache.json carregado (%d colaboradores).", len(self.colaboradores_cache))
        else:
            logger.warning("Sem cache.json: todo cartão será INVASAO até o servidor enviar a lista.")

    @staticmethod
    def _ler_json(arquivo: Path) -> dict[str, Any]:
        try:
            with open(arquivo, "r", encoding="utf-8") as f:
                dados = json.load(f)
            return dados if isinstance(dados, dict) else {}
        except Exception:
            return {}

    def _salvar_estado(self) -> None:
        with open(self.estado_file, "w", encoding="utf-8") as f:
            json.dump(self.estado_local, f, ensure_ascii=False, indent=2)

    # -------------------------------------------------------------------------
    # LISTA DE COLABORADORES (servidor → fila → cache.json)
    # -------------------------------------------------------------------------

    def atualizar_cache(self, dados: dict[str, Any]) -> None:
        temp_file = self.cache_file.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        temp_file.replace(self.cache_file)
        self.colaboradores_cache = dados.get("colaboradores", [])
        logger.info("Lista recebida do servidor (%d colaboradores).", len(self.colaboradores_cache))

    def _receber_lista(self, ch: Any, method: Any, properties: Any, body: bytes) -> None:
        try:
            dados = json.loads(body.decode("utf-8"))
            if dados.get("versao") != 1 or not isinstance(dados.get("colaboradores"), list):
                raise ValueError("mensagem fora do contrato v1")
            self.atualizar_cache(dados)
            ch.basic_ack(delivery_tag=method.delivery_tag)
        except Exception as exc:
            logger.warning("Lista de colaboradores descartada (%s).", exc)
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def _consumir_colaboradores(self) -> None:
        """Escuta a fila de colaboradores para sempre; reconecta se o RabbitMQ cair."""
        while True:
            try:
                parameters = pika.ConnectionParameters(
                    host=self.host,
                    port=self.port,
                    virtual_host=self.vhost,
                    credentials=pika.PlainCredentials(self.user, self.password),
                    socket_timeout=10.0,
                )
                with pika.BlockingConnection(parameters) as connection:
                    channel = connection.channel()
                    # Mesma declaração do servidor (servidor/server/rabbit_producer.py).
                    channel.queue_declare(
                        queue=self.fila_colaboradores,
                        durable=True,
                        arguments={"x-max-length": 1},
                    )
                    channel.basic_consume(
                        queue=self.fila_colaboradores,
                        on_message_callback=self._receber_lista,
                    )
                    channel.start_consuming()
            except Exception as exc:
                logger.debug("Fila de colaboradores indisponível (%s). Nova tentativa em 5s.", exc)
                time.sleep(5)

    def iniciar_sincronizacao(self) -> None:
        threading.Thread(target=self._consumir_colaboradores, daemon=True).start()
        threading.Thread(target=self._reenviar_pendentes_periodicamente, daemon=True).start()

    def buscar_colaborador(self, tag_norm: str) -> dict[str, Any] | None:
        for colab in self.colaboradores_cache:
            if str(colab.get("tag_uid", "")).upper() == tag_norm:
                return colab
        return None

    # -------------------------------------------------------------------------
    # DECISÃO DO ACESSO
    # -------------------------------------------------------------------------

    def decidir_acesso(self, tag_uid: str) -> dict[str, Any]:
        tag_norm = tag_uid.strip().upper()
        colab = self.buscar_colaborador(tag_norm)

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
        logger.info("%s %s: %s", evento["tag_uid"], resultado, evento["mensagem"])
        if self.is_real:
            atuadores.sinalizar(resultado)
        else:
            print(CORES_SIMULADOR[resultado])

    # -------------------------------------------------------------------------
    # PUBLICAÇÃO NO RABBITMQ (com confirmação; se falhar, guarda em pendentes.jsonl)
    # -------------------------------------------------------------------------

    def _salvar_pendente(self, evento: dict[str, Any]) -> None:
        with self._trava_pendentes:
            with open(self.pendentes_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(evento, ensure_ascii=False) + "\n")
        logger.info("RabbitMQ indisponível. Evento salvo em 'pendentes.jsonl' para envio posterior.")

    def _ler_pendentes(self) -> list[str]:
        try:
            with open(self.pendentes_file, "r", encoding="utf-8") as f:
                return [l.strip() for l in f if l.strip()]
        except FileNotFoundError:
            return []

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
                    exchange=config.RABBITMQ_EXCHANGE,
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
        """Reenvia os eventos guardados em pendentes.jsonl, na ordem em que aconteceram.

        Roda tanto depois de uma publicação bem-sucedida quanto periodicamente em
        segundo plano. Se os dois rodarem juntos, um evento pode ser enviado duas
        vezes, o que é inofensivo: o servidor ignora evento_id repetido.
        """
        # A trava só cobre o acesso ao arquivo, não o envio pela rede, para não
        # segurar a leitura do próximo cartão enquanto o broker responde.
        with self._trava_pendentes:
            linhas = self._ler_pendentes()
        if not linhas:
            return

        resolvidas: set[str] = set()
        for linha in linhas:
            try:
                ev = json.loads(linha)
            except json.JSONDecodeError:
                logger.error("Linha corrompida em pendentes.jsonl descartada: %s", linha[:80])
                resolvidas.add(linha)
                continue
            if not self._enviar_evento_ao_broker(ev):
                # Broker fora: para aqui e tenta tudo de novo depois, mantendo a ordem.
                break
            logger.info("Pendente reenviado com sucesso: %s", ev.get("evento_id"))
            resolvidas.add(linha)

        if not resolvidas:
            return
        try:
            with self._trava_pendentes:
                # Relê o arquivo: eventos novos podem ter sido gravados durante o envio.
                restantes = [l for l in self._ler_pendentes() if l not in resolvidas]
                if restantes:
                    temp_file = self.pendentes_file.with_suffix(".tmp")
                    with open(temp_file, "w", encoding="utf-8") as f:
                        f.write("".join(r + "\n" for r in restantes))
                    temp_file.replace(self.pendentes_file)
                else:
                    self.pendentes_file.unlink(missing_ok=True)
        except Exception as exc:
            logger.error("Erro ao atualizar pendentes.jsonl: %s", exc)

    def _reenviar_pendentes_periodicamente(self) -> None:
        """Garante o reenvio mesmo que ninguém passe o cartão depois que a rede voltar."""
        while True:
            time.sleep(config.REENVIO_PENDENTES_SEGUNDOS)
            try:
                self._reenviar_pendentes_se_houver()
            except Exception as exc:
                logger.error("Erro no reenvio periódico de pendentes: %s", exc)

    # -------------------------------------------------------------------------
    # LOOP DE LEITURA
    # -------------------------------------------------------------------------

    def loop_leitura_continua(self) -> None:
        self.iniciar_sincronizacao()
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


if __name__ == "__main__":
    client = RaspberryPiClient()
    client.loop_leitura_continua()

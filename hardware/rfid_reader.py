from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pika

from server.config import (
    RABBITMQ_DISPOSITIVO,
    RABBITMQ_EXCHANGE,
    RABBITMQ_FILA_PI,
    RABBITMQ_HOST,
    RABBITMQ_PASS,
    RABBITMQ_PORT,
    RABBITMQ_USER,
    RABBITMQ_VHOST,
)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [Pi-Hardware] %(message)s",
)
logger = logging.getLogger("rfid.hardware")
logging.getLogger("pika").setLevel(logging.CRITICAL)

BASE_DIR = Path(__file__).resolve().parent
CACHE_FILE = BASE_DIR / "cache.json"
ESTADO_FILE = BASE_DIR / "estado.json"
PENDENTES_FILE = BASE_DIR / "pendentes.jsonl"

PINO_LED_VERDE = int(os.environ.get("PINO_LED_VERDE", "17"))
PINO_LED_VERMELHO = int(os.environ.get("PINO_LED_VERMELHO", "27"))
PINO_BUZZER = int(os.environ.get("PINO_BUZZER", "22"))

try:
    import RPi.GPIO as GPIO  # type: ignore[import-not-found]
    from mfrc522 import SimpleMFRC522  # type: ignore[import-not-found]
    HARDWARE_REAL = True
except ImportError:
    HARDWARE_REAL = False


class RaspberryPiClient:
    """Cliente Embarcado para Raspberry Pi conforme Contrato RabbitMQ v1 (@Brayan)."""

    def __init__(
        self,
        dispositivo: str = RABBITMQ_DISPOSITIVO,
        host: str = RABBITMQ_HOST,
        port: int = RABBITMQ_PORT,
        user: str = RABBITMQ_USER,
        password: str = RABBITMQ_PASS,
        vhost: str = RABBITMQ_VHOST,
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
        self._reader: Any = None
        self.colaboradores_cache: list[dict[str, Any]] = []
        self.estado_local: dict[str, Any] = {}

        self._inicializar_arquivos()
        self._inicializar_gpio()

    def _inicializar_arquivos(self) -> None:
        # Carrega cache.json
        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    dados = json.load(f)
                    self.colaboradores_cache = dados.get("colaboradores", [])
            except Exception:
                self.colaboradores_cache = []

        # Carrega estado.json (quem está na sala e quem já entrou hoje)
        if ESTADO_FILE.exists():
            try:
                with open(ESTADO_FILE, "r", encoding="utf-8") as f:
                    self.estado_local = json.load(f)
            except Exception:
                self.estado_local = {}

    def _salvar_cache_atomico(self, dados: dict[str, Any]) -> None:
        """Salva cache.json com escrita atômica para evitar corrupção em quedas de energia."""
        temp_file = CACHE_FILE.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        temp_file.replace(CACHE_FILE)
        self.colaboradores_cache = dados.get("colaboradores", [])
        logger.info("Cache local atualizado com sucesso (%d colaboradores).", len(self.colaboradores_cache))

    def _salvar_estado(self) -> None:
        with open(ESTADO_FILE, "w", encoding="utf-8") as f:
            json.dump(self.estado_local, f, ensure_ascii=False, indent=2)

    def _inicializar_gpio(self) -> None:
        if self.is_real:
            logger.info("Inicializando pinos GPIO físicos e leitor RC522...")
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(PINO_LED_VERDE, GPIO.OUT, initial=GPIO.LOW)
            GPIO.setup(PINO_LED_VERMELHO, GPIO.OUT, initial=GPIO.LOW)
            GPIO.setup(PINO_BUZZER, GPIO.OUT, initial=GPIO.LOW)
            self._reader = SimpleMFRC522()
        else:
            logger.info("Ambiente de Desenvolvimento (Modo Mock simulado ativo).")

    # -------------------------------------------------------------------------
    # SINALIZAÇÃO FÍSICA IMEDIATA (O LED nunca espera a rede - Página 4 do PDF)
    # -------------------------------------------------------------------------

    def sinalizar_sucesso(self, nome: str, mensagem: str) -> None:
        logger.info(">>> [ACESSO LIBERADO] %s | %s <<<", nome, mensagem)
        if self.is_real:
            GPIO.output(PINO_LED_VERDE, GPIO.HIGH)
            GPIO.output(PINO_BUZZER, GPIO.HIGH)
            time.sleep(0.15)
            GPIO.output(PINO_BUZZER, GPIO.LOW)
            time.sleep(1.85)
            GPIO.output(PINO_LED_VERDE, GPIO.LOW)
        else:
            print(f"\033[92m[LED VERDE ACESO]\033[0m Sucesso: {mensagem} (Bipe curto)")

    def sinalizar_negado(self, resultado: str, mensagem: str) -> None:
        logger.warning(">>> [ACESSO NEGADO - %s] %s <<<", resultado, mensagem)
        if self.is_real:
            for _ in range(3):
                GPIO.output(PINO_LED_VERMELHO, GPIO.HIGH)
                GPIO.output(PINO_BUZZER, GPIO.HIGH)
                time.sleep(0.12)
                GPIO.output(PINO_LED_VERMELHO, GPIO.LOW)
                GPIO.output(PINO_BUZZER, GPIO.LOW)
                time.sleep(0.12)
            GPIO.output(PINO_LED_VERMELHO, GPIO.HIGH)
            time.sleep(1.0)
            GPIO.output(PINO_LED_VERMELHO, GPIO.LOW)
        else:
            print(f"\033[91m[LED VERMELHO PISCANDO]\033[0m Alerta: {mensagem} (3 bipes)")

    # -------------------------------------------------------------------------
    # DECISÃO LOCAL AUTÔNOMA (comum/regras.py na Pi)
    # -------------------------------------------------------------------------

    def decidir_acesso(self, tag_uid: str) -> dict[str, Any]:
        """A Pi decide o acesso sozinha na ponta conforme o PDF."""
        tag_norm = tag_uid.strip().upper()
        now_iso = datetime.now(timezone.utc).astimezone().isoformat()
        evento_id = str(uuid.uuid4())

        # Mensagem padrão de INVASAO exigida na Página 4 do PDF
        MSG_INVASAO = "Acesso negado, tag não cadastrada"

        # Se não há cache.json (nunca recebeu lista), todo crachá vira INVASAO (Página 4)
        if not self.colaboradores_cache:
            return {
                "versao": 1,
                "evento_id": evento_id,
                "dispositivo": self.dispositivo,
                "data_hora": now_iso,
                "tag_uid": tag_norm,
                "colaborador_id": None,
                "nome": None,
                "resultado": "INVASAO",
                "mensagem": MSG_INVASAO,
            }

        # Busca colaborador no cache
        colab = next((c for c in self.colaboradores_cache if str(c.get("tag_uid", "")).upper() == tag_norm), None)

        if colab is None:
            return {
                "versao": 1,
                "evento_id": evento_id,
                "dispositivo": self.dispositivo,
                "data_hora": now_iso,
                "tag_uid": tag_norm,
                "colaborador_id": None,
                "nome": None,
                "resultado": "INVASAO",
                "mensagem": MSG_INVASAO,
            }

        colab_id = colab.get("id")
        nome = colab.get("nome", "Colaborador")
        ativo = bool(colab.get("ativo", True))
        acesso_sala = bool(colab.get("acesso_sala", True))

        if not ativo or not acesso_sala:
            return {
                "versao": 1,
                "evento_id": evento_id,
                "dispositivo": self.dispositivo,
                "data_hora": now_iso,
                "tag_uid": tag_norm,
                "colaborador_id": colab_id,
                "nome": nome,
                "resultado": "NEGADO",
                "mensagem": f"Acesso negado, {nome}",
            }

        # Colaborador Autorizado: verifica estado.json
        hoje_str = datetime.now().strftime("%Y-%m-%d")
        estado_colab = self.estado_local.get(tag_norm, {})
        ultimo_dia = estado_colab.get("data")
        na_sala = estado_colab.get("na_sala", False) if ultimo_dia == hoje_str else False
        entrou_hoje = estado_colab.get("entrou_hoje", False) if ultimo_dia == hoje_str else False

        if not entrou_hoje and not na_sala:
            resultado = "ENTRADA"
            mensagem = f"Bem-vindo, {nome}"
            self.estado_local[tag_norm] = {"data": hoje_str, "na_sala": True, "entrou_hoje": True}
        elif na_sala:
            resultado = "SAIDA"
            mensagem = f"Até logo, {nome}"
            self.estado_local[tag_norm] = {"data": hoje_str, "na_sala": False, "entrou_hoje": True}
        else:
            resultado = "ENTRADA"
            mensagem = f"Bem-vindo de volta, {nome}"
            self.estado_local[tag_norm] = {"data": hoje_str, "na_sala": True, "entrou_hoje": True}

        self._salvar_estado()

        return {
            "versao": 1,
            "evento_id": evento_id,
            "dispositivo": self.dispositivo,
            "data_hora": now_iso,
            "tag_uid": tag_norm,
            "colaborador_id": colab_id,
            "nome": nome,
            "resultado": resultado,
            "mensagem": mensagem,
        }

    # -------------------------------------------------------------------------
    # PUBLICAÇÃO COM CONFIRMS E FILA PENDENTES (pendentes.jsonl)
    # -------------------------------------------------------------------------

    def _salvar_pendente(self, evento: dict[str, Any]) -> None:
        with open(PENDENTES_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(evento, ensure_ascii=False) + "\n")
        logger.info("Evento salvo em 'pendentes.jsonl' para envio posterior.")

    def _enviar_evento_ao_broker(self, evento: dict[str, Any]) -> bool:
        """Envia evento ao RabbitMQ com publisher confirms conforme Página 4."""
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
        """Ciclo completo de leitura: decide -> sinaliza LED -> publica evento (ou salva pendente)."""
        # 1. Decide na hora
        evento = self.decidir_acesso(tag_uid)

        # 2. Sinaliza fisicamente na hora (o LED nunca espera a rede)
        if evento["resultado"] in ("ENTRADA", "SAIDA"):
            self.sinalizar_sucesso(evento["nome"] or tag_uid, evento["mensagem"])
        else:
            self.sinalizar_negado(evento["resultado"], evento["mensagem"])

        # 3. Publica no RabbitMQ com publisher confirm
        sucesso = self._enviar_evento_ao_broker(evento)
        if not sucesso:
            self._salvar_pendente(evento)
        else:
            self._reenviar_pendentes_se_houver()

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
    # CONSUMO DA FILA pi.sala-aaa.colaboradores EM BACKGROUND
    # -------------------------------------------------------------------------

    def _consumir_colaboradores_background(self) -> None:
        """Fica escutando a fila 'pi.<disp>.colaboradores' para atualizar o cache.json na hora."""
        while True:
            try:
                credentials = pika.PlainCredentials(self.user, self.password)
                parameters = pika.ConnectionParameters(
                    host=self.host,
                    port=self.port,
                    virtual_host=self.vhost,
                    credentials=credentials,
                    socket_timeout=10.0,
                )
                with pika.BlockingConnection(parameters) as connection:
                    channel = connection.channel()
                    channel.queue_declare(queue=self.fila_colaboradores, durable=True, arguments={"x-max-length": 1})

                    def callback(ch: Any, method: Any, properties: Any, body: bytes) -> None:
                        try:
                            dados = json.loads(body.decode("utf-8"))
                            self._salvar_cache_atomico(dados)
                            ch.basic_ack(delivery_tag=method.delivery_tag)
                        except Exception as exc:
                            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

                    channel.basic_consume(queue=self.fila_colaboradores, on_message_callback=callback)
                    channel.start_consuming()
            except Exception:
                time.sleep(5)

    def iniciar_thread_sincronizacao(self) -> None:
        t = threading.Thread(target=self._consumir_colaboradores_background, daemon=True)
        t.start()

    def loop_leitura_continua(self) -> None:
        self.iniciar_thread_sincronizacao()
        logger.info("Loop de leitura ativo (Dispositivo: %s)...", self.dispositivo)

        if self.is_real:
            try:
                while True:
                    tag_id, _ = self._reader.read()
                    tag_hex = hex(tag_id)[2:].upper()
                    self.processar_leitura(tag_hex)
                    time.sleep(1.0)
            except KeyboardInterrupt:
                pass
            finally:
                GPIO.cleanup()
        else:
            logger.info("=== SIMULADOR DE CARTÃO RFID (CONTRATO RABBITMQ v1) ===")
            logger.info("Digite uma Tag (ex: A1B2C3D4, B2C3D4E5, FF998877) ou 'sair':")
            try:
                while True:
                    tag = input("\n[LEITOR RFID] Aproxime o cartão: ").strip().upper()
                    if not tag:
                        continue
                    if tag.lower() in ("sair", "exit", "quit"):
                        break
                    self.processar_leitura(tag)
            except KeyboardInterrupt:
                pass


HardwareController = RaspberryPiClient

if __name__ == "__main__":
    client = RaspberryPiClient()
    client.loop_leitura_continua()

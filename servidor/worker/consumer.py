from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime
from typing import Any

import pika

from server.config import (
    DB_PATH,
    RABBITMQ_FILA_SERVIDOR,
    RABBITMQ_HOST,
    RABBITMQ_PASS,
    RABBITMQ_PORT,
    RABBITMQ_USER,
    RABBITMQ_VHOST,
)
from server.database import DatabaseRepository
from server.rabbit_producer import declarar_topologia

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [Worker-RabbitMQ] %(message)s",
)
logger = logging.getLogger("rfid.worker")
logging.getLogger("pika").setLevel(logging.CRITICAL)

PAUSA_FALHA_BANCO_SEGUNDOS = 2


def normalizar_data_hora(iso_string: str) -> str:
    """Converte ISO 8601 com fuso (ex: '2026-11-06T20:15:02-03:00') para '2026-11-06 20:15:02'."""
    try:
        dt = datetime.fromisoformat(iso_string)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        # Se já estiver no formato ou falhar o parse, limpa o 'T'
        return iso_string.replace("T", " ")[:19]


class EventConsumer:
    """Consumidor do Servidor que escuta 'servidor.eventos' e persiste no SQLite com deduplicação."""

    def __init__(
        self,
        db_path: Any = DB_PATH,
        host: str = RABBITMQ_HOST,
        port: int = RABBITMQ_PORT,
        user: str = RABBITMQ_USER,
        password: str = RABBITMQ_PASS,
        vhost: str = RABBITMQ_VHOST,
        queue: str = RABBITMQ_FILA_SERVIDOR,
    ) -> None:
        self.repo = DatabaseRepository(db_path=db_path)
        self.repo.init_db(seed_default=False)
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.vhost = vhost
        self.queue = queue
        self.running = True

    def processar_mensagem(
        self, ch: Any, method: Any, properties: Any, body: bytes
    ) -> None:
        """Processa a mensagem de evento da Pi conforme Contrato de Mensageria v1."""
        try:
            payload = json.loads(body.decode("utf-8"))

            # Validação de versão conforme PDF (Página 5)
            versao = payload.get("versao")
            if versao != 1:
                logger.warning("Versão desconhecida (%s). Rejeitando mensagem com nack sem requeue.", versao)
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
                return

            evento_id = payload.get("evento_id")
            dispositivo = payload.get("dispositivo", "sala-aaa")
            data_hora_raw = str(payload.get("data_hora", ""))
            data_hora = normalizar_data_hora(data_hora_raw)
            tag_uid = str(payload.get("tag_uid", "DESCONHECIDO")).strip().upper()
            colaborador_id = payload.get("colaborador_id")
            nome = payload.get("nome") or "Desconhecido"
            resultado = str(payload.get("resultado", "INVASAO")).strip()
            mensagem = payload.get("mensagem", "")

            # Grava no banco ignorando evento_id duplicado
            self.repo.registrar_evento(
                data_hora=data_hora,
                tag_uid=tag_uid,
                nome=nome,
                resultado=resultado,  # type: ignore[arg-type]
                evento_id=evento_id,
                colaborador_id=colaborador_id,
                mensagem=mensagem,
                dispositivo=dispositivo,
            )
            logger.info("Evento gravado no SQLite: %s | %s | %s (ID: %s)", data_hora, nome, resultado, evento_id)

            # Só dá ack DEPOIS de comitar no banco de dados (Regra da Página 3 do PDF)
            ch.basic_ack(delivery_tag=method.delivery_tag)
        except sqlite3.IntegrityError as exc:
            # Dado inválido (ex.: resultado fora da lista): tentar de novo não resolve.
            logger.error("Evento rejeitado pelo banco (%s). Descartando.", exc)
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        except sqlite3.Error as exc:
            # Falha do banco (travado, schema antigo, disco): o evento volta para a fila
            # e é entregue de novo. A pausa evita repetir em ritmo frenético.
            logger.error("Falha ao gravar no banco (%s). Evento devolvido à fila.", exc)
            time.sleep(PAUSA_FALHA_BANCO_SEGUNDOS)
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        except Exception as exc:
            # Mensagem malformada (JSON inválido, campos errados): descarta.
            logger.error("Mensagem inválida na fila (%s). Descartando.", exc)
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def iniciar(self) -> None:
        logger.info("Iniciando Worker de Eventos (RabbitMQ 'servidor.eventos' -> SQLite)...")
        while self.running:
            try:
                credentials = pika.PlainCredentials(self.user, self.password)
                parameters = pika.ConnectionParameters(
                    host=self.host,
                    port=self.port,
                    virtual_host=self.vhost,
                    credentials=credentials,
                    heartbeat=60,
                    blocked_connection_timeout=300,
                )
                connection = pika.BlockingConnection(parameters)
                channel = connection.channel()

                # Declara a topologia combinada
                declarar_topologia(channel)

                channel.basic_qos(prefetch_count=1)
                channel.basic_consume(
                    queue=self.queue, on_message_callback=self.processar_mensagem
                )

                logger.info("Aguardando mensagens na fila '%s'...", self.queue)
                channel.start_consuming()
            except pika.exceptions.AMQPConnectionError:
                logger.warning("RabbitMQ offline na porta 5672. Inicie o Docker Desktop para habilitar mensageria. Tentando reconectar em 10s...")
                time.sleep(10)
            except KeyboardInterrupt:
                logger.info("Worker interrompido pelo usuário.")
                self.running = False
                break
            except Exception as exc:
                logger.warning("Aguardando conexão com o broker (%s)...", exc)
                time.sleep(10)


if __name__ == "__main__":
    consumer = EventConsumer()
    consumer.iniciar()

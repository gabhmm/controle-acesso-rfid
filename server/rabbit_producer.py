from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import pika

from server.config import (
    RABBITMQ_DISPOSITIVO,
    RABBITMQ_EXCHANGE,
    RABBITMQ_FILA_PI,
    RABBITMQ_FILA_SERVIDOR,
    RABBITMQ_HOST,
    RABBITMQ_PASS,
    RABBITMQ_PORT,
    RABBITMQ_USER,
    RABBITMQ_VHOST,
)

logger = logging.getLogger("rfid.rabbitmq")

RABBITMQ_HABILITADO = os.environ.get("ENABLE_RABBITMQ", "true").lower() in ("true", "1", "sim")


def declarar_topologia(channel: Any) -> None:
    """Declara a topologia combinada do RabbitMQ conforme o PDF:
    - Exchange 'acesso' (topic, durável)
    - Fila 'servidor.eventos' (durável, bind 'evento.*')
    - Fila 'pi.<dispositivo>.colaboradores' (durável, x-max-length: 1, bind 'colaboradores')
    """
    # 1. Exchange
    channel.exchange_declare(
        exchange=RABBITMQ_EXCHANGE,
        exchange_type="topic",
        durable=True,
    )

    # 2. Fila do Servidor (recebe eventos de todos os dispositivos)
    channel.queue_declare(queue=RABBITMQ_FILA_SERVIDOR, durable=True)
    channel.queue_bind(
        queue=RABBITMQ_FILA_SERVIDOR,
        exchange=RABBITMQ_EXCHANGE,
        routing_key="evento.*",
    )

    # 3. Fila da Raspberry Pi (armazena apenas a lista mais recente: x-max-length: 1)
    channel.queue_declare(
        queue=RABBITMQ_FILA_PI,
        durable=True,
        arguments={"x-max-length": 1},
    )
    channel.queue_bind(
        queue=RABBITMQ_FILA_PI,
        exchange=RABBITMQ_EXCHANGE,
        routing_key="colaboradores",
    )


class RabbitMQProducer:
    """Produtor para publicação da lista de colaboradores para a Pi conforme Contrato RabbitMQ v1."""

    def __init__(
        self,
        host: str = RABBITMQ_HOST,
        port: int = RABBITMQ_PORT,
        user: str = RABBITMQ_USER,
        password: str = RABBITMQ_PASS,
        vhost: str = RABBITMQ_VHOST,
        habilitado: bool = RABBITMQ_HABILITADO,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.vhost = vhost
        self.habilitado = habilitado
        self._ultima_tentativa: float = 0.0
        self._intervalo_tentativa: float = 10.0
        self.fila_memoria: list[dict[str, Any]] = []

    def _obter_conexao(self) -> pika.BlockingConnection | None:
        if not self.habilitado:
            return None
        agora = time.time()
        if agora - self._ultima_tentativa < self._intervalo_tentativa:
            return None
        try:
            credentials = pika.PlainCredentials(self.user, self.password)
            parameters = pika.ConnectionParameters(
                host=self.host,
                port=self.port,
                virtual_host=self.vhost,
                credentials=credentials,
                connection_attempts=1,
                retry_delay=1,
                socket_timeout=1.0,
            )
            return pika.BlockingConnection(parameters)
        except Exception as exc:
            self._ultima_tentativa = time.time()
            logger.debug("RabbitMQ indisponível (%s).", exc)
            return None

    def publicar_colaboradores(self, colaboradores_lista: list[dict[str, Any]]) -> bool:
        """Publica a lista completa de colaboradores (Servidor -> Pi) conforme Página 3 do PDF.
        Routing key: 'colaboradores' na exchange 'acesso'.
        """
        payload = {
            "versao": 1,
            "atualizado_em": datetime.now(timezone.utc).astimezone().isoformat(),
            "colaboradores": [
                {
                    "id": c.get("id"),
                    "nome": c.get("nome"),
                    "tag_uid": str(c.get("tag_uid", "")).upper(),
                    "acesso_sala": bool(c.get("acesso_sala", True)),
                    "ativo": bool(c.get("ativo", True)),
                }
                for c in colaboradores_lista
            ],
        }

        # Salva em memória para testes e fallback
        self.fila_memoria.append(payload)

        connection = self._obter_conexao()
        if not connection:
            return False

        try:
            channel = connection.channel()
            declarar_topologia(channel)

            corpo = json.dumps(payload, ensure_ascii=False)
            channel.basic_publish(
                exchange=RABBITMQ_EXCHANGE,
                routing_key="colaboradores",
                body=corpo.encode("utf-8"),
                properties=pika.BasicProperties(
                    content_type="application/json",
                    delivery_mode=pika.DeliveryMode.Persistent,
                ),
            )
            logger.info("Lista de %d colaboradores publicada para a Pi no RabbitMQ.", len(colaboradores_lista))
            return True
        except Exception as exc:
            logger.warning("Falha ao publicar colaboradores no RabbitMQ: %s", exc)
            return False
        finally:
            try:
                connection.close()
            except Exception:
                pass


rabbit_producer = RabbitMQProducer()

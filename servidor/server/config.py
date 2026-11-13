from __future__ import annotations

import os
from pathlib import Path

BASE_DIR: Path = Path(__file__).resolve().parent
PROJECT_ROOT: Path = BASE_DIR.parent

# Banco de Dados SQLite
DB_PATH: Path = Path(os.environ.get("ACESSO_DB_PATH", str(BASE_DIR / "acesso.db")))

# Autenticação do Administrador
ADMIN_USER: str = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS: str = os.environ.get("ADMIN_PASS", "admin")

# Configurações do Redis (Cache Distribuído)
REDIS_HOST: str = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT: int = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_DB: int = int(os.environ.get("REDIS_DB", "0"))
REDIS_PASSWORD: str | None = os.environ.get("REDIS_PASSWORD", None)

# Configurações do RabbitMQ — Conforme Contrato RabbitMQ v1 (@Brayan)
RABBITMQ_HOST: str = os.environ.get("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT: int = int(os.environ.get("RABBITMQ_PORT", "5672"))
RABBITMQ_USER: str = os.environ.get("RABBITMQ_USER", "guest")
RABBITMQ_PASS: str = os.environ.get("RABBITMQ_PASS", "guest")
RABBITMQ_VHOST: str = os.environ.get("RABBITMQ_VHOST", "/")

RABBITMQ_EXCHANGE: str = "acesso"  # topic, durável
RABBITMQ_FILA_SERVIDOR: str = "servidor.eventos"  # bind evento.*
RABBITMQ_DISPOSITIVO: str = os.environ.get("DISPOSITIVO", "sala-aaa")
RABBITMQ_FILA_PI: str = f"pi.{RABBITMQ_DISPOSITIVO}.colaboradores"  # x-max-length: 1, bind colaboradores

# A cada quantos segundos o servidor republica a lista de colaboradores para a Pi.
# Garante que uma Pi que liga sem cache.json (ou que perdeu a última mensagem)
# receba a lista sem depender de alguém editar um colaborador.
REPUBLICAR_LISTA_SEGUNDOS: int = int(os.environ.get("REPUBLICAR_LISTA_SEGUNDOS", "60"))

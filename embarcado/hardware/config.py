# Configuração do sistema embarcado (pinos em numeração GPIO/BCM).

import os

DEBOUNCE_SEGUNDOS = 3

PINO_LED_VERMELHO = 17
PINO_LED_VERDE = 27
PINO_LED_AZUL = 22
LED_ANODO_COMUM = False

PINO_BUZZER = 18
BUZZER_ATIVO = True

# Conexão com o RabbitMQ do servidor (única ligação da Pi com o servidor).
# Na Pi, aponte RABBITMQ_HOST para o IP do servidor e use um usuário próprio:
# o "guest" só é aceito em conexões locais.
RABBITMQ_HOST = os.environ.get("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.environ.get("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.environ.get("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.environ.get("RABBITMQ_PASS", "guest")
RABBITMQ_VHOST = os.environ.get("RABBITMQ_VHOST", "/")

# Precisam ser iguais aos do servidor (servidor/server/config.py).
RABBITMQ_EXCHANGE = "acesso"
DISPOSITIVO = os.environ.get("DISPOSITIVO", "sala-aaa")

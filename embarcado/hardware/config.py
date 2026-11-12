# Configuração do sistema embarcado (pinos em numeração GPIO/BCM).

DEBOUNCE_SEGUNDOS = 3

# A cada quantos segundos a Pi tenta reenviar os eventos que ficaram em pendentes.jsonl.
REENVIO_PENDENTES_SEGUNDOS = 15

PINO_LED_VERMELHO = 17
PINO_LED_VERDE = 27
PINO_LED_AZUL = 22
LED_ANODO_COMUM = False

PINO_BUZZER = 18
BUZZER_ATIVO = True


RABBITMQ_HOST = "localhost"
RABBITMQ_USER = "guest"
RABBITMQ_PASS = "guest"
RABBITMQ_PORT = 5672
RABBITMQ_VHOST = "/"

# Precisam ser iguais aos do servidor (servidor/server/config.py).
RABBITMQ_EXCHANGE = "acesso"
DISPOSITIVO = "sala-aaa"

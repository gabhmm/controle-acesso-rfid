from time import sleep

from gpiozero import RGBLED, Buzzer

from hardware import config

led = RGBLED(
    config.PINO_LED_VERMELHO,
    config.PINO_LED_VERDE,
    config.PINO_LED_AZUL,
    active_high=not config.LED_ANODO_COMUM,
)

buzzer = Buzzer(config.PINO_BUZZER) if config.BUZZER_ATIVO else None

VERDE = (0, 1, 0)
AMARELO = (1, 0.5, 0)
VERMELHO = (1, 0, 0)


def bipar(ligado, desligado, vezes):
    if buzzer:
        buzzer.beep(on_time=ligado, off_time=desligado, n=vezes, background=False)


def acender(cor, segundos):
    led.color = cor
    sleep(segundos)
    led.off()


def sinalizar(resultado):
    if resultado == "ENTRADA":
        bipar(0.1, 0.1, 1)
        acender(VERDE, 2)
    elif resultado == "SAIDA":
        bipar(0.1, 0.1, 2)
        acender(AMARELO, 2)
    elif resultado == "NEGADO":
        bipar(0.8, 0.1, 1)
        acender(AMARELO, 2)
    elif resultado == "INVASAO":
        for i in range(3):
            bipar(0.1, 0.1, 1)
            acender(VERMELHO, 0.5)
            sleep(0.1)


if __name__ == "__main__":
    for resultado in ["ENTRADA", "SAIDA", "NEGADO", "INVASAO"]:
        print(resultado)
        sinalizar(resultado)
        sleep(1)

import RPi.GPIO as GPIO
from mfrc522 import SimpleMFRC522

leitor = SimpleMFRC522()


def ler_tag():
    id_tag = leitor.read_id()
    return format(id_tag, "X")


def encerrar():
    GPIO.cleanup()


if __name__ == "__main__":
    try:
        while True:
            print("Aproxime o crachá...")
            print(ler_tag())
    except KeyboardInterrupt:
        encerrar()

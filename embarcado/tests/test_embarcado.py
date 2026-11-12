from __future__ import annotations

import json
import tempfile
import unittest

from hardware.rfid_reader import RaspberryPiClient

# Mensagem no formato que o servidor publica na fila pi.<dispositivo>.colaboradores
# (Contrato RabbitMQ v1). Fixa aqui porque o embarcado não depende do código do servidor.
LISTA_DO_SERVIDOR = {
    "versao": 1,
    "atualizado_em": "2026-11-09T22:23:53-03:00",
    "colaboradores": [
        {"id": 1, "nome": "Ana", "tag_uid": "A1B2C3D4", "acesso_sala": True, "ativo": True},
        {"id": 2, "nome": "Carlos", "tag_uid": "C3D4E5F6", "acesso_sala": False, "ativo": True},
    ],
}


class MockChannel:
    def __init__(self) -> None:
        self.acks = 0
        self.nacks = 0

    def basic_ack(self, delivery_tag: int) -> None:
        self.acks += 1

    def basic_nack(self, delivery_tag: int, requeue: bool = False) -> None:
        self.nacks += 1


class MockMethod:
    delivery_tag = 1


class TestEmbarcado(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.pi = RaspberryPiClient(dispositivo="sala-aaa", pasta_dados=self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def receber(self, mensagem: dict) -> MockChannel:
        canal = MockChannel()
        self.pi._receber_lista(canal, MockMethod(), None, json.dumps(mensagem).encode("utf-8"))
        return canal

    def test_sem_lista_todo_cartao_e_invasao(self) -> None:
        self.assertEqual(self.pi.decidir_acesso("A1B2C3D4")["resultado"], "INVASAO")

    def test_recebe_lista_e_guarda_no_cache_json(self) -> None:
        canal = self.receber(LISTA_DO_SERVIDOR)
        self.assertEqual(canal.acks, 1)
        self.assertEqual(len(self.pi.colaboradores_cache), 2)

        # A lista sobrevive a um reinício da Pi
        reiniciada = RaspberryPiClient(dispositivo="sala-aaa", pasta_dados=self.temp_dir.name)
        self.assertEqual(len(reiniciada.colaboradores_cache), 2)

    def test_mensagem_fora_do_contrato_e_descartada(self) -> None:
        self.receber(LISTA_DO_SERVIDOR)
        canal = self.receber({"versao": 2})
        self.assertEqual(canal.nacks, 1)
        self.assertEqual(len(self.pi.colaboradores_cache), 2)

    def test_decisao_autonoma(self) -> None:
        self.receber(LISTA_DO_SERVIDOR)

        ev1 = self.pi.decidir_acesso("A1B2C3D4")
        self.assertEqual(ev1["resultado"], "ENTRADA")
        self.assertEqual(ev1["mensagem"], "Bem-vindo, Ana")
        self.assertEqual(ev1["versao"], 1)
        self.assertEqual(ev1["dispositivo"], "sala-aaa")

        ev2 = self.pi.decidir_acesso("A1B2C3D4")
        self.assertEqual(ev2["resultado"], "SAIDA")
        self.assertEqual(ev2["mensagem"], "Até logo, Ana")

        ev3 = self.pi.decidir_acesso("A1B2C3D4")
        self.assertEqual(ev3["resultado"], "ENTRADA")
        self.assertEqual(ev3["mensagem"], "Bem-vindo de volta, Ana")

        ev4 = self.pi.decidir_acesso("C3D4E5F6")
        self.assertEqual(ev4["resultado"], "NEGADO")
        self.assertEqual(ev4["mensagem"], "Acesso negado, Carlos")

        ev5 = self.pi.decidir_acesso("FF998877")
        self.assertEqual(ev5["resultado"], "INVASAO")
        self.assertEqual(ev5["mensagem"], "Acesso negado, tag não cadastrada")
        self.assertIsNone(ev5["nome"])
        self.assertIsNone(ev5["colaborador_id"])

    def test_quem_perde_acesso_dentro_da_sala_ainda_sai(self) -> None:
        self.receber(LISTA_DO_SERVIDOR)
        self.assertEqual(self.pi.decidir_acesso("A1B2C3D4")["resultado"], "ENTRADA")

        bloqueada = json.loads(json.dumps(LISTA_DO_SERVIDOR))
        bloqueada["colaboradores"][0]["ativo"] = False
        self.receber(bloqueada)

        self.assertEqual(self.pi.decidir_acesso("A1B2C3D4")["resultado"], "SAIDA")
        self.assertEqual(self.pi.decidir_acesso("A1B2C3D4")["resultado"], "NEGADO")


if __name__ == "__main__":
    unittest.main()

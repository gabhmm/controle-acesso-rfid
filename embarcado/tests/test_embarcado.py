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

    def test_lista_repetida_nao_regrava_o_cache(self) -> None:
        """O servidor republica a lista a cada minuto; lista igual não regrava o cache.json."""
        self.receber(LISTA_DO_SERVIDOR)
        dados = json.loads(self.pi.cache_file.read_text(encoding="utf-8"))
        dados["marcador"] = "intocado"
        self.pi.cache_file.write_text(json.dumps(dados), encoding="utf-8")

        canal = self.receber(dict(LISTA_DO_SERVIDOR, atualizado_em="2026-11-09T22:24:53-03:00"))
        self.assertEqual(canal.acks, 1)
        self.assertIn("marcador", json.loads(self.pi.cache_file.read_text(encoding="utf-8")))

        # Lista diferente regrava
        alterada = json.loads(json.dumps(LISTA_DO_SERVIDOR))
        alterada["colaboradores"][0]["ativo"] = False
        self.receber(alterada)
        self.assertNotIn("marcador", json.loads(self.pi.cache_file.read_text(encoding="utf-8")))

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


class TestPendentes(unittest.TestCase):
    """Eventos que não chegam ao broker ficam em pendentes.jsonl e são reenviados depois."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.pi = RaspberryPiClient(dispositivo="sala-aaa", pasta_dados=self.temp_dir.name)
        self.pi.sinalizar = lambda evento: None  # sem LED nem texto nos testes
        self.broker_no_ar = False
        self.enviados: list[str] = []

        def enviar_falso(evento: dict) -> bool:
            if self.broker_no_ar:
                self.enviados.append(evento["evento_id"])
            return self.broker_no_ar

        self.pi._enviar_evento_ao_broker = enviar_falso

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_broker_fora_guarda_e_reenvia_em_ordem(self) -> None:
        ev1 = self.pi.processar_leitura("FF000001")
        ev2 = self.pi.processar_leitura("FF000002")
        self.assertEqual(len(self.pi._ler_pendentes()), 2)

        # Rede volta: o reenvio periódico manda tudo, sem ninguém passar o cartão
        self.broker_no_ar = True
        self.pi._reenviar_pendentes_se_houver()
        self.assertEqual(self.enviados, [ev1["evento_id"], ev2["evento_id"]])
        self.assertFalse(self.pi.pendentes_file.exists())

    def test_broker_ainda_fora_mantem_pendentes(self) -> None:
        self.pi.processar_leitura("FF000001")
        self.pi._reenviar_pendentes_se_houver()
        self.assertEqual(len(self.pi._ler_pendentes()), 1)

    def test_evento_gravado_durante_o_reenvio_nao_se_perde(self) -> None:
        self.pi.processar_leitura("FF000001")
        self.broker_no_ar = True
        envio_original = self.pi._enviar_evento_ao_broker
        novo: dict = {}
        cartao_chegou = False

        def enviar_e_chegar_cartao(evento: dict) -> bool:
            # Enquanto o reenvio acontece, outro cartão chega com o broker caindo de novo
            nonlocal cartao_chegou
            if not cartao_chegou:
                cartao_chegou = True
                self.broker_no_ar = False
                novo.update(self.pi.processar_leitura("FF000002"))
                self.broker_no_ar = True
            return envio_original(evento)

        self.pi._enviar_evento_ao_broker = enviar_e_chegar_cartao
        self.pi._reenviar_pendentes_se_houver()

        restantes = [json.loads(l)["evento_id"] for l in self.pi._ler_pendentes()]
        self.assertEqual(restantes, [novo["evento_id"]])

    def test_linha_corrompida_e_descartada(self) -> None:
        self.pi.processar_leitura("FF000001")
        with open(self.pi.pendentes_file, "a", encoding="utf-8") as f:
            f.write("{isso não é json\n")
        self.broker_no_ar = True
        self.pi._reenviar_pendentes_se_houver()
        self.assertEqual(len(self.enviados), 1)
        self.assertFalse(self.pi.pendentes_file.exists())


if __name__ == "__main__":
    unittest.main()

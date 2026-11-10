from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from hardware.rfid_reader import RaspberryPiClient
from server.database import DatabaseRepository
from server.models import Colaborador
from server.rabbit_producer import RabbitMQProducer
from server.redis_client import RedisClient
from server.services import AccessService
from worker.consumer import EventConsumer


class TestControleAcessoContratoRabbitMQ(unittest.TestCase):
    """Testes cobrindo 100% da especificação do Contrato de Mensageria — RabbitMQ v1 (@Brayan)."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_acesso.db"
        self.repo = DatabaseRepository(db_path=self.db_path)
        self.repo.init_db(seed_default=False)
        self.redis = RedisClient(habilitado=False)
        self.rabbit = RabbitMQProducer(habilitado=False)
        self.service = AccessService(repo=self.repo, redis=self.redis, rabbit=self.rabbit)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_01_banco_dados_crud_colaboradores(self) -> None:
        novo = Colaborador(
            id=None,
            nome="Ana",
            matricula="01",
            tag_uid="A1B2C3D4",
            cargo="Artist",
            acesso_sala=True,
            ativo=True,
        )
        criado = self.repo.criar_colaborador(novo)
        self.assertIsNotNone(criado.id)
        self.assertEqual(criado.tag_uid, "A1B2C3D4")

        buscado_id = self.repo.obter_colaborador_por_id(criado.id)
        self.assertIsNotNone(buscado_id)
        self.assertEqual(buscado_id.nome, "Ana")

        # Atualizar
        criado.acesso_sala = False
        atualizado = self.repo.atualizar_colaborador(criado.id, criado)
        self.assertFalse(atualizado.acesso_sala)

        # Excluir
        removido = self.repo.excluir_colaborador(criado.id)
        self.assertTrue(removido)

    def test_02_regras_negocio_mensagens_pdf(self) -> None:
        self.repo.criar_colaborador(
            Colaborador(id=None, nome="Carlos", matricula="03", tag_uid="C3D4E5F6", cargo="QA", acesso_sala=False, ativo=True)
        )
        self.repo.criar_colaborador(
            Colaborador(id=None, nome="Bruno", matricula="02", tag_uid="B2C3D4E5", cargo="Dev", acesso_sala=True, ativo=True)
        )

        agora = datetime(2026, 11, 9, 8, 0, 0)

        # INVASAO: Mensagem exata exigida na Página 4 do PDF
        resp_inv = self.service.validar_acesso("UNKNOWN_TAG", agora=agora)
        self.assertEqual(resp_inv.resultado, "INVASAO")
        self.assertEqual(resp_inv.mensagem, "Acesso negado, tag não cadastrada")

        # NEGADO
        resp_neg = self.service.validar_acesso("C3D4E5F6", agora=agora)
        self.assertEqual(resp_neg.resultado, "NEGADO")
        self.assertEqual(resp_neg.mensagem, "Acesso negado, Carlos")

        # ENTRADA
        resp_ent1 = self.service.validar_acesso("B2C3D4E5", agora=agora)
        self.assertEqual(resp_ent1.resultado, "ENTRADA")
        self.assertEqual(resp_ent1.mensagem, "Bem-vindo, Bruno")

        # SAIDA
        resp_sai = self.service.validar_acesso("B2C3D4E5", agora=agora + timedelta(hours=4))
        self.assertEqual(resp_sai.resultado, "SAIDA")
        self.assertEqual(resp_sai.mensagem, "Até logo, Bruno")

        # ENTRADA (volta)
        resp_ent2 = self.service.validar_acesso("B2C3D4E5", agora=agora + timedelta(hours=5))
        self.assertEqual(resp_ent2.resultado, "ENTRADA")
        self.assertEqual(resp_ent2.mensagem, "Bem-vindo de volta, Bruno")

    def test_03_worker_consumo_e_deduplicacao(self) -> None:
        """Testa o consumidor processando mensagem idêntica à Página 3 do PDF e ignorando duplicata."""
        consumer = EventConsumer(db_path=self.db_path)
        evento_uuid = str(uuid.uuid4())

        msg_pdf = {
            "versao": 1,
            "evento_id": evento_uuid,
            "dispositivo": "sala-aaa",
            "data_hora": "2026-11-06T20:15:02-03:00",
            "tag_uid": "A1B2C3D4",
            "colaborador_id": 1,
            "nome": "Ana",
            "resultado": "ENTRADA",
            "mensagem": "Bem-vindo, Ana",
        }

        class MockChannel:
            acks = 0
            nacks = 0
            def basic_ack(self, delivery_tag: int) -> None:
                self.acks += 1
            def basic_nack(self, delivery_tag: int, requeue: bool = False) -> None:
                self.nacks += 1

        class MockMethod:
            delivery_tag = 1

        canal = MockChannel()
        corpo = json.dumps(msg_pdf).encode("utf-8")

        # 1. Primeira entrega -> Grava no SQLite e dá ACK
        consumer.processar_mensagem(canal, MockMethod(), None, corpo)
        self.assertEqual(canal.acks, 1)

        eventos = self.repo.listar_eventos()
        self.assertEqual(len(eventos), 1)
        self.assertEqual(eventos[0].evento_id, evento_uuid)
        self.assertEqual(eventos[0].data_hora, "2026-11-06 20:15:02")

        # 2. Reentrega da mesma mensagem (mesmo evento_id) -> Não duplica!
        consumer.processar_mensagem(canal, MockMethod(), None, corpo)
        self.assertEqual(canal.acks, 2)
        eventos_apos_reentrega = self.repo.listar_eventos()
        self.assertEqual(len(eventos_apos_reentrega), 1)  # Mantém exatamente 1 registro

        # 3. Mensagem com versão inválida -> nack sem requeue
        msg_invalida = dict(msg_pdf, versao=2)
        consumer.processar_mensagem(canal, MockMethod(), None, json.dumps(msg_invalida).encode("utf-8"))
        self.assertEqual(canal.nacks, 1)

    def test_04_publicacao_colaboradores_servidor_para_pi(self) -> None:
        """Testa o envio de lista de colaboradores (Servidor -> Pi) conforme Página 3 do PDF."""
        colabs = [
            {"id": 1, "nome": "Ana", "tag_uid": "A1B2C3D4", "acesso_sala": True, "ativo": True}
        ]
        self.rabbit.fila_memoria.clear()
        self.rabbit.publicar_colaboradores(colabs)

        self.assertEqual(len(self.rabbit.fila_memoria), 1)
        enviado = self.rabbit.fila_memoria[0]
        self.assertEqual(enviado["versao"], 1)
        self.assertIn("atualizado_em", enviado)
        self.assertEqual(len(enviado["colaboradores"]), 1)
        self.assertEqual(enviado["colaboradores"][0]["tag_uid"], "A1B2C3D4")

    def test_05_decisao_autonoma_na_raspberry_pi(self) -> None:
        """Testa a Pi decidindo o acesso localmente usando seu cache.json e regras."""
        pi = RaspberryPiClient(dispositivo="sala-aaa")
        # Simula cache recebido da Pi
        pi.colaboradores_cache = [
            {"id": 1, "nome": "Ana", "tag_uid": "A1B2C3D4", "acesso_sala": True, "ativo": True},
            {"id": 2, "nome": "Carlos", "tag_uid": "C3D4E5F6", "acesso_sala": False, "ativo": True},
        ]
        pi.estado_local.clear()

        # 1. Ana (autorizada) -> ENTRADA
        ev1 = pi.decidir_acesso("A1B2C3D4")
        self.assertEqual(ev1["resultado"], "ENTRADA")
        self.assertEqual(ev1["versao"], 1)
        self.assertEqual(ev1["nome"], "Ana")
        self.assertEqual(ev1["dispositivo"], "sala-aaa")

        # 2. Carlos (bloqueado) -> NEGADO
        ev2 = pi.decidir_acesso("C3D4E5F6")
        self.assertEqual(ev2["resultado"], "NEGADO")

        # 3. Desconhecido -> INVASAO (mensagem exata da Página 4)
        ev3 = pi.decidir_acesso("FF998877")
        self.assertEqual(ev3["resultado"], "INVASAO")
        self.assertEqual(ev3["mensagem"], "Acesso negado, tag não cadastrada")
        self.assertIsNone(ev3["nome"])
        self.assertIsNone(ev3["colaborador_id"])


if __name__ == "__main__":
    unittest.main()

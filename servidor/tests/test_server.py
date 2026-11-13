from __future__ import annotations

import json
import tempfile
import unittest
import uuid

from pathlib import Path

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
        self.service = AccessService(repo=self.repo, redis=self.redis)

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

    def test_03b_worker_falha_do_banco_devolve_evento_a_fila(self) -> None:
        """Falha do banco não pode descartar o evento: ele volta para a fila. Dado inválido é descartado."""
        import sqlite3
        import worker.consumer as modulo_consumer

        modulo_consumer.PAUSA_FALHA_BANCO_SEGUNDOS = 0
        consumer = EventConsumer(db_path=self.db_path)

        class CanalComRequeue:
            def __init__(self) -> None:
                self.nacks: list[bool] = []
            def basic_ack(self, delivery_tag: int) -> None:
                raise AssertionError("não deveria dar ack")
            def basic_nack(self, delivery_tag: int, requeue: bool = False) -> None:
                self.nacks.append(requeue)

        class MockMethod:
            delivery_tag = 1

        evento = {
            "versao": 1, "evento_id": str(uuid.uuid4()), "dispositivo": "sala-aaa",
            "data_hora": "2026-11-06T20:15:02-03:00", "tag_uid": "A1B2C3D4",
            "colaborador_id": 1, "nome": "Ana", "resultado": "ENTRADA", "mensagem": "Bem-vindo, Ana",
        }

        # Banco fora do ar / schema antigo -> requeue=True
        def falha_banco(*args, **kwargs):
            raise sqlite3.OperationalError("table eventos has no column named colaborador_id")

        consumer.repo.registrar_evento = falha_banco
        canal = CanalComRequeue()
        consumer.processar_mensagem(canal, MockMethod(), None, json.dumps(evento).encode("utf-8"))
        self.assertEqual(canal.nacks, [True])

        # Resultado fora da lista (CHECK do banco) -> descarta
        consumer = EventConsumer(db_path=self.db_path)
        canal = CanalComRequeue()
        invalido = dict(evento, evento_id=str(uuid.uuid4()), resultado="QUALQUER")
        consumer.processar_mensagem(canal, MockMethod(), None, json.dumps(invalido).encode("utf-8"))
        self.assertEqual(canal.nacks, [False])

        # JSON malformado -> descarta
        canal = CanalComRequeue()
        consumer.processar_mensagem(canal, MockMethod(), None, b"{nao e json")
        self.assertEqual(canal.nacks, [False])

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


    def test_05_servidor_republica_a_lista_periodicamente(self) -> None:
        """Uma Pi que liga sem cache.json recebe a lista sem depender de edição no painel."""
        import time
        from fastapi.testclient import TestClient
        import server.app as modulo_app

        publicacoes: list[int] = []

        class ProdutorFalso:
            def publicar_colaboradores(self, colaboradores: list) -> bool:
                publicacoes.append(len(colaboradores))
                return True

        produtor_original = modulo_app.rabbit_producer
        intervalo_original = modulo_app.REPUBLICAR_LISTA_SEGUNDOS
        modulo_app.rabbit_producer = ProdutorFalso()
        modulo_app.REPUBLICAR_LISTA_SEGUNDOS = 0.1
        try:
            app = modulo_app.create_app(db_path=self.db_path, seed_default=True)
            with TestClient(app):
                time.sleep(0.5)
            parado_em = len(publicacoes)
            time.sleep(0.3)
        finally:
            modulo_app.rabbit_producer = produtor_original
            modulo_app.REPUBLICAR_LISTA_SEGUNDOS = intervalo_original

        # 1 publicação ao iniciar + várias periódicas, sempre com os 5 colaboradores
        self.assertGreaterEqual(parado_em, 3)
        self.assertTrue(all(n == 5 for n in publicacoes))
        # Depois do shutdown, a thread para
        self.assertEqual(len(publicacoes), parado_em)


if __name__ == "__main__":
    unittest.main()

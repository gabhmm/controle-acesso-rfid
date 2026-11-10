from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from server.app import create_app
from server.database import DatabaseRepository
from server.services import AccessService


class TestControleAcessoServer(unittest.TestCase):
    """Testes automatizados cobrindo todas as rotas e regras de negócio do Controle de Acesso v1."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_acesso.db"
        self.app = create_app(db_path=self.db_path, seed_default=False)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.repo: DatabaseRepository = self.app.config["REPO"]
        self.service: AccessService = self.app.config["SERVICE"]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_01_login_sucesso_e_falha(self) -> None:
        # Login inválido -> 401
        res_err = self.client.post("/login", json={"usuario": "admin", "senha": "123"})
        self.assertEqual(res_err.status_code, 401)

        # Login válido -> 200
        res_ok = self.client.post("/login", json={"usuario": "admin", "senha": "admin"})
        self.assertEqual(res_ok.status_code, 200)
        self.assertTrue(res_ok.get_json()["ok"])

    def test_02_crud_colaboradores_e_campos_estado(self) -> None:
        # 1. Cadastrar Ana
        payload = {
            "nome": "Ana",
            "matricula": "01",
            "tag_uid": "a1b2c3d4",
            "cargo": "Artist",
            "acesso_sala": True,
            "ativo": True,
        }
        res_post = self.client.post("/api/colaboradores", json=payload)
        self.assertEqual(res_post.status_code, 200)
        criado = res_post.get_json()
        self.assertEqual(criado["id"], 1)
        self.assertEqual(criado["tag_uid"], "A1B2C3D4")  # Normalizado em uppercase

        # 2. Duplicidade de tag_uid ou matrícula -> 400
        res_dup = self.client.post("/api/colaboradores", json=payload)
        self.assertEqual(res_dup.status_code, 400)

        # 3. Listar colaboradores (verifica campos na_sala, entrou_hoje, tempo_hoje_segundos)
        res_get = self.client.get("/api/colaboradores")
        self.assertEqual(res_get.status_code, 200)
        lista = res_get.get_json()
        self.assertEqual(len(lista), 1)
        self.assertIn("na_sala", lista[0])
        self.assertIn("entrou_hoje", lista[0])
        self.assertIn("tempo_hoje_segundos", lista[0])
        self.assertFalse(lista[0]["na_sala"])
        self.assertFalse(lista[0]["entrou_hoje"])

        # 4. Editar colaborador (PUT)
        res_put = self.client.put(
            "/api/colaboradores/1",
            json={
                "nome": "Ana Silva",
                "matricula": "01",
                "tag_uid": "A1B2C3D4",
                "cargo": "Lead Artist",
                "acesso_sala": False,
                "ativo": True,
            },
        )
        self.assertEqual(res_put.status_code, 200)
        atualizado = res_put.get_json()
        self.assertEqual(atualizado["nome"], "Ana Silva")
        self.assertFalse(atualizado["acesso_sala"])

        # 5. Excluir colaborador (DELETE)
        res_del = self.client.delete("/api/colaboradores/1")
        self.assertEqual(res_del.status_code, 200)
        self.assertEqual(len(self.client.get("/api/colaboradores").get_json()), 0)

    def test_03_regras_de_validacao_completas(self) -> None:
        # Cadastra colaboradores para cada caso de teste
        self.client.post(
            "/api/colaboradores",
            json={
                "nome": "Ana",
                "matricula": "01",
                "tag_uid": "A1B2C3D4",
                "cargo": "Artist",
                "acesso_sala": True,
                "ativo": True,
            },
        )
        self.client.post(
            "/api/colaboradores",
            json={
                "nome": "Carlos",
                "matricula": "02",
                "tag_uid": "C3D4E5F6",
                "cargo": "Sound",
                "acesso_sala": False,
                "ativo": True,
            },
        )
        self.client.post(
            "/api/colaboradores",
            json={
                "nome": "Diana",
                "matricula": "03",
                "tag_uid": "D4E5F607",
                "cargo": "Ex-Artist",
                "acesso_sala": True,
                "ativo": False,
            },
        )

        # Caso 1: Tag não cadastrada -> INVASAO
        r_inv = self.client.post("/api/validar", json={"tag_uid": "FF998877"}).get_json()
        self.assertEqual(r_inv["resultado"], "INVASAO")

        # Caso 2: Colaborador sem permissão à sala -> NEGADO
        r_neg1 = self.client.post("/api/validar", json={"tag_uid": "C3D4E5F6"}).get_json()
        self.assertEqual(r_neg1["resultado"], "NEGADO")
        self.assertIn("Carlos", r_neg1["mensagem"])

        # Caso 3: Colaborador inativo -> NEGADO
        r_neg2 = self.client.post("/api/validar", json={"tag_uid": "D4E5F607"}).get_json()
        self.assertEqual(r_neg2["resultado"], "NEGADO")
        self.assertIn("Diana", r_neg2["mensagem"])

        # Caso 4: Colaborador autorizado (1ª entrada no dia) -> "Bem-vindo, Ana"
        r_ent1 = self.client.post("/api/validar", json={"tag_uid": "A1B2C3D4"}).get_json()
        self.assertEqual(r_ent1["resultado"], "ENTRADA")
        self.assertEqual(r_ent1["mensagem"], "Bem-vindo, Ana")

        # Verifica que Ana consta como na_sala=True e entrou_hoje=True no GET /api/colaboradores
        colabs_apos_entrada = self.client.get("/api/colaboradores").get_json()
        ana_estado = next(c for c in colabs_apos_entrada if c["tag_uid"] == "A1B2C3D4")
        self.assertTrue(ana_estado["na_sala"])
        self.assertTrue(ana_estado["entrou_hoje"])

        # Caso 5: Colaborador autorizado passa novamente -> SAIDA ("Até logo, Ana")
        r_sai = self.client.post("/api/validar", json={"tag_uid": "A1B2C3D4"}).get_json()
        self.assertEqual(r_sai["resultado"], "SAIDA")
        self.assertEqual(r_sai["mensagem"], "Até logo, Ana")

        # Caso 6: Colaborador autorizado retorna no mesmo dia -> ENTRADA ("Bem-vindo de volta, Ana")
        r_ent2 = self.client.post("/api/validar", json={"tag_uid": "A1B2C3D4"}).get_json()
        self.assertEqual(r_ent2["resultado"], "ENTRADA")
        self.assertEqual(r_ent2["mensagem"], "Bem-vindo de volta, Ana")

        # Verifica GET /api/eventos (6 eventos hoje, mais recente primeiro)
        eventos = self.client.get("/api/eventos").get_json()
        self.assertEqual(len(eventos), 6)
        self.assertEqual(eventos[0]["resultado"], "ENTRADA")
        self.assertEqual(eventos[-1]["resultado"], "INVASAO")

        # Verifica GET /api/eventos.csv
        res_csv = self.client.get("/api/eventos.csv")
        self.assertEqual(res_csv.status_code, 200)
        linhas_csv = res_csv.get_data(as_text=True).strip().splitlines()
        self.assertEqual(linhas_csv[0], "id,data_hora,tag_uid,nome,resultado")
        self.assertEqual(len(linhas_csv), 7)  # 1 header + 6 eventos

    def test_04_calculo_tempo_diario_permanencia(self) -> None:
        self.client.post(
            "/api/colaboradores",
            json={
                "nome": "Ana",
                "matricula": "01",
                "tag_uid": "A1B2C3D4",
                "cargo": "Artist",
                "acesso_sala": True,
                "ativo": True,
            },
        )
        t1 = datetime(2026, 10, 27, 10, 0, 0)
        t2 = datetime(2026, 10, 27, 11, 30, 0)  # +5400s (1h30m)
        t3 = datetime(2026, 10, 27, 14, 0, 0)
        t4 = datetime(2026, 10, 27, 14, 30, 0)  # +1800s (30m) -> Total 7200s (2h)

        self.service.validar_acesso("A1B2C3D4", agora=t1)
        self.service.validar_acesso("A1B2C3D4", agora=t2)
        self.service.validar_acesso("A1B2C3D4", agora=t3)

        # Enquanto ainda está na sala às 14:30:
        colabs = self.service.listar_colaboradores_com_estado(agora=t4)
        self.assertTrue(colabs[0].na_sala)
        self.assertEqual(colabs[0].tempo_hoje_segundos, 7200)


if __name__ == "__main__":
    unittest.main()

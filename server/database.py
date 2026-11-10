from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

from server.config import DB_PATH
from server.models import Colaborador, Evento, ResultadoEvento


class DatabaseRepository:
    """Repositório SQLite3 para gestão de colaboradores e eventos de acesso."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path: Path = Path(db_path) if db_path is not None else DB_PATH

    @contextmanager
    def _get_connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def init_db(self, seed_default: bool = True) -> None:
        """Cria as tabelas caso não existam e opcionalmente insere dados iniciais."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS colaboradores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT NOT NULL,
                    matricula TEXT NOT NULL UNIQUE,
                    tag_uid TEXT NOT NULL UNIQUE,
                    cargo TEXT NOT NULL,
                    acesso_sala INTEGER NOT NULL DEFAULT 1,
                    ativo INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS eventos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data_hora TEXT NOT NULL,
                    tag_uid TEXT NOT NULL,
                    nome TEXT NOT NULL,
                    resultado TEXT NOT NULL CHECK (resultado IN ('ENTRADA', 'SAIDA', 'NEGADO', 'INVASAO'))
                );

                CREATE INDEX IF NOT EXISTS idx_eventos_data_hora ON eventos(data_hora DESC);
                CREATE INDEX IF NOT EXISTS idx_eventos_tag_uid ON eventos(tag_uid);
                """
            )

            if seed_default:
                cur = conn.execute("SELECT COUNT(*) AS total FROM colaboradores")
                total: int = int(cur.fetchone()["total"])
                if total == 0:
                    iniciais: list[tuple[str, str, str, str, int, int]] = [
                        ("Ana", "01", "A1B2C3D4", "Character Artist", 1, 1),
                        ("Bruno", "02", "B2C3D4E5", "Lead Concept Artist", 1, 1),
                        ("Carlos", "03", "C3D4E5F6", "Sound Designer", 0, 1),
                        ("Diana", "04", "D4E5F607", "3D Modeler (Ex-Colab)", 1, 0),
                    ]
                    conn.executemany(
                        """
                        INSERT INTO colaboradores (nome, matricula, tag_uid, cargo, acesso_sala, ativo)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        iniciais,
                    )
            conn.commit()

    @staticmethod
    def _row_to_colaborador(row: sqlite3.Row) -> Colaborador:
        return Colaborador(
            id=int(row["id"]),
            nome=str(row["nome"]),
            matricula=str(row["matricula"]),
            tag_uid=str(row["tag_uid"]),
            cargo=str(row["cargo"]),
            acesso_sala=bool(row["acesso_sala"]),
            ativo=bool(row["ativo"]),
        )

    @staticmethod
    def _row_to_evento(row: sqlite3.Row) -> Evento:
        return Evento(
            id=int(row["id"]),
            data_hora=str(row["data_hora"]),
            tag_uid=str(row["tag_uid"]),
            nome=str(row["nome"]),
            resultado=cast(ResultadoEvento, str(row["resultado"])),
        )

    def listar_colaboradores(self) -> list[Colaborador]:
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT id, nome, matricula, tag_uid, cargo, acesso_sala, ativo FROM colaboradores ORDER BY id ASC"
            )
            return [self._row_to_colaborador(row) for row in cur.fetchall()]

    def obter_colaborador_por_id(self, colab_id: int) -> Colaborador | None:
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT id, nome, matricula, tag_uid, cargo, acesso_sala, ativo FROM colaboradores WHERE id = ?",
                (colab_id,),
            )
            row = cur.fetchone()
            return self._row_to_colaborador(row) if row else None

    def obter_colaborador_por_tag(self, tag_uid: str) -> Colaborador | None:
        tag_norm = tag_uid.strip().upper()
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT id, nome, matricula, tag_uid, cargo, acesso_sala, ativo FROM colaboradores WHERE UPPER(tag_uid) = ?",
                (tag_norm,),
            )
            row = cur.fetchone()
            return self._row_to_colaborador(row) if row else None

    def criar_colaborador(self, colab: Colaborador) -> Colaborador:
        tag_norm = colab.tag_uid.strip().upper()
        matricula_norm = colab.matricula.strip()
        with self._get_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO colaboradores (nome, matricula, tag_uid, cargo, acesso_sala, ativo)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    colab.nome.strip(),
                    matricula_norm,
                    tag_norm,
                    colab.cargo.strip(),
                    1 if colab.acesso_sala else 0,
                    1 if colab.ativo else 0,
                ),
            )
            conn.commit()
            novo_id = int(cur.lastrowid) if cur.lastrowid is not None else 0
        criado = self.obter_colaborador_por_id(novo_id)
        if criado is None:
            raise RuntimeError("Falha ao recuperar colaborador recém-criado.")
        return criado

    def atualizar_colaborador(self, colab_id: int, colab: Colaborador) -> Colaborador | None:
        tag_norm = colab.tag_uid.strip().upper()
        matricula_norm = colab.matricula.strip()
        with self._get_connection() as conn:
            cur = conn.execute(
                """
                UPDATE colaboradores
                SET nome = ?, matricula = ?, tag_uid = ?, cargo = ?, acesso_sala = ?, ativo = ?
                WHERE id = ?
                """,
                (
                    colab.nome.strip(),
                    matricula_norm,
                    tag_norm,
                    colab.cargo.strip(),
                    1 if colab.acesso_sala else 0,
                    1 if colab.ativo else 0,
                    colab_id,
                ),
            )
            conn.commit()
            if cur.rowcount == 0:
                return None
        return self.obter_colaborador_por_id(colab_id)

    def excluir_colaborador(self, colab_id: int) -> bool:
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM colaboradores WHERE id = ?", (colab_id,))
            conn.commit()
            return cur.rowcount > 0

    def registrar_evento(self, data_hora: str, tag_uid: str, nome: str, resultado: ResultadoEvento) -> Evento:
        tag_norm = tag_uid.strip().upper()
        with self._get_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO eventos (data_hora, tag_uid, nome, resultado)
                VALUES (?, ?, ?, ?)
                """,
                (data_hora, tag_norm, nome, resultado),
            )
            conn.commit()
            novo_id = int(cur.lastrowid) if cur.lastrowid is not None else 0
        return Evento(id=novo_id, data_hora=data_hora, tag_uid=tag_norm, nome=nome, resultado=resultado)

    def listar_eventos(self, data_prefixo: str | None = None) -> list[Evento]:
        """Retorna eventos ordenados do mais recente para o mais antigo.
        Se data_prefixo ('YYYY-MM-DD') for informado, filtra apenas os eventos daquele dia.
        """
        with self._get_connection() as conn:
            if data_prefixo:
                cur = conn.execute(
                    """
                    SELECT id, data_hora, tag_uid, nome, resultado
                    FROM eventos
                    WHERE data_hora LIKE ?
                    ORDER BY data_hora DESC, id DESC
                    """,
                    (f"{data_prefixo}%",),
                )
            else:
                cur = conn.execute(
                    """
                    SELECT id, data_hora, tag_uid, nome, resultado
                    FROM eventos
                    ORDER BY data_hora DESC, id DESC
                    """
                )
            return [self._row_to_evento(row) for row in cur.fetchall()]

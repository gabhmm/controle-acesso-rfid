from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

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
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            # 1. Cria tabelas base
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS colaboradores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT NOT NULL,
                    matricula TEXT NOT NULL UNIQUE,
                    tag_uid TEXT NOT NULL UNIQUE,
                    cargo TEXT NOT NULL,
                    acesso_sala INTEGER NOT NULL DEFAULT 1,
                    ativo INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS eventos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    evento_id TEXT UNIQUE,
                    data_hora TEXT NOT NULL,
                    tag_uid TEXT NOT NULL,
                    nome TEXT,
                    resultado TEXT NOT NULL CHECK (resultado IN ('ENTRADA', 'SAIDA', 'NEGADO', 'INVASAO')),
                    colaborador_id INTEGER,
                    mensagem TEXT,
                    dispositivo TEXT
                )
                """
            )

            # Migração caso a coluna evento_id ainda não exista na tabela existente
            cur_info = conn.execute("PRAGMA table_info(eventos)")
            colunas = [row["name"] for row in cur_info.fetchall()]
            if "evento_id" not in colunas and colunas:
                try:
                    conn.execute("ALTER TABLE eventos ADD COLUMN evento_id TEXT")
                    conn.commit()
                except Exception:
                    pass

            conn.execute("CREATE INDEX IF NOT EXISTS idx_eventos_data_hora ON eventos(data_hora DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_eventos_tag_uid ON eventos(tag_uid)")
            try:
                conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_eventos_uid ON eventos(evento_id)")
            except Exception:
                pass

            if seed_default:
                cur = conn.execute("SELECT COUNT(*) AS total FROM colaboradores")
                total: int = int(cur.fetchone()["total"])
                if total == 0:
                    colaboradores_iniciais = [
                        ("Ana", "01", "A1B2C3D4", "Artist", 1, 1),
                        ("Bruno", "02", "B2C3D4E5", "Developer", 1, 1),
                        ("Carlos", "03", "C3D4E5F6", "Game Designer", 0, 1),
                        ("Daniela", "04", "D4E5F6A7", "Producer", 1, 0),
                        ("Eduardo", "05", "E5F6A7B8", "Sound Designer", 1, 1),
                    ]
                    conn.executemany(
                        """
                        INSERT INTO colaboradores (nome, matricula, tag_uid, cargo, acesso_sala, ativo)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        colaboradores_iniciais,
                    )
            conn.commit()

    @staticmethod
    def _row_to_colaborador(row: sqlite3.Row) -> Colaborador:
        return Colaborador(
            id=int(row["id"]),
            nome=str(row["nome"]),
            matricula=str(row["matricula"]),
            tag_uid=str(row["tag_uid"]).upper(),
            cargo=str(row["cargo"]),
            acesso_sala=bool(row["acesso_sala"]),
            ativo=bool(row["ativo"]),
        )

    @staticmethod
    def _row_to_evento(row: sqlite3.Row) -> Evento:
        return Evento(
            id=int(row["id"]),
            evento_id=str(row["evento_id"]) if row["evento_id"] else None,
            data_hora=str(row["data_hora"]),
            tag_uid=str(row["tag_uid"]).upper(),
            nome=str(row["nome"]) if row["nome"] else "Desconhecido",
            resultado=str(row["resultado"]),  # type: ignore[arg-type]
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
        return Colaborador(
            id=novo_id,
            nome=colab.nome.strip(),
            matricula=matricula_norm,
            tag_uid=tag_norm,
            cargo=colab.cargo.strip(),
            acesso_sala=colab.acesso_sala,
            ativo=colab.ativo,
        )

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

    def registrar_evento(
        self,
        data_hora_ou_evento: str | Evento,
        tag_uid: str | None = None,
        nome: str | None = None,
        resultado: ResultadoEvento | None = None,
        evento_id: str | None = None,
        colaborador_id: int | None = None,
        mensagem: str | None = None,
        dispositivo: str | None = None,
    ) -> Evento | None:
        """Registra um evento de acesso. Se evento_id for duplicado, ignora (INSERT OR IGNORE)."""
        if isinstance(data_hora_ou_evento, Evento):
            ev = data_hora_ou_evento
            d_hora = ev.data_hora
            t_uid = ev.tag_uid.strip().upper()
            n_nome = ev.nome
            r_resultado = ev.resultado
            e_id = ev.evento_id
            c_id = ev.colaborador_id
            m_msg = ev.mensagem
            disp = ev.dispositivo
        else:
            d_hora = data_hora_ou_evento
            t_uid = (tag_uid or "DESCONHECIDO").strip().upper()
            n_nome = nome or "Desconhecido"
            r_resultado = resultado or "INVASAO"
            e_id = evento_id
            c_id = colaborador_id
            m_msg = mensagem
            disp = dispositivo

        with self._get_connection() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO eventos (evento_id, data_hora, tag_uid, nome, resultado, colaborador_id, mensagem, dispositivo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (e_id, d_hora, t_uid, n_nome, r_resultado, c_id, m_msg, disp),
            )
            conn.commit()
            novo_id = int(cur.lastrowid) if cur.lastrowid is not None else 0
        return Evento(
            id=novo_id,
            evento_id=e_id,
            data_hora=d_hora,
            tag_uid=t_uid,
            nome=n_nome,
            resultado=r_resultado,
            colaborador_id=c_id,
            mensagem=m_msg,
            dispositivo=disp,
        )

    def listar_eventos(self, data_prefixo: str | None = None) -> list[Evento]:
        """Retorna eventos ordenados sempre por data_hora DESC (momento da leitura), conforme o PDF."""
        with self._get_connection() as conn:
            if data_prefixo:
                cur = conn.execute(
                    """
                    SELECT id, evento_id, data_hora, tag_uid, nome, resultado
                    FROM eventos
                    WHERE data_hora LIKE ?
                    ORDER BY data_hora DESC, id DESC
                    """,
                    (f"{data_prefixo}%",),
                )
            else:
                cur = conn.execute(
                    """
                    SELECT id, evento_id, data_hora, tag_uid, nome, resultado
                    FROM eventos
                    ORDER BY data_hora DESC, id DESC
                    """
                )
            return [self._row_to_evento(row) for row in cur.fetchall()]

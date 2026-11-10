from __future__ import annotations

import sqlite3
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from server.config import ADMIN_PASS, ADMIN_USER, DB_PATH, PROJECT_ROOT, SECRET_KEY
from server.database import DatabaseRepository
from server.models import Colaborador
from server.services import FORMATO_DATA, AccessService


def create_app(db_path: Path | str | None = None, seed_default: bool = True) -> Flask:
    """Factory da aplicação Flask (Server + Web Client)."""
    template_dir = PROJECT_ROOT / "client" / "templates"
    static_dir = PROJECT_ROOT / "client" / "static"

    app = Flask(
        __name__,
        template_folder=str(template_dir),
        static_folder=str(static_dir),
    )
    app.secret_key = SECRET_KEY

    repo = DatabaseRepository(db_path=db_path or DB_PATH)
    repo.init_db(seed_default=seed_default)
    service = AccessService(repo=repo)

    # Guardamos nas extensões do app para acesso limpo em testes caso necessário
    app.config["REPO"] = repo
    app.config["SERVICE"] = service

    def login_required_page(view_func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view_func)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            if not session.get("autenticado"):
                return redirect(url_for("pagina_login"))
            return view_func(*args, **kwargs)

        return wrapped

    # -------------------------------------------------------------------------
    # ROTAS DE PÁGINAS WEB (Front-end exige login)
    # -------------------------------------------------------------------------

    @app.get("/")
    def index() -> Any:
        if session.get("autenticado"):
            return redirect(url_for("pagina_monitor"))
        return redirect(url_for("pagina_login"))

    @app.get("/login")
    def pagina_login() -> Any:
        if session.get("autenticado"):
            return redirect(url_for("pagina_monitor"))
        return render_template("login.html")

    @app.get("/colaboradores")
    @login_required_page
    def pagina_colaboradores() -> Any:
        return render_template("colaboradores.html", usuario=session.get("usuario", "admin"))

    @app.get("/monitor")
    @login_required_page
    def pagina_monitor() -> Any:
        return render_template("monitor.html", usuario=session.get("usuario", "admin"))

    # -------------------------------------------------------------------------
    # ROTAS DE AUTENTICAÇÃO
    # -------------------------------------------------------------------------

    @app.post("/login")
    def api_login() -> tuple[Response, int]:
        dados: dict[str, Any] = request.get_json(silent=True) or {}
        usuario = str(dados.get("usuario", "")).strip()
        senha = str(dados.get("senha", "")).strip()

        if usuario == ADMIN_USER and senha == ADMIN_PASS:
            session["autenticado"] = True
            session["usuario"] = usuario
            return jsonify({"ok": True, "mensagem": "Autenticado com sucesso"}), 200

        return jsonify({"ok": False, "erro": "Credenciais inválidas"}), 401

    @app.post("/logout")
    def api_logout() -> tuple[Response, int]:
        session.clear()
        return jsonify({"ok": True}), 200

    # -------------------------------------------------------------------------
    # ROTAS DA API REST (Abertas na v1 conforme api contratos.md)
    # -------------------------------------------------------------------------

    @app.get("/api/colaboradores")
    def listar_colaboradores() -> Response:
        colaboradores = service.listar_colaboradores_com_estado()
        resp = jsonify([c.to_dict() for c in colaboradores])
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return resp

    @app.post("/api/colaboradores")
    def criar_colaborador() -> tuple[Response, int]:
        dados: dict[str, Any] = request.get_json(silent=True) or {}
        nome = str(dados.get("nome", "")).strip()
        matricula = str(dados.get("matricula", "")).strip()
        tag_uid = str(dados.get("tag_uid", "")).strip().upper()
        cargo = str(dados.get("cargo", "")).strip()
        acesso_sala = bool(dados.get("acesso_sala", True))
        ativo = bool(dados.get("ativo", True))

        if not nome or not matricula or not tag_uid or not cargo:
            return (
                jsonify({"erro": "Campos obrigatórios: nome, matricula, tag_uid, cargo"}),
                400,
            )

        novo = Colaborador(
            id=None,
            nome=nome,
            matricula=matricula,
            tag_uid=tag_uid,
            cargo=cargo,
            acesso_sala=acesso_sala,
            ativo=ativo,
        )
        try:
            criado = repo.criar_colaborador(novo)
            return jsonify(criado.to_dict()), 200
        except sqlite3.IntegrityError:
            return (
                jsonify({"erro": "Matrícula ou Tag RFID já cadastrada para outro colaborador."}),
                400,
            )

    @app.put("/api/colaboradores/<int:colab_id>")
    def editar_colaborador(colab_id: int) -> tuple[Response, int]:
        existente = repo.obter_colaborador_por_id(colab_id)
        if existente is None:
            return jsonify({"erro": "Colaborador não encontrado"}), 404

        dados: dict[str, Any] = request.get_json(silent=True) or {}
        nome = str(dados.get("nome", existente.nome)).strip()
        matricula = str(dados.get("matricula", existente.matricula)).strip()
        tag_uid = str(dados.get("tag_uid", existente.tag_uid)).strip().upper()
        cargo = str(dados.get("cargo", existente.cargo)).strip()
        acesso_sala = (
            bool(dados["acesso_sala"])
            if "acesso_sala" in dados
            else existente.acesso_sala
        )
        ativo = bool(dados["ativo"]) if "ativo" in dados else existente.ativo

        if not nome or not matricula or not tag_uid or not cargo:
            return (
                jsonify({"erro": "Campos obrigatórios não podem ficar vazios"}),
                400,
            )

        atualizado_obj = Colaborador(
            id=colab_id,
            nome=nome,
            matricula=matricula,
            tag_uid=tag_uid,
            cargo=cargo,
            acesso_sala=acesso_sala,
            ativo=ativo,
        )
        try:
            resultado = repo.atualizar_colaborador(colab_id, atualizado_obj)
            if resultado is None:
                return jsonify({"erro": "Colaborador não encontrado"}), 404
            return jsonify(resultado.to_dict()), 200
        except sqlite3.IntegrityError:
            return (
                jsonify({"erro": "Matrícula ou Tag RFID já pertence a outro colaborador."}),
                400,
            )

    @app.delete("/api/colaboradores/<int:colab_id>")
    def remover_colaborador(colab_id: int) -> tuple[Response, int]:
        removido = repo.excluir_colaborador(colab_id)
        if not removido:
            return jsonify({"erro": "Colaborador não encontrado"}), 404
        return jsonify({"ok": True}), 200

    @app.post("/api/validar")
    def validar_tag() -> tuple[Response, int]:
        dados: dict[str, Any] = request.get_json(silent=True) or {}
        tag_uid = str(dados.get("tag_uid", ""))
        resposta = service.validar_acesso(tag_uid=tag_uid)
        return jsonify(resposta.to_dict()), 200

    @app.get("/api/eventos")
    def listar_eventos() -> Response:
        todos = request.args.get("todos", "").lower() in ("true", "1", "sim")
        data_param = request.args.get("data", "").strip()

        if todos:
            eventos = repo.listar_eventos(data_prefixo=None)
        elif data_param:
            eventos = repo.listar_eventos(data_prefixo=data_param)
        else:
            hoje_str = datetime.now().strftime(FORMATO_DATA)
            eventos = repo.listar_eventos(data_prefixo=hoje_str)

        resp = jsonify([e.to_dict() for e in eventos])
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return resp

    @app.get("/api/eventos.csv")
    def exportar_csv() -> Response:
        conteudo_csv = service.exportar_eventos_csv()
        return Response(
            conteudo_csv,
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=eventos.csv"},
        )

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

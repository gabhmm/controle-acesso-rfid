from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from server.config import ADMIN_PASS, ADMIN_USER, DB_PATH, PROJECT_ROOT, RABBITMQ_DISPOSITIVO, RABBITMQ_EXCHANGE
from server.database import DatabaseRepository
from server.models import (
    Colaborador,
    ColaboradorCreate,
    ColaboradorResponse,
    ColaboradorUpdate,
    Dashboard10MinResponse,
    EventoResponse,
    LoginRequest,
)
from server.rabbit_producer import rabbit_producer
from server.redis_client import redis_client
from server.services import FORMATO_DATA, AccessService

# Diretórios de Templates e Arquivos Estáticos
TEMPLATE_DIR = PROJECT_ROOT / "client" / "templates"
STATIC_DIR = PROJECT_ROOT / "client" / "static"


def create_app(db_path: Path | str | None = None, seed_default: bool = True) -> FastAPI:
    """Factory da aplicação FastAPI para o Controle de Acesso Distribuído."""
    app = FastAPI(
        title="Controle de Acesso RFID & Monitoramento — Lab AAA",
        description="Servidor REST em FastAPI integrado a Mensageria RabbitMQ e Cache Redis conforme Contrato RabbitMQ v1.",
        version="2.0.0",
    )

    # Configuração de CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Arquivos Estáticos e Templates
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

    # Repositório e Serviço
    repo = DatabaseRepository(db_path=db_path or DB_PATH)
    repo.init_db(seed_default=seed_default)
    service = AccessService(repo=repo, redis=redis_client, rabbit=rabbit_producer)

    app.state.repo = repo
    app.state.service = service

    def esta_autenticado(request: Request) -> bool:
        return request.cookies.get("auth_session") == "admin_authenticated"

    def sincronizar_colaboradores_com_pi() -> None:
        """Publica a lista atualizada de colaboradores para a Raspberry Pi no RabbitMQ."""
        colabs = repo.listar_colaboradores()
        rabbit_producer.publicar_colaboradores([c.to_dict() for c in colabs])

    # Publica a lista inicial ao iniciar o servidor
    @app.on_event("startup")
    def on_startup() -> None:
        try:
            sincronizar_colaboradores_com_pi()
        except Exception:
            pass

    # =========================================================================
    # ROTAS DE PÁGINAS WEB (FRONT-END)
    # =========================================================================

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> Any:
        if esta_autenticado(request):
            return RedirectResponse(url="/monitor", status_code=status.HTTP_302_FOUND)
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    @app.get("/login", response_class=HTMLResponse)
    def pagina_login(request: Request) -> Any:
        if esta_autenticado(request):
            return RedirectResponse(url="/monitor", status_code=status.HTTP_302_FOUND)
        return templates.TemplateResponse(request, "login.html")

    @app.get("/monitor", response_class=HTMLResponse)
    def pagina_monitor(request: Request) -> Any:
        if not esta_autenticado(request):
            return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
        return templates.TemplateResponse(request, "monitor.html", {"usuario": "admin"})

    @app.get("/colaboradores", response_class=HTMLResponse)
    def pagina_colaboradores(request: Request) -> Any:
        if not esta_autenticado(request):
            return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
        return templates.TemplateResponse(request, "colaboradores.html", {"usuario": "admin"})

    # =========================================================================
    # ROTAS DE AUTENTICAÇÃO
    # =========================================================================

    @app.post("/login")
    def api_login(payload: LoginRequest, response: Response) -> Any:
        if payload.usuario.strip() == ADMIN_USER and payload.senha.strip() == ADMIN_PASS:
            response.set_cookie(key="auth_session", value="admin_authenticated", max_age=86400, httponly=True)
            return {"ok": True, "mensagem": "Autenticado com sucesso"}

        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"ok": False, "erro": "Credenciais inválidas"},
        )

    @app.post("/logout")
    def api_logout(response: Response) -> Any:
        response.delete_cookie(key="auth_session")
        return {"ok": True}

    # =========================================================================
    # ENDPOINTS REST: GESTÃO DE COLABORADORES (Servidor -> Pi via RabbitMQ)
    # =========================================================================

    @app.get("/api/colaboradores", response_model=list[ColaboradorResponse])
    def listar_colaboradores() -> Any:
        colabs = service.listar_colaboradores_com_estado()
        return [c.to_dict() for c in colabs]

    @app.post("/api/colaboradores", response_model=ColaboradorResponse, status_code=status.HTTP_201_CREATED)
    def criar_colaborador(payload: ColaboradorCreate) -> Any:
        tag_norm = payload.tag_uid.strip().upper()
        novo = Colaborador(
            id=None,
            nome=payload.nome.strip(),
            matricula=payload.matricula.strip(),
            tag_uid=tag_norm,
            cargo=payload.cargo.strip(),
            acesso_sala=payload.acesso_sala,
            ativo=payload.ativo,
        )
        try:
            criado = repo.criar_colaborador(novo)
            redis_client.invalidar_tag_cache(tag_norm)
            # Notifica a Raspberry Pi publicando a nova lista na fila 'pi.<disp>.colaboradores'
            sincronizar_colaboradores_com_pi()
            return criado.to_dict()
        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Matrícula ou Tag RFID já cadastrada para outro colaborador.",
            )

    @app.put("/api/colaboradores/{colab_id}", response_model=ColaboradorResponse)
    def atualizar_colaborador(colab_id: int, payload: ColaboradorUpdate) -> Any:
        existente = repo.obter_colaborador_por_id(colab_id)
        if not existente:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Colaborador não encontrado")

        tag_norm = (payload.tag_uid or existente.tag_uid).strip().upper()
        atualizado_obj = Colaborador(
            id=colab_id,
            nome=(payload.nome or existente.nome).strip(),
            matricula=(payload.matricula or existente.matricula).strip(),
            tag_uid=tag_norm,
            cargo=(payload.cargo or existente.cargo).strip(),
            acesso_sala=payload.acesso_sala if payload.acesso_sala is not None else existente.acesso_sala,
            ativo=payload.ativo if payload.ativo is not None else existente.ativo,
        )
        try:
            res = repo.atualizar_colaborador(colab_id, atualizado_obj)
            if res is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Colaborador não encontrado")
            redis_client.invalidar_tag_cache(existente.tag_uid)
            redis_client.invalidar_tag_cache(tag_norm)
            # Notifica a Raspberry Pi com a lista atualizada
            sincronizar_colaboradores_com_pi()
            return res.to_dict()
        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Matrícula ou Tag RFID já pertence a outro colaborador.",
            )

    @app.delete("/api/colaboradores/{colab_id}")
    def excluir_colaborador(colab_id: int) -> dict[str, bool]:
        existente = repo.obter_colaborador_por_id(colab_id)
        if not existente:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Colaborador não encontrado")

        sucesso = repo.excluir_colaborador(colab_id)
        if sucesso:
            redis_client.invalidar_tag_cache(existente.tag_uid)
            sincronizar_colaboradores_com_pi()
        return {"ok": sucesso}

    # =========================================================================
    # ENDPOINTS DE EVENTOS E DASHBOARD (Lidos da base alimentada pelo RabbitMQ)
    # =========================================================================

    @app.get("/api/dashboard/10min", response_model=Dashboard10MinResponse)
    def dashboard_10min() -> Any:
        return service.obter_dashboard_10_minutos()

    @app.get("/api/eventos", response_model=list[EventoResponse])
    def listar_eventos(todos: bool = False, data: str | None = None) -> Any:
        if todos:
            eventos = repo.listar_eventos(data_prefixo=None)
        elif data:
            eventos = repo.listar_eventos(data_prefixo=data.strip())
        else:
            hoje_str = datetime.now().strftime(FORMATO_DATA)
            eventos = repo.listar_eventos(data_prefixo=hoje_str)

        return [e.to_dict() for e in eventos]

    @app.get("/api/eventos.csv")
    def exportar_csv() -> Response:
        csv_conteudo = service.exportar_eventos_csv()
        return Response(
            content=csv_conteudo,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=eventos.csv"},
        )

    # =========================================================================
    # SIMULADOR DO FRONT-END (Injeta evento no RabbitMQ simulando a Pi)
    # =========================================================================
    @app.post("/api/simular")
    def simular_leitura_frontend(dados: dict[str, str]) -> dict[str, Any]:
        """Permite que os botões de simulação da interface web enviem um evento para o RabbitMQ como se fosse a Pi."""
        tag_uid = str(dados.get("tag_uid", "")).strip().upper()
        # Valida regra local
        resposta = service.validar_acesso(tag_uid=tag_uid)
        return resposta.to_dict()

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.app:app", host="0.0.0.0", port=5000, reload=True)

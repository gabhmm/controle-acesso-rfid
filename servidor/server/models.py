from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal
from pydantic import BaseModel, Field

ResultadoEvento = Literal["ENTRADA", "SAIDA", "NEGADO", "INVASAO"]


# =============================================================================
# DATACLASSES DE DOMÍNIO E BANCO DE DADOS
# =============================================================================

@dataclass(slots=True)
class Colaborador:
    id: int | None
    nome: str
    matricula: str
    tag_uid: str
    cargo: str
    acesso_sala: bool = True
    ativo: bool = True
    na_sala: bool = False
    entrou_hoje: bool = False
    tempo_hoje_segundos: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Evento:
    id: int | None
    data_hora: str
    tag_uid: str
    nome: str
    resultado: ResultadoEvento
    evento_id: str | None = None
    colaborador_id: int | None = None
    mensagem: str | None = None
    dispositivo: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RespostaValidacao:
    resultado: ResultadoEvento
    mensagem: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


# =============================================================================
# MODELOS PYDANTIC PARA API REST FASTAPI
# =============================================================================

class LoginRequest(BaseModel):
    usuario: str
    senha: str


class ColaboradorCreate(BaseModel):
    nome: str
    matricula: str
    tag_uid: str
    cargo: str
    acesso_sala: bool = True
    ativo: bool = True


class ColaboradorUpdate(BaseModel):
    nome: str | None = None
    matricula: str | None = None
    tag_uid: str | None = None
    cargo: str | None = None
    acesso_sala: bool | None = None
    ativo: bool | None = None


class ColaboradorResponse(BaseModel):
    id: int
    nome: str
    matricula: str
    tag_uid: str
    cargo: str
    acesso_sala: bool
    ativo: bool
    na_sala: bool = False
    entrou_hoje: bool = False
    tempo_hoje_segundos: int = 0


class EventoResponse(BaseModel):
    id: int | None
    data_hora: str
    tag_uid: str
    nome: str | None
    resultado: ResultadoEvento
    evento_id: str | None = None


class Dashboard10MinResponse(BaseModel):
    timestamp_consulta: str
    total_acessos: int
    total_entradas: int
    total_saidas: int
    total_negados: int
    total_invasoes: int
    ultimos_eventos: list[dict[str, Any]]
    fonte: str = "redis_cache"

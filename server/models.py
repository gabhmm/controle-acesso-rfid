from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

ResultadoEvento = Literal["ENTRADA", "SAIDA", "NEGADO", "INVASAO"]


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

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class Evento:
    id: int | None
    data_hora: str
    tag_uid: str
    nome: str
    resultado: ResultadoEvento

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class RespostaValidacao:
    resultado: ResultadoEvento
    mensagem: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

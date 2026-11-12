from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta
from typing import Any

from server.database import DatabaseRepository
from server.models import Colaborador, Evento
from server.redis_client import RedisClient, redis_client

FORMATO_DATA_HORA = "%Y-%m-%d %H:%M:%S"
FORMATO_DATA = "%Y-%m-%d"


class AccessService:
    """Camada de Regras de Negócio e Serviços com conformidade ao Contrato RabbitMQ v1."""

    def __init__(
        self,
        repo: DatabaseRepository,
        redis: RedisClient = redis_client,
    ) -> None:
        self.repo: DatabaseRepository = repo
        self.redis: RedisClient = redis

    @staticmethod
    def _calcular_estado_colaborador_hoje(
        tag_uid: str,
        eventos_hoje: list[Evento],
        agora: datetime,
    ) -> tuple[bool, bool, int]:
        tag_norm = tag_uid.strip().upper()
        # Eventos vêm ordenados por data_hora DESC; invertemos para ordem cronológica
        eventos_colab = [
            ev
            for ev in reversed(eventos_hoje)
            if ev.tag_uid.upper() == tag_norm and ev.resultado in ("ENTRADA", "SAIDA")
        ]

        if not eventos_colab:
            return False, False, 0

        entrou_hoje = any(ev.resultado == "ENTRADA" for ev in eventos_colab)
        na_sala = eventos_colab[-1].resultado == "ENTRADA"

        tempo_total_segundos: float = 0.0
        inicio_entrada: datetime | None = None

        for ev in eventos_colab:
            try:
                dt_ev = datetime.strptime(ev.data_hora, FORMATO_DATA_HORA)
            except ValueError:
                continue

            if ev.resultado == "ENTRADA":
                if inicio_entrada is None:
                    inicio_entrada = dt_ev
            elif ev.resultado == "SAIDA":
                if inicio_entrada is not None:
                    delta = (dt_ev - inicio_entrada).total_seconds()
                    if delta > 0:
                        tempo_total_segundos += delta
                    inicio_entrada = None

        if inicio_entrada is not None and na_sala:
            delta_aberto = (agora - inicio_entrada).total_seconds()
            if delta_aberto > 0:
                tempo_total_segundos += delta_aberto

        return na_sala, entrou_hoje, int(tempo_total_segundos)

    def listar_colaboradores_com_estado(self, agora: datetime | None = None) -> list[Colaborador]:
        dt_agora = agora or datetime.now()
        hoje_str = dt_agora.strftime(FORMATO_DATA)
        colaboradores = self.repo.listar_colaboradores()
        eventos_hoje = self.repo.listar_eventos(data_prefixo=hoje_str)

        for colab in colaboradores:
            na_sala, entrou_hoje, tempo_seg = self._calcular_estado_colaborador_hoje(
                colab.tag_uid, eventos_hoje, dt_agora
            )
            colab.na_sala = na_sala
            colab.entrou_hoje = entrou_hoje
            colab.tempo_hoje_segundos = tempo_seg

        return colaboradores

    def obter_dashboard_10_minutos(self) -> dict[str, Any]:
        cache = self.redis.obter_dashboard_cache()
        if cache is not None:
            cache["fonte"] = "redis_cache"
            return cache

        agora = datetime.now()
        limite_10min = agora - timedelta(minutes=10)
        limite_str = limite_10min.strftime(FORMATO_DATA_HORA)

        eventos = self.repo.listar_eventos(data_prefixo=None)
        eventos_10min = [e for e in eventos if e.data_hora >= limite_str]

        total = len(eventos_10min)
        entradas = sum(1 for e in eventos_10min if e.resultado == "ENTRADA")
        saidas = sum(1 for e in eventos_10min if e.resultado == "SAIDA")
        negados = sum(1 for e in eventos_10min if e.resultado == "NEGADO")
        invasoes = sum(1 for e in eventos_10min if e.resultado == "INVASAO")

        dados_dashboard = {
            "timestamp_consulta": agora.strftime(FORMATO_DATA_HORA),
            "total_acessos": total,
            "total_entradas": entradas,
            "total_saidas": saidas,
            "total_negados": negados,
            "total_invasoes": invasoes,
            "ultimos_eventos": [e.to_dict() for e in eventos_10min[:15]],
        }

        self.redis.salvar_dashboard_cache(dados_dashboard, ttl_segundos=10)
        dados_dashboard["fonte"] = "database_fallback"
        return dados_dashboard

    def exportar_eventos_csv(self) -> str:
        """Gera string CSV ordenada por data_hora (momento da leitura)."""
        eventos = self.repo.listar_eventos(data_prefixo=None)
        # No CSV, os mais antigos primeiro ou mais recentes:
        eventos_ordenados = sorted(eventos, key=lambda e: e.data_hora)

        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(["id", "data_hora", "tag_uid", "nome", "resultado"])
        for ev in eventos_ordenados:
            writer.writerow([ev.id, ev.data_hora, ev.tag_uid, ev.nome, ev.resultado])
        return buffer.getvalue()

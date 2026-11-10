from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from server.config import RABBITMQ_DISPOSITIVO
from server.database import DatabaseRepository
from server.models import Colaborador, Evento, RespostaValidacao, ResultadoEvento
from server.rabbit_producer import RabbitMQProducer, rabbit_producer
from server.redis_client import RedisClient, redis_client

FORMATO_DATA_HORA = "%Y-%m-%d %H:%M:%S"
FORMATO_DATA = "%Y-%m-%d"


class AccessService:
    """Camada de Regras de Negócio e Serviços com conformidade ao Contrato RabbitMQ v1."""

    def __init__(
        self,
        repo: DatabaseRepository,
        redis: RedisClient = redis_client,
        rabbit: RabbitMQProducer = rabbit_producer,
    ) -> None:
        self.repo: DatabaseRepository = repo
        self.redis: RedisClient = redis
        self.rabbit: RabbitMQProducer = rabbit

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

    def validar_acesso(self, tag_uid: str, agora: datetime | None = None) -> RespostaValidacao:
        """Validação de regras com mensagens padronizadas conforme Contrato RabbitMQ v1."""
        dt_agora = agora or datetime.now()
        data_hora_str = dt_agora.strftime(FORMATO_DATA_HORA)
        hoje_str = dt_agora.strftime(FORMATO_DATA)
        tag_norm = tag_uid.strip().upper()

        # Mensagem de INVASAO exata do PDF (Página 4)
        MSG_INVASAO = "Acesso negado, tag não cadastrada"

        if not tag_norm:
            self.repo.registrar_evento(data_hora_str, "DESCONHECIDO", "Desconhecido", "INVASAO")
            return RespostaValidacao(
                resultado="INVASAO",
                mensagem=MSG_INVASAO,
            )

        colab = self.repo.obter_colaborador_por_tag(tag_norm)
        if colab is None:
            self.repo.registrar_evento(
                data_hora_ou_evento=data_hora_str,
                tag_uid=tag_norm,
                nome="Desconhecido",
                resultado="INVASAO",
                evento_id=str(uuid.uuid4()),
                colaborador_id=None,
                mensagem=MSG_INVASAO,
                dispositivo=RABBITMQ_DISPOSITIVO,
            )
            return RespostaValidacao(
                resultado="INVASAO",
                mensagem=MSG_INVASAO,
            )

        if not colab.ativo or not colab.acesso_sala:
            msg = f"Acesso negado, {colab.nome}"
            self.repo.registrar_evento(
                data_hora_ou_evento=data_hora_str,
                tag_uid=tag_norm,
                nome=colab.nome,
                resultado="NEGADO",
                evento_id=str(uuid.uuid4()),
                colaborador_id=colab.id,
                mensagem=msg,
                dispositivo=RABBITMQ_DISPOSITIVO,
            )
            return RespostaValidacao(
                resultado="NEGADO",
                mensagem=msg,
            )

        # Regra de Entrada / Saída
        estado_sala_redis = self.redis.obter_estado_na_sala(colab.matricula)
        entrou_hoje_redis = self.redis.obter_entrou_hoje(colab.matricula)
        eventos_hoje = self.repo.listar_eventos(data_prefixo=hoje_str)
        na_sala, entrou_hoje, _ = self._calcular_estado_colaborador_hoje(
            tag_norm, eventos_hoje, dt_agora
        )

        if estado_sala_redis is not None:
            na_sala = estado_sala_redis
        if entrou_hoje_redis:
            entrou_hoje = True

        resultado: ResultadoEvento
        mensagem: str

        if not entrou_hoje and not na_sala:
            resultado = "ENTRADA"
            mensagem = f"Bem-vindo, {colab.nome}"
            self.redis.definir_estado_na_sala(colab.matricula, True)
            self.redis.definir_entrou_hoje(colab.matricula)
        elif na_sala:
            resultado = "SAIDA"
            mensagem = f"Até logo, {colab.nome}"
            self.redis.definir_estado_na_sala(colab.matricula, False)
        else:
            resultado = "ENTRADA"
            mensagem = f"Bem-vindo de volta, {colab.nome}"
            self.redis.definir_estado_na_sala(colab.matricula, True)

        self.repo.registrar_evento(
            data_hora_ou_evento=data_hora_str,
            tag_uid=tag_norm,
            nome=colab.nome,
            resultado=resultado,
            evento_id=str(uuid.uuid4()),
            colaborador_id=colab.id,
            mensagem=mensagem,
            dispositivo=RABBITMQ_DISPOSITIVO,
        )
        return RespostaValidacao(resultado=resultado, mensagem=mensagem)

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

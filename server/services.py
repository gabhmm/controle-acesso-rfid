from __future__ import annotations

import csv
import io
from datetime import datetime

from server.database import DatabaseRepository
from server.models import Colaborador, Evento, RespostaValidacao, ResultadoEvento

FORMATO_DATA_HORA = "%Y-%m-%d %H:%M:%S"
FORMATO_DATA = "%Y-%m-%d"


class AccessService:
    """Camada de Regras de Negócio para validação de crachá RFID e monitoramento da sala AAA."""

    def __init__(self, repo: DatabaseRepository) -> None:
        self.repo: DatabaseRepository = repo

    @staticmethod
    def _calcular_estado_colaborador_hoje(
        tag_uid: str,
        eventos_hoje: list[Evento],
        agora: datetime,
    ) -> tuple[bool, bool, int]:
        """Calcula (na_sala, entrou_hoje, tempo_hoje_segundos) para um tag_uid com base nos eventos do dia."""
        tag_norm = tag_uid.strip().upper()
        # Eventos vêm do mais recente para o mais antigo; invertemos para ordem cronológica
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
        """Retorna todos os colaboradores enriquecidos com na_sala, entrou_hoje e tempo_hoje_segundos."""
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
        """Valida a leitura de uma tag RFID aplicando RN01, RN02 e RN03 e registra o evento no SQLite."""
        dt_agora = agora or datetime.now()
        data_hora_str = dt_agora.strftime(FORMATO_DATA_HORA)
        hoje_str = dt_agora.strftime(FORMATO_DATA)
        tag_norm = tag_uid.strip().upper()

        if not tag_norm:
            self.repo.registrar_evento(data_hora_str, "DESCONHECIDO", "Desconhecido", "INVASAO")
            return RespostaValidacao(
                resultado="INVASAO",
                mensagem="Alerta de invasão: Tag não cadastrada",
            )

        colab = self.repo.obter_colaborador_por_tag(tag_norm)

        # RN01 — Tag não cadastrada -> INVASAO
        if colab is None:
            self.repo.registrar_evento(data_hora_str, tag_norm, "Desconhecido", "INVASAO")
            return RespostaValidacao(
                resultado="INVASAO",
                mensagem="Alerta de invasão: Tag não cadastrada",
            )

        # RN02 — Colaborador cadastrado, mas inativo ou sem permissão -> NEGADO
        if not colab.ativo or not colab.acesso_sala:
            self.repo.registrar_evento(data_hora_str, tag_norm, colab.nome, "NEGADO")
            return RespostaValidacao(
                resultado="NEGADO",
                mensagem=f"Acesso negado, {colab.nome}",
            )

        # RN03 — Colaborador autorizado -> verificar histórico do dia
        eventos_hoje = self.repo.listar_eventos(data_prefixo=hoje_str)
        na_sala, entrou_hoje, _ = self._calcular_estado_colaborador_hoje(
            tag_norm, eventos_hoje, dt_agora
        )

        resultado: ResultadoEvento
        mensagem: str

        if not entrou_hoje:
            resultado = "ENTRADA"
            mensagem = f"Bem-vindo, {colab.nome}"
        elif na_sala:
            resultado = "SAIDA"
            mensagem = f"Até logo, {colab.nome}"
        else:
            resultado = "ENTRADA"
            mensagem = f"Bem-vindo de volta, {colab.nome}"

        self.repo.registrar_evento(data_hora_str, tag_norm, colab.nome, resultado)
        return RespostaValidacao(resultado=resultado, mensagem=mensagem)

    def exportar_eventos_csv(self) -> str:
        """Gera string CSV com todos os eventos registrados (id,data_hora,tag_uid,nome,resultado)."""
        eventos = self.repo.listar_eventos(data_prefixo=None)
        # No CSV pode ser interessante ordenar por id crescente ou manter decrescente;
        # Invertemos para ordem cronológica (id crescente) como no exemplo do contrato (id 1 primeiro)
        eventos_ordenados = sorted(eventos, key=lambda e: e.id or 0)

        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(["id", "data_hora", "tag_uid", "nome", "resultado"])
        for ev in eventos_ordenados:
            writer.writerow([ev.id, ev.data_hora, ev.tag_uid, ev.nome, ev.resultado])
        return buffer.getvalue()

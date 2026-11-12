from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import redis

from server.config import REDIS_DB, REDIS_HOST, REDIS_PASSWORD, REDIS_PORT

logger = logging.getLogger("rfid.redis")

REDIS_HABILITADO = os.environ.get("ENABLE_REDIS", "true").lower() in ("true", "1", "sim")


class RedisClient:
    """Gerenciador de Cache Distribuído com suporte a Cache-Aside e Fallback Gracioso."""

    def __init__(
        self,
        host: str = REDIS_HOST,
        port: int = REDIS_PORT,
        db: int = REDIS_DB,
        password: str | None = REDIS_PASSWORD,
        habilitado: bool = REDIS_HABILITADO,
    ) -> None:
        self.host = host
        self.port = port
        self.db = db
        self.password = password
        self.habilitado = habilitado
        self._client: redis.Redis | None = None
        self._ultima_tentativa: float = 0.0
        self._intervalo_tentativa: float = 30.0
        # Fallback local em memória para testes e quando Redis estiver indisponível
        self._memoria_cache: dict[str, Any] = {}

    def _conectar(self) -> None:
        if not self.habilitado:
            return
        agora = time.time()
        if agora - self._ultima_tentativa < self._intervalo_tentativa:
            return
        self._ultima_tentativa = agora
        try:
            client = redis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                password=self.password,
                decode_responses=True,
                socket_timeout=0.1,
                socket_connect_timeout=0.1,
            )
            client.ping()
            self._client = client
            logger.info("Conectado ao Redis em %s:%s", self.host, self.port)
        except Exception as exc:
            self._client = None
            logger.debug("Redis não disponível (%s). Usando fallback em memória.", exc)

    @property
    def disponivel(self) -> bool:
        if self._client is None and self.habilitado:
            self._conectar()
        return self._client is not None

    def obter_tag_cache(self, tag_uid: str) -> dict[str, Any] | None:
        chave = f"rfid:tag:{tag_uid.strip().upper()}"
        if self.disponivel and self._client:
            try:
                dados = self._client.get(chave)
                if dados:
                    return json.loads(dados)
            except Exception:
                pass
        return self._memoria_cache.get(chave)

    def salvar_tag_cache(self, tag_uid: str, dados: dict[str, Any], ttl_segundos: int = 300) -> None:
        chave = f"rfid:tag:{tag_uid.strip().upper()}"
        if self.disponivel and self._client:
            try:
                self._client.setex(chave, ttl_segundos, json.dumps(dados, ensure_ascii=False))
                return
            except Exception:
                pass
        self._memoria_cache[chave] = dados

    def invalidar_tag_cache(self, tag_uid: str) -> None:
        chave = f"rfid:tag:{tag_uid.strip().upper()}"
        if self.disponivel and self._client:
            try:
                self._client.delete(chave)
            except Exception:
                pass
        self._memoria_cache.pop(chave, None)

    def obter_dashboard_cache(self) -> dict[str, Any] | None:
        if self.disponivel and self._client:
            try:
                dados = self._client.get("rfid:dashboard:10min")
                if dados:
                    return json.loads(dados)
            except Exception:
                pass
        return self._memoria_cache.get("rfid:dashboard:10min")

    def salvar_dashboard_cache(self, dados: dict[str, Any], ttl_segundos: int = 10) -> None:
        if self.disponivel and self._client:
            try:
                self._client.setex("rfid:dashboard:10min", ttl_segundos, json.dumps(dados, ensure_ascii=False))
                return
            except Exception:
                pass
        self._memoria_cache["rfid:dashboard:10min"] = dados

    def obter_estado_na_sala(self, matricula: str) -> bool | None:
        chave = f"rfid:na_sala:{matricula}"
        if self.disponivel and self._client:
            try:
                val = self._client.get(chave)
                if val is not None:
                    return val == "1"
            except Exception:
                pass
        val_mem = self._memoria_cache.get(chave)
        return val_mem if isinstance(val_mem, bool) else None

    def definir_estado_na_sala(self, matricula: str, na_sala: bool, ttl_segundos: int = 86400) -> None:
        chave = f"rfid:na_sala:{matricula}"
        if self.disponivel and self._client:
            try:
                self._client.setex(chave, ttl_segundos, "1" if na_sala else "0")
                return
            except Exception:
                pass
        self._memoria_cache[chave] = na_sala

    def obter_entrou_hoje(self, matricula: str) -> bool:
        chave = f"rfid:entrou_hoje:{matricula}"
        if self.disponivel and self._client:
            try:
                val = self._client.get(chave)
                if val is not None:
                    return val == "1"
            except Exception:
                pass
        return bool(self._memoria_cache.get(chave, False))

    def definir_entrou_hoje(self, matricula: str, ttl_segundos: int = 86400) -> None:
        chave = f"rfid:entrou_hoje:{matricula}"
        if self.disponivel and self._client:
            try:
                self._client.setex(chave, ttl_segundos, "1")
                return
            except Exception:
                pass
        self._memoria_cache[chave] = True


redis_client = RedisClient()

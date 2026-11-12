from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [Orquestrador] %(message)s",
)
logger = logging.getLogger("rfid.main")

ROOT_DIR = Path(__file__).resolve().parent


def verificar_e_subir_docker() -> None:
    """Tenta subir os contêineres do Redis e RabbitMQ caso o Docker esteja disponível."""
    cmd = None
    if shutil.which("docker"):
        cmd = ["docker", "compose", "up", "-d"]
    elif shutil.which("docker-compose"):
        cmd = ["docker-compose", "up", "-d"]

    if not cmd:
        logger.info("Docker não detectado no PATH. Serviços utilizarão fallback resiliente.")
        return

    logger.info("Verificando infraestrutura Docker (Redis e RabbitMQ)...")
    try:
        res = subprocess.run(
            cmd,
            cwd=str(ROOT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        if res.returncode == 0:
            logger.info("Contêineres Redis e RabbitMQ iniciados com sucesso!")
        else:
            # Tenta a sintaxe alternativa se falhar
            if cmd[0] == "docker":
                subprocess.run(["docker-compose", "up", "-d"], cwd=str(ROOT_DIR), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def imprimir_banner() -> None:
    print(r"""
========================================================================
   🛡️ SISTEMA DISTRIBUÍDO DE CONTROLE DE ACESSO & MONITORAMENTO RFID
   SERVIDOR: FastAPI  ·  Redis  ·  RabbitMQ  ·  Worker  ·  SQLite
========================================================================
    """)
    print("  🌐 Painel de Monitoramento : http://localhost:5000/monitor")
    print("  👥 Gestão de Colaboradores  : http://localhost:5000/colaboradores")
    print("  📖 Documentação da API      : http://localhost:5000/docs")
    print("  🐇 Painel Web do RabbitMQ   : http://localhost:15672 (guest / guest)")
    print("------------------------------------------------------------------------")
    print("  Pressione Ctrl+C a qualquer momento para encerrar todos os serviços.")
    print("========================================================================\n")


def main() -> None:
    imprimir_banner()

    # 1. Tenta iniciar Docker (Redis + RabbitMQ)
    verificar_e_subir_docker()

    processos: list[subprocess.Popen[Any]] = []
    python_exe = sys.executable

    def encerrar_todos(sig: Any = None, frame: Any = None) -> None:
        print("\n\n[Orquestrador] Encerrando todos os serviços...")
        for p in processos:
            try:
                p.terminate()
            except Exception:
                pass
        time.sleep(0.5)
        for p in processos:
            try:
                p.kill()
            except Exception:
                pass
        print("[Orquestrador] Todos os serviços foram finalizados. Até logo!")
        sys.exit(0)

    signal.signal(signal.SIGINT, encerrar_todos)
    signal.signal(signal.SIGTERM, encerrar_todos)

    # Configura ambiente com PYTHONPATH
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT_DIR)

    # 2. Inicia o Worker do RabbitMQ em background
    logger.info("Iniciando Worker Consumidor (RabbitMQ -> SQLite)...")
    proc_worker = subprocess.Popen(
        [python_exe, "-m", "worker.consumer"],
        cwd=str(ROOT_DIR),
        env=env,
    )
    processos.append(proc_worker)

    # 3. Inicia o Servidor FastAPI (Uvicorn) em background
    logger.info("Iniciando Servidor Web FastAPI (porta 5000)...")
    proc_server = subprocess.Popen(
        [
            python_exe,
            "-m",
            "uvicorn",
            "server.app:app",
            "--host",
            "0.0.0.0",
            "--port",
            "5000",
            "--log-level",
            "warning",
        ],
        cwd=str(ROOT_DIR),
        env=env,
    )
    processos.append(proc_server)

    # O leitor RFID não roda aqui: ele fica no projeto embarcado/ (na Raspberry)
    # e conversa com este servidor só pelo RabbitMQ.
    logger.info("Servidor no ar. Aguardando eventos da Raspberry pelo RabbitMQ...")
    try:
        while all(p.poll() is None for p in processos):
            time.sleep(1)
        logger.error("Um dos serviços parou inesperadamente.")
    except KeyboardInterrupt:
        pass
    finally:
        encerrar_todos()


if __name__ == "__main__":
    main()

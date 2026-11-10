from __future__ import annotations

import os
from pathlib import Path

BASE_DIR: Path = Path(__file__).resolve().parent
PROJECT_ROOT: Path = BASE_DIR.parent

DB_PATH: Path = Path(os.environ.get("ACESSO_DB_PATH", str(BASE_DIR / "acesso.db")))
SECRET_KEY: str = os.environ.get("FLASK_SECRET_KEY", "aaa-studio-nda-secret-key-2026")

ADMIN_USER: str = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS: str = os.environ.get("ADMIN_PASS", "admin")

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f ".env" ] && [ -f ".env.example" ]; then
  cp .env.example .env
fi

if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [ ! -x ".venv/bin/uvicorn" ] || [ ! -x ".venv/bin/alembic" ]; then
  if ! python3 -m venv .venv >/dev/null 2>&1; then
    DEBIAN_FRONTEND=noninteractive apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3.11-venv || true
    python3 -m venv .venv
  fi
  .venv/bin/pip install -q -r requirements.txt
fi

if [ -w "/usr/local/bin" ]; then
  ln -sf "$ROOT_DIR/.venv/bin/pip3" /usr/local/bin/pip3
  ln -sf "$ROOT_DIR/.venv/bin/pip" /usr/local/bin/pip
fi

# Bootstrap local PostgreSQL 15 automatically if DATABASE_URL points locally and port is closed
.venv/bin/python - <<'PY'
import os
import pwd
import shutil
import socket
import subprocess
from urllib.parse import urlparse

raw_db_url = os.environ.get("DATABASE_URL", "")
if not raw_db_url:
    raise SystemExit("DATABASE_URL is missing in environment/.env")

parsed = urlparse(raw_db_url.replace("postgresql+psycopg://", "postgresql://"))
host = parsed.hostname or "127.0.0.1"
port = parsed.port or 5432

def pg_listening(h: str, p: int) -> bool:
    try:
        with socket.create_connection((h, p), timeout=1):
            return True
    except OSError:
        return False

if not pg_listening(host, port) and host in {"127.0.0.1", "localhost"}:
    pg_bin = "/usr/lib/postgresql/15/bin"
    if not os.path.exists(f"{pg_bin}/initdb"):
        subprocess.run(["bash", "-lc", "DEBIAN_FRONTEND=noninteractive apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends postgresql-15 || true"], check=False)

    if not os.path.exists(f"{pg_bin}/initdb"):
        raise SystemExit("PostgreSQL 15 binaries are unavailable for local dev startup.")

    subprocess.run(["bash", "-lc", "id postgres >/dev/null 2>&1 || useradd -r -M -s /bin/bash postgres"], check=True)
    pw = pwd.getpwnam("postgres")

    pg_data = "/tmp/pgdata"
    pg_sock = "/tmp/pgsock"
    os.makedirs(pg_sock, exist_ok=True)
    os.chown(pg_sock, pw.pw_uid, pw.pw_gid)

    if not os.path.exists(os.path.join(pg_data, "PG_VERSION")):
        if os.path.exists(pg_data):
            shutil.rmtree(pg_data)
        os.makedirs(pg_data, exist_ok=True)
        os.chown(pg_data, pw.pw_uid, pw.pw_gid)
        subprocess.run(["su", "-", "postgres", "-c", f"{pg_bin}/initdb -D {pg_data} --auth=trust"], check=True)

    subprocess.run(
        ["su", "-", "postgres", "-c", f"{pg_bin}/pg_ctl -D {pg_data} -l /tmp/pg.log -o \"-k {pg_sock} -p {port} -h 127.0.0.1\" start"],
        check=True,
    )

    pg_user = parsed.username or "bravebank"
    pg_pass = (parsed.password or "").replace("'", "''")
    db_name = parsed.path.lstrip("/") or "bravebank"

    test_raw = os.environ.get("TEST_DATABASE_URL", "")
    test_db = urlparse(test_raw.replace("postgresql+psycopg://", "postgresql://")).path.lstrip("/") if test_raw else "bravebank_test"

    role_exists = subprocess.run(
        [f"{pg_bin}/psql", "-h", "127.0.0.1", "-p", str(port), "-U", "postgres", "-d", "postgres", "-tAc", f"SELECT 1 FROM pg_roles WHERE rolname='{pg_user}'"],
        capture_output=True, text=True, check=True
    ).stdout.strip()
    if role_exists != "1":
        subprocess.run(
            [f"{pg_bin}/psql", "-h", "127.0.0.1", "-p", str(port), "-U", "postgres", "-d", "postgres"],
            input=f'CREATE ROLE "{pg_user}" WITH LOGIN SUPERUSER PASSWORD \'{pg_pass}\';\n',
            text=True, check=True
        )

    for dbname in [db_name, test_db]:
        if not dbname:
            continue
        db_exists = subprocess.run(
            [f"{pg_bin}/psql", "-h", "127.0.0.1", "-p", str(port), "-U", "postgres", "-d", "postgres", "-tAc", f"SELECT 1 FROM pg_database WHERE datname='{dbname}'"],
            capture_output=True, text=True, check=True
        ).stdout.strip()
        if db_exists != "1":
            subprocess.run(
                [f"{pg_bin}/psql", "-h", "127.0.0.1", "-p", str(port), "-U", "postgres", "-d", "postgres"],
                input=f'CREATE DATABASE "{dbname}" OWNER "{pg_user}";\n',
                text=True, check=True
            )
PY

export DIRECT_URL="${DIRECT_URL:-$DATABASE_URL}"
.venv/bin/alembic -c backend/alembic.ini upgrade head

exec .venv/bin/uvicorn backend.app.main:app --host 0.0.0.0 --port "${PORT:-3000}"

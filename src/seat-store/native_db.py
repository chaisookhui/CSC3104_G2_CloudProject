"""Optional local PostgreSQL backend using installed server tools, not a service.

Owns only .local/postgres in this checkout. Never modifies another installation's
data or authentication. The existing migrations still define application tables.
"""

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import psycopg
from dotenv import load_dotenv
from psycopg import sql

ROOT = Path(__file__).resolve().parent
LOCAL = ROOT.parents[1] / ".local"
DATA = LOCAL / "postgres"


def tool(name):
    path = shutil.which(name)
    if not path:
        raise ValueError(f"Install PostgreSQL 17+ and add its bin directory to PATH: missing {name}")
    return path


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("setup", "start", "stop"))
    command = parser.parse_args().command
    load_dotenv(ROOT / ".env", override=False)
    if os.getenv("POSTGRES_BACKEND") != "native":
        raise ValueError("Set POSTGRES_BACKEND=native through the documented setup first")
    pg_ctl = tool("pg_ctl")
    status = subprocess.run([pg_ctl, "-D", str(DATA), "status"], capture_output=True)
    if command == "stop":
        if status.returncode == 0:
            run(pg_ctl, "-D", str(DATA), "-m", "fast", "-w", "stop")
        return
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    if not 1024 <= port <= 65535:
        raise ValueError("POSTGRES_PORT must be between 1024 and 65535")
    admin_password = os.environ["POSTGRES_ADMIN_PASSWORD"]
    app_password = os.environ["SEAT_STORE_DB_PASSWORD"]
    if not admin_password or not app_password or "replace_me" in (admin_password, app_password):
        raise ValueError("Use setup.ps1 to generate local passwords")
    expected_urls = {
        "DATABASE_URL": f"postgresql://seat_store:{app_password}@127.0.0.1:{port}/seat_booking",
        "TEST_DATABASE_URL": f"postgresql://seat_store:{app_password}@127.0.0.1:{port}/seat_booking_test",
    }
    if any(os.getenv(key) != value for key, value in expected_urls.items()):
        raise ValueError("Native setup requires the generated local URLs and matching POSTGRES_PORT")
    LOCAL.mkdir(exist_ok=True)
    if not (DATA / "PG_VERSION").exists():
        if command != "setup":
            raise ValueError("Run setup.ps1 -NativePostgres first")
        initdb = tool("initdb")
        version = subprocess.check_output([initdb, "--version"], text=True)
        if int(re.search(r"\b(\d+)\.", version).group(1)) < 17:
            raise ValueError("PostgreSQL 17+ is required")
        # Passwords stay out of command arguments and logs; the new temp file is
        # removed immediately after initdb. The durable copy is the ignored .env.
        with tempfile.NamedTemporaryFile(mode="w", dir=LOCAL, delete=False) as secret:
            secret.write(admin_password + "\n")
            password_file = Path(secret.name)
        try:
            run(initdb, "-D", str(DATA), "-U", "postgres", "--auth=scram-sha-256",
                "--encoding=UTF8", "--locale=C", f"--pwfile={password_file}")
        finally:
            password_file.unlink()
    if status.returncode != 0:
        run(pg_ctl, "-D", str(DATA), "-l", str(LOCAL / "postgres.log"),
            "-o", f"-h 127.0.0.1 -p {port}", "-w", "start")
    if command == "setup":
        # Never alter an existing role/password. Mismatches fail at init-db rather
        # than changing existing credentials behind the developer's back.
        with psycopg.connect(host="127.0.0.1", port=port, user="postgres",
                             password=admin_password, dbname="postgres",
                             autocommit=True, connect_timeout=5) as conn:
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname='seat_store'").fetchone():
                conn.execute(sql.SQL("CREATE ROLE seat_store LOGIN PASSWORD {}").format(
                    sql.Literal(app_password)))
            for database in ("seat_booking", "seat_booking_test"):
                if not conn.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone():
                    conn.execute(sql.SQL("CREATE DATABASE {} OWNER seat_store").format(
                        sql.Identifier(database)))
    print(f"Native PostgreSQL ready on 127.0.0.1:{port}; data stays in .local/postgres")


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        raise SystemExit(str(error)) from None
    except (KeyError, psycopg.Error, subprocess.CalledProcessError) as error:
        # Do not print database exceptions or connection URLs containing passwords.
        raise SystemExit(f"Native PostgreSQL operation failed ({type(error).__name__}). "
                         "Check configuration, port availability and .local/postgres.log.") from None

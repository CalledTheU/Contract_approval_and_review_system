# Author: WangLei
# Email: WangLei1578@outlook.com
# Date: 2026-09-28

import json
import hashlib
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
UPLOADS = DATA / "uploads"
DB = DATA / "contracts.db"
UPLOADS.mkdir(parents=True, exist_ok=True)


@contextmanager
def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL, role TEXT NOT NULL, salt TEXT NOT NULL, password_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, name TEXT NOT NULL, filename TEXT NOT NULL, text TEXT NOT NULL, status TEXT NOT NULL, blocked_reason TEXT, metadata TEXT NOT NULL DEFAULT '{}', comments TEXT NOT NULL DEFAULT '', writeback_status TEXT NOT NULL DEFAULT 'not_written', writeback TEXT, created_at TEXT NOT NULL, owner_id TEXT);
        CREATE TABLE IF NOT EXISTS risks (id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE, level TEXT NOT NULL, title TEXT NOT NULL, clause_type TEXT NOT NULL, original_text TEXT NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL, page INTEGER NOT NULL, reason TEXT NOT NULL, legal_basis TEXT NOT NULL, suggestion TEXT NOT NULL, suggested_text TEXT NOT NULL, accepted INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY, task_id TEXT NOT NULL, event TEXT NOT NULL, created_at TEXT NOT NULL);
        """)
        task_columns = {row["name"] for row in db.execute("PRAGMA table_info(tasks)")}
        if "owner_id" not in task_columns:
            db.execute("ALTER TABLE tasks ADD COLUMN owner_id TEXT")
        if not db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            for username, name, role in [("business", "业务经办人", "business"), ("legal", "法务审查员", "legal"), ("admin", "系统管理员", "admin")]:
                salt = secrets.token_hex(16)
                digest = hashlib.pbkdf2_hmac("sha256", b"Demo123!", bytes.fromhex(salt), 160000).hex()
                db.execute("INSERT INTO users VALUES(?,?,?,?,?,?)", (secrets.token_hex(16), username, name, role, salt, digest))


def log(db, task_id, event):
    db.execute("INSERT INTO logs(task_id,event,created_at) VALUES(?,?,?)", (task_id, event, datetime.now(timezone.utc).isoformat()))


def task_data(task_id, user=None):
    with connect() as db:
        task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not task:
            from fastapi import HTTPException
            raise HTTPException(404, "任务不存在")
        if user and user["role"] == "business" and task["owner_id"] != user["id"]:
            from fastapi import HTTPException
            raise HTTPException(404, "任务不存在")
        risks = db.execute("SELECT * FROM risks WHERE task_id=? ORDER BY CASE level WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END, start", (task_id,)).fetchall()
        return dict(task), [dict(risk) for risk in risks]


init_db()

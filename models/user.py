"""
models/user.py
SQLite 用户模型 —— 零外部依赖，Python 标准库 sqlite3
"""

import os
import sqlite3
from dataclasses import dataclass
from werkzeug.security import generate_password_hash, check_password_hash

from config import DATABASE_DIR

_DB_PATH = os.path.join(DATABASE_DIR, "users.db")


@dataclass
class User:
    id: int
    username: str
    password_hash: str

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_active(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    def get_id(self) -> str:
        return str(self.id)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


# ── 数据库操作 ──────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    os.makedirs(DATABASE_DIR, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """建表（幂等）"""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    UNIQUE NOT NULL,
            password_hash TEXT    NOT NULL,
            created_at    TEXT    DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()
    print(f"[DB] 数据库就绪：{_DB_PATH}")


def get_user_by_username(username: str) -> User | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if row is None:
        return None
    return User(id=row["id"], username=row["username"], password_hash=row["password_hash"])


def get_user_by_id(user_id: int) -> User | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    return User(id=row["id"], username=row["username"], password_hash=row["password_hash"])


def create_user(username: str, password: str) -> User:
    """创建用户，密码用 werkzeug 哈希后存储"""
    conn = _get_conn()
    try:
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, generate_password_hash(password))
        )
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
        return User(id=user_id, username=username, password_hash="")
    except sqlite3.IntegrityError:
        conn.close()
        raise ValueError(f"用户 '{username}' 已存在")

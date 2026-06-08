"""
auth.py — 使用者認證模組

資料表：users
操作：register / login / get_user / create_demo_user

⚠  密碼雜湊說明（課堂專案用）：
   本模組使用 hashlib.sha256 + secrets.token_hex(32) 實作每用戶獨立 salt。
   此方案對展示用途足夠，但正式產品應改用 bcrypt 或 argon2-cffi，
   因為這兩者具備 cost factor，可抵抗暴力破解（SHA-256 速度太快）。
   替換方式：將 _hash_password() 改為 bcrypt.hashpw() 即可，其餘介面不變。

執行方式（建立 demo 帳號）：
    cd ~/Desktop/stock_sentiment
    python3 models/auth.py
"""

import hashlib
import secrets
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "news.db"


# ─────────────────────────────────────────────────────────────
# 密碼工具（內部使用）
# ─────────────────────────────────────────────────────────────

def _hash_password(password: str, salt: str) -> str:
    """
    SHA-256(salt + password) → hex digest。
    ⚠ 課堂用簡易方案，正式產品請改 bcrypt/argon2。
    """
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────
# 資料表管理
# ─────────────────────────────────────────────────────────────

def ensure_users_table(conn: sqlite3.Connection) -> None:
    """
    建立 users 表（若不存在）。
    在各操作函式中防禦性呼叫，確保舊版 DB 升級後仍可使用。
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT    NOT NULL,
            salt          TEXT    NOT NULL,
            created_at    TEXT    NOT NULL,
            -- 預留欄位：未來個人化功能用
            watchlist     TEXT    DEFAULT '[]',   -- JSON，如 ["2330","2454"]
            preferences   TEXT    DEFAULT '{}'    -- JSON，個人化設定
        )
    """)
    conn.commit()


# ─────────────────────────────────────────────────────────────
# 核心操作
# ─────────────────────────────────────────────────────────────

def register(
    conn: sqlite3.Connection,
    username: str,
    password: str,
) -> tuple:
    """
    註冊新使用者。
    回傳 (success: bool, message: str)。
    """
    ensure_users_table(conn)

    username = username.strip()
    if not username:
        return False, "使用者名稱不可為空"
    if len(username) > 32:
        return False, "使用者名稱不可超過 32 個字元"
    if len(password) < 4:
        return False, "密碼至少需要 4 個字元"

    salt          = secrets.token_hex(32)      # 每個用戶獨立 salt
    password_hash = _hash_password(password, salt)

    try:
        conn.execute(
            """INSERT INTO users (username, password_hash, salt, created_at)
               VALUES (?, ?, ?, ?)""",
            (username, password_hash, salt, datetime.now().isoformat()),
        )
        conn.commit()
        return True, f"帳號 「{username}」 建立成功"
    except sqlite3.IntegrityError:
        return False, f"使用者名稱 「{username}」 已存在"


def login(
    conn: sqlite3.Connection,
    username: str,
    password: str,
) -> tuple:
    """
    驗證使用者登入。
    回傳 (success: bool, message: str)。
    錯誤訊息刻意模糊化（不透露是帳號還是密碼錯），防止帳號枚舉攻擊。
    """
    ensure_users_table(conn)

    username = username.strip()
    row = conn.execute(
        "SELECT password_hash, salt FROM users WHERE username = ? COLLATE NOCASE",
        (username,),
    ).fetchone()

    if row is None:
        # 仍計算一次 hash，避免 timing attack（不讓攻擊者透過回應速度分辨帳號是否存在）
        _hash_password(password, "dummy_salt_to_avoid_timing_attack")
        return False, "使用者名稱或密碼錯誤"

    expected = _hash_password(password, row["salt"])
    if expected != row["password_hash"]:
        return False, "使用者名稱或密碼錯誤"

    return True, "登入成功"


def get_user(conn: sqlite3.Connection, username: str) -> Optional[sqlite3.Row]:
    """取得使用者基本資料（不含密碼欄位）。"""
    ensure_users_table(conn)
    return conn.execute(
        "SELECT id, username, created_at, watchlist, preferences "
        "FROM users WHERE username = ? COLLATE NOCASE",
        (username.strip(),),
    ).fetchone()


def user_exists(conn: sqlite3.Connection, username: str) -> bool:
    """檢查使用者名稱是否已存在。"""
    ensure_users_table(conn)
    row = conn.execute(
        "SELECT 1 FROM users WHERE username = ? COLLATE NOCASE",
        (username.strip(),),
    ).fetchone()
    return row is not None


def list_users(conn: sqlite3.Connection) -> list:
    """列出所有使用者（debug 用）。"""
    ensure_users_table(conn)
    return conn.execute(
        "SELECT id, username, created_at FROM users ORDER BY created_at"
    ).fetchall()


# ─────────────────────────────────────────────────────────────
# Demo 帳號建立
# ─────────────────────────────────────────────────────────────

def create_demo_user(
    db_path: Path = DEFAULT_DB_PATH,
    username: str = "demo",
    password: str = "demo1234",
) -> None:
    """
    建立 demo 測試帳號。
    帳號已存在時跳過，不覆寫。
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ensure_users_table(conn)

    if user_exists(conn, username):
        print(f"[auth] demo 帳號 「{username}」 已存在，跳過建立")
    else:
        ok, msg = register(conn, username, password)
        print(f"[auth] {msg}")

    conn.close()


# ─────────────────────────────────────────────────────────────
# 直接執行：建立 demo 帳號
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))
    create_demo_user()
    print()
    print("Dashboard 測試帳號：")
    print("  帳號：demo")
    print("  密碼：demo1234")
    print()
    print("啟動 Dashboard：")
    print("  streamlit run web/app.py")

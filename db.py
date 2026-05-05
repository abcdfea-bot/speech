import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "app_data.db"
MAX_HISTORY_RECORDS = 50


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account TEXT NOT NULL UNIQUE,
                username TEXT,
                display_name TEXT,
                phone TEXT,
                email TEXT UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS prediction_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                total_files INTEGER NOT NULL,
                real_count INTEGER NOT NULL,
                fake_count INTEGER NOT NULL,
                error_count INTEGER NOT NULL,
                results_json TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS prediction_history_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                history_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                result_label TEXT NOT NULL,
                score REAL NOT NULL,
                is_bonafide INTEGER NOT NULL,
                error TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (history_id) REFERENCES prediction_history(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_prediction_history_user_created
            ON prediction_history(user_id, created_at DESC, id DESC);

            CREATE INDEX IF NOT EXISTS idx_prediction_history_records_user_created
            ON prediction_history_records(user_id, created_at DESC, id DESC);
            """
        )


def _clean_optional(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _row_to_user(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return {
        "id": row["id"],
        "account": row["account"],
        "username": row["username"],
        "display_name": row["display_name"],
        "phone": row["phone"],
        "email": row["email"],
        "password_hash": row["password_hash"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_user(
    account: str,
    password_hash: str,
    username: Optional[str] = None,
    display_name: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
) -> Dict[str, Any]:
    account = account.strip()
    username = _clean_optional(username)
    display_name = _clean_optional(display_name)
    phone = _clean_optional(phone)
    email = _clean_optional(email)
    if email:
        email = email.lower()
    now = utcnow_iso()

    try:
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO users (account, username, display_name, phone, email, password_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (account, username, display_name, phone, email, password_hash, now, now),
            )
            user_id = cursor.lastrowid
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    except sqlite3.IntegrityError as exc:
        message = str(exc).lower()
        if "users.account" in message:
            raise ValueError("账号已存在") from exc
        if "users.email" in message:
            raise ValueError("邮箱已被使用") from exc
        raise ValueError("用户创建失败") from exc

    user = _row_to_user(row)
    if user is None:
        raise ValueError("用户创建失败")
    return user


def get_user_by_account(account: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE account = ?", (account.strip(),)).fetchone()
    return _row_to_user(row)


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _row_to_user(row)


def update_user_profile(
    user_id: int,
    display_name: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    password_hash: Optional[str] = None,
) -> Dict[str, Any]:
    display_name = _clean_optional(display_name)
    phone = _clean_optional(phone)
    email = _clean_optional(email)
    if email:
        email = email.lower()
    now = utcnow_iso()

    try:
        with get_connection() as conn:
            if password_hash:
                conn.execute(
                    """
                    UPDATE users
                    SET display_name = ?, phone = ?, email = ?, password_hash = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (display_name, phone, email, password_hash, now, user_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE users
                    SET display_name = ?, phone = ?, email = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (display_name, phone, email, now, user_id),
                )
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    except sqlite3.IntegrityError as exc:
        message = str(exc).lower()
        if "users.email" in message:
            raise ValueError("邮箱已被使用") from exc
        raise ValueError("个人信息更新失败") from exc

    user = _row_to_user(row)
    if user is None:
        raise ValueError("用户不存在")
    return user


def _normalize_history_file(item: Dict[str, Any]) -> Dict[str, Any]:
    score = item.get("score", 0)
    try:
        numeric_score = float(score)
    except (TypeError, ValueError):
        numeric_score = 0.0

    return {
        "filename": item.get("filename", ""),
        "result_label": item.get("result_label", "错误"),
        "score": numeric_score,
        "is_bonafide": bool(item.get("is_bonafide", False)),
        "error": item.get("error"),
    }


def _row_to_history(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "total_files": row["total_files"],
        "real_count": row["real_count"],
        "fake_count": row["fake_count"],
        "error_count": row["error_count"],
        "files": json.loads(row["results_json"]),
    }


def _row_to_history_record(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "history_id": row["history_id"],
        "filename": row["filename"],
        "result_label": row["result_label"],
        "score": row["score"],
        "is_bonafide": bool(row["is_bonafide"]),
        "error": row["error"],
        "created_at": row["created_at"],
    }


def create_prediction_history(user_id: int, results: List[Dict[str, Any]]) -> Dict[str, Any]:
    files = [_normalize_history_file(item) for item in results]
    now = utcnow_iso()
    real_count = sum(1 for item in files if item["result_label"] == "真实")
    fake_count = sum(1 for item in files if item["result_label"] == "伪造")
    error_count = sum(1 for item in files if item.get("error"))

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO prediction_history (
                user_id, created_at, total_files, real_count, fake_count, error_count, results_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                now,
                len(files),
                real_count,
                fake_count,
                error_count,
                json.dumps(files, ensure_ascii=False),
            ),
        )
        history_id = cursor.lastrowid

        conn.executemany(
            """
            INSERT INTO prediction_history_records (
                user_id, history_id, filename, result_label, score, is_bonafide, error, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    user_id,
                    history_id,
                    item["filename"],
                    item["result_label"],
                    item["score"],
                    1 if item["is_bonafide"] else 0,
                    item.get("error"),
                    now,
                )
                for item in files
            ],
        )

        stale_records = conn.execute(
            """
            SELECT id
            FROM prediction_history_records
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT -1 OFFSET ?
            """,
            (user_id, MAX_HISTORY_RECORDS),
        ).fetchall()
        if stale_records:
            conn.executemany(
                "DELETE FROM prediction_history_records WHERE id = ?",
                [(row["id"],) for row in stale_records],
            )

        conn.execute(
            """
            DELETE FROM prediction_history
            WHERE user_id = ?
              AND id NOT IN (
                    SELECT DISTINCT history_id
                    FROM prediction_history_records
                    WHERE user_id = ?
              )
            """,
            (user_id, user_id),
        )

        row = conn.execute(
            "SELECT * FROM prediction_history WHERE id = ?",
            (history_id,),
        ).fetchone()

    return _row_to_history(row)


def list_prediction_history(user_id: int, limit: int = MAX_HISTORY_RECORDS) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM prediction_history_records
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    return [_row_to_history_record(row) for row in rows]

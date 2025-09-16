import sqlite3
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager
import time
import uuid

DB_PATH = Path("complaints.db")

# -------------------------------
# ВНУТРЕННЯЯ УТИЛИТКА: соединение + ретраи
# -------------------------------

def _open_connection():
    """
    Открывает соединение c расширенным timeout, WAL и busy_timeout.
    check_same_thread=False — чтобы можно было вызывать из thread-пула.
    """
    conn = sqlite3.connect(
        str(DB_PATH),
        timeout=30,                 # ожидание блокировки до 30с
        check_same_thread=False,    # можно из других потоков
        isolation_level=None,       # управляем транзакциями вручную
    )
    conn.row_factory = sqlite3.Row
    # Быстрые PRAGMA (дёшево вызывать каждый раз)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")   # 30с
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

@contextmanager
def _conn_ctx():
    conn = _open_connection()
    try:
        yield conn
    finally:
        conn.close()

def _execute_with_retry(conn: sqlite3.Connection, sql: str, params=()):
    """
    Выполняет SQL c ретраями на 'database is locked'.
    """
    delay = 0.05
    for _ in range(7):
        try:
            cur = conn.execute(sql, params)
            return cur
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e).lower():
                time.sleep(delay)
                delay = min(delay * 2, 1.0)
                continue
            raise
    raise sqlite3.OperationalError("database is locked (after retries)")

# -------------------------------
# ИНИЦИАЛИЗАЦИЯ БД
# -------------------------------

def init_db():
    with _conn_ctx() as conn:
        # Таблица жалоб
        _execute_with_retry(conn, """
        CREATE TABLE IF NOT EXISTS complaints(
            id TEXT PRIMARY KEY,
            user_id INTEGER,
            username TEXT,
            category TEXT,
            district TEXT,
            address_text TEXT,
            geo_lat REAL,
            geo_lon REAL,
            text TEXT,
            media_group_id TEXT,
            status TEXT,
            assignee_id INTEGER,
            created_at TEXT,
            taken_at TEXT,
            done_at TEXT,
            closed_at TEXT
        );
        """)

        # Таблица медиа
        _execute_with_retry(conn, """
        CREATE TABLE IF NOT EXISTS media(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            complaint_id TEXT,
            file_id TEXT,
            kind TEXT
        );
        """)

        # Таблица постов (карточка в группе ↔ message_id)
        _execute_with_retry(conn, """
        CREATE TABLE IF NOT EXISTS posts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            complaint_id TEXT,
            chat_id INTEGER,
            message_id INTEGER
        );
        """)

        # Таблица подсказок/хинтов (временные сообщения «Свободная заявка»)
        _execute_with_retry(conn, """
        CREATE TABLE IF NOT EXISTS hints(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            complaint_id TEXT,
            message_id INTEGER
        );
        """)

        # Индексы для ускорения выборок
        _execute_with_retry(conn, "CREATE INDEX IF NOT EXISTS idx_complaints_status ON complaints(status);")
        _execute_with_retry(conn, "CREATE INDEX IF NOT EXISTS idx_complaints_assignee ON complaints(assignee_id);")
        _execute_with_retry(conn, "CREATE INDEX IF NOT EXISTS idx_complaints_created ON complaints(created_at);")
        _execute_with_retry(conn, "CREATE INDEX IF NOT EXISTS idx_complaints_taken ON complaints(taken_at);")
        _execute_with_retry(conn, "CREATE INDEX IF NOT EXISTS idx_complaints_done ON complaints(done_at);")

# -------------------------------
# Жалобы
# -------------------------------

def save_complaint(row: dict) -> str | None:
    """
    Пытается вставить жалобу. При коллизии PRIMARY KEY(id) — один раз
    перегенерирует id и повторяет. Возвращает фактический id или None.
    """
    sql = """
        INSERT INTO complaints(
            id, user_id, username, category, district, address_text, geo_lat, geo_lon,
            text, media_group_id, status, assignee_id, created_at, taken_at, done_at, closed_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """

    def _params(_row):
        return (
            _row["id"],
            _row["user_id"],
            _row.get("username"),
            _row.get("category"),
            _row.get("district"),
            _row.get("address_text"),
            _row.get("geo_lat"),
            _row.get("geo_lon"),
            _row.get("text"),
            _row.get("media_group_id"),
            _row.get("status", "New"),
            _row.get("assignee_id"),
            datetime.utcnow().isoformat(),
            None, None, None
        )

    tries = 2  # исходный id + 1 перегенерация
    for attempt in range(tries):
        try:
            with _conn_ctx() as conn:
                _execute_with_retry(conn, "BEGIN IMMEDIATE;")
                try:
                    _execute_with_retry(conn, sql, _params(row))
                    _execute_with_retry(conn, "COMMIT;")
                    return row["id"]
                except Exception:
                    _execute_with_retry(conn, "ROLLBACK;")
                    raise
        except sqlite3.IntegrityError as e:
            # только коллизия по complaints.id
            if "UNIQUE constraint failed: complaints.id" in str(e):
                # генерируем новый id и пробуем последний раз
                row["id"] = f'{row["id"]}-{uuid.uuid4().hex[:4]}'
                continue
            # другая Integrity — не чиним
            print("save_complaint integrity error:", e)
            return None
        except sqlite3.OperationalError as e:
            print("save_complaint oper error:", e)
            return None
        except Exception as e:
            print("save_complaint error:", e)
            return None
    return None

def add_media(cid: str, file_id: str, kind: str) -> bool:
    try:
        with _conn_ctx() as conn:
            _execute_with_retry(conn, "BEGIN IMMEDIATE;")
            try:
                _execute_with_retry(conn, "INSERT INTO media (complaint_id, file_id, kind) VALUES (?, ?, ?)",
                                    (cid, file_id, kind))
                _execute_with_retry(conn, "COMMIT;")
                return True
            except Exception:
                _execute_with_retry(conn, "ROLLBACK;")
                raise
    except Exception as e:
        print("add_media error:", e)
        return False

def get_media(cid: str):
    with _conn_ctx() as conn:
        cur = _execute_with_retry(conn, "SELECT file_id, kind FROM media WHERE complaint_id=?", (cid,))
        return cur.fetchall()

def set_status(cid: str, status: str) -> bool:
    try:
        with _conn_ctx() as conn:
            now = datetime.utcnow().isoformat()
            _execute_with_retry(conn, "BEGIN IMMEDIATE;")
            try:
                if status == "InProgress":
                    _execute_with_retry(conn, "UPDATE complaints SET status=?, taken_at=? WHERE id=?",
                                        (status, now, cid))
                elif status == "Done":
                    _execute_with_retry(conn, "UPDATE complaints SET status=?, done_at=? WHERE id=?",
                                        (status, now, cid))
                elif status == "Closed":
                    _execute_with_retry(conn, "UPDATE complaints SET status=?, closed_at=? WHERE id=?",
                                        (status, now, cid))
                else:
                    _execute_with_retry(conn, "UPDATE complaints SET status=? WHERE id=?", (status, cid))
                _execute_with_retry(conn, "COMMIT;")
                return True
            except Exception:
                _execute_with_retry(conn, "ROLLBACK;")
                raise
    except Exception as e:
        print("set_status error:", e)
        return False

def assign(cid: str, user_id: int | None) -> bool:
    """
    Назначить/снять исполнителя.
    - Если user_id is None → снимаем исполнителя и taken_at.
    - Если задан → ставим исполнителя, проставляем taken_at и переводим в InProgress.
    """
    try:
        with _conn_ctx() as conn:
            _execute_with_retry(conn, "BEGIN IMMEDIATE;")
            try:
                if user_id is None:
                    _execute_with_retry(conn, "UPDATE complaints SET assignee_id=NULL, taken_at=NULL WHERE id=?", (cid,))
                else:
                    _execute_with_retry(conn,
                        "UPDATE complaints SET assignee_id=?, taken_at=?, status='InProgress' WHERE id=?",
                        (user_id, datetime.utcnow().isoformat(), cid)
                    )
                _execute_with_retry(conn, "COMMIT;")
                return True
            except Exception:
                _execute_with_retry(conn, "ROLLBACK;")
                raise
    except Exception as e:
        print("assign error:", e)
        return False

def get_complaint(cid: str):
    with _conn_ctx() as conn:
        cur = _execute_with_retry(conn, "SELECT * FROM complaints WHERE id=?", (cid,))
        return cur.fetchone()

# -------------------------------
# Посты (карточки в группе)
# -------------------------------

def save_post_message(cid: str, chat_id: int, msg_id: int) -> bool:
    try:
        with _conn_ctx() as conn:
            _execute_with_retry(conn, "BEGIN IMMEDIATE;")
            try:
                _execute_with_retry(conn,
                    "INSERT INTO posts (complaint_id, chat_id, message_id) VALUES (?, ?, ?)",
                    (cid, chat_id, msg_id)
                )
                _execute_with_retry(conn, "COMMIT;")
                return True
            except Exception:
                _execute_with_retry(conn, "ROLLBACK;")
                raise
    except Exception as e:
        print("save_post_message error:", e)
        return False

def get_post_message_id(cid: str):
    with _conn_ctx() as conn:
        cur = _execute_with_retry(conn,
            "SELECT message_id FROM posts WHERE complaint_id=? ORDER BY id DESC LIMIT 1", (cid,)
        )
        row = cur.fetchone()
        return row["message_id"] if row else None

# -------------------------------
# Хинты (временные подсказочные сообщения)
# -------------------------------

def save_hint_message(cid: str, msg_id: int) -> bool:
    try:
        with _conn_ctx() as conn:
            _execute_with_retry(conn, "BEGIN IMMEDIATE;")
            try:
                _execute_with_retry(conn, "INSERT INTO hints (complaint_id, message_id) VALUES (?, ?)", (cid, msg_id))
                _execute_with_retry(conn, "COMMIT;")
                return True
            except Exception:
                _execute_with_retry(conn, "ROLLBACK;")
                raise
    except Exception as e:
        print("save_hint_message error:", e)
        return False

def get_hint_message(cid: str):
    with _conn_ctx() as conn:
        cur = _execute_with_retry(conn,
            "SELECT message_id FROM hints WHERE complaint_id=? ORDER BY id DESC LIMIT 1", (cid,)
        )
        row = cur.fetchone()
        return row["message_id"] if row else None

def delete_hint_message(cid: str) -> bool:
    try:
        with _conn_ctx() as conn:
            _execute_with_retry(conn, "BEGIN IMMEDIATE;")
            try:
                _execute_with_retry(conn, "DELETE FROM hints WHERE complaint_id=?", (cid,))
                _execute_with_retry(conn, "COMMIT;")
                return True
            except Exception:
                _execute_with_retry(conn, "ROLLBACK;")
                raise
    except Exception as e:
        print("delete_hint_message error:", e)
        return False

# -------------------------------
# Выборки для команд
# -------------------------------

def list_user_complaints(user_id: int, limit: int = 10):
    """Ровно те поля, которые ждёт handlers_user.py"""
    with _conn_ctx() as conn:
        cur = _execute_with_retry(conn, """
            SELECT id, category, address_text, text, status, created_at, done_at
            FROM complaints
            WHERE user_id = ?
            ORDER BY datetime(created_at) DESC
            LIMIT ?
        """, (user_id, limit))
        return cur.fetchall()

def list_inprogress_detailed(limit: int = 20):
    """(id, category, address_text, text, assignee_id, taken_at)"""
    with _conn_ctx() as conn:
        cur = _execute_with_retry(conn, """
            SELECT id, category, address_text, text, assignee_id, taken_at
            FROM complaints
            WHERE status = 'InProgress'
            ORDER BY datetime(taken_at) DESC
            LIMIT ?
        """, (limit,))
        return cur.fetchall()

def list_done_detailed(limit: int = 20):
    """(id, category, address_text, text, assignee_id, done_at)"""
    with _conn_ctx() as conn:
        cur = _execute_with_retry(conn, """
            SELECT id, category, address_text, text, assignee_id, done_at
            FROM complaints
            WHERE status = 'Done'
            ORDER BY datetime(done_at) DESC
            LIMIT ?
        """, (limit,))
        return cur.fetchall()

def list_free(limit: int = 10):
    """Свободные заявки: самые новые вверху"""
    with _conn_ctx() as conn:
        cur = _execute_with_retry(conn, """
            SELECT id, category, address_text, text, created_at
            FROM complaints
            WHERE status = 'New' AND assignee_id IS NULL
            ORDER BY datetime(created_at) DESC
            LIMIT ?
        """, (limit,))
        return cur.fetchall()

def list_assignee_jobs(user_id: int, limit: int = 20, active_only: bool = True):
    with _conn_ctx() as conn:
        if active_only:
            cur = _execute_with_retry(conn, """
                SELECT id, category, address_text, text, status, taken_at
                FROM complaints
                WHERE assignee_id = ? AND status = 'InProgress'
                ORDER BY datetime(taken_at) DESC
                LIMIT ?
            """, (user_id, limit))
        else:
            cur = _execute_with_retry(conn, """
                SELECT id, category, address_text, text, status, taken_at
                FROM complaints
                WHERE assignee_id = ?
                ORDER BY datetime(taken_at) DESC
                LIMIT ?
            """, (user_id, limit))
        return cur.fetchall()

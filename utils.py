# utils.py — FULL FILE (drop-in replacement, robust numeric IDs)
# --------------------------------------------------------------
# What this does:
# - gen_id() now ALWAYS returns a short sequential number: "1", "2", "3", ...
#   It uses COUNT(*) from the 'complaints' table and returns count + 1.
#   If the DB or table doesn't exist yet, it returns "1".
# - notify_user is included (handlers_group imports it).
# - safe_mention / gen_filename unchanged.

from typing import Optional
from datetime import datetime
from pathlib import Path
import sqlite3
from aiogram import Bot


# Adjust this if your DB is stored elsewhere or named differently
DB_PATH = (Path(__file__).resolve().parent / "complaints.db")


def _next_numeric_id() -> int:
    """
    Robustly compute the next number for complaints.
    Uses COUNT(*) to avoid issues with MAX(id) on brand-new DBs.
    Returns 1 if DB/table not present yet.
    """
    try:
        if not DB_PATH.exists():
            return 1
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            # If table doesn't exist yet, this SELECT will raise OperationalError,
            # which we catch and return 1.
            c.execute("SELECT COUNT(*) FROM complaints")
            count = c.fetchone()[0] or 0
            return count + 1
    except Exception:
        # On any unexpected error, be safe and return 1 so the bot still works.
        return 1


def gen_id() -> str:
    """
    Return a short numeric string like "1", "2", "3"...
    """
    return str(_next_numeric_id())


def safe_mention(username: Optional[str], first_name: Optional[str]) -> str:
    """
    Prefer @username; else fall back to first_name; else a neutral label.
    """
    if username:
        return f"@{username}"
    return first_name or "Пользователь"


def gen_filename(prefix: str, ext: str) -> str:
    """
    Generate a timestamped filename like 'photo-20250101-123000.jpg'.
    """
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{prefix}-{ts}.{ext.strip('.')}"


async def notify_user(bot: Bot, user_id: int, text: str):
    """
    Try to send a message to a user.
    If bot is blocked or any error occurs, ignore (don't crash).
    """
    try:
        await bot.send_message(user_id, text)
    except Exception:
        pass

# handlers_group.py — FULL FILE (buttons + DM notifications + admin check)
# Works with your current handlers_user.py (it calls: await post_to_group(c.bot, {**row, "id": new_id}))
# What’s new:
#   • Buttons: ✅ Принять / ❌ Отказаться / ✅ Готово
#   • The "Статус:" line updates in the post
#   • Author gets a DM when status changes (taken / declined / done)
#   • Only admins/owner can press "Готово" (mark as completed)
#
# No database schema changes are required.

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import List, Tuple, Optional

from aiogram import Router, F, types
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaDocument,
)
from aiogram.exceptions import TelegramBadRequest

from utils import safe_mention, notify_user

group_router = Router()

# --------------------------------------------------------------------
# DB helpers: media & complaint author lookup
# --------------------------------------------------------------------

DB_PATH = Path(__file__).resolve().parent / "complaints.db"

def _fetch_media(complaint_id: int) -> List[Tuple[str, str]]:
    """Return list of (file_id, kind) for given complaint_id."""
    if not DB_PATH.exists():
        return []
    try:
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute(
                "SELECT file_id, kind FROM media WHERE complaint_id = ? ORDER BY rowid ASC",
                (complaint_id,),
            )
            return c.fetchall()
    except Exception:
        return []

def _fetch_author(complaint_id: int) -> Optional[Tuple[int, Optional[str]]]:
    """
    Return (user_id, username) for the complaint author.
    Expects complaints table with columns: id, user_id, username, ...
    """
    if not DB_PATH.exists():
        return None
    try:
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT user_id, username FROM complaints WHERE id = ?", (complaint_id,))
            row = c.fetchone()
            if row:
                return int(row[0]), row[1]
            return None
    except Exception:
        return None

# --------------------------------------------------------------------
# UI helpers
# --------------------------------------------------------------------

def _kb(req_no: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Принять",   callback_data=f"take:{req_no}"),
                InlineKeyboardButton(text="❌ Отказаться", callback_data=f"decline:{req_no}"),
                InlineKeyboardButton(text="✅ Готово",    callback_data=f"done:{req_no}"),
            ]
        ]
    )

def _render_card_text(
    req_no: str,
    category: str,
    from_user_mention: str,
    address: str | None,
    description: str | None,
    status: str = "Новая",
    assignee: str | None = None,
) -> str:
    lines = [
        f"#{req_no}  [категория: {category}]",
        f"От: {from_user_mention}",
        f"Адрес: {address or '—'}",
        f"Описание: {description or '—'}",
        "",
        f"Статус: {status}" + (f" (исполнитель: {assignee})" if assignee else ""),
    ]
    return "\n".join(lines)

def _edit_status_text(orig: str, new_status: str) -> str:
    """Replace/append the 'Статус:' line in message text/caption."""
    lines = (orig or "").splitlines()
    for i, line in enumerate(lines):
        if line.startswith("Статус:"):
            lines[i] = f"Статус: {new_status}"
            return "\n".join(lines)
    lines.append(f"Статус: {new_status}")
    return "\n".join(lines)

async def _is_admin(bot: types.Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        # aiogram v3: member.status in {"creator", "administrator", "member", ...}
        return getattr(member, "status", None) in {"creator", "administrator"}
    except Exception:
        return False

# --------------------------------------------------------------------
# Public entry point (called from handlers_user)
# --------------------------------------------------------------------

async def post_to_group(bot: types.Bot, row: dict):
    """
    Post complaint card into the target group/channel with buttons.
    `row` is the dict built in handlers_user; required keys:
      id, username, category, address_text, text
    """

    chat_id_env = os.getenv("ZAYAVKI_CHAT_ID")
    if not chat_id_env:
        print("send_message error: ZAYAVKI_CHAT_ID not set")
        return
    try:
        chat_id = int(chat_id_env)
    except Exception:
        print("send_message error: invalid ZAYAVKI_CHAT_ID:", chat_id_env)
        return

    req_no = str(row.get("id"))
    category = row.get("category") or "—"
    address = row.get("address_text")
    description = row.get("text")
    from_user_mention = safe_mention(row.get("username"), None)

    # 1) Album (if media exists)
    media_rows = _fetch_media(int(row["id"]))
    if media_rows:
        album = []
        for file_id, kind in media_rows[:10]:  # safe cap
            if kind == "photo":
                album.append(InputMediaPhoto(media=file_id))
            elif kind == "video":
                album.append(InputMediaVideo(media=file_id))
            elif kind == "document":
                album.append(InputMediaDocument(media=file_id))
        if album:
            try:
                await bot.send_media_group(chat_id, album)
            except Exception as e:
                print("send_media_group error:", e)

    # 2) Card with buttons
    text = _render_card_text(
        req_no=req_no,
        category=category,
        from_user_mention=from_user_mention,
        address=address,
        description=description,
        status="Новая",
    )
    try:
        await bot.send_message(chat_id, text, reply_markup=_kb(req_no))
    except Exception as e:
        print("send_message error:", e)

# --------------------------------------------------------------------
# Button callbacks (with DM & admin check)
# --------------------------------------------------------------------

@group_router.callback_query(F.data.startswith("take:"))
async def on_take(callback: CallbackQuery):
    req_no = callback.data.split(":", 1)[1]
    chat_id = callback.message.chat.id if callback.message else None
    assignee = safe_mention(callback.from_user.username, callback.from_user.first_name)

    msg = callback.message
    if not msg:
        await callback.answer("Сообщение не найдено", show_alert=True)
        return

    # Update the post
    new_text = _edit_status_text(msg.text or msg.caption or "", f"В работе (исполнитель: {assignee})")
    try:
        if msg.text:
            await msg.edit_text(new_text, reply_markup=_kb(req_no))
        else:
            await msg.edit_caption(new_text, reply_markup=_kb(req_no))
        await callback.answer("Принято")
    except TelegramBadRequest:
        await callback.answer("Невозможно изменить сообщение", show_alert=True)
        return

    # Notify the author in DM
    try:
        author = _fetch_author(int(req_no))
        if author:
            user_id, username = author
            await notify_user(
                callback.bot,
                user_id,
                f"✅ Вашу заявку #{req_no} взял в работу {assignee}.",
            )
    except Exception:
        pass

@group_router.callback_query(F.data.startswith("decline:"))
async def on_decline(callback: CallbackQuery):
    req_no = callback.data.split(":", 1)[1]
    msg = callback.message
    if not msg:
        await callback.answer("Сообщение не найдено", show_alert=True)
        return

    new_text = _edit_status_text(msg.text or msg.caption or "", "Свободна")
    try:
        if msg.text:
            await msg.edit_text(new_text, reply_markup=_kb(req_no))
        else:
            await msg.edit_caption(new_text, reply_markup=_kb(req_no))
        await callback.answer("Заявка освобождена")
    except TelegramBadRequest:
        await callback.answer("Невозможно изменить сообщение", show_alert=True)
        return

    # Notify the author in DM
    try:
        author = _fetch_author(int(req_no))
        if author:
            user_id, username = author
            await notify_user(
                callback.bot,
                user_id,
                f"⚠️ Заявка #{req_no} снова свободна. Её пока никто не выполняет.",
            )
    except Exception:
        pass

@group_router.callback_query(F.data.startswith("done:"))
async def on_done(callback: CallbackQuery):
    req_no = callback.data.split(":", 1)[1]
    msg = callback.message
    if not msg:
        await callback.answer("Сообщение не найдено", show_alert=True)
        return

    # Only admins/owner can mark as done
    chat_id = msg.chat.id
    is_admin = await _is_admin(callback.bot, chat_id, callback.from_user.id)
    if not is_admin:
        await callback.answer("Только администраторы могут завершать заявки.", show_alert=True)
        return

    new_text = _edit_status_text(msg.text or msg.caption or "", "Завершена ✅")
    try:
        if msg.text:
            await msg.edit_text(new_text, reply_markup=_kb(req_no))
        else:
            await msg.edit_caption(new_text, reply_markup=_kb(req_no))
        await callback.answer("Отмечено как завершено")
    except TelegramBadRequest:
        await callback.answer("Невозможно изменить сообщение", show_alert=True)
        return

    # Notify the author in DM
    try:
        author = _fetch_author(int(req_no))
        if author:
            user_id, username = author
            finisher = safe_mention(callback.from_user.username, callback.from_user.first_name)
            await notify_user(
                callback.bot,
                user_id,
                f"🎉 Ваша заявка #{req_no} отмечена как завершённая ({finisher}).",
            )
    except Exception:
        pass

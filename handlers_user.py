from __future__ import annotations

import re
import asyncio
from typing import Optional, Tuple

from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from states import NewComplaint
from keyboards import main_menu_kb, categories_kb, skip_kb, confirm_kb, location_kb
from utils import gen_id
from storage import save_complaint, add_media, list_user_complaints

# router MUST be top-level (so main.py can import it)
user_router = Router()

CATEGORIES = [
    "Вода", "Свет", "Газ", "Канализация", "Мусор",
    "Дороги", "Лифт", "Благоустройство", "Шум", "Животные", "Другое",
]

# -----------------------------
# Helpers
# -----------------------------

def _parse_coords_from_text(text: str) -> Optional[Tuple[float, float]]:
    """
    Accepts:
      - "41.3111, 69.2797"  (comma or space separated)
      - "41.3111 69.2797"
      - Any Google/Apple/Yandex maps link that contains "...,<lat>,<lon>..." or "q=<lat>,<lon>"
    Returns (lat, lon) or None.
    """
    if not text:
        return None

    # Try direct "lat, lon" or "lat lon" with floats
    m = re.search(r'([-+]?\d{1,3}\.\d+)[,\s]+([-+]?\d{1,3}\.\d+)', text)
    if m:
        try:
            lat = float(m.group(1))
            lon = float(m.group(2))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return (lat, lon)
        except Exception:
            pass

    # Try q=<lat>,<lon> in query (e.g., https://maps.google.com/?q=41.3111,69.2797)
    m = re.search(r'[?&]q=([-+]?\d{1,3}\.\d+),([-+]?\d{1,3}\.\d+)', text)
    if m:
        try:
            lat = float(m.group(1))
            lon = float(m.group(2))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return (lat, lon)
        except Exception:
            pass

    return None

# =========================
# Commands
# =========================
@user_router.message(Command("start"))
async def cmd_start(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(
        "Здравствуйте! Я бот обращений. Что хотите сделать?",
        reply_markup=main_menu_kb(),
    )

@user_router.message(Command("stop"))
async def cmd_stop(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(
        "⛔️ Бот остановлен. Чтобы возобновить работу, введите /start",
        reply_markup=main_menu_kb(),
    )

@user_router.message(Command("mine"))
async def cmd_mine(m: Message):
    await my_complaints(m)

# =========================
# New complaint flow
# =========================
@user_router.message(F.text == "Оставить жалобу")
async def new_complaint(m: Message, state: FSMContext):
    await state.set_state(NewComplaint.category)
    await m.answer("Выберите категорию:", reply_markup=categories_kb(CATEGORIES))

@user_router.callback_query(F.data.startswith("cat:"), NewComplaint.category)
async def set_category(c: CallbackQuery, state: FSMContext):
    cat = c.data.split(":", 1)[1]
    await state.update_data(category=cat)
    await state.set_state(NewComplaint.text)
    await c.message.edit_reply_markup()  # убираем клавиатуру категорий
    await c.message.answer("Опишите проблему (текст):")
    await c.answer()

@user_router.message(NewComplaint.text)
async def after_text_ask_address(m: Message, state: FSMContext):
    await state.update_data(text=(m.text or "").strip())
    await state.set_state(NewComplaint.address)
    await m.answer(
        "Адрес (улица/дом/ориентир). Или нажмите «Пропустить».",
        reply_markup=skip_kb(),
    )

@user_router.callback_query(F.data == "skip", NewComplaint.address)
async def skip_address(c: CallbackQuery, state: FSMContext):
    await state.update_data(address_text=None)
    await state.set_state(NewComplaint.location)
    await c.message.answer(
        "Отправьте геолокацию или вставьте координаты/ссылку на карту.\n"
        "Пример: `41.3111, 69.2797` или ссылка Google Maps.\n"
        "Либо нажмите «Пропустить».",
        reply_markup=location_kb(),
    )
    await c.answer()

@user_router.message(NewComplaint.address)
async def set_address(m: Message, state: FSMContext):
    await state.update_data(address_text=(m.text or "").strip())
    await state.set_state(NewComplaint.location)
    await m.answer(
        "Отправьте геолокацию или вставьте координаты/ссылку на карту.\n"
        "Пример: `41.3111, 69.2797` или ссылка Google Maps.\n"
        "Либо нажмите «Пропустить».",
        reply_markup=location_kb(),
    )

# ---- Location

# 1) Mobile GPS location
@user_router.message(NewComplaint.location, F.location)
async def set_location(m: Message, state: FSMContext):
    await state.update_data(geo=(m.location.latitude, m.location.longitude))
    await state.set_state(NewComplaint.media)
    await m.answer("Прикрепите фото/видео (по желанию) или нажмите «Пропустить».", reply_markup=skip_kb())

# 2) Desktop: paste coords or a maps link
@user_router.message(NewComplaint.location, F.text)
async def set_location_text(m: Message, state: FSMContext):
    coords = _parse_coords_from_text(m.text.strip())
    if coords:
        await state.update_data(geo=coords)
        await state.set_state(NewComplaint.media)
        await m.answer("Геолокация сохранена. Прикрепите фото/видео (по желанию) или нажмите «Пропустить».", reply_markup=skip_kb())
    else:
        await m.answer(
            "Не удалось распознать координаты.\n"
            "Отправьте геолокацию с телефона или вставьте координаты/ссылку, например:\n"
            "`41.3111, 69.2797` или Google Maps ссылку.\n"
            "Либо нажмите «Пропустить».",
            reply_markup=location_kb(),
            parse_mode="Markdown"
        )

@user_router.message(NewComplaint.location, F.text.casefold() == "пропустить")
async def skip_location(m: Message, state: FSMContext):
    await state.update_data(geo=None)
    await state.set_state(NewComplaint.media)
    await m.answer("Прикрепите фото/видео (по желанию) или нажмите «Пропустить».", reply_markup=skip_kb())

# --- Медиа

@user_router.message(NewComplaint.media, F.photo | F.video | F.document)
async def collect_media(m: Message, state: FSMContext):
    data = await state.get_data()
    cid = data.get("cid") or gen_id()
    if not data.get("cid"):
        await state.update_data(cid=cid)

    file_id, kind, meta = None, None, {}
    if m.photo:
        file_id = m.photo[-1].file_id
        kind = "photo"
    elif m.video:
        file_id = m.video.file_id
        kind = "video"
    elif m.document:
        file_id = m.document.file_id
        kind = "document"
        meta = {"file_name": m.document.file_name, "mime": m.document.mime_type}

    if file_id:
        buf = (await state.get_data()).get("media_buf", [])
        item = {"file_id": file_id, "kind": kind}
        if meta:
            item.update(meta)
        buf.append(item)
        await state.update_data(media_buf=buf)

    data = await state.get_data()
    last_album_id = data.get("last_album_id")
    if m.media_group_id:
        if last_album_id == m.media_group_id:
            return
        await state.update_data(last_album_id=m.media_group_id)

    prev_hint = data.get("hint_msg_id")
    if prev_hint and prev_hint != -1:
        try:
            await m.bot.delete_message(chat_id=m.chat.id, message_id=prev_hint)
        except Exception:
            pass

    count = len((await state.get_data()).get("media_buf", []))
    text = f"Медиа добавлено ({count}). Можно отправить ещё или нажмите «Проверить и отправить»."
    await state.update_data(hint_msg_id=-1)
    try:
        msg = await m.answer(text, reply_markup=confirm_kb())
        await state.update_data(hint_msg_id=msg.message_id)
    except Exception:
        await state.update_data(hint_msg_id=None)

@user_router.message(NewComplaint.media, F.text.casefold() == "пропустить")
async def skip_media_text(m: Message, state: FSMContext):
    data = await state.get_data()
    hint_id = data.get("hint_msg_id")
    if hint_id and hint_id != -1:
        try:
            await m.bot.delete_message(chat_id=m.chat.id, message_id=hint_id)
        except Exception:
            pass
    await state.set_state(NewComplaint.confirm)
    await m.answer("Проверить и отправить?", reply_markup=confirm_kb())

@user_router.callback_query(F.data == "skip", NewComplaint.media)
async def skip_media_cb(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    hint_id = data.get("hint_msg_id")
    if hint_id and hint_id != -1:
        try:
            await c.bot.delete_message(chat_id=c.message.chat.id, message_id=hint_id)
        except Exception:
            pass
    await state.set_state(NewComplaint.confirm)
    await c.message.answer("Проверить и отправить?", reply_markup=confirm_kb())
    await c.answer()

@user_router.message(NewComplaint.media)
async def media_unrecognized(m: Message):
    await m.answer("Пришлите фото/видео или нажмите «Пропустить».", reply_markup=skip_kb())

# --- Подтверждение

@user_router.callback_query(F.data.startswith("confirm:"), NewComplaint.confirm)
async def confirm_send(c: CallbackQuery, state: FSMContext):
    await c.answer()
    action = c.data.split(":", 1)[1]

    if action != "send":
        data = await state.get_data()
        hint_id = data.get("hint_msg_id")
        if hint_id:
            try:
                await c.bot.delete_message(chat_id=c.message.chat.id, message_id=hint_id)
            except Exception:
                pass
        await state.clear()
        await c.message.answer("Отменено.", reply_markup=main_menu_kb())
        return

    data = await state.get_data()
    cid = data.get("cid", gen_id())
    media_buf = data.get("media_buf", [])
    row = {
        "id": cid,
        "user_id": c.from_user.id,
        "username": c.from_user.username,
        "category": data.get("category"),
        "district": None,
        "address_text": data.get("address_text"),
        "geo_lat": (data.get("geo")[0] if data.get("geo") else None),
        "geo_lon": (data.get("geo")[1] if data.get("geo") else None),
        "text": data.get("text"),
        "media_group_id": None,
        "status": "New",
        "assignee_id": None,
    }

    hint_id = data.get("hint_msg_id")
    if hint_id:
        try:
            await c.bot.delete_message(chat_id=c.message.chat.id, message_id=hint_id)
        except Exception:
            pass

    await c.message.answer(
        f"Ваша жалоба зарегистрирована: #{cid}\n"
        f"Статус: Новая. Я сообщу, когда её возьмут в работу.",
        reply_markup=main_menu_kb(),
    )
    await state.clear()

    async def _finalize_and_post():
        new_id = await asyncio.to_thread(save_complaint, row)
        if not new_id:
            return

        try:
            from storage import _conn_ctx, _execute_with_retry  # optional
            with _conn_ctx() as conn:
                _execute_with_retry(conn, "BEGIN;")
                try:
                    for mrow in media_buf:
                        _execute_with_retry(
                            conn,
                            "INSERT INTO media (complaint_id, file_id, kind) VALUES (?, ?, ?)",
                            (new_id, mrow["file_id"], mrow["kind"]),
                        )
                    _execute_with_retry(conn, "COMMIT;")
                except Exception:
                    _execute_with_retry(conn, "ROLLBACK;")
                    raise
        except Exception:
            for mrow in media_buf:
                await asyncio.to_thread(add_media, new_id, mrow["file_id"], mrow["kind"])

        from handlers_group import post_to_group
        try:
            await post_to_group(c.bot, {**row, "id": new_id})
        except Exception as e:
            print("post_to_group error:", e)

    asyncio.create_task(_finalize_and_post())

@user_router.callback_query(F.data.startswith("confirm:"), NewComplaint.media)
async def confirm_send_from_media(c: CallbackQuery, state: FSMContext):
    await state.set_state(NewComplaint.confirm)
    await confirm_send(c, state)

@user_router.message(NewComplaint.confirm, F.photo | F.video | F.document)
async def collect_media_while_confirm(m: Message, state: FSMContext):
    await state.set_state(NewComplaint.media)
    await collect_media(m, state)

# =========================
# Мои заявки
# =========================
@user_router.message(F.text == "Мои заявки")
async def my_complaints(m: Message):
    rows = list_user_complaints(m.from_user.id, limit=10)
    if not rows:
        await m.answer("У вас пока нет заявок.")
        return

    lines = []
    for cid, cat, addr, text, status, created_at, done_at in rows:
        short = (text or "—")
        if len(short) > 60:
            short = short[:57] + "…"
        lines.append(
            f"#{cid} • {status}\nКатегория: {cat or '—'}\nАдрес: {addr or '—'}\nОписание: {short}\n"
        )
    await m.answer("Ваши последние заявки:\n\n" + "\n".join(lines))

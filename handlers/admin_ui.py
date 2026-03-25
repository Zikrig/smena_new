"""Панель /admin в ЛС: только user_id из ADMIN_IDS. Управление группами и охранниками — на кнопках."""

from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import texts_ru as T
from db.database import Database, ObjectRow
from core.states import AdminStates
from core.utils import is_bot_admin

router = Router(name="admin_ui")

PAGE = 6


def _main_kb() -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Группы", callback_data="adm:gr:0"))
    b.row(InlineKeyboardButton(text="Охранники", callback_data="adm:us:0"))
    b.row(InlineKeyboardButton(text="➕ Привязать охранника", callback_data="adm:add"))
    b.row(InlineKeyboardButton(text="➕ Зарегистрировать группу (по id чата)", callback_data="adm:ng"))
    return b


def _groups_kb(objects: list[ObjectRow], page: int) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    start = page * PAGE
    chunk = objects[start : start + PAGE]
    for o in chunk:
        status = "⏸" if o.is_paused else "▶️"
        b.row(
            InlineKeyboardButton(
                text=f"{status} {o.name[:28]} (id{o.id})",
                callback_data=f"adm:g:{o.id}",
            )
        )
    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton(text="«", callback_data=f"adm:gr:{page - 1}"))
    if start + PAGE < len(objects):
        nav.append(InlineKeyboardButton(text="»", callback_data=f"adm:gr:{page + 1}"))
    if nav:
        b.row(*nav)
    b.row(InlineKeyboardButton(text="« В админку", callback_data="adm:main"))
    return b


def _group_detail_kb(o: ObjectRow) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    if o.is_paused:
        b.row(InlineKeyboardButton(text="▶️ Снять паузу", callback_data=f"adm:up:{o.id}"))
    else:
        b.row(InlineKeyboardButton(text="⏸ Пауза", callback_data=f"adm:ps:{o.id}"))
    b.row(InlineKeyboardButton(text="🗑 Удалить объект", callback_data=f"adm:dc:{o.id}"))
    b.row(InlineKeyboardButton(text="« К списку групп", callback_data="adm:gr:0"))
    return b


def _confirm_del_kb(oid: int) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="Да, удалить", callback_data=f"adm:dy:{oid}"),
        InlineKeyboardButton(text="Отмена", callback_data=f"adm:g:{oid}"),
    )
    return b


def _users_kb(rows: list[tuple[int, int, str]], page: int) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    start = page * PAGE
    chunk = rows[start : start + PAGE]
    for uid, _oid, oname in chunk:
        b.row(
            InlineKeyboardButton(
                text=f"🗑 {uid} — {oname[:20]}",
                callback_data=f"adm:rm:{uid}",
            )
        )
    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton(text="«", callback_data=f"adm:us:{page - 1}"))
    if start + PAGE < len(rows):
        nav.append(InlineKeyboardButton(text="»", callback_data=f"adm:us:{page + 1}"))
    if nav:
        b.row(*nav)
    b.row(InlineKeyboardButton(text="« В админку", callback_data="adm:main"))
    return b


def _pick_object_kb(objects: list[ObjectRow], prefix: str) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    for o in objects:
        b.row(InlineKeyboardButton(text=o.name[:40], callback_data=f"{prefix}{o.id}"))
    b.row(InlineKeyboardButton(text="Отмена", callback_data="adm:main"))
    return b


@router.message(Command("admin"), F.chat.type == ChatType.PRIVATE)
async def cmd_admin(message: Message, state: FSMContext) -> None:
    if not message.from_user or not is_bot_admin(message.from_user.id):
        return await message.answer(T.BOT_ADMIN_DENIED)
    await state.clear()
    await message.answer(
        "Админ-панель бота. Выберите раздел:",
        reply_markup=_main_kb().as_markup(),
    )


@router.message(Command("info"), F.chat.type == ChatType.PRIVATE)
async def cmd_info_private(message: Message) -> None:
    """Справка по командам; в этом роутере (до private_guard), чтобы /info в ЛС не терялся."""
    await message.answer(T.ADMIN_COMMANDS_LIST, parse_mode=ParseMode.HTML)


@router.callback_query(F.data == "adm:main")
async def cb_main(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not is_bot_admin(callback.from_user.id):
        return await callback.answer(T.BOT_ADMIN_DENIED, show_alert=True)
    await state.clear()
    await callback.message.edit_text(
        "Админ-панель бота. Выберите раздел:",
        reply_markup=_main_kb().as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:gr:"))
async def cb_groups(callback: CallbackQuery, db: Database) -> None:
    if not callback.from_user or not is_bot_admin(callback.from_user.id):
        return await callback.answer(T.BOT_ADMIN_DENIED, show_alert=True)
    page = int(callback.data.split(":")[-1])
    objs = await db.list_objects()
    if not objs:
        text = "Групп (объектов) пока нет. Зарегистрируйте через кнопку ниже или /set_object в группе."
    else:
        text = f"Группы (стр. {page + 1}): нажмите для деталей."
    await callback.message.edit_text(
        text,
        reply_markup=_groups_kb(objs, page).as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:g:"))
async def cb_group_detail(callback: CallbackQuery, db: Database) -> None:
    if not callback.from_user or not is_bot_admin(callback.from_user.id):
        return await callback.answer(T.BOT_ADMIN_DENIED, show_alert=True)
    oid = int(callback.data.split(":")[-1])
    o = await db.get_object_by_id(oid)
    if not o:
        return await callback.answer("Нет объекта", show_alert=True)
    st = "на паузе" if o.is_paused else "активен"
    text = (
        f"<b>{o.name}</b>\n"
        f"id объекта: <code>{o.id}</code>\n"
        f"id чата: <code>{o.group_chat_id}</code>\n"
        f"Статус: {st}"
    )
    await callback.message.edit_text(
        text,
        reply_markup=_group_detail_kb(o).as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:dc:"))
async def cb_group_del_confirm(callback: CallbackQuery, db: Database) -> None:
    if not callback.from_user or not is_bot_admin(callback.from_user.id):
        return await callback.answer(T.BOT_ADMIN_DENIED, show_alert=True)
    oid = int(callback.data.split(":")[-1])
    o = await db.get_object_by_id(oid)
    if not o:
        return await callback.answer("Нет объекта", show_alert=True)
    await callback.message.edit_text(
        f"Удалить объект «{o.name}» и все привязки охранников к нему?",
        reply_markup=_confirm_del_kb(oid).as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:ps:"))
@router.callback_query(F.data.startswith("adm:up:"))
@router.callback_query(F.data.startswith("adm:dy:"))
async def cb_group_actions(callback: CallbackQuery, db: Database) -> None:
    if not callback.from_user or not is_bot_admin(callback.from_user.id):
        return await callback.answer(T.BOT_ADMIN_DENIED, show_alert=True)
    parts = callback.data.split(":")
    action, oid_s = parts[1], parts[2]
    oid = int(oid_s)
    o = await db.get_object_by_id(oid)
    if not o:
        return await callback.answer("Нет объекта", show_alert=True)
    if action == "ps":
        await db.set_object_paused(oid, True)
    elif action == "up":
        await db.set_object_paused(oid, False)
    elif action == "dy":
        await db.delete_object(oid)
        await callback.message.edit_text(
            "Объект удалён.",
            reply_markup=_main_kb().as_markup(),
        )
        await callback.answer()
        return
    o = await db.get_object_by_id(oid)
    st = "на паузе" if o.is_paused else "активен"
    text = (
        f"<b>{o.name}</b>\n"
        f"id объекта: <code>{o.id}</code>\n"
        f"id чата: <code>{o.group_chat_id}</code>\n"
        f"Статус: {st}"
    )
    await callback.message.edit_text(
        text,
        reply_markup=_group_detail_kb(o).as_markup(),
        parse_mode="HTML",
    )
    await callback.answer("Готово")


@router.callback_query(F.data.startswith("adm:us:"))
async def cb_users(callback: CallbackQuery, db: Database) -> None:
    if not callback.from_user or not is_bot_admin(callback.from_user.id):
        return await callback.answer(T.BOT_ADMIN_DENIED, show_alert=True)
    page = int(callback.data.split(":")[-1])
    rows = await db.list_guards()
    if not rows:
        text = "Охранников нет. Добавьте через «Привязать охранника» или ссылку /bind_guard."
    else:
        text = f"Охранники (стр. {page + 1}). Нажмите, чтобы снять привязку."
    await callback.message.edit_text(
        text,
        reply_markup=_users_kb(rows, page).as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:rm:"))
async def cb_remove_guard(callback: CallbackQuery, db: Database) -> None:
    if not callback.from_user or not is_bot_admin(callback.from_user.id):
        return await callback.answer(T.BOT_ADMIN_DENIED, show_alert=True)
    uid = int(callback.data.split(":")[-1])
    ok = await db.remove_guard(uid)
    await callback.answer("Снято" if ok else "Не найден")
    rows = await db.list_guards()
    page = 0
    text = "Охранники." if rows else "Список пуст."
    await callback.message.edit_text(
        text,
        reply_markup=_users_kb(rows, page).as_markup(),
    )


@router.callback_query(F.data == "adm:add")
async def cb_add_guard_pick(callback: CallbackQuery, db: Database) -> None:
    if not callback.from_user or not is_bot_admin(callback.from_user.id):
        return await callback.answer(T.BOT_ADMIN_DENIED, show_alert=True)
    objs = await db.list_objects()
    if not objs:
        return await callback.answer("Сначала создайте объект.", show_alert=True)
    await callback.message.edit_text(
        "Выберите объект, к которому привязать охранника:",
        reply_markup=_pick_object_kb(objs, "adm:bd:").as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:bd:"))
async def cb_add_guard_object(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not is_bot_admin(callback.from_user.id):
        return await callback.answer(T.BOT_ADMIN_DENIED, show_alert=True)
    oid = int(callback.data.split(":")[-1])
    await state.set_state(AdminStates.wait_guard_user_id)
    await state.update_data(admin_bind_object_id=oid)
    await callback.message.edit_text(
        "Отправьте числовой Telegram user id охранника (только цифры, одним сообщением).\n"
        "Отмена: /cancel",
    )
    await callback.answer()


@router.message(AdminStates.wait_guard_user_id, F.text.regexp(r"^\d+$"))
async def msg_guard_id(message: Message, state: FSMContext, db: Database) -> None:
    if not message.from_user or not is_bot_admin(message.from_user.id):
        return
    data = await state.get_data()
    oid = int(data["admin_bind_object_id"])
    uid = int(message.text.strip())
    await db.bind_guard(uid, oid)
    await state.clear()
    o = await db.get_object_by_id(oid)
    await message.answer(
        f"Охранник <code>{uid}</code> привязан к «{o.name if o else '?'}».",
        parse_mode="HTML",
        reply_markup=_main_kb().as_markup(),
    )


@router.message(Command("cancel"), StateFilter(AdminStates))
async def admin_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.", reply_markup=_main_kb().as_markup())


@router.callback_query(F.data == "adm:ng")
async def cb_new_group(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not is_bot_admin(callback.from_user.id):
        return await callback.answer(T.BOT_ADMIN_DENIED, show_alert=True)
    await state.set_state(AdminStates.wait_group_chat_id)
    await callback.message.edit_text(
        "Отправьте id группы (отрицательное число, например <code>-1001234567890</code>).\n"
        "Узнать id можно через @userinfobot или бота в группе.\n"
        "/cancel — отмена.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.wait_group_chat_id, F.text)
async def msg_group_chat(message: Message, state: FSMContext) -> None:
    if not message.from_user or not is_bot_admin(message.from_user.id):
        return
    t = (message.text or "").strip()
    if not re.match(r"^-?\d+$", t):
        return await message.answer("Нужно целое число (id чата).")
    cid = int(t)
    await state.update_data(admin_new_group_chat_id=cid)
    await state.set_state(AdminStates.wait_group_name)
    await message.answer("Отправьте название объекта (текстом). /cancel — отмена.")


@router.message(AdminStates.wait_group_name, F.text)
async def msg_group_name(message: Message, state: FSMContext, db: Database) -> None:
    if not message.from_user or not is_bot_admin(message.from_user.id):
        return
    name = (message.text or "").strip()
    if not name:
        return await message.answer("Название не может быть пустым.")
    data = await state.get_data()
    cid = int(data["admin_new_group_chat_id"])
    row = await db.upsert_object(name, cid)
    await state.clear()
    await message.answer(
        f"Объект «{row.name}» зарегистрирован для чата <code>{cid}</code>.",
        parse_mode="HTML",
        reply_markup=_main_kb().as_markup(),
    )

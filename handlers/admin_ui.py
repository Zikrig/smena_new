"""Панель /admin в ЛС: только user_id из ADMIN_IDS."""

from __future__ import annotations

import re

from maxapi import F, Router
from maxapi.context.base import BaseContext
from maxapi.enums.parse_mode import ParseMode
from maxapi.filters.command import Command
from maxapi.types.attachments.buttons.callback_button import CallbackButton
from maxapi.types.updates.message_callback import MessageCallback
from maxapi.types.updates.message_created import MessageCreated
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

import texts_ru as T
from core.max_filters import BodyTextAny, BodyTextDigits, IsDialog
from core.states import AdminStates
from core.utils import is_bot_admin
from db.database import Database, ObjectRow

router = Router(router_id="admin_ui")

PAGE = 6


def _main_kb() -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    b.row(CallbackButton(text="Группы", payload="adm:gr:0"))
    b.row(CallbackButton(text="Охранники", payload="adm:us:0"))
    b.row(CallbackButton(text="➕ Привязать охранника", payload="adm:add"))
    b.row(
        CallbackButton(
            text="➕ Зарегистрировать группу (по id чата)",
            payload="adm:ng",
        )
    )
    return b


def _groups_kb(objects: list[ObjectRow], page: int) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    start = page * PAGE
    chunk = objects[start : start + PAGE]
    for o in chunk:
        status = "⏸" if o.is_paused else "▶️"
        b.row(
            CallbackButton(
                text=f"{status} {o.name[:28]} (id{o.id})",
                payload=f"adm:g:{o.id}",
            )
        )
    nav = []
    if start > 0:
        nav.append(CallbackButton(text="«", payload=f"adm:gr:{page - 1}"))
    if start + PAGE < len(objects):
        nav.append(CallbackButton(text="»", payload=f"adm:gr:{page + 1}"))
    if nav:
        b.row(*nav)
    b.row(CallbackButton(text="« В админку", payload="adm:main"))
    return b


def _group_detail_kb(o: ObjectRow) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    if o.is_paused:
        b.row(CallbackButton(text="▶️ Снять паузу", payload=f"adm:up:{o.id}"))
    else:
        b.row(CallbackButton(text="⏸ Пауза", payload=f"adm:ps:{o.id}"))
    b.row(CallbackButton(text="🗑 Удалить объект", payload=f"adm:dc:{o.id}"))
    b.row(CallbackButton(text="« К списку групп", payload="adm:gr:0"))
    return b


def _confirm_del_kb(oid: int) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    b.row(
        CallbackButton(text="Да, удалить", payload=f"adm:dy:{oid}"),
        CallbackButton(text="Отмена", payload=f"adm:g:{oid}"),
    )
    return b


def _users_kb(rows: list[tuple[int, int, str]], page: int) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    start = page * PAGE
    chunk = rows[start : start + PAGE]
    for uid, _oid, oname in chunk:
        b.row(
            CallbackButton(
                text=f"🗑 {uid} — {oname[:20]}",
                payload=f"adm:rm:{uid}",
            )
        )
    nav = []
    if start > 0:
        nav.append(CallbackButton(text="«", payload=f"adm:us:{page - 1}"))
    if start + PAGE < len(rows):
        nav.append(CallbackButton(text="»", payload=f"adm:us:{page + 1}"))
    if nav:
        b.row(*nav)
    b.row(CallbackButton(text="« В админку", payload="adm:main"))
    return b


def _pick_object_kb(objects: list[ObjectRow], prefix: str) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    for o in objects:
        b.row(CallbackButton(text=o.name[:40], payload=f"{prefix}{o.id}"))
    b.row(CallbackButton(text="Отмена", payload="adm:main"))
    return b


@router.message_created(Command("admin"), IsDialog())
async def cmd_admin(event: MessageCreated, context: BaseContext) -> None:
    message = event.message
    su = message.sender.user_id if message.sender else None
    if su is None or not is_bot_admin(su):
        return await message.answer(text=T.BOT_ADMIN_DENIED)
    await context.clear()
    await message.answer(
        text="Админ-панель бота. Выберите раздел:",
        attachments=[_main_kb().as_markup()],
    )


@router.message_created(Command("info"), IsDialog())
async def cmd_info_private(event: MessageCreated, context: BaseContext) -> None:
    message = event.message
    await message.answer(text=T.ADMIN_COMMANDS_LIST, parse_mode=ParseMode.HTML)


@router.message_callback(F.callback.payload == "adm:main")
async def cb_main(event: MessageCallback, context: BaseContext) -> None:
    cb = event.callback
    msg = event.message
    if msg is None or msg.body is None:
        return await event.answer(notification="")
    if not is_bot_admin(cb.user.user_id):
        return await event.answer(notification=T.BOT_ADMIN_DENIED)
    await context.clear()
    await msg.edit(
        text="Админ-панель бота. Выберите раздел:",
        attachments=[_main_kb().as_markup()],
    )
    await event.answer(notification="")


@router.message_callback(F.callback.payload.startswith("adm:gr:"))
async def cb_groups(event: MessageCallback, context: BaseContext, db: Database) -> None:
    cb = event.callback
    msg = event.message
    if msg is None or msg.body is None:
        return await event.answer(notification="")
    if not is_bot_admin(cb.user.user_id):
        return await event.answer(notification=T.BOT_ADMIN_DENIED)
    page = int((cb.payload or "").split(":")[-1])
    objs = await db.list_objects()
    if not objs:
        text = "Групп (объектов) пока нет. Зарегистрируйте через кнопку ниже или /set в группе."
    else:
        text = f"Группы (стр. {page + 1}): нажмите для деталей."
    await msg.edit(text=text, attachments=[_groups_kb(objs, page).as_markup()])
    await event.answer(notification="")


@router.message_callback(F.callback.payload.startswith("adm:g:"))
async def cb_group_detail(event: MessageCallback, context: BaseContext, db: Database) -> None:
    cb = event.callback
    msg = event.message
    if msg is None or msg.body is None:
        return await event.answer(notification="")
    if not is_bot_admin(cb.user.user_id):
        return await event.answer(notification=T.BOT_ADMIN_DENIED)
    oid = int((cb.payload or "").split(":")[-1])
    o = await db.get_object_by_id(oid)
    if not o:
        return await event.answer(notification="Нет объекта")
    st = "на паузе" if o.is_paused else "активен"
    text = (
        f"<b>{o.name}</b>\n"
        f"id объекта: <code>{o.id}</code>\n"
        f"id чата: <code>{o.group_chat_id}</code>\n"
        f"Статус: {st}"
    )
    await msg.edit(
        text=text,
        attachments=[_group_detail_kb(o).as_markup()],
        parse_mode=ParseMode.HTML,
    )
    await event.answer(notification="")


@router.message_callback(F.callback.payload.startswith("adm:dc:"))
async def cb_group_del_confirm(event: MessageCallback, context: BaseContext, db: Database) -> None:
    cb = event.callback
    msg = event.message
    if msg is None or msg.body is None:
        return await event.answer(notification="")
    if not is_bot_admin(cb.user.user_id):
        return await event.answer(notification=T.BOT_ADMIN_DENIED)
    oid = int((cb.payload or "").split(":")[-1])
    o = await db.get_object_by_id(oid)
    if not o:
        return await event.answer(notification="Нет объекта")
    await msg.edit(
        text=f"Удалить объект «{o.name}» и все привязки охранников к нему?",
        attachments=[_confirm_del_kb(oid).as_markup()],
    )
    await event.answer(notification="")


@router.message_callback(F.callback.payload.startswith("adm:ps:"))
@router.message_callback(F.callback.payload.startswith("adm:up:"))
@router.message_callback(F.callback.payload.startswith("adm:dy:"))
async def cb_group_actions(event: MessageCallback, context: BaseContext, db: Database) -> None:
    cb = event.callback
    msg = event.message
    if msg is None or msg.body is None:
        return await event.answer(notification="")
    if not is_bot_admin(cb.user.user_id):
        return await event.answer(notification=T.BOT_ADMIN_DENIED)
    parts = (cb.payload or "").split(":")
    action, oid_s = parts[1], parts[2]
    oid = int(oid_s)
    o = await db.get_object_by_id(oid)
    if not o:
        return await event.answer(notification="Нет объекта")
    if action == "ps":
        await db.set_object_paused(oid, True)
    elif action == "up":
        await db.set_object_paused(oid, False)
    elif action == "dy":
        await db.delete_object(oid)
        await msg.edit(
            text="Объект удалён.",
            attachments=[_main_kb().as_markup()],
        )
        await event.answer(notification="")
        return
    o = await db.get_object_by_id(oid)
    assert o
    st = "на паузе" if o.is_paused else "активен"
    text = (
        f"<b>{o.name}</b>\n"
        f"id объекта: <code>{o.id}</code>\n"
        f"id чата: <code>{o.group_chat_id}</code>\n"
        f"Статус: {st}"
    )
    await msg.edit(
        text=text,
        attachments=[_group_detail_kb(o).as_markup()],
        parse_mode=ParseMode.HTML,
    )
    await event.answer(notification="Готово")


@router.message_callback(F.callback.payload.startswith("adm:us:"))
async def cb_users(event: MessageCallback, context: BaseContext, db: Database) -> None:
    cb = event.callback
    msg = event.message
    if msg is None or msg.body is None:
        return await event.answer(notification="")
    if not is_bot_admin(cb.user.user_id):
        return await event.answer(notification=T.BOT_ADMIN_DENIED)
    page = int((cb.payload or "").split(":")[-1])
    rows = await db.list_guards()
    if not rows:
        text = "Охранников нет. Добавьте через «Привязать охранника» или ссылку из /bind в группе."
    else:
        text = f"Охранники (стр. {page + 1}). Нажмите, чтобы снять привязку."
    await msg.edit(text=text, attachments=[_users_kb(rows, page).as_markup()])
    await event.answer(notification="")


@router.message_callback(F.callback.payload.startswith("adm:rm:"))
async def cb_remove_guard(event: MessageCallback, context: BaseContext, db: Database) -> None:
    cb = event.callback
    msg = event.message
    if msg is None or msg.body is None:
        return await event.answer(notification="")
    if not is_bot_admin(cb.user.user_id):
        return await event.answer(notification=T.BOT_ADMIN_DENIED)
    uid = int((cb.payload or "").split(":")[-1])
    ok = await db.remove_guard(uid)
    await event.answer(notification="Снято" if ok else "Не найден")
    rows = await db.list_guards()
    page = 0
    text = "Охранники." if rows else "Список пуст."
    await msg.edit(text=text, attachments=[_users_kb(rows, page).as_markup()])


@router.message_callback(F.callback.payload == "adm:add")
async def cb_add_guard_pick(event: MessageCallback, context: BaseContext, db: Database) -> None:
    cb = event.callback
    msg = event.message
    if msg is None or msg.body is None:
        return await event.answer(notification="")
    if not is_bot_admin(cb.user.user_id):
        return await event.answer(notification=T.BOT_ADMIN_DENIED)
    objs = await db.list_objects()
    if not objs:
        return await event.answer(notification="Сначала создайте объект.")
    await msg.edit(
        text="Выберите объект, к которому привязать охранника:",
        attachments=[_pick_object_kb(objs, "adm:bd:").as_markup()],
    )
    await event.answer(notification="")


@router.message_callback(F.callback.payload.startswith("adm:bd:"))
async def cb_add_guard_object(event: MessageCallback, context: BaseContext) -> None:
    cb = event.callback
    msg = event.message
    if msg is None or msg.body is None:
        return await event.answer(notification="")
    if not is_bot_admin(cb.user.user_id):
        return await event.answer(notification=T.BOT_ADMIN_DENIED)
    oid = int((cb.payload or "").split(":")[-1])
    await context.set_state(AdminStates.wait_guard_user_id)
    await context.update_data(admin_bind_object_id=oid)
    await msg.edit(
        text="Отправьте числовой user id охранника в MAX (только цифры, одним сообщением).\n"
        "Отмена: /cancel",
    )
    await event.answer(notification="")


@router.message_created(AdminStates.wait_guard_user_id, BodyTextDigits())
async def msg_guard_id(event: MessageCreated, context: BaseContext, db: Database) -> None:
    message = event.message
    su = message.sender.user_id if message.sender else None
    if su is None or not is_bot_admin(su):
        return
    data = await context.get_data()
    oid = int(data["admin_bind_object_id"])
    body = message.body
    uid = int((body.text or "").strip())
    await db.bind_guard(uid, oid)
    await context.clear()
    o = await db.get_object_by_id(oid)
    await message.answer(
        text=f"Охранник <code>{uid}</code> привязан к «{o.name if o else '?'}».",
        parse_mode=ParseMode.HTML,
        attachments=[_main_kb().as_markup()],
    )


@router.message_created(Command("cancel"), AdminStates.wait_guard_user_id)
@router.message_created(Command("cancel"), AdminStates.wait_group_chat_id)
@router.message_created(Command("cancel"), AdminStates.wait_group_name)
async def admin_cancel(event: MessageCreated, context: BaseContext) -> None:
    message = event.message
    await context.clear()
    await message.answer(text="Отменено.", attachments=[_main_kb().as_markup()])


@router.message_callback(F.callback.payload == "adm:ng")
async def cb_new_group(event: MessageCallback, context: BaseContext) -> None:
    cb = event.callback
    msg = event.message
    if msg is None or msg.body is None:
        return await event.answer(notification="")
    if not is_bot_admin(cb.user.user_id):
        return await event.answer(notification=T.BOT_ADMIN_DENIED)
    await context.set_state(AdminStates.wait_group_chat_id)
    await msg.edit(
        text="Отправьте id группового чата в MAX (целое число).\n"
        "/cancel — отмена.",
        parse_mode=ParseMode.HTML,
    )
    await event.answer(notification="")


@router.message_created(AdminStates.wait_group_chat_id, BodyTextAny())
async def msg_group_chat(event: MessageCreated, context: BaseContext) -> None:
    message = event.message
    su = message.sender.user_id if message.sender else None
    if su is None or not is_bot_admin(su):
        return
    t = (message.body.text or "").strip()
    if not re.match(r"^-?\d+$", t):
        return await message.answer(text="Нужно целое число (id чата).")
    cid = int(t)
    await context.update_data(admin_new_group_chat_id=cid)
    await context.set_state(AdminStates.wait_group_name)
    await message.answer(text="Отправьте название объекта (текстом). /cancel — отмена.")


@router.message_created(AdminStates.wait_group_name, BodyTextAny())
async def msg_group_name(event: MessageCreated, context: BaseContext, db: Database) -> None:
    message = event.message
    su = message.sender.user_id if message.sender else None
    if su is None or not is_bot_admin(su):
        return
    name = (message.body.text or "").strip()
    if not name:
        return await message.answer(text="Название не может быть пустым.")
    data = await context.get_data()
    cid = int(data["admin_new_group_chat_id"])
    row = await db.upsert_object(name, cid)
    await context.clear()
    await message.answer(
        text=f"Объект «{row.name}» зарегистрирован для чата <code>{cid}</code>.",
        parse_mode=ParseMode.HTML,
        attachments=[_main_kb().as_markup()],
    )

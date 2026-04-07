from __future__ import annotations

import asyncio
import logging
from io import BytesIO
from datetime import datetime
from typing import Any, List, Optional

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.methods import SendMediaGroup
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InputMediaPhoto, Message

from constants import (
    ALBUM_DEBOUNCE_SECONDS,
    HARD_PHOTO_LIMIT,
    SECONDS_BETWEEN_GROUP_SENDS,
    SECONDS_BETWEEN_MEDIA_GROUPS,
    SOFT_PHOTO_LIMIT,
    TELEGRAM_MEDIA_GROUP_MAX,
)
from core.config import EMERGENCY_CONTACTS
from core.keyboards import accounted_markup, main_menu_keyboard
from core.report_types import ReportKind, report_title
from core.states import GuardStates
from core.utils import telegram_group_message_link
from db.database import Database, ObjectRow
import texts_ru as T
from services.album_tasks import cancel_album_task, schedule_album_task
from services.fallback_menu_tasks import cancel_fallback_menu_task, schedule_fallback_menu_task
from services.report_build import format_group_caption, format_text_report_caption
from services.service_menu import (
    clear_scenario_hint_message,
    clear_service_menu_message,
    delete_bot_message_safe,
    purge_disposable_messages,
    refresh_service_menu,
    register_disposable,
    send_explaining,
)
from services import sheets
from services.image_stamp import stamp_datetime_on_photo

router = Router(name="private_guard")
_log = logging.getLogger(__name__)


async def _pause_between_group_sends() -> None:
    await asyncio.sleep(SECONDS_BETWEEN_GROUP_SENDS)


async def _delete_main_menu_message(message: Message) -> None:
    """Сообщение с главным меню, с которого нажата кнопка — удаляем целиком."""
    if not message.chat:
        return
    await delete_bot_message_safe(message.bot, message.chat.id, message.message_id)


async def _refresh_message_report_menu(bot, chat_id: int, state: FSMContext) -> None:
    data = await state.get_data()
    entries = list(data.get("photo_entries") or [])
    n = len(entries)
    locked = data.get("msg_locked_kind")
    if locked == "photo" or n > 0:
        await refresh_service_menu(
            bot,
            chat_id,
            state,
            show_photo_counter=True,
            photo_count=n,
            no_counter_caption=T.SERVICE_MENU_CAPTION_MESSAGE_WITH_PHOTOS,
        )
    else:
        await refresh_service_menu(
            bot,
            chat_id,
            state,
            show_photo_counter=False,
            photo_count=0,
            no_counter_caption=T.SERVICE_MENU_CAPTION_MESSAGE,
        )


async def _delete_scenario_hint_if_needed(bot, chat_id: int, state: FSMContext) -> None:
    """Удаляет длинную подсказку сценария после первого фото или первого видеокружка."""
    data = await state.get_data()
    hint_id = data.get("scenario_hint_message_id")
    if not hint_id:
        return
    entries: List[dict] = list(data.get("photo_entries") or [])
    video_ids: List[int] = list(data.get("video_msg_ids") or [])
    if len(entries) < 1 and len(video_ids) < 1:
        return
    await delete_bot_message_safe(bot, chat_id, int(hint_id))
    await state.update_data(scenario_hint_message_id=None)


async def _pin_report_message(bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.pin_chat_message(chat_id, message_id, disable_notification=True)
    except Exception as e:
        _log.warning("Не удалось закрепить сообщение %s в чате %s: %s", message_id, chat_id, e)


async def _recover_from_group_send_error(
    callback: CallbackQuery, state: FSMContext, exc: Exception
) -> None:
    _log.warning("Отправка в группу объекта не удалась: %s", exc)
    await clear_scenario_hint_message(
        callback.bot, callback.message.chat.id, state
    )
    await purge_disposable_messages(callback.bot, callback.message.chat.id, state)
    await clear_service_menu_message(callback.bot, callback.message.chat.id, state)
    await state.clear()
    await send_explaining(
        callback.bot,
        callback.message.chat.id,
        T.GROUP_CHAT_UNAVAILABLE,
    )
    await callback.message.answer(T.BOT_DESCRIPTION, reply_markup=main_menu_keyboard())


async def guard_access(
    db: Database, user_id: int
) -> tuple[Optional[ObjectRow], Optional[str]]:
    """(объект, None) или (None, not_bound|paused)."""
    oid = await db.get_guard_object_id(user_id)
    if not oid:
        return None, "not_bound"
    obj = await db.get_object_by_id(oid)
    if not obj:
        return None, "not_bound"
    if obj.is_paused:
        return None, "paused"
    return obj, None


async def _start_bind(message: Message, state: FSMContext, token: str, db: Database) -> None:
    object_id = await db.consume_bind_token(token)
    if not object_id or not message.from_user:
        return await message.answer(T.BIND_INVALID)
    if await db.get_guard_object_id(message.from_user.id):
        return await message.answer(T.ALREADY_BOUND)
    await db.bind_guard(message.from_user.id, object_id)
    obj = await db.get_object_by_id(object_id)
    await message.answer(T.BIND_OK.format(name=obj.name if obj else "?"))
    await message.answer(T.BOT_DESCRIPTION, reply_markup=main_menu_keyboard())


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, db: Database) -> None:
    await state.clear()
    if not message.from_user:
        return
    cancel_album_task(message.from_user.id)
    cancel_fallback_menu_task(message.from_user.id)
    parts = (message.text or "").split(maxsplit=1)
    arg = parts[1].strip() if len(parts) > 1 else ""
    if arg.startswith("bind_"):
        return await _start_bind(message, state, arg.replace("bind_", "", 1), db)
    _, err = await guard_access(db, message.from_user.id)
    if err == "not_bound":
        return await message.answer(T.NOT_BOUND)
    if err == "paused":
        return await message.answer(T.OBJECT_PAUSED)
    await message.answer(T.BOT_DESCRIPTION, reply_markup=main_menu_keyboard())


def _base_photo_data(kind: ReportKind) -> dict:
    return {
        "report_kind": kind.value,
        "photo_entries": [],
        "album_buffer": [],
        "album_group_id": None,
        "soft_warned": False,
    }


async def _enter_photo_scenario(message: Message, state: FSMContext, kind: ReportKind) -> None:
    await _delete_main_menu_message(message)
    await state.clear()
    cancel_album_task(message.from_user.id)
    cancel_fallback_menu_task(message.from_user.id)
    await state.set_state(GuardStates.photo_report)
    await state.update_data(**_base_photo_data(kind))
    title = report_title(kind)
    await message.answer(T.REPORT_STARTED.format(report_title=title))
    photo_hint = {
        ReportKind.HANDOVER: T.PHOTO_SCENARIO_HINT_HANDOVER,
        ReportKind.PATROL: T.PHOTO_SCENARIO_HINT_PATROL,
        ReportKind.INSPECTION: T.PHOTO_SCENARIO_HINT_INSPECTION,
    }.get(kind)
    if photo_hint:
        hint_msg = await message.answer(photo_hint)
        await state.update_data(scenario_hint_message_id=hint_msg.message_id)
    await refresh_service_menu(
        message.bot,
        message.chat.id,
        state,
        show_photo_counter=False,
        photo_count=0,
        no_counter_caption=T.SERVICE_MENU_CAPTION_NO_COUNTER,
    )


async def _enter_video_scenario(message: Message, state: FSMContext, kind: ReportKind) -> None:
    await _delete_main_menu_message(message)
    await state.clear()
    cancel_album_task(message.from_user.id)
    cancel_fallback_menu_task(message.from_user.id)
    await state.set_state(GuardStates.video_note_report)
    await state.update_data(report_kind=kind.value, video_msg_ids=[])
    title = report_title(kind)
    await message.answer(T.REPORT_STARTED.format(report_title=title))
    video_hint = {
        ReportKind.START_SHIFT: T.VIDEO_SCENARIO_HINT_START_SHIFT,
        ReportKind.POST_CHECK: T.VIDEO_SCENARIO_HINT_POST_CHECK,
    }.get(kind)
    if video_hint:
        hint_msg = await message.answer(video_hint)
        await state.update_data(scenario_hint_message_id=hint_msg.message_id)
    await refresh_service_menu(
        message.bot,
        message.chat.id,
        state,
        show_photo_counter=False,
        photo_count=0,
    )


async def _enter_message_scenario(message: Message, state: FSMContext) -> None:
    await _delete_main_menu_message(message)
    await state.clear()
    cancel_album_task(message.from_user.id)
    cancel_fallback_menu_task(message.from_user.id)
    await state.set_state(GuardStates.message_report)
    await state.update_data(
        report_kind=ReportKind.MESSAGE.value,
        msg_locked_kind=None,
        photo_entries=[],
        album_buffer=[],
        album_group_id=None,
        single_msg_id=None,
        message_text_body=None,
    )
    await message.answer(
        T.REPORT_STARTED.format(report_title=report_title(ReportKind.MESSAGE))
    )
    hint_msg = await message.answer(T.MESSAGE_SCENARIO_HINT)
    await state.update_data(scenario_hint_message_id=hint_msg.message_id)
    await _refresh_message_report_menu(message.bot, message.chat.id, state)


async def _main_menu_from_callback(
    callback: CallbackQuery, state: FSMContext, db: Database
) -> bool:
    """True если можно продолжить сценарий, False если ответили ошибкой."""
    if not callback.message or callback.message.chat.type != ChatType.PRIVATE:
        await callback.answer()
        return False
    await callback.answer()
    _, err = await guard_access(db, callback.from_user.id)
    if err == "not_bound":
        await callback.message.answer(T.NOT_BOUND)
        return False
    if err == "paused":
        await callback.message.answer(T.OBJECT_PAUSED)
        return False
    return True


@router.callback_query(F.data == "menu:shift", StateFilter(None))
async def menu_start_shift(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await _main_menu_from_callback(callback, state, db):
        return
    await _enter_video_scenario(callback.message, state, ReportKind.START_SHIFT)


@router.callback_query(F.data == "menu:post", StateFilter(None))
async def menu_post_check(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await _main_menu_from_callback(callback, state, db):
        return
    await _enter_video_scenario(callback.message, state, ReportKind.POST_CHECK)


@router.callback_query(F.data == "menu:handover", StateFilter(None))
async def menu_handover(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await _main_menu_from_callback(callback, state, db):
        return
    await _enter_photo_scenario(callback.message, state, ReportKind.HANDOVER)


@router.callback_query(F.data == "menu:patrol", StateFilter(None))
async def menu_patrol(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await _main_menu_from_callback(callback, state, db):
        return
    await _enter_photo_scenario(callback.message, state, ReportKind.PATROL)


@router.callback_query(F.data == "menu:inspection", StateFilter(None))
async def menu_inspection(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await _main_menu_from_callback(callback, state, db):
        return
    await _enter_photo_scenario(callback.message, state, ReportKind.INSPECTION)


@router.callback_query(F.data == "menu:message", StateFilter(None))
async def menu_message(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await _main_menu_from_callback(callback, state, db):
        return
    await _enter_message_scenario(callback.message, state)


@router.callback_query(F.data == "menu:alarm", StateFilter(None))
async def menu_alarm(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await _main_menu_from_callback(callback, state, db):
        return
    msg = callback.message
    if not msg:
        return
    text = T.format_alarm_contacts_html(EMERGENCY_CONTACTS)
    try:
        if msg.text is not None:
            await msg.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=None)
        else:
            await msg.answer(text, parse_mode=ParseMode.HTML)
    except TelegramBadRequest:
        await msg.answer(text, parse_mode=ParseMode.HTML)
    await msg.answer(T.ALARM_WHAT_ELSE, reply_markup=main_menu_keyboard())


async def _flush_album_to_entries(
    bot,
    chat_id: int,
    state: FSMContext,
    *,
    show_counter: bool,
    is_message_scenario: bool = False,
) -> None:
    data = await state.get_data()
    buf: List[dict] = list(data.get("album_buffer") or [])
    if not buf:
        await state.update_data(album_buffer=[], album_group_id=None)
        return
    entries: List[dict] = list(data.get("photo_entries") or [])
    if is_message_scenario:
        no_counter = (
            T.SERVICE_MENU_CAPTION_MESSAGE_WITH_PHOTOS
            if show_counter
            else T.SERVICE_MENU_CAPTION_MESSAGE
        )
    else:
        no_counter = None
    if len(entries) + len(buf) > HARD_PHOTO_LIMIT:
        can_take = max(0, HARD_PHOTO_LIMIT - len(entries))
        dropped = len(buf) - can_take
        if can_take > 0:
            entries.extend(buf[:can_take])
        await state.update_data(photo_entries=entries, album_buffer=[], album_group_id=None)
        if dropped > 0:
            await send_explaining(
                bot,
                chat_id,
                T.PHOTO_LIMIT_PARTIAL_ACCEPTED.format(n=dropped),
                state,
            )
        menu_show_counter = (
            show_counter
            if is_message_scenario
            else (show_counter and len(entries) > 0)
        )
        await refresh_service_menu(
            bot,
            chat_id,
            state,
            show_photo_counter=menu_show_counter,
            photo_count=len(entries),
            no_counter_caption=no_counter,
        )
        if len(entries) > 0:
            await _delete_scenario_hint_if_needed(bot, chat_id, state)
        return
    entries.extend(buf)
    await state.update_data(photo_entries=entries, album_buffer=[], album_group_id=None)
    if (
        not is_message_scenario
        and len(entries) > SOFT_PHOTO_LIMIT
        and not data.get("soft_warned")
    ):
        await state.update_data(soft_warned=True)
        await send_explaining(
            bot,
            chat_id,
            T.SOFT_LIMIT_WARNING.format(n=len(entries), soft=SOFT_PHOTO_LIMIT, hard=HARD_PHOTO_LIMIT),
            state,
        )
    menu_show_counter = (
        show_counter
        if is_message_scenario
        else (show_counter and len(entries) > 0)
    )
    await refresh_service_menu(
        bot,
        chat_id,
        state,
        show_photo_counter=menu_show_counter,
        photo_count=len(entries),
        no_counter_caption=no_counter,
    )
    if len(entries) > 0:
        await _delete_scenario_hint_if_needed(bot, chat_id, state)


def _make_photo_entry(message: Message) -> dict:
    return {
        "file_id": message.photo[-1].file_id,
        "dt": datetime.now(),
        "message_id": message.message_id,
    }


@router.message(GuardStates.photo_report, F.photo)
async def photo_report_collect(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    entries: List[dict] = list(data.get("photo_entries") or [])
    mg = message.media_group_id
    uid = message.from_user.id

    # Для альбомов не отвечаем на каждый кадр отдельно: дождёмся debounce и посчитаем общее N.
    if mg is None and len(entries) >= HARD_PHOTO_LIMIT:
        await send_explaining(
            message.bot,
            message.chat.id,
            T.PHOTO_LIMIT_PARTIAL_ACCEPTED.format(n=1),
            state,
        )
        await refresh_service_menu(
            message.bot,
            message.chat.id,
            state,
            show_photo_counter=len(entries) > 0,
            photo_count=len(entries),
        )
        return

    if mg is None:
        cancel_album_task(uid)
        await _flush_album_to_entries(message.bot, message.chat.id, state, show_counter=True)
        data = await state.get_data()
        entries = list(data.get("photo_entries") or [])
        if len(entries) >= HARD_PHOTO_LIMIT:
            await send_explaining(
                message.bot,
                message.chat.id,
                T.PHOTO_LIMIT_PARTIAL_ACCEPTED.format(n=1),
                state,
            )
            await refresh_service_menu(
                message.bot,
                message.chat.id,
                state,
                show_photo_counter=len(entries) > 0,
                photo_count=len(entries),
            )
            return
        entries.append(_make_photo_entry(message))
        await state.update_data(photo_entries=entries)
        await _delete_scenario_hint_if_needed(message.bot, message.chat.id, state)
        if len(entries) > SOFT_PHOTO_LIMIT and not data.get("soft_warned"):
            await state.update_data(soft_warned=True)
            await send_explaining(
                message.bot,
                message.chat.id,
                T.SOFT_LIMIT_WARNING.format(
                    n=len(entries),
                    soft=SOFT_PHOTO_LIMIT,
                    hard=HARD_PHOTO_LIMIT,
                ),
                state,
            )
        await refresh_service_menu(
            message.bot,
            message.chat.id,
            state,
            show_photo_counter=len(entries) > 0,
            photo_count=len(entries),
        )
        return

    gid = str(mg)
    cur_gid = data.get("album_group_id")
    if cur_gid and cur_gid != gid:
        cancel_album_task(uid)
        await _flush_album_to_entries(message.bot, message.chat.id, state, show_counter=True)

    data = await state.get_data()
    buf = list(data.get("album_buffer") or [])
    buf.append(_make_photo_entry(message))
    await state.update_data(album_buffer=buf, album_group_id=gid)

    schedule_album_task(
        uid,
        lambda: _debounce_photo(uid, message.bot, message.chat.id, state, True, False),
    )


async def _debounce_photo(
    user_id: int,
    bot,
    chat_id: int,
    state: FSMContext,
    show_counter: bool,
    is_message_scenario: bool,
) -> None:
    await asyncio.sleep(ALBUM_DEBOUNCE_SECONDS)
    await _flush_album_to_entries(
        bot,
        chat_id,
        state,
        show_counter=show_counter,
        is_message_scenario=is_message_scenario,
    )


@router.message(GuardStates.photo_report)
async def photo_report_wrong(message: Message, state: FSMContext) -> None:
    await send_explaining(
        message.bot,
        message.chat.id,
        T.WRONG_CONTENT.format(reason="нужны только фото"),
        state,
    )
    data = await state.get_data()
    entries_wrong = list(data.get("photo_entries") or [])
    n_wrong = len(entries_wrong)
    await refresh_service_menu(
        message.bot,
        message.chat.id,
        state,
        show_photo_counter=n_wrong > 0,
        photo_count=n_wrong,
    )


@router.message(GuardStates.video_note_report, F.video_note)
async def video_note_collect(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    ids: List[int] = list(data.get("video_msg_ids") or [])
    if ids:
        await send_explaining(
            message.bot, message.chat.id, T.SECOND_MEDIA_NOT_ALLOWED, state
        )
    else:
        ids.append(message.message_id)
        await state.update_data(video_msg_ids=ids)
    await _delete_scenario_hint_if_needed(message.bot, message.chat.id, state)
    await refresh_service_menu(
        message.bot,
        message.chat.id,
        state,
        show_photo_counter=False,
        photo_count=0,
    )


@router.message(GuardStates.video_note_report)
async def video_note_wrong(message: Message, state: FSMContext) -> None:
    # Видеосценарий: если пользователь шлёт пачку «не того» (например много фото),
    # не спамим одинаковой ошибкой и не пересоздаём сервисное меню на каждое сообщение.
    if message.media_group_id is not None:
        data = await state.get_data()
        current_group_id = str(message.media_group_id)
        last_group_id = data.get("wrong_content_album_group_id")
        if last_group_id == current_group_id:
            return
        await state.update_data(wrong_content_album_group_id=current_group_id)

    data = await state.get_data()
    if not data.get("wrong_content_warned_video_note"):
        await state.update_data(wrong_content_warned_video_note=True)
        await send_explaining(
            message.bot,
            message.chat.id,
            T.WRONG_CONTENT.format(reason="нужен только видеокружок"),
            state,
        )
    await refresh_service_menu(
        message.bot,
        message.chat.id,
        state,
        show_photo_counter=False,
        photo_count=0,
    )


@router.message(GuardStates.message_report, F.photo)
async def message_scenario_photo(message: Message, state: FSMContext) -> None:
    if message.caption:
        await send_explaining(
            message.bot, message.chat.id, T.PHOTO_CAPTION_FORBIDDEN, state
        )
        return await _refresh_message_report_menu(message.bot, message.chat.id, state)
    data = await state.get_data()
    locked = data.get("msg_locked_kind")
    if locked and locked != "photo":
        await send_explaining(
            message.bot, message.chat.id, T.WRONG_CONTENT_MESSAGE_MIX, state
        )
        return await _refresh_message_report_menu(message.bot, message.chat.id, state)
    await state.update_data(msg_locked_kind="photo")
    uid = message.from_user.id
    mg = message.media_group_id
    entries: List[dict] = list(data.get("photo_entries") or [])

    if mg is None:
        cancel_album_task(uid)
        await _flush_album_to_entries(
            message.bot,
            message.chat.id,
            state,
            show_counter=True,
            is_message_scenario=True,
        )
        data = await state.get_data()
        entries = list(data.get("photo_entries") or [])
        if len(entries) >= HARD_PHOTO_LIMIT:
            await send_explaining(
                message.bot,
                message.chat.id,
                T.PHOTO_LIMIT_PARTIAL_ACCEPTED.format(n=1),
                state,
            )
            return await _refresh_message_report_menu(message.bot, message.chat.id, state)
        entries.append(_make_photo_entry(message))
        await state.update_data(photo_entries=entries)
        await _delete_scenario_hint_if_needed(message.bot, message.chat.id, state)
        return await _refresh_message_report_menu(message.bot, message.chat.id, state)

    gid = str(mg)
    cur_gid = data.get("album_group_id")
    if cur_gid and cur_gid != gid:
        cancel_album_task(uid)
        await _flush_album_to_entries(
            message.bot,
            message.chat.id,
            state,
            show_counter=True,
            is_message_scenario=True,
        )

    data = await state.get_data()
    buf = list(data.get("album_buffer") or [])
    buf.append(_make_photo_entry(message))
    await state.update_data(album_buffer=buf, album_group_id=gid)
    schedule_album_task(
        uid,
        lambda: _debounce_photo(uid, message.bot, message.chat.id, state, True, True),
    )


@router.message(GuardStates.message_report, F.video)
async def message_scenario_video(message: Message, state: FSMContext) -> None:
    await _message_single_media(message, state, "video", lambda m: m.video is not None)


@router.message(GuardStates.message_report, F.voice)
async def message_scenario_voice(message: Message, state: FSMContext) -> None:
    await _message_single_media(message, state, "voice", lambda m: m.voice is not None)


@router.message(GuardStates.message_report, F.text & ~F.text.startswith("/"))
async def message_scenario_text(message: Message, state: FSMContext) -> None:
    if not message.text:
        return
    await _message_single_media(message, state, "text", lambda m: bool(m.text))


async def _message_single_media(message: Message, state: FSMContext, kind: str, _check) -> None:
    data = await state.get_data()
    locked = data.get("msg_locked_kind")
    if locked and locked != kind:
        await send_explaining(
            message.bot, message.chat.id, T.WRONG_CONTENT_MESSAGE_MIX, state
        )
        return await _refresh_message_report_menu(message.bot, message.chat.id, state)
    if kind == "text":
        if data.get("message_text_body") is not None:
            await send_explaining(
                message.bot, message.chat.id, T.SECOND_MEDIA_NOT_ALLOWED, state
            )
            return await _refresh_message_report_menu(message.bot, message.chat.id, state)
        await state.update_data(
            msg_locked_kind=kind,
            message_text_body=message.text,
            single_msg_id=None,
        )
    else:
        if data.get("single_msg_id") is not None:
            await send_explaining(
                message.bot, message.chat.id, T.SECOND_MEDIA_NOT_ALLOWED, state
            )
            return await _refresh_message_report_menu(message.bot, message.chat.id, state)
        await state.update_data(msg_locked_kind=kind, single_msg_id=message.message_id)
    await _refresh_message_report_menu(message.bot, message.chat.id, state)


@router.message(GuardStates.message_report)
async def message_scenario_wrong(message: Message, state: FSMContext) -> None:
    await send_explaining(
        message.bot,
        message.chat.id,
        T.WRONG_CONTENT.format(reason="допустимы текст, фото, одно видео или одно голосовое"),
        state,
    )
    await _refresh_message_report_menu(message.bot, message.chat.id, state)


@router.callback_query(F.data == "svc_cancel", StateFilter(GuardStates))
async def svc_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    cancel_album_task(callback.from_user.id)
    cancel_fallback_menu_task(callback.from_user.id)
    await clear_scenario_hint_message(
        callback.bot, callback.message.chat.id, state
    )
    await purge_disposable_messages(callback.bot, callback.message.chat.id, state)
    await clear_service_menu_message(callback.bot, callback.message.chat.id, state)
    await state.clear()
    await callback.message.answer(T.ACTION_CANCELLED)
    await callback.message.answer(T.BOT_DESCRIPTION, reply_markup=main_menu_keyboard())


async def _send_media_group_with_flood_retry(
    bot,
    chat_id: int,
    medias: list,
    reply_markup: Optional[Any] = None,
) -> List[Message]:
    """SendMediaGroup + reply_markup на первое сообщение альбома (Bot API); flood — retry_after."""
    while True:
        try:
            call = SendMediaGroup(chat_id=chat_id, media=medias, reply_markup=reply_markup)
            return await bot(call)
        except TelegramRetryAfter as e:
            await asyncio.sleep(float(e.retry_after))


async def _send_photo_with_flood_retry(
    bot,
    chat_id: int,
    photo: str | BufferedInputFile,
    *,
    caption: Optional[str] = None,
    reply_markup: Optional[Any] = None,
) -> Message:
    while True:
        try:
            return await bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=caption,
                reply_markup=reply_markup,
            )
        except TelegramRetryAfter as e:
            await asyncio.sleep(float(e.retry_after))


async def _send_message_with_flood_retry(
    bot,
    chat_id: int,
    text: str,
    *,
    reply_to_message_id: Optional[int] = None,
    reply_markup: Optional[Any] = None,
) -> Message:
    while True:
        try:
            return await bot.send_message(
                chat_id,
                text,
                reply_to_message_id=reply_to_message_id,
                reply_markup=reply_markup,
            )
        except TelegramRetryAfter as e:
            await asyncio.sleep(float(e.retry_after))


async def _copy_message_with_flood_retry(
    bot,
    chat_id: int,
    from_chat_id: int,
    message_id: int,
    *,
    reply_markup: Optional[Any] = None,
) -> Message:
    while True:
        try:
            return await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=from_chat_id,
                message_id=message_id,
                reply_markup=reply_markup,
            )
        except TelegramRetryAfter as e:
            await asyncio.sleep(float(e.retry_after))


async def _build_stamped_photo(bot, file_id: str, dt: datetime) -> BufferedInputFile:
    tg_file = await bot.get_file(file_id)
    raw = BytesIO()
    await bot.download_file(tg_file.file_path, destination=raw)
    stamped = stamp_datetime_on_photo(raw.getvalue(), dt.strftime("%d.%m.%Y %H:%M:%S"))
    return BufferedInputFile(stamped, filename="report.jpg")


async def _send_photos_in_album_chunks(
    bot,
    chat_id: int,
    entries: List[dict],
    caption_on_first: str,
    reply_markup_first: Optional[Any] = None,
) -> int:
    """Не более TELEGRAM_MEDIA_GROUP_MAX фото в альбоме; 1 фото — send_photo (альбом от 2 элементов)."""
    first_message_id: Optional[int] = None
    for start in range(0, len(entries), TELEGRAM_MEDIA_GROUP_MAX):
        if start > 0:
            await asyncio.sleep(SECONDS_BETWEEN_MEDIA_GROUPS)
        chunk = entries[start : start + TELEGRAM_MEDIA_GROUP_MAX]
        rm = reply_markup_first if start == 0 else None
        if len(chunk) == 1:
            cap = caption_on_first if start == 0 else None
            photo = await _build_stamped_photo(bot, chunk[0]["file_id"], chunk[0]["dt"])
            msg = await _send_photo_with_flood_retry(
                bot,
                chat_id,
                photo,
                caption=cap,
                reply_markup=rm,
            )
            msgs = [msg]
        else:
            medias = []
            for e in chunk:
                photo = await _build_stamped_photo(bot, e["file_id"], e["dt"])
                medias.append(InputMediaPhoto(media=photo))
            if start == 0:
                medias[0].caption = caption_on_first
            msgs = await _send_media_group_with_flood_retry(bot, chat_id, medias, reply_markup=rm)
        if first_message_id is None:
            first_message_id = msgs[0].message_id
    assert first_message_id is not None
    return first_message_id


async def _send_to_group_and_log(
    bot,
    db: Database,
    user: Any,
    obj,
    *,
    event_type: str,
    link: str,
    comment: str,
) -> None:
    """Лог в Google Sheets в фоне — не блокируем «Отчёт отправлен» ожиданием сети."""
    label = f"id:{user.id}" + (f" @{user.username}" if getattr(user, "username", None) else "")

    async def _bg() -> None:
        try:
            await sheets.log_event(obj.sheet_title, event_type, label, link, comment)
        except Exception as e:
            _log.warning("Фоновый лог в Sheets не выполнен: %s", e)

    asyncio.create_task(_bg())


@router.callback_query(F.data == "svc_send", GuardStates.photo_report)
async def svc_send_photo(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    uid = callback.from_user.id
    cancel_album_task(uid)
    data = await state.get_data()
    entries: List[dict] = list(data.get("photo_entries") or [])
    if data.get("album_buffer"):
        await _flush_album_to_entries(callback.bot, callback.message.chat.id, state, show_counter=True)
        data = await state.get_data()
        entries = list(data.get("photo_entries") or [])
    if not entries:
        await send_explaining(
            callback.bot,
            callback.message.chat.id,
            "Нет фото для отправки.",
            state,
        )
        return await callback.answer()

    kind = ReportKind(data["report_kind"])
    obj, err = await guard_access(db, uid)
    if err:
        await send_explaining(
            callback.bot,
            callback.message.chat.id,
            T.OBJECT_PAUSED if err == "paused" else T.NOT_BOUND,
            state,
        )
        return await callback.answer()

    await callback.answer()
    sending_msg = await callback.message.answer(T.REPORT_SENDING)
    await register_disposable(state, sending_msg.message_id)

    try:
        caption = format_group_caption(kind, len(entries), [e["dt"] for e in entries])
        first_id = await _send_photos_in_album_chunks(
            callback.bot,
            obj.group_chat_id,
            entries,
            caption,
        )
        link = telegram_group_message_link(obj.group_chat_id, first_id)
        await _send_to_group_and_log(
            callback.bot,
            db,
            callback.from_user,
            obj,
            event_type=report_title(kind),
            link=link,
            comment=f"фото: {len(entries)}",
        )

        await clear_service_menu_message(callback.bot, callback.message.chat.id, state)
        await clear_scenario_hint_message(
            callback.bot, callback.message.chat.id, state
        )
        await purge_disposable_messages(callback.bot, callback.message.chat.id, state)
        await state.clear()
        await callback.message.answer(T.REPORT_SENT)
        await callback.message.answer(T.BOT_DESCRIPTION, reply_markup=main_menu_keyboard())
    except TelegramBadRequest as e:
        await _recover_from_group_send_error(callback, state, e)


@router.callback_query(F.data == "svc_send", GuardStates.video_note_report)
async def svc_send_video(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    ids: List[int] = list(data.get("video_msg_ids") or [])
    if not ids:
        await send_explaining(
            callback.bot,
            callback.message.chat.id,
            "Нет видеокружка для отправки.",
            state,
        )
        return await callback.answer()
    kind = ReportKind(data["report_kind"])
    obj, err = await guard_access(db, callback.from_user.id)
    if err:
        await send_explaining(
            callback.bot,
            callback.message.chat.id,
            T.OBJECT_PAUSED if err == "paused" else T.NOT_BOUND,
            state,
        )
        return await callback.answer()

    await callback.answer()
    sending_msg = await callback.message.answer(T.REPORT_SENDING)
    await register_disposable(state, sending_msg.message_id)

    try:
        times = [datetime.now()]
        cap = format_text_report_caption(kind, times)
        msg = await _copy_message_with_flood_retry(
            callback.bot,
            obj.group_chat_id,
            callback.from_user.id,
            ids[0],
        )
        await _pause_between_group_sends()
        # У video_note нет caption в API — текст отчёта отдельным сообщением (ответ на кружок).
        await _send_message_with_flood_retry(
            callback.bot,
            obj.group_chat_id,
            cap,
            reply_to_message_id=msg.message_id,
        )
        link = telegram_group_message_link(obj.group_chat_id, msg.message_id)
        await _send_to_group_and_log(
            callback.bot,
            db,
            callback.from_user,
            obj,
            event_type=report_title(kind),
            link=link,
            comment="видеокружок",
        )
        await clear_service_menu_message(callback.bot, callback.message.chat.id, state)
        await clear_scenario_hint_message(
            callback.bot, callback.message.chat.id, state
        )
        await purge_disposable_messages(callback.bot, callback.message.chat.id, state)
        await state.clear()
        await callback.message.answer(T.REPORT_SENT)
        await callback.message.answer(T.BOT_DESCRIPTION, reply_markup=main_menu_keyboard())
    except TelegramBadRequest as e:
        await _recover_from_group_send_error(callback, state, e)


@router.callback_query(F.data == "svc_send", GuardStates.message_report)
async def svc_send_message(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    uid = callback.from_user.id
    cancel_album_task(uid)
    data = await state.get_data()
    if data.get("album_buffer"):
        await _flush_album_to_entries(
            callback.bot,
            callback.message.chat.id,
            state,
            show_counter=False,
            is_message_scenario=True,
        )
        data = await state.get_data()

    locked = data.get("msg_locked_kind")
    obj, err = await guard_access(db, uid)
    if err:
        await send_explaining(
            callback.bot,
            callback.message.chat.id,
            T.OBJECT_PAUSED if err == "paused" else T.NOT_BOUND,
            state,
        )
        return await callback.answer()

    await callback.answer()
    chat_id = callback.message.chat.id
    bot = callback.bot
    sending_msg = await callback.message.answer(T.REPORT_SENDING)

    try:
        if locked == "photo":
            entries = list(data.get("photo_entries") or [])
            if not entries:
                await send_explaining(
                    bot, chat_id, "Нет фото для отправки.", state
                )
                await delete_bot_message_safe(bot, chat_id, sending_msg.message_id)
                return
            ref_id = await db.create_group_post_ref_pending(obj.group_chat_id)
            kb = accounted_markup(f"a:{ref_id}")
            caption = format_text_report_caption(ReportKind.MESSAGE, [e["dt"] for e in entries])
            mid = await _send_photos_in_album_chunks(
                bot,
                obj.group_chat_id,
                entries,
                caption,
                reply_markup_first=kb,
            )
        elif locked == "text":
            body = data.get("message_text_body")
            if not body:
                await send_explaining(
                    bot, chat_id, "Нет текста для отправки.", state
                )
                await delete_bot_message_safe(bot, chat_id, sending_msg.message_id)
                return
            ref_id = await db.create_group_post_ref_pending(obj.group_chat_id)
            kb = accounted_markup(f"a:{ref_id}")
            header = format_text_report_caption(ReportKind.MESSAGE, [datetime.now()])
            msg = await _send_message_with_flood_retry(
                bot,
                obj.group_chat_id,
                f"{header}\n\n{body}",
                reply_markup=kb,
            )
            mid = msg.message_id
        elif locked in ("video", "voice"):
            smid = data.get("single_msg_id")
            if not smid:
                await send_explaining(
                    bot, chat_id, "Нет содержимого для отправки.", state
                )
                await delete_bot_message_safe(bot, chat_id, sending_msg.message_id)
                return
            ref_id = await db.create_group_post_ref_pending(obj.group_chat_id)
            kb = accounted_markup(f"a:{ref_id}")
            msg = await _copy_message_with_flood_retry(
                bot,
                obj.group_chat_id,
                uid,
                smid,
                reply_markup=kb,
            )
            mid = msg.message_id
            await _pause_between_group_sends()
            extra = format_text_report_caption(ReportKind.MESSAGE, [datetime.now()])
            try:
                await callback.bot.edit_message_caption(
                    chat_id=obj.group_chat_id, message_id=mid, caption=extra
                )
            except Exception:
                await _send_message_with_flood_retry(callback.bot, obj.group_chat_id, extra)
        else:
            await send_explaining(
                bot, chat_id, "Сначала отправьте содержимое отчёта.", state
            )
            await delete_bot_message_safe(bot, chat_id, sending_msg.message_id)
            return

        await db.finalize_group_post_ref(ref_id, mid)
        link = telegram_group_message_link(obj.group_chat_id, mid)
        await _pause_between_group_sends()
        await _pin_report_message(callback.bot, obj.group_chat_id, mid)

        await _send_to_group_and_log(
            callback.bot,
            db,
            callback.from_user,
            obj,
            event_type=report_title(ReportKind.MESSAGE),
            link=link,
            comment=f"тип: {locked}",
        )

        await register_disposable(state, sending_msg.message_id)
        await clear_service_menu_message(callback.bot, chat_id, state)
        await clear_scenario_hint_message(bot, chat_id, state)
        await purge_disposable_messages(bot, chat_id, state)
        await state.clear()
        await callback.message.answer(T.REPORT_SENT)
        await callback.message.answer(T.BOT_DESCRIPTION, reply_markup=main_menu_keyboard())
    except TelegramBadRequest as e:
        await register_disposable(state, sending_msg.message_id)
        await _recover_from_group_send_error(callback, state, e)


@router.message(StateFilter(None), F.chat.type == ChatType.PRIVATE, F.photo)
async def main_menu_photo_without_scenario(
    message: Message, state: FSMContext, db: Database
) -> None:
    """Фото вне сценария: напомнить выбрать пункт меню (как в ТЗ)."""
    if not message.from_user:
        return
    uid = message.from_user.id
    cancel_album_task(uid)
    cancel_fallback_menu_task(uid)

    if message.media_group_id is not None:
        bot = message.bot
        chat_id = message.chat.id

        async def _after_album() -> None:
            try:
                await asyncio.sleep(ALBUM_DEBOUNCE_SECONDS)
            except asyncio.CancelledError:
                return
            _, err = await guard_access(db, uid)
            if err == "not_bound":
                await bot.send_message(chat_id, T.NOT_BOUND)
            elif err == "paused":
                await bot.send_message(chat_id, T.OBJECT_PAUSED)
            else:
                await bot.send_message(
                    chat_id,
                    T.REPORT_REQUIRES_MENU_BUTTON,
                    reply_markup=main_menu_keyboard(),
                )

        schedule_fallback_menu_task(uid, _after_album)
        return

    _, err = await guard_access(db, uid)
    if err == "not_bound":
        return await message.answer(T.NOT_BOUND)
    if err == "paused":
        return await message.answer(T.OBJECT_PAUSED)
    await message.answer(T.REPORT_REQUIRES_MENU_BUTTON, reply_markup=main_menu_keyboard())


@router.message(StateFilter(None), F.chat.type == ChatType.PRIVATE)
async def fallback_private(message: Message, state: FSMContext, db: Database) -> None:
    """Любое сообщение в ЛС без состояния и без более специфичного обработчика — показать главное меню."""
    if not message.from_user:
        return
    uid = message.from_user.id
    cancel_album_task(uid)
    cancel_fallback_menu_task(uid)

    _, err = await guard_access(db, uid)
    if err == "not_bound":
        return await message.answer(T.NOT_BOUND)
    if err == "paused":
        return await message.answer(T.OBJECT_PAUSED)
    await message.answer(T.BOT_DESCRIPTION, reply_markup=main_menu_keyboard())

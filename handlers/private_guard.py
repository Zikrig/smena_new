from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, List, Optional

from maxapi import F, Router
from maxapi.context.base import BaseContext
from maxapi.enums.message_link_type import MessageLinkType
from maxapi.enums.parse_mode import ParseMode
from maxapi.exceptions.max import MaxApiError
from maxapi.filters.command import CommandStart
from maxapi.types.input_media import InputMediaBuffer
from maxapi.types.message import NewMessageLink
from maxapi.types.updates.message_callback import MessageCallback
from maxapi.types.updates.message_created import MessageCreated
from maxapi.enums.chat_type import ChatType

from constants import (
    ALBUM_DEBOUNCE_SECONDS,
    HARD_PHOTO_LIMIT,
    MEDIA_GROUP_CHUNK_MAX,
    SECONDS_BETWEEN_MEDIA_GROUPS,
    SOFT_PHOTO_LIMIT,
)
from core.keyboards import accounted_markup, hide_inline_keyboard, main_menu_keyboard
from core.max_filters import (
    BodyTextNotCommand,
    HasAudioAttachment,
    HasImageAttachment,
    HasPhotoCaption,
    HasVideoAttachment,
    IsDialog,
)
from core.max_helpers import (
    album_group_token,
    build_stamped_photo_buffer,
    make_photo_entries,
    message_mid,
    message_text,
    peer_from_message,
    send_peer,
)
from core.report_types import ReportKind, report_title
from core.states import GuardStates
from core.utils import is_bind_token_hex, max_group_message_ref
from db.database import Database, ObjectRow
import texts_ru as T
from services.album_tasks import cancel_album_task, schedule_album_task
from services.fallback_menu_tasks import cancel_fallback_menu_task, schedule_fallback_menu_task
from services.report_build import format_group_caption, format_text_report_caption
from services.service_menu import (
    clear_service_menu_message,
    clear_submenu_instructions,
    refresh_service_menu,
    send_explaining,
    send_or_replace_main_menu,
    send_submenu_instruction,
)
from services import sheets

router = Router(router_id="private_guard")
_log = logging.getLogger(__name__)

_GUARD_STATES = [
    GuardStates.photo_report,
    GuardStates.video_report,
    GuardStates.message_report,
]

# Тревога доступна только из главного меню.
_ALARM_CALLBACK_STATES = [None]


async def _pin_report_message(bot, chat_id: int, message_mid_s: str) -> None:
    try:
        await bot.pin_message(chat_id, message_mid_s, notify=False)
    except Exception as e:
        _log.warning("Не удалось закрепить сообщение %s в чате %s: %s", message_mid_s, chat_id, e)


async def _recover_from_group_send_error(
    event: MessageCallback, context: BaseContext, exc: Exception
) -> None:
    _log.warning("Отправка в группу объекта не удалась: %s", exc)
    msg = event.message
    if msg is None:
        return
    c, u = peer_from_message(msg)
    await send_explaining(msg.bot, c, u, T.GROUP_CHAT_UNAVAILABLE)
    await clear_service_menu_message(msg.bot, c, u, context)
    await context.clear()
    await send_or_replace_main_menu(
        msg.bot,
        c,
        u,
        context,
        text=T.BOT_DESCRIPTION,
        attachments=[main_menu_keyboard()],
    )


async def guard_access(
    db: Database, user_id: int
) -> tuple[Optional[ObjectRow], Optional[str]]:
    oid = await db.get_guard_object_id(user_id)
    if not oid:
        return None, "not_bound"
    obj = await db.get_object_by_id(oid)
    if not obj:
        return None, "not_bound"
    if obj.is_paused:
        return None, "paused"
    return obj, None


def _peer_data(message) -> dict[str, Any]:
    r = message.recipient
    return {"peer_chat_id": r.chat_id, "peer_user_id": r.user_id}


def _base_photo_data(kind: ReportKind, message) -> dict:
    return {
        "report_kind": kind.value,
        "photo_entries": [],
        "album_buffer": [],
        "album_group_id": None,
        "soft_warned": False,
        **_peer_data(message),
    }


async def _start_bind(message, context: BaseContext, token: str, db: Database) -> None:
    token = token.strip().lower()
    object_id = await db.consume_bind_token(token)
    su = message.sender.user_id if message.sender else None
    if not object_id or su is None:
        return await message.answer(text=T.BIND_INVALID)
    if await db.get_guard_object_id(su):
        return await message.answer(text=T.ALREADY_BOUND)
    await db.bind_guard(su, object_id)
    obj = await db.get_object_by_id(object_id)
    await message.answer(text=T.BIND_OK.format(name=obj.name if obj else "?"))
    r = message.recipient
    await send_or_replace_main_menu(
        message.bot,
        r.chat_id,
        r.user_id,
        context,
        text=T.BOT_DESCRIPTION,
        attachments=[main_menu_keyboard()],
    )


@router.message_created(CommandStart(), IsDialog())
async def cmd_start(
    event: MessageCreated, context: BaseContext, db: Database, args: list[str]
) -> None:
    message = event.message
    su = message.sender.user_id if message.sender else None
    if su is None:
        return
    await context.clear()
    cancel_album_task(su)
    cancel_fallback_menu_task(su)
    arg = " ".join(args).strip() if args else ""
    token: str | None = None
    if arg.startswith("bind_"):
        rest = arg.replace("bind_", "", 1).strip()
        if rest:
            token = rest
    elif arg and is_bind_token_hex(arg):
        token = arg.strip().lower()
    if token:
        return await _start_bind(message, context, token, db)
    _, err = await guard_access(db, su)
    if err == "not_bound":
        return await message.answer(text=T.NOT_BOUND)
    if err == "paused":
        return await message.answer(text=T.OBJECT_PAUSED)
    r = message.recipient
    await send_or_replace_main_menu(
        message.bot,
        r.chat_id,
        r.user_id,
        context,
        text=T.BOT_DESCRIPTION,
        attachments=[main_menu_keyboard()],
    )


async def _enter_photo_scenario(message, context: BaseContext, kind: ReportKind) -> None:
    await hide_inline_keyboard(message)
    await context.clear()
    su = message.sender.user_id if message.sender else None
    if su:
        cancel_album_task(su)
        cancel_fallback_menu_task(su)
    await context.set_state(GuardStates.photo_report)
    await context.update_data(**_base_photo_data(kind, message))
    title = report_title(kind)
    await send_submenu_instruction(
        message.bot,
        message.recipient.chat_id,
        message.recipient.user_id,
        context,
        text=T.REPORT_STARTED.format(report_title=title),
    )
    hint = None
    if kind == ReportKind.HANDOVER:
        hint = T.PHOTO_SCENARIO_HINT_HANDOVER
    elif kind == ReportKind.PATROL:
        hint = T.PHOTO_SCENARIO_HINT_PATROL
    elif kind == ReportKind.INSPECTION:
        hint = T.PHOTO_SCENARIO_HINT_INSPECTION
    if hint:
        await send_submenu_instruction(
            message.bot,
            message.recipient.chat_id,
            message.recipient.user_id,
            context,
            text=hint,
        )
    r = message.recipient
    await refresh_service_menu(
        message.bot,
        r.chat_id,
        r.user_id,
        context,
        show_photo_counter=True,
        photo_count=0,
    )


async def _enter_video_scenario(message, context: BaseContext, kind: ReportKind) -> None:
    await hide_inline_keyboard(message)
    await context.clear()
    su = message.sender.user_id if message.sender else None
    if su:
        cancel_album_task(su)
        cancel_fallback_menu_task(su)
    await context.set_state(GuardStates.video_report)
    await context.update_data(
        report_kind=kind.value,
        video_msg_ids=[],
        **_peer_data(message),
    )
    title = report_title(kind)
    await send_submenu_instruction(
        message.bot,
        message.recipient.chat_id,
        message.recipient.user_id,
        context,
        text=T.REPORT_STARTED.format(report_title=title),
    )
    hint = None
    if kind == ReportKind.START_SHIFT:
        hint = T.VIDEO_SCENARIO_HINT_START_SHIFT
    elif kind == ReportKind.POST_CHECK:
        hint = T.VIDEO_SCENARIO_HINT_POST_CHECK
    if hint:
        await send_submenu_instruction(
            message.bot,
            message.recipient.chat_id,
            message.recipient.user_id,
            context,
            text=hint,
        )
    r = message.recipient
    await refresh_service_menu(
        message.bot,
        r.chat_id,
        r.user_id,
        context,
        show_photo_counter=False,
        photo_count=0,
    )


async def _enter_message_scenario(message, context: BaseContext) -> None:
    await hide_inline_keyboard(message)
    await context.clear()
    su = message.sender.user_id if message.sender else None
    if su:
        cancel_album_task(su)
        cancel_fallback_menu_task(su)
    await context.set_state(GuardStates.message_report)
    await context.update_data(
        report_kind=ReportKind.MESSAGE.value,
        msg_locked_kind=None,
        photo_entries=[],
        album_buffer=[],
        album_group_id=None,
        single_msg_id=None,
        message_text_body=None,
        **_peer_data(message),
    )
    await send_submenu_instruction(
        message.bot,
        message.recipient.chat_id,
        message.recipient.user_id,
        context,
        text=T.REPORT_STARTED.format(report_title=report_title(ReportKind.MESSAGE)),
    )
    await send_submenu_instruction(
        message.bot,
        message.recipient.chat_id,
        message.recipient.user_id,
        context,
        text=T.MESSAGE_SCENARIO_HINT,
    )
    r = message.recipient
    await refresh_service_menu(
        message.bot,
        r.chat_id,
        r.user_id,
        context,
        show_photo_counter=False,
        photo_count=0,
    )


async def _main_menu_from_callback(
    event: MessageCallback, context: BaseContext, db: Database
) -> bool:
    cb = event.callback
    msg = event.message
    if msg is None or msg.recipient.chat_type != ChatType.DIALOG:
        await event.answer(notification="")
        return False
    await event.answer(notification="")
    _, err = await guard_access(db, cb.user.user_id)
    if err == "not_bound":
        await msg.answer(text=T.NOT_BOUND)
        return False
    if err == "paused":
        await msg.answer(text=T.OBJECT_PAUSED)
        return False
    return True


async def _deliver_emergency_contacts(
    bot,
    chat_id: Optional[int],
    user_id: Optional[int],
    context: BaseContext,
) -> None:
    """Показать номера тревоги: из главного меню — с возвратом в меню; в сценарии отчёта — обновить сервисное меню."""
    await send_peer(
        bot,
        chat_id=chat_id,
        user_id=user_id,
        text=T.format_emergency_call_html(),
        parse_mode=ParseMode.HTML,
    )
    st = await context.get_state()
    st_name = str(st) if st is not None else ""
    data = await context.get_data()
    if st_name == str(GuardStates.photo_report):
        await refresh_service_menu(
            bot,
            chat_id,
            user_id,
            context,
            show_photo_counter=True,
            photo_count=len(data.get("photo_entries") or []),
        )
    elif st_name in (str(GuardStates.video_report), str(GuardStates.message_report)):
        await refresh_service_menu(
            bot,
            chat_id,
            user_id,
            context,
            show_photo_counter=False,
            photo_count=0,
        )
    else:
        await send_or_replace_main_menu(
            bot,
            chat_id,
            user_id,
            context,
            text=T.EMERGENCY_CALL_FOLLOWUP,
            attachments=[main_menu_keyboard()],
        )


@router.message_callback(F.callback.payload == "menu:shift", states=[None])
async def menu_start_shift(event: MessageCallback, context: BaseContext, db: Database) -> None:
    if not await _main_menu_from_callback(event, context, db):
        return
    msg = event.message
    if msg:
        await _enter_video_scenario(msg, context, ReportKind.START_SHIFT)


@router.message_callback(F.callback.payload == "menu:post", states=[None])
async def menu_post_check(event: MessageCallback, context: BaseContext, db: Database) -> None:
    if not await _main_menu_from_callback(event, context, db):
        return
    msg = event.message
    if msg:
        await _enter_video_scenario(msg, context, ReportKind.POST_CHECK)


@router.message_callback(F.callback.payload == "menu:handover", states=[None])
async def menu_handover(event: MessageCallback, context: BaseContext, db: Database) -> None:
    if not await _main_menu_from_callback(event, context, db):
        return
    msg = event.message
    if msg:
        await _enter_photo_scenario(msg, context, ReportKind.HANDOVER)


@router.message_callback(F.callback.payload == "menu:patrol", states=[None])
async def menu_patrol(event: MessageCallback, context: BaseContext, db: Database) -> None:
    if not await _main_menu_from_callback(event, context, db):
        return
    msg = event.message
    if msg:
        await _enter_photo_scenario(msg, context, ReportKind.PATROL)


@router.message_callback(F.callback.payload == "menu:inspection", states=[None])
async def menu_inspection(event: MessageCallback, context: BaseContext, db: Database) -> None:
    if not await _main_menu_from_callback(event, context, db):
        return
    msg = event.message
    if msg:
        await _enter_photo_scenario(msg, context, ReportKind.INSPECTION)


@router.message_callback(F.callback.payload == "menu:message", states=[None])
async def menu_message(event: MessageCallback, context: BaseContext, db: Database) -> None:
    if not await _main_menu_from_callback(event, context, db):
        return
    msg = event.message
    if msg:
        await _enter_message_scenario(msg, context)


@router.message_callback(
    F.callback.payload == "menu:alarm",
    states=_ALARM_CALLBACK_STATES,
)
async def alarm_show_contacts(event: MessageCallback, context: BaseContext, db: Database) -> None:
    if not await _main_menu_from_callback(event, context, db):
        return
    msg = event.message
    if not msg:
        return
    await hide_inline_keyboard(msg)
    r = msg.recipient
    await _deliver_emergency_contacts(msg.bot, r.chat_id, r.user_id, context)


async def _flush_album_to_entries(
    bot,
    chat_id: Optional[int],
    user_id: Optional[int],
    context: BaseContext,
    *,
    show_counter: bool,
    is_message_scenario: bool = False,
) -> None:
    data = await context.get_data()
    buf: List[dict] = list(data.get("album_buffer") or [])
    if not buf:
        await context.update_data(album_buffer=[], album_group_id=None)
        return
    entries: List[dict] = list(data.get("photo_entries") or [])
    if len(entries) + len(buf) > HARD_PHOTO_LIMIT:
        can_take = max(0, HARD_PHOTO_LIMIT - len(entries))
        await context.update_data(album_buffer=[], album_group_id=None)
        await send_explaining(
            bot,
            chat_id,
            user_id,
            T.PHOTO_LIMIT_CAN_ACCEPT_ONLY.format(n=can_take, hard=HARD_PHOTO_LIMIT),
        )
        await refresh_service_menu(
            bot,
            chat_id,
            user_id,
            context,
            show_photo_counter=show_counter,
            photo_count=len(entries),
        )
        return
    entries.extend(buf)
    await context.update_data(photo_entries=entries, album_buffer=[], album_group_id=None)
    if (
        not is_message_scenario
        and len(entries) > SOFT_PHOTO_LIMIT
        and not data.get("soft_warned")
    ):
        await context.update_data(soft_warned=True)
        await send_explaining(
            bot,
            chat_id,
            user_id,
            T.SOFT_LIMIT_WARNING.format(
                n=len(entries),
                soft=SOFT_PHOTO_LIMIT,
                hard=HARD_PHOTO_LIMIT,
            ),
        )
    await refresh_service_menu(
        bot,
        chat_id,
        user_id,
        context,
        show_photo_counter=show_counter,
        photo_count=len(entries),
    )


async def _debounce_photo(
    user_id: int,
    bot,
    chat_id: Optional[int],
    user_id_peer: Optional[int],
    context: BaseContext,
    show_counter: bool,
    is_message_scenario: bool,
) -> None:
    await asyncio.sleep(ALBUM_DEBOUNCE_SECONDS)
    await _flush_album_to_entries(
        bot,
        chat_id,
        user_id_peer,
        context,
        show_counter=show_counter,
        is_message_scenario=is_message_scenario,
    )


@router.message_created(GuardStates.photo_report, HasImageAttachment())
async def photo_report_collect(event: MessageCreated, context: BaseContext) -> None:
    message = event.message
    su = message.sender.user_id if message.sender else None
    if su is None:
        return
    batch_entries = make_photo_entries(message)
    if not batch_entries:
        return
    data = await context.get_data()
    entries: List[dict] = list(data.get("photo_entries") or [])
    mg = album_group_token(message)
    r = message.recipient
    bot = message.bot

    if mg is None and len(entries) >= HARD_PHOTO_LIMIT:
        await send_explaining(
            bot,
            r.chat_id,
            r.user_id,
            T.PHOTO_LIMIT_CAN_ACCEPT_ONLY.format(n=0, hard=HARD_PHOTO_LIMIT),
        )
        await refresh_service_menu(
            bot,
            r.chat_id,
            r.user_id,
            context,
            show_photo_counter=True,
            photo_count=len(entries),
        )
        return

    if mg is None:
        cancel_album_task(su)
        await _flush_album_to_entries(
            bot,
            r.chat_id,
            r.user_id,
            context,
            show_counter=True,
        )
        data = await context.get_data()
        entries = list(data.get("photo_entries") or [])
        if len(entries) >= HARD_PHOTO_LIMIT:
            await send_explaining(
                bot,
                r.chat_id,
                r.user_id,
                T.PHOTO_LIMIT_CAN_ACCEPT_ONLY.format(n=0, hard=HARD_PHOTO_LIMIT),
            )
            await refresh_service_menu(
                bot,
                r.chat_id,
                r.user_id,
                context,
                show_photo_counter=True,
                photo_count=len(entries),
            )
            return
        can_take = max(0, HARD_PHOTO_LIMIT - len(entries))
        if len(batch_entries) > can_take:
            await send_explaining(
                bot,
                r.chat_id,
                r.user_id,
                T.PHOTO_LIMIT_CAN_ACCEPT_ONLY.format(n=can_take, hard=HARD_PHOTO_LIMIT),
            )
            await refresh_service_menu(
                bot,
                r.chat_id,
                r.user_id,
                context,
                show_photo_counter=True,
                photo_count=len(entries),
            )
            return
        entries.extend(batch_entries)
        await context.update_data(photo_entries=entries)
        if len(entries) > SOFT_PHOTO_LIMIT and not data.get("soft_warned"):
            await context.update_data(soft_warned=True)
            await send_explaining(
                bot,
                r.chat_id,
                r.user_id,
                T.SOFT_LIMIT_WARNING.format(
                    n=len(entries),
                    soft=SOFT_PHOTO_LIMIT,
                    hard=HARD_PHOTO_LIMIT,
                ),
            )
        await refresh_service_menu(
            bot,
            r.chat_id,
            r.user_id,
            context,
            show_photo_counter=True,
            photo_count=len(entries),
        )
        return

    gid = str(mg)
    cur_gid = data.get("album_group_id")
    if cur_gid and cur_gid != gid:
        cancel_album_task(su)
        await _flush_album_to_entries(bot, r.chat_id, r.user_id, context, show_counter=True)

    data = await context.get_data()
    buf = list(data.get("album_buffer") or [])
    buf.extend(batch_entries)
    await context.update_data(album_buffer=buf, album_group_id=gid)
    schedule_album_task(
        su,
        lambda: _debounce_photo(su, bot, r.chat_id, r.user_id, context, True, False),
    )


@router.message_created(GuardStates.photo_report)
async def photo_report_wrong(event: MessageCreated, context: BaseContext) -> None:
    message = event.message
    r = message.recipient
    bot = message.bot
    await send_explaining(bot, r.chat_id, r.user_id, T.WRONG_CONTENT.format(reason="нужны только фото"))
    data = await context.get_data()
    await refresh_service_menu(
        bot,
        r.chat_id,
        r.user_id,
        context,
        show_photo_counter=True,
        photo_count=len(data.get("photo_entries") or []),
    )


@router.message_created(GuardStates.video_report, HasVideoAttachment())
async def video_collect(event: MessageCreated, context: BaseContext) -> None:
    message = event.message
    r = message.recipient
    bot = message.bot
    mid = message_mid(message)
    if not mid:
        return
    data = await context.get_data()
    ids: List[str] = list(data.get("video_msg_ids") or [])
    if ids:
        await send_explaining(bot, r.chat_id, r.user_id, T.SECOND_MEDIA_NOT_ALLOWED)
    else:
        ids.append(mid)
        await context.update_data(video_msg_ids=ids)
    await refresh_service_menu(
        bot,
        r.chat_id,
        r.user_id,
        context,
        show_photo_counter=False,
        photo_count=0,
    )


@router.message_created(GuardStates.video_report)
async def video_wrong(event: MessageCreated, context: BaseContext) -> None:
    message = event.message
    r = message.recipient
    bot = message.bot
    await send_explaining(
        bot,
        r.chat_id,
        r.user_id,
        T.WRONG_CONTENT.format(reason="нужно одно видео"),
    )
    await refresh_service_menu(
        bot,
        r.chat_id,
        r.user_id,
        context,
        show_photo_counter=False,
        photo_count=0,
    )


@router.message_created(GuardStates.message_report, HasImageAttachment())
async def message_scenario_photo(event: MessageCreated, context: BaseContext) -> None:
    message = event.message
    batch_entries = make_photo_entries(message)
    if not batch_entries:
        return
    if await HasPhotoCaption()(event):
        r = message.recipient
        await send_explaining(message.bot, r.chat_id, r.user_id, T.PHOTO_CAPTION_FORBIDDEN)
        return await refresh_service_menu(
            message.bot,
            r.chat_id,
            r.user_id,
            context,
            show_photo_counter=False,
            photo_count=0,
        )
    data = await context.get_data()
    locked = data.get("msg_locked_kind")
    if locked and locked != "photo":
        r = message.recipient
        await send_explaining(message.bot, r.chat_id, r.user_id, T.WRONG_CONTENT_MESSAGE_MIX)
        return await refresh_service_menu(
            message.bot,
            r.chat_id,
            r.user_id,
            context,
            show_photo_counter=False,
            photo_count=0,
        )
    await context.update_data(msg_locked_kind="photo")
    su = message.sender.user_id if message.sender else None
    if su is None:
        return
    mg = album_group_token(message)
    entries: List[dict] = list(data.get("photo_entries") or [])
    r = message.recipient
    bot = message.bot

    if mg is None:
        cancel_album_task(su)
        await _flush_album_to_entries(
            bot,
            r.chat_id,
            r.user_id,
            context,
            show_counter=False,
            is_message_scenario=True,
        )
        data = await context.get_data()
        entries = list(data.get("photo_entries") or [])
        if len(entries) >= HARD_PHOTO_LIMIT:
            await send_explaining(
                bot,
                r.chat_id,
                r.user_id,
                T.PHOTO_LIMIT_CAN_ACCEPT_ONLY.format(n=0, hard=HARD_PHOTO_LIMIT),
            )
            return await refresh_service_menu(
                bot,
                r.chat_id,
                r.user_id,
                context,
                show_photo_counter=False,
                photo_count=0,
            )
        can_take = max(0, HARD_PHOTO_LIMIT - len(entries))
        if len(batch_entries) > can_take:
            await send_explaining(
                bot,
                r.chat_id,
                r.user_id,
                T.PHOTO_LIMIT_CAN_ACCEPT_ONLY.format(n=can_take, hard=HARD_PHOTO_LIMIT),
            )
            return await refresh_service_menu(
                bot,
                r.chat_id,
                r.user_id,
                context,
                show_photo_counter=False,
                photo_count=0,
            )
        entries.extend(batch_entries)
        await context.update_data(photo_entries=entries)
        return await refresh_service_menu(
            bot,
            r.chat_id,
            r.user_id,
            context,
            show_photo_counter=False,
            photo_count=0,
        )

    gid = str(mg)
    cur_gid = data.get("album_group_id")
    if cur_gid and cur_gid != gid:
        cancel_album_task(su)
        await _flush_album_to_entries(
            bot,
            r.chat_id,
            r.user_id,
            context,
            show_counter=False,
            is_message_scenario=True,
        )

    data = await context.get_data()
    buf = list(data.get("album_buffer") or [])
    buf.extend(batch_entries)
    await context.update_data(album_buffer=buf, album_group_id=gid)
    schedule_album_task(
        su,
        lambda: _debounce_photo(su, bot, r.chat_id, r.user_id, context, False, True),
    )


@router.message_created(GuardStates.message_report, HasVideoAttachment())
async def message_scenario_video(event: MessageCreated, context: BaseContext) -> None:
    await _message_single_media(event, context, "video")


@router.message_created(GuardStates.message_report, HasAudioAttachment())
async def message_scenario_voice(event: MessageCreated, context: BaseContext) -> None:
    await _message_single_media(event, context, "voice")


@router.message_created(GuardStates.message_report, BodyTextNotCommand())
async def message_scenario_text(event: MessageCreated, context: BaseContext) -> None:
    await _message_single_media(event, context, "text")


async def _message_single_media(event: MessageCreated, context: BaseContext, kind: str) -> None:
    message = event.message
    r = message.recipient
    bot = message.bot
    data = await context.get_data()
    locked = data.get("msg_locked_kind")
    if locked and locked != kind:
        await send_explaining(bot, r.chat_id, r.user_id, T.WRONG_CONTENT_MESSAGE_MIX)
        return await refresh_service_menu(
            bot,
            r.chat_id,
            r.user_id,
            context,
            show_photo_counter=False,
            photo_count=0,
        )
    mid = message_mid(message)
    if kind == "text":
        if data.get("message_text_body") is not None:
            await send_explaining(bot, r.chat_id, r.user_id, T.SECOND_MEDIA_NOT_ALLOWED)
            return await refresh_service_menu(
                bot,
                r.chat_id,
                r.user_id,
                context,
                show_photo_counter=False,
                photo_count=0,
            )
        await context.update_data(
            msg_locked_kind=kind,
            message_text_body=message_text(message),
            single_msg_id=None,
        )
    else:
        if data.get("single_msg_id") is not None:
            await send_explaining(bot, r.chat_id, r.user_id, T.SECOND_MEDIA_NOT_ALLOWED)
            return await refresh_service_menu(
                bot,
                r.chat_id,
                r.user_id,
                context,
                show_photo_counter=False,
                photo_count=0,
            )
        if not mid:
            return
        await context.update_data(msg_locked_kind=kind, single_msg_id=mid)
    await refresh_service_menu(
        bot,
        r.chat_id,
        r.user_id,
        context,
        show_photo_counter=False,
        photo_count=0,
    )


@router.message_created(GuardStates.message_report)
async def message_scenario_wrong(event: MessageCreated, context: BaseContext) -> None:
    message = event.message
    r = message.recipient
    bot = message.bot
    await send_explaining(
        bot,
        r.chat_id,
        r.user_id,
        T.WRONG_CONTENT.format(reason="допустимы текст, фото, одно видео или одно голосовое"),
    )
    await refresh_service_menu(
        bot,
        r.chat_id,
        r.user_id,
        context,
        show_photo_counter=False,
        photo_count=0,
    )


@router.message_callback(F.callback.payload == "svc_cancel", states=_GUARD_STATES)
async def svc_cancel(event: MessageCallback, context: BaseContext) -> None:
    cb = event.callback
    await event.answer(notification="")
    cancel_album_task(cb.user.user_id)
    cancel_fallback_menu_task(cb.user.user_id)
    msg = event.message
    if msg:
        r = msg.recipient
        await clear_service_menu_message(msg.bot, r.chat_id, r.user_id, context)
        await clear_submenu_instructions(msg.bot, context)
        await msg.answer(text=T.ACTION_CANCELLED)
        await send_or_replace_main_menu(
            msg.bot,
            r.chat_id,
            r.user_id,
            context,
            text=T.BOT_DESCRIPTION,
            attachments=[main_menu_keyboard()],
        )
    await context.clear()


async def _send_photos_in_album_chunks(
    bot,
    chat_id: int,
    entries: List[dict],
    caption_on_first: str,
    reply_markup_first: Optional[Any] = None,
) -> str:
    first_mid: Optional[str] = None
    for start in range(0, len(entries), MEDIA_GROUP_CHUNK_MAX):
        if start > 0:
            await asyncio.sleep(SECONDS_BETWEEN_MEDIA_GROUPS)
        chunk = entries[start : start + MEDIA_GROUP_CHUNK_MAX]
        rm = reply_markup_first if start == 0 else None
        atts: list = []
        for e in chunk:
            buf = await build_stamped_photo_buffer(bot, e, e["dt"])
            atts.append(InputMediaBuffer(buf, filename="report.jpg"))
        if rm:
            atts.append(rm)
        cap = caption_on_first if start == 0 else None
        sent = await bot.send_message(
            chat_id=chat_id,
            text=cap,
            attachments=atts if atts else None,
        )
        if sent and sent.message and sent.message.body:
            if first_mid is None:
                first_mid = sent.message.body.mid
    assert first_mid is not None
    return first_mid


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
    label = f"id:{user.user_id}" + (f" @{user.username}" if getattr(user, "username", None) else "")
    await sheets.log_event(obj.sheet_title, event_type, label, link, comment)


@router.message_callback(F.callback.payload == "svc_send", states=[GuardStates.photo_report])
async def svc_send_photo(event: MessageCallback, context: BaseContext, db: Database) -> None:
    cb = event.callback
    msg = event.message
    if msg is None:
        return await event.answer(notification="")
    uid = cb.user.user_id
    cancel_album_task(uid)
    data = await context.get_data()
    entries: List[dict] = list(data.get("photo_entries") or [])
    r = msg.recipient
    bot = msg.bot
    if data.get("album_buffer"):
        await _flush_album_to_entries(bot, r.chat_id, r.user_id, context, show_counter=True)
        data = await context.get_data()
        entries = list(data.get("photo_entries") or [])
    if not entries:
        await send_explaining(bot, r.chat_id, r.user_id, "Нет фото для отправки.")
        return await event.answer(notification="")

    kind = ReportKind(data["report_kind"])
    obj, err = await guard_access(db, uid)
    if err:
        await send_explaining(
            bot,
            r.chat_id,
            r.user_id,
            T.OBJECT_PAUSED if err == "paused" else T.NOT_BOUND,
        )
        return await event.answer(notification="")

    await event.answer(notification="")
    await msg.answer(text=T.REPORT_SENDING)

    try:
        caption = format_group_caption(kind, len(entries), [e["dt"] for e in entries])
        first_mid = await _send_photos_in_album_chunks(
            bot,
            obj.group_chat_id,
            entries,
            caption,
        )
        link = max_group_message_ref(obj.group_chat_id, first_mid)
        await _send_to_group_and_log(
            bot,
            db,
            cb.user,
            obj,
            event_type=report_title(kind),
            link=link,
            comment=f"фото: {len(entries)}",
        )
        await clear_submenu_instructions(bot, context)
        await clear_service_menu_message(bot, r.chat_id, r.user_id, context)
        await context.clear()
        await msg.answer(text=T.REPORT_SENT)
        await send_or_replace_main_menu(
            bot,
            r.chat_id,
            r.user_id,
            context,
            text=T.BOT_DESCRIPTION,
            attachments=[main_menu_keyboard()],
        )
    except MaxApiError as e:
        await _recover_from_group_send_error(event, context, e)


@router.message_callback(F.callback.payload == "svc_send", states=[GuardStates.video_report])
async def svc_send_video(event: MessageCallback, context: BaseContext, db: Database) -> None:
    cb = event.callback
    msg = event.message
    if msg is None:
        return await event.answer(notification="")
    data = await context.get_data()
    ids: List[str] = list(data.get("video_msg_ids") or [])
    if not ids:
        await send_explaining(msg.bot, msg.recipient.chat_id, msg.recipient.user_id, "Нет видео для отправки.")
        return await event.answer(notification="")
    kind = ReportKind(data["report_kind"])
    obj, err = await guard_access(db, cb.user.user_id)
    r = msg.recipient
    bot = msg.bot
    if err:
        await send_explaining(
            bot,
            r.chat_id,
            r.user_id,
            T.OBJECT_PAUSED if err == "paused" else T.NOT_BOUND,
        )
        return await event.answer(notification="")

    await event.answer(notification="")
    await msg.answer(text=T.REPORT_SENDING)

    try:
        times = [datetime.now()]
        cap = format_text_report_caption(kind, times)
        src = await bot.get_message(ids[0])
        sent = await src.forward(chat_id=obj.group_chat_id)
        mid = sent.message.body.mid if sent and sent.message and sent.message.body else ""
        if mid:
            await bot.send_message(
                chat_id=obj.group_chat_id,
                text=cap,
                link=NewMessageLink(type=MessageLinkType.REPLY, mid=mid),
            )
        else:
            await bot.send_message(chat_id=obj.group_chat_id, text=cap)
        link = max_group_message_ref(obj.group_chat_id, mid or "?")
        await _send_to_group_and_log(
            bot,
            db,
            cb.user,
            obj,
            event_type=report_title(kind),
            link=link,
            comment="видео",
        )
        await clear_submenu_instructions(bot, context)
        await clear_service_menu_message(bot, r.chat_id, r.user_id, context)
        await context.clear()
        await msg.answer(text=T.REPORT_SENT)
        await send_or_replace_main_menu(
            bot,
            r.chat_id,
            r.user_id,
            context,
            text=T.BOT_DESCRIPTION,
            attachments=[main_menu_keyboard()],
        )
    except MaxApiError as e:
        await _recover_from_group_send_error(event, context, e)


@router.message_callback(F.callback.payload == "svc_send", states=[GuardStates.message_report])
async def svc_send_message(event: MessageCallback, context: BaseContext, db: Database) -> None:
    cb = event.callback
    msg = event.message
    if msg is None:
        return await event.answer(notification="")
    uid = cb.user.user_id
    cancel_album_task(uid)
    data = await context.get_data()
    r = msg.recipient
    bot = msg.bot
    if data.get("album_buffer"):
        await _flush_album_to_entries(
            bot,
            r.chat_id,
            r.user_id,
            context,
            show_counter=False,
            is_message_scenario=True,
        )
        data = await context.get_data()

    locked = data.get("msg_locked_kind")
    obj, err = await guard_access(db, uid)
    if err:
        await send_explaining(
            bot,
            r.chat_id,
            r.user_id,
            T.OBJECT_PAUSED if err == "paused" else T.NOT_BOUND,
        )
        return await event.answer(notification="")

    await event.answer(notification="")
    await msg.answer(text=T.REPORT_SENDING)

    try:
        ref_id: int
        mid: str
        if locked == "photo":
            entries = list(data.get("photo_entries") or [])
            if not entries:
                await send_explaining(bot, r.chat_id, r.user_id, "Нет фото для отправки.")
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
                await send_explaining(bot, r.chat_id, r.user_id, "Нет текста для отправки.")
                return
            ref_id = await db.create_group_post_ref_pending(obj.group_chat_id)
            kb = accounted_markup(f"a:{ref_id}")
            header = format_text_report_caption(ReportKind.MESSAGE, [datetime.now()])
            sent = await bot.send_message(
                chat_id=obj.group_chat_id,
                text=f"{header}\n\n{body}",
                attachments=[kb],
            )
            mid = sent.message.body.mid if sent and sent.message and sent.message.body else ""
        elif locked in ("video", "voice"):
            smid = data.get("single_msg_id")
            if not smid:
                await send_explaining(bot, r.chat_id, r.user_id, "Нет содержимого для отправки.")
                return
            ref_id = await db.create_group_post_ref_pending(obj.group_chat_id)
            kb = accounted_markup(f"a:{ref_id}")
            src = await bot.get_message(str(smid))
            sent = await src.forward(chat_id=obj.group_chat_id)
            mid = sent.message.body.mid if sent and sent.message and sent.message.body else ""
            extra = format_text_report_caption(ReportKind.MESSAGE, [datetime.now()])
            if mid:
                try:
                    gm = await bot.get_message(mid)
                    await gm.edit(
                        text=extra,
                        attachments=[kb],
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    try:
                        gm2 = await bot.get_message(mid)
                        await gm2.edit(attachments=[kb])
                    except Exception:
                        pass
                    await bot.send_message(chat_id=obj.group_chat_id, text=extra)
        else:
            await send_explaining(bot, r.chat_id, r.user_id, "Сначала отправьте содержимое отчёта.")
            return

        await db.finalize_group_post_ref(ref_id, mid)
        link = max_group_message_ref(obj.group_chat_id, mid)
        await _pin_report_message(bot, obj.group_chat_id, mid)

        await _send_to_group_and_log(
            bot,
            db,
            cb.user,
            obj,
            event_type=report_title(ReportKind.MESSAGE),
            link=link,
            comment=f"тип: {locked}",
        )
        await clear_submenu_instructions(bot, context)
        await clear_service_menu_message(bot, r.chat_id, r.user_id, context)
        await context.clear()
        await msg.answer(text=T.REPORT_SENT)
        await send_or_replace_main_menu(
            bot,
            r.chat_id,
            r.user_id,
            context,
            text=T.BOT_DESCRIPTION,
            attachments=[main_menu_keyboard()],
        )
    except MaxApiError as e:
        await _recover_from_group_send_error(event, context, e)


@router.message_created(IsDialog(), states=[None])
async def fallback_private(event: MessageCreated, context: BaseContext, db: Database) -> None:
    message = event.message
    su = message.sender.user_id if message.sender else None
    if su is None:
        return
    body = message.body
    txt = (body.text or "").strip() if body else ""
    if txt.startswith("/"):
        return
    cancel_album_task(su)
    cancel_fallback_menu_task(su)

    r = message.recipient
    bot = message.bot

    if HasImageAttachment()(event) and not txt:
        async def _send_main_menu_after_album() -> None:
            try:
                await asyncio.sleep(ALBUM_DEBOUNCE_SECONDS)
            except asyncio.CancelledError:
                return
            _, err = await guard_access(db, su)
            if err == "not_bound":
                await send_peer(bot, chat_id=r.chat_id, user_id=r.user_id, text=T.NOT_BOUND)
            elif err == "paused":
                await send_peer(bot, chat_id=r.chat_id, user_id=r.user_id, text=T.OBJECT_PAUSED)
            else:
                await send_or_replace_main_menu(
                    bot,
                    r.chat_id,
                    r.user_id,
                    context,
                    text=T.BOT_DESCRIPTION,
                    attachments=[main_menu_keyboard()],
                )

        schedule_fallback_menu_task(su, _send_main_menu_after_album)
        return

    _, err = await guard_access(db, su)
    if err == "not_bound":
        return await message.answer(text=T.NOT_BOUND)
    if err == "paused":
        return await message.answer(text=T.OBJECT_PAUSED)
    await send_or_replace_main_menu(
        bot,
        r.chat_id,
        r.user_id,
        context,
        text=T.BOT_DESCRIPTION,
        attachments=[main_menu_keyboard()],
    )

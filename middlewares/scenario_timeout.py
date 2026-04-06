from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, Optional

from aiogram import BaseMiddleware, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject

from constants import SCENARIO_TIMEOUT_MINUTES
from core.keyboards import main_menu_keyboard
from core.states import GuardStates
import texts_ru as T
from services.service_menu import (
    clear_scenario_hint_message,
    clear_service_menu_message,
    delete_bot_message_safe,
    purge_disposable_messages,
)


class ScenarioTimeoutMiddleware(BaseMiddleware):
    """После обработчика: таймер 15 мин с момента последнего события (ТЗ п.9)."""

    def __init__(self) -> None:
        self._tasks: Dict[int, asyncio.Task] = {}

    def _cancel(self, user_id: int) -> None:
        t = self._tasks.pop(user_id, None)
        if t and not t.done():
            t.cancel()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        result = await handler(event, data)

        if isinstance(event, Message) and event.chat.type == "private":
            uid = event.from_user.id if event.from_user else None
            if uid:
                await self._arm_if_scenario(uid, data.get("state"), data)
        elif isinstance(event, CallbackQuery) and event.message and event.message.chat.type == "private":
            uid = event.from_user.id if event.from_user else None
            if uid:
                await self._arm_if_scenario(uid, data.get("state"), data)

        return result

    async def _arm_if_scenario(self, user_id: int, state: Optional[FSMContext], data: Dict[str, Any]) -> None:
        if state is None:
            return
        st = await state.get_state()
        if st not in {
            GuardStates.photo_report.state,
            GuardStates.video_note_report.state,
            GuardStates.message_report.state,
        }:
            self._cancel(user_id)
            return

        await state.update_data(last_activity_wall=time.time())
        bot: Bot = data["bot"]
        chat_id = user_id
        self._cancel(user_id)

        async def _fire() -> None:
            try:
                await asyncio.sleep(SCENARIO_TIMEOUT_MINUTES * 60)
                cur = await state.get_state()
                if cur != st:
                    return
                d = await state.get_data()
                if time.time() - float(d.get("last_activity_wall", 0)) < SCENARIO_TIMEOUT_MINUTES * 60:
                    return
                await clear_scenario_hint_message(bot, chat_id, state)
                await purge_disposable_messages(bot, chat_id, state)
                await clear_service_menu_message(bot, chat_id, state)
                await state.clear()
                timeout_msg = await bot.send_message(chat_id, T.SCENARIO_TIMEOUT)
                await bot.send_message(chat_id, T.BOT_DESCRIPTION, reply_markup=main_menu_keyboard())
                await delete_bot_message_safe(bot, chat_id, timeout_msg.message_id)
            except asyncio.CancelledError:
                return

        self._tasks[user_id] = asyncio.create_task(_fire())

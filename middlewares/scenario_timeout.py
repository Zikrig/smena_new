from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict

from maxapi.filters.middleware import BaseMiddleware

from constants import SCENARIO_TIMEOUT_MINUTES
from core.keyboards import main_menu_keyboard
from core.max_helpers import send_peer
from core.states import GuardStates
import texts_ru as T
from services.service_menu import clear_service_menu_message

# State из maxapi не hashable — нельзя класть в set; сравниваем по строковому имени.
_GUARD_SCENARIO_STATE_NAMES = frozenset(GuardStates.states())


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
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event_object: Any,
        data: dict[str, Any],
    ) -> Any:
        result = await handler(event_object, data)

        context = data.get("context")
        if context is None:
            return result
        uid = getattr(context, "user_id", None)
        if uid is None:
            return result

        st = await context.get_state()
        st_name = str(st) if st is not None else ""
        if st_name not in _GUARD_SCENARIO_STATE_NAMES:
            self._cancel(uid)
            return result

        await context.update_data(last_activity_wall=time.time())
        bot = event_object._ensure_bot()
        chat_id = context.chat_id
        user_id = context.user_id
        self._cancel(uid)

        async def _fire() -> None:
            try:
                await asyncio.sleep(SCENARIO_TIMEOUT_MINUTES * 60)
                cur = await context.get_state()
                if cur != st:
                    return
                d = await context.get_data()
                if time.time() - float(d.get("last_activity_wall", 0)) < SCENARIO_TIMEOUT_MINUTES * 60:
                    return
                await clear_service_menu_message(bot, chat_id, user_id, context)
                await context.clear()
                await send_peer(bot, chat_id=chat_id, user_id=user_id, text=T.SCENARIO_TIMEOUT)
                await send_peer(
                    bot,
                    chat_id=chat_id,
                    user_id=user_id,
                    text=T.BOT_DESCRIPTION,
                    attachments=[main_menu_keyboard()],
                )
            except asyncio.CancelledError:
                return

        self._tasks[uid] = asyncio.create_task(_fire())
        return result

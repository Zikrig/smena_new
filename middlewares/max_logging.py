"""Логирование ответов MAX API и входящих апдейтов (отладка при неполной документации)."""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

from maxapi import Dispatcher
from maxapi.filters.middleware import BaseMiddleware

log = logging.getLogger("max_api")
MAX_JSON_LOG = 16_000


def _short_json(obj: Any) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, default=str)
    except TypeError:
        s = repr(obj)
    if len(s) > MAX_JSON_LOG:
        return s[:MAX_JSON_LOG] + f"... [обрезано, всего {len(s)} симв.]"
    return s


class MaxUpdateLogMiddleware(BaseMiddleware):
    """Пишет тип апдейта и JSON события (после парсинга maxapi)."""

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event_object: Any,
        data: dict[str, Any],
    ) -> Any:
        try:
            raw = (
                event_object.model_dump(mode="json", exclude_none=True)
                if hasattr(event_object, "model_dump")
                else str(event_object)
            )
            log.debug(
                "Входящее событие %s: %s",
                getattr(event_object, "update_type", type(event_object).__name__),
                _short_json(raw),
            )
        except Exception as e:
            log.warning("Не удалось залогировать событие: %s", e)
        return await handler(event_object, data)


def register_max_api_response_logging(dp: Dispatcher) -> None:
    """
    Регистрирует обработчик RAW_API_RESPONSE: каждый JSON-ответ HTTP-методов
    maxapi (в т.ч. GET /updates, POST /messages) уже диспатчится библиотекой.
    """

    @dp.raw_api_response()
    async def _log_raw_api_response(raw: dict[str, Any]) -> None:
        log.info("Ответ MAX API: %s", _short_json(raw))

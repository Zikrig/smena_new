from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from core.config import GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_SHEETS_SPREADSHEET_ID

logger = logging.getLogger(__name__)

_client = None
_spreadsheet = None


def _ensure_client():
    global _client, _spreadsheet
    if _spreadsheet is not None:
        return _spreadsheet
    if not GOOGLE_SHEETS_SPREADSHEET_ID:
        return None
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(
            GOOGLE_SERVICE_ACCOUNT_JSON,
            scopes=scopes,
        )
        _client = gspread.authorize(creds)
        _spreadsheet = _client.open_by_key(GOOGLE_SHEETS_SPREADSHEET_ID)
        return _spreadsheet
    except Exception as e:
        logger.warning("Google Sheets недоступен: %s", e)
        return None


def _ensure_worksheet(sh: Any, title: str):
    try:
        return sh.worksheet(title)
    except Exception:
        ws = sh.add_worksheet(title=title, rows=1000, cols=10)
        ws.append_row(
            [
                "дата",
                "время",
                "тип события",
                "автор",
                "ссылка",
                "комментарий",
                "учтено",
            ]
        )
        return ws


async def log_event(
    sheet_title: str,
    event_type: str,
    author_label: str,
    link: str,
    comment: str,
    *,
    accounted_by: str = "",
) -> None:
    """Лог строки (ТЗ п.12). Не бросает наружу — fail-open."""

    def _write():
        sh = _ensure_client()
        if not sh:
            return
        ws = _ensure_worksheet(sh, sheet_title[:99])
        now = datetime.now()
        ws.append_row(
            [
                now.strftime("%Y-%m-%d"),
                now.strftime("%H:%M:%S"),
                event_type,
                author_label,
                link,
                comment,
                accounted_by,
            ]
        )

    try:
        await asyncio.to_thread(_write)
    except Exception as e:
        logger.warning("Sheets log skip: %s", e)

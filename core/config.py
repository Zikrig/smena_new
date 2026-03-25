import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


def _parse_admin_ids(raw: str) -> list[int]:
    if not raw or not raw.strip():
        return []
    out: list[int] = []
    for part in raw.replace(" ", "").split(","):
        p = part.strip()
        if p.isdigit():
            out.append(int(p))
    return out


BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_PATH = os.getenv(
    "DATABASE_PATH",
    str(ROOT / "guard_bot.db"),
)
# Список user_id через запятую — доступ к командам в группах, «Учтено», /admin в ЛС
ADMIN_IDS: list[int] = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))

# Google Sheets (опционально; при отсутствии — только Telegram)
GOOGLE_SHEETS_SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    str(ROOT / "service_account.json"),
)

# Часовой пояс для подписи отчётов (п.11); по умолчанию локальное время процесса.
REPORT_TIMEZONE = os.getenv("TZ", "")

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

# Кнопка «Тревога»: экстренные номера (как «Вызов» в smena_sled). Можно переопределить в .env.
EMERGENCY_CONTACTS: list[tuple[str, str]] = [
    ("Телефон экстренных служб", os.getenv("PHONE_EMERGENCY_UNIFIED", "112")),
    ("Начальник охраны в СПб", os.getenv("PHONE_SECURITY_CHIEF_SPB", "+79213666399")),
    ("Начальник охраны в ЛО", os.getenv("PHONE_SECURITY_CHIEF_LO", "+79219590313")),
    ("Начальник ОП «ОРА»", os.getenv("PHONE_SECURITY_CHIEF_ORA", "+79213173079")),
]

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


def _parse_admin_ids(raw: str) -> list[int]:
    """Читает ADMIN_IDS из .env: запятая или точка с запятой, пробелы, кавычки вокруг чисел."""
    if not raw or not raw.strip():
        return []
    s = raw.strip().strip('"').strip("'")
    out: list[int] = []
    for part in s.replace(";", ",").split(","):
        p = part.strip().strip('"').strip("'")
        if not p:
            continue
        try:
            out.append(int(p))
        except ValueError:
            continue
    return out


# MAX Bot API (https://dev.max.ru); токен из MAX Business → Чат-боты → Интеграция
MAX_BOT_TOKEN = os.getenv("MAX_BOT_TOKEN", os.getenv("BOT_TOKEN", ""))

# Ссылка для привязки охранника: шаблон с {token} (и опционально {username} бота)
MAX_BIND_LINK_TEMPLATE = os.getenv(
    "MAX_BIND_LINK_TEMPLATE",
    "/start {token}",
)
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

# Кнопка «Тревога» в ЛС: справка по номерам, без отправки в группу и без сценария с фото.
EMERGENCY_CALL_CONTACTS: list[tuple[str, str]] = [
    ("🆘 Единый номер экстренных служб", "112"),
    ("🚒 Пожарная служба", "101"),
    ("📞 Дежурная часть ОРА", "+79213092809"),
    ("👨‍💼 Начальник охраны в ЛО", "+79219590313"),
    ("👨‍💼 Начальник охраны в СПб", "+79213666399"),
    ("👨‍💼 Начальник ОП «ОРА»", "+79213173079"),
    ("👨‍💼 Пожарная служба в Сосново", "+78137961262"),
]

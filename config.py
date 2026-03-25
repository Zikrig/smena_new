import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_PATH = os.getenv(
    "DATABASE_PATH",
    str(Path(__file__).resolve().parent / "guard_bot.db"),
)
# Google Sheets (опционально; при отсутствии — только Telegram)
GOOGLE_SHEETS_SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    str(Path(__file__).resolve().parent / "service_account.json"),
)

# Часовой пояс для подписи отчётов (п.11); по умолчанию локальное время процесса.
REPORT_TIMEZONE = os.getenv("TZ", "")

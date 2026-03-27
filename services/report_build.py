from __future__ import annotations

from datetime import datetime
from typing import List

from core.report_types import ReportKind, emoji_for_kind, report_title


def format_group_caption(
    kind: ReportKind,
    photo_count: int,
    times: List[datetime],
) -> str:
    """Подпись отчёта в группе в стиле старой версии: время, дата, медиа."""
    title = report_title(kind)
    em = emoji_for_kind(kind)
    t = times[0] if times else datetime.now()
    lines = [
        f"{em} {title}",
        f"⏰ Время: {t.strftime('%H:%M:%S')}",
        f"📅 Дата: {t.strftime('%d.%m.%Y')}",
        f"🖼 Медиа: фото ({photo_count})",
    ]
    return "\n".join(lines)


def format_text_report_caption(kind: ReportKind, times: List[datetime], extra: str = "") -> str:
    em = emoji_for_kind(kind)
    title = report_title(kind)
    t = times[0] if times else datetime.now()
    media = {
        ReportKind.START_SHIFT: "видеокружок",
        ReportKind.POST_CHECK: "видеокружок",
        ReportKind.MESSAGE: "сообщение",
        ReportKind.ALARM: "сообщение",
    }.get(kind, "сообщение")
    lines = [
        f"{em} {title}",
        f"⏰ Время: {t.strftime('%H:%M:%S')}",
        f"📅 Дата: {t.strftime('%d.%m.%Y')}",
        f"📎 Медиа: {media}",
    ]
    if extra:
        lines.append(extra)
    return "\n".join(lines)

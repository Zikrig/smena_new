from __future__ import annotations

from datetime import datetime
from typing import List

from core.report_types import ReportKind, emoji_for_kind, report_title


def format_group_caption(
    kind: ReportKind,
    photo_count: int,
    times: List[datetime],
) -> str:
    """Подпись отчёта в группе (ТЗ п.11) — дата и список времён."""
    title = report_title(kind)
    em = emoji_for_kind(kind)
    lines = [f"{em} {title}", f"Фото: {photo_count}", "Время:"]
    for i, t in enumerate(times, start=1):
        lines.append(f"{i}) {t.strftime('%d.%m.%Y %H:%M:%S')}")
    return "\n".join(lines)


def format_text_report_caption(kind: ReportKind, times: List[datetime], extra: str = "") -> str:
    em = emoji_for_kind(kind)
    title = report_title(kind)
    lines = [f"{em} {title}", "Время:"]
    for i, t in enumerate(times, start=1):
        lines.append(f"{i}) {t.strftime('%d.%m.%Y %H:%M:%S')}")
    if extra:
        lines.append(extra)
    return "\n".join(lines)

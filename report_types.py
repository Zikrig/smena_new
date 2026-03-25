from enum import Enum

import texts_ru as T


class ReportKind(str, Enum):
    START_SHIFT = "start_shift"
    HANDOVER = "handover"
    PATROL = "patrol"
    INSPECTION = "inspection"
    POST_CHECK = "post_check"
    MESSAGE = "message"
    ALARM = "alarm"


def report_title(kind: ReportKind) -> str:
    return {
        ReportKind.START_SHIFT: T.REPORT_TITLE_START_SHIFT,
        ReportKind.HANDOVER: T.REPORT_TITLE_HANDOVER,
        ReportKind.PATROL: T.REPORT_TITLE_PATROL,
        ReportKind.INSPECTION: T.REPORT_TITLE_INSPECTION,
        ReportKind.POST_CHECK: T.REPORT_TITLE_POST_CHECK,
        ReportKind.MESSAGE: T.REPORT_TITLE_MESSAGE,
        ReportKind.ALARM: T.REPORT_TITLE_ALARM,
    }[kind]


def emoji_for_kind(kind: ReportKind) -> str:
    return {
        ReportKind.START_SHIFT: "📹",
        ReportKind.HANDOVER: "📸",
        ReportKind.PATROL: "📸",
        ReportKind.INSPECTION: "📸",
        ReportKind.POST_CHECK: "📹",
        ReportKind.MESSAGE: "📸",
        ReportKind.ALARM: "🚨",
    }.get(kind, "📋")

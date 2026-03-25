from aiogram.fsm.state import State, StatesGroup


class GuardStates(StatesGroup):
    """Состояния активного сценария отчёта в ЛС."""

    photo_report = State()
    video_note_report = State()
    message_report = State()
    alarm_report = State()

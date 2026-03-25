from aiogram.fsm.state import State, StatesGroup


class GuardStates(StatesGroup):
    """Состояния активного сценария отчёта в ЛС."""

    photo_report = State()
    video_note_report = State()
    message_report = State()
    alarm_report = State()


class AdminStates(StatesGroup):
    """Панель /admin: ввод id охранника или регистрация группы."""

    wait_guard_user_id = State()
    wait_group_chat_id = State()
    wait_group_name = State()

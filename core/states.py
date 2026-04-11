from maxapi.context.state_machine import State, StatesGroup


class GuardStates(StatesGroup):
    """Состояния активного сценария отчёта в ЛС."""

    photo_report = State()
    video_report = State()
    message_report = State()


class AdminStates(StatesGroup):
    """Панель /admin: ввод id охранника или регистрация группы."""

    wait_guard_user_id = State()
    wait_group_chat_id = State()
    wait_group_name = State()


class GroupStates(StatesGroup):
    """Команды в группе объекта: двухшаговый /set."""

    wait_object_name = State()

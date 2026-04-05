from maxapi.types.attachments.buttons.callback_button import CallbackButton
from maxapi.types.message import Message
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

import texts_ru as T


async def hide_inline_keyboard(message: Message) -> None:
    """Убирает inline-клавиатуру с сообщения бота."""
    if message.body is None:
        return
    try:
        await message.edit(text=message.body.text, attachments=[])
    except Exception:
        pass


def main_menu_keyboard():
    b = InlineKeyboardBuilder()
    b.row(
        CallbackButton(text=T.BTN_START_SHIFT, payload="menu:shift"),
        CallbackButton(text=T.BTN_HANDOVER, payload="menu:handover"),
    )
    b.row(
        CallbackButton(text=T.BTN_PATROL, payload="menu:patrol"),
        CallbackButton(text=T.BTN_INSPECTION, payload="menu:inspection"),
    )
    b.row(
        CallbackButton(text=T.BTN_POST_CHECK, payload="menu:post"),
        CallbackButton(text=T.BTN_MESSAGE, payload="menu:message"),
    )
    b.row(CallbackButton(text=T.BTN_ALARM, payload="menu:alarm"))
    return b.as_markup()


def service_menu_inline(*, show_photo_counter: bool, photo_count: int):
    builder = InlineKeyboardBuilder()
    builder.add(
        CallbackButton(text=T.BTN_ALARM, payload="svc:alarm"),
        CallbackButton(text=T.BTN_SEND_REPORT, payload="svc_send"),
        CallbackButton(text=T.BTN_MAIN_MENU, payload="svc_cancel"),
    )
    builder.adjust(1)
    return builder


def service_menu_markup(*, show_photo_counter: bool, photo_count: int):
    return service_menu_inline(
        show_photo_counter=show_photo_counter,
        photo_count=photo_count,
    ).as_markup()


def accounted_markup(callback_payload: str):
    b = InlineKeyboardBuilder()
    b.button(text=T.INLINE_ACCOUNTED, payload=callback_payload)
    return b.as_markup()

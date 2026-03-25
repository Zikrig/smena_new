from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import texts_ru as T


async def hide_inline_keyboard(message: Message) -> None:
    """Убирает inline-клавиатуру с сообщения бота (например главное меню)."""
    try:
        await message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


def main_menu_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text=T.BTN_START_SHIFT, callback_data="menu:shift"),
        InlineKeyboardButton(text=T.BTN_HANDOVER, callback_data="menu:handover"),
    )
    b.row(
        InlineKeyboardButton(text=T.BTN_PATROL, callback_data="menu:patrol"),
        InlineKeyboardButton(text=T.BTN_INSPECTION, callback_data="menu:inspection"),
    )
    b.row(
        InlineKeyboardButton(text=T.BTN_POST_CHECK, callback_data="menu:post"),
        InlineKeyboardButton(text=T.BTN_MESSAGE, callback_data="menu:message"),
    )
    b.row(InlineKeyboardButton(text=T.BTN_ALARM, callback_data="menu:alarm"))
    return b.as_markup()


def service_menu_inline(*, show_photo_counter: bool, photo_count: int) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text=T.BTN_SEND_REPORT, callback_data="svc_send")
    builder.button(text=T.BTN_MAIN_MENU, callback_data="svc_cancel")
    builder.adjust(1)
    return builder


def service_menu_markup(*, show_photo_counter: bool, photo_count: int):
    return service_menu_inline(
        show_photo_counter=show_photo_counter,
        photo_count=photo_count,
    ).as_markup()


def accounted_markup(callback_data: str):
    b = InlineKeyboardBuilder()
    b.button(text=T.INLINE_ACCOUNTED, callback_data=callback_data)
    return b.as_markup()

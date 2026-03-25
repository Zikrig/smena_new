from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import texts_ru as T


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=T.BTN_START_SHIFT), KeyboardButton(text=T.BTN_HANDOVER)],
            [KeyboardButton(text=T.BTN_PATROL), KeyboardButton(text=T.BTN_INSPECTION)],
            [KeyboardButton(text=T.BTN_POST_CHECK), KeyboardButton(text=T.BTN_MESSAGE)],
            [KeyboardButton(text=T.BTN_ALARM)],
        ],
        resize_keyboard=True,
    )


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

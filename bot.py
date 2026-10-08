def back_only() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Назад", callback_data="back")]]
    )


async def send_sub(message: Message, text: str, sub_id: str) -> None:
    await message.answer_photo(
        qr_file(sub_url(sub_id)),
        caption=text,
        parse_mode="Markdown",
        reply_markup=back_only(),
    )

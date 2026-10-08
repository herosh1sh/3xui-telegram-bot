async def send_sub(message: Message, text: str, sub_id: str) -> None:
    caption = text if len(text) <= 1000 else text[:1000].rsplit("\n", 1)[0]
    try:
        await message.answer_photo(
            qr_file(sub_url(sub_id)),
            caption=caption,
            parse_mode="Markdown",
            reply_markup=back_only(),
        )
    except TelegramBadRequest:
        await message.answer_photo(
            qr_file(sub_url(sub_id)),
            caption=caption[:1000],
            reply_markup=back_only(),
        )
    rest = text[len(caption):].strip()
    while rest:
        chunk, rest = rest[:3500], rest[3500:]
        await message.answer(chunk)

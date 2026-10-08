"""Картинка к каждому сообщению и Premium-эмодзи на кнопках."""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, InlineKeyboardButton, KeyboardButton, Message

log = logging.getLogger("ui")
_banner_cache: bytes | None = None
_banner_file_id: str | None = None


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def emoji_id(key: str = "") -> str:
    specific = env(f"BUTTON_EMOJI_{key.upper()}") if key else ""
    return specific or env("BUTTON_EMOJI")


def btn(text: str, *, callback_data: str | None = None, url: str | None = None, emoji: str = "") -> InlineKeyboardButton:
    kwargs: dict = {"text": text}
    if callback_data:
        kwargs["callback_data"] = callback_data
    if url:
        kwargs["url"] = url
    icon = emoji_id(emoji)
    if icon:
        kwargs["icon_custom_emoji_id"] = icon
    try:
        return InlineKeyboardButton(**kwargs)
    except TypeError:
        log.warning("aiogram не знает icon_custom_emoji_id, обновите пакет: pip install -U 'aiogram>=3.22'")
        kwargs.pop("icon_custom_emoji_id", None)
        return InlineKeyboardButton(**kwargs)


def key_btn(text: str, *, emoji: str = "") -> KeyboardButton:
    icon = emoji_id(emoji)
    if not icon:
        return KeyboardButton(text=text)
    try:
        return KeyboardButton(text=text, icon_custom_emoji_id=icon)
    except TypeError:
        return KeyboardButton(text=text)


def _draw_banner() -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1280, 640), (8, 14, 28))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((36, 36, 1244, 604), radius=40, fill=(16, 32, 58), outline=(78, 154, 255), width=5)
    draw.ellipse((980, 80, 1180, 280), fill=(24, 58, 110))
    font = ImageFont.load_default()
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ):
        if Path(path).is_file():
            font = ImageFont.truetype(path, 84)
            break
    draw.text((80, 220), "HeroshishVPN", fill=(236, 244, 255), font=font)
    small = ImageFont.load_default()
    draw.text((84, 340), "Subscription access", fill=(150, 182, 220), font=small)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def banner_bytes() -> bytes:
    global _banner_cache
    if _banner_cache is not None:
        return _banner_cache
    path = Path(env("BANNER_PATH", "assets/banner.png"))
    _banner_cache = path.read_bytes() if path.is_file() else _draw_banner()
    return _banner_cache


def banner_input():
    global _banner_file_id
    if _banner_file_id:
        return _banner_file_id
    return BufferedInputFile(banner_bytes(), filename="banner.png")


def _remember(sent: Message) -> None:
    global _banner_file_id
    if sent.photo:
        _banner_file_id = sent.photo[-1].file_id


async def say(message: Message, text: str, reply_markup=None, parse_mode: str | None = "Markdown") -> Message:
    caption = text if len(text) <= 1000 else text[:1000].rsplit("\n", 1)[0]
    try:
        sent = await message.answer_photo(
            banner_input(),
            caption=caption or " ",
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
    except TelegramBadRequest:
        sent = await message.answer_photo(banner_input(), caption=(caption or " ")[:1000], reply_markup=reply_markup)
    except Exception:
        log.exception("banner send failed")
        return await message.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)
    _remember(sent)
    rest = text[len(caption):].strip()
    while rest:
        chunk, rest = rest[:1000], rest[1000:]
        try:
            extra = await message.answer_photo(banner_input(), caption=chunk)
            _remember(extra)
        except Exception:
            await message.answer(chunk)
    return sent


async def notify(bot, chat_id: int, text: str) -> None:
    try:
        sent = await bot.send_photo(chat_id, banner_input(), caption=text[:1000])
        _remember(sent)
    except Exception:
        await bot.send_message(chat_id, text[:4000])

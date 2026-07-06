import asyncio
import logging
import os
from html import escape
from urllib.parse import quote

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "otdel_chudes_bot")
DELETE_WELCOME_AFTER_SECONDS = int(os.getenv("DELETE_WELCOME_AFTER_SECONDS", "600"))

if not BOT_TOKEN:
    raise RuntimeError("Не найден BOT_TOKEN. Добавь BOT_TOKEN в Variables на Railway.")

router = Router()

WELCOME_TEXT = """🌙 Добро пожаловать в «Личный отдел чудес», {mention}!

Рады видеть тебя в нашем пространстве.

Здесь можно общаться, задавать вопросы, делиться мыслями, знакомиться и быть собой.

Перед тем как вливаться в общение, ознакомься с правилами чата 👇

И немного расскажи о себе в любой удобной форме — кто ты, чем занимаешься, что тебя привело сюда или просто то, чем хочется поделиться ✨"""

RULES_TEXT = """🌙 ПРАВИЛА ЧАТА

Материться можно. Материть друг друга — нельзя.

Никакой политики. Совсем. Нарушение — сразу бан.

Реклама и спам разрешены только во флудилке.

Хотите разместить рекламу для участников сообщества — присылайте её администратору. После согласования она будет опубликована от имени администратора в отдельной папке.

Уважаем друг друга и не превращаем обсуждения в срач.

На этом всё. Общайтесь, знакомьтесь и чувствуйте себя свободно 🌙"""


def rules_keyboard() -> InlineKeyboardMarkup:
    deep_link = f"https://t.me/{BOT_USERNAME}?start=rules"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📜 Правила чата", url=deep_link)]
        ]
    )


async def delete_later(bot: Bot, chat_id: int, message_id: int, delay: int) -> None:
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except (TelegramBadRequest, TelegramForbiddenError):
        pass


@router.message(CommandStart())
async def start_command(message: Message) -> None:
    text = message.text or ""
    if "rules" in text:
        await message.answer(RULES_TEXT)
        return

    await message.answer(
        "Привет 🌙 Я Хранитель чудес. Добавь меня администратором в чат, чтобы я встречал новых участников и удалял системные уведомления.\n\n"
        "Чтобы посмотреть правила чата, нажми /rules"
    )


@router.message(Command("rules"))
async def rules_command(message: Message) -> None:
    await message.answer(RULES_TEXT)


@router.message(F.new_chat_members)
async def welcome_new_members(message: Message, bot: Bot) -> None:
    try:
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    except (TelegramBadRequest, TelegramForbiddenError):
        pass

    for member in message.new_chat_members:
        if member.is_bot:
            continue

        safe_name = escape(member.first_name or "новый участник")
        mention = f'<a href="tg://user?id={member.id}">{safe_name}</a>'

        welcome = await bot.send_message(
            chat_id=message.chat.id,
            text=WELCOME_TEXT.format(mention=mention),
            reply_markup=rules_keyboard(),
        )

        asyncio.create_task(
            delete_later(
                bot=bot,
                chat_id=message.chat.id,
                message_id=welcome.message_id,
                delay=DELETE_WELCOME_AFTER_SECONDS,
            )
        )


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

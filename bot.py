import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder


BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

DATA_FILE = "registrations.json"

EVENTS = {
    "networking_10july": {
        "title": "Большой онлайн-нетворкинг предпринимателей и экспертов",
        "date": "10 июля",
        "time": "18:00 МСК",
        "description": "200 предпринимателей, экспертов и руководителей. Живое общение, новые связи, партнёрства и клиенты.",
        "link": "Ссылка на эфир будет отправлена перед началом."
    }
}


class Register(StatesGroup):
    name = State()
    phone = State()
    sphere = State()


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


def load_data():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    args = message.text.split(maxsplit=1)
    event_id = args[1] if len(args) > 1 else "networking_10july"

    if event_id not in EVENTS:
        await message.answer("Мероприятие не найдено. Проверьте ссылку.")
        return

    event = EVENTS[event_id]
    await state.update_data(event_id=event_id)

    text = (
        f"👋 Добро пожаловать!\n\n"
        f"Вы регистрируетесь на мероприятие:\n\n"
        f"**{event['title']}**\n\n"
        f"📅 {event['date']}\n"
        f"🕕 {event['time']}\n\n"
        f"{event['description']}\n\n"
        f"Чтобы зарегистрироваться, напишите ваше имя."
    )

    await message.answer(text, parse_mode="Markdown")
    await state.set_state(Register.name)


@dp.message(Register.name)
async def get_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)

    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поделиться номером", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

    await message.answer("Отправьте номер телефона:", reply_markup=keyboard)
    await state.set_state(Register.phone)


@dp.message(Register.phone)
async def get_phone(message: Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else message.text
    await state.update_data(phone=phone)

    await message.answer(
        "Чем вы занимаетесь?\n\nНапример: маркетолог, предприниматель, дизайнер, юрист.",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(Register.sphere)


@dp.message(Register.sphere)
async def get_sphere(message: Message, state: FSMContext):
    data = await state.get_data()
    event = EVENTS[data["event_id"]]

    registrations = load_data()

    registrations.append({
        "event_id": data["event_id"],
        "event_title": event["title"],
        "name": data["name"],
        "phone": data["phone"],
        "sphere": message.text,
        "telegram_id": message.from_user.id,
        "telegram_username": message.from_user.username,
        "registered_at": datetime.now(ZoneInfo("Europe/Moscow")).strftime("%Y-%m-%d %H:%M:%S")
    })

    save_data(registrations)

builder = InlineKeyboardBuilder()

builder.button(
text="💬 Чат участников",
url="https://t.me/+vyrw8Q-AnAlkYWVi"
)

builder.button(
text="📢 Канал сообщества",
url="https://t.me/voice_clubbbb"
)

builder.adjust(1)

await message.answer(
    f"🎉 <b>Регистрация подтверждена!</b>\n\n"
    f"Вы записаны на:\n\n"
    f"<b>{event['title']}</b>\n\n"
    f"📅 <b>{event['date']}</b>\n"
    f"🕕 <b>{event['time']}</b>\n\n"
    f"За сутки и за час до начала мы пришлем вам напоминание.\n\n"
    f"До встречи на мероприятии! 🚀",
    parse_mode="HTML",
    reply_markup=builder.as_markup()
)
)

    for admin_id in ADMIN_IDS:
        await bot.send_message(
            admin_id,
            f"🔥 Новая регистрация\n\n"
            f"Мероприятие: {event['title']}\n"
            f"Имя: {data['name']}\n"
            f"Телефон: {data['phone']}\n"
            f"Сфера: {message.text}\n"
            f"Telegram: @{message.from_user.username}"
        )

    await state.clear()


@dp.message(Command("participants"))
async def participants(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("У вас нет доступа к этой команде.")
        return

    registrations = load_data()

    if not registrations:
        await message.answer("Пока нет регистраций.")
        return

    text = "👥 Участники:\n\n"

    for i, user in enumerate(registrations, start=1):
        text += (
            f"{i}. {user['name']}\n"
            f"Телефон: {user['phone']}\n"
            f"Сфера: {user['sphere']}\n"
            f"Telegram: @{user['telegram_username']}\n\n"
        )

    await message.answer(text)


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

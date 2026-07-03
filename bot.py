import os
import json
import secrets
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger


BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "vsesvoi_event_business_bot")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

EVENTS_FILE = "events.json"
REGISTRATIONS_FILE = "registrations.json"
SUMMARY_STATE_FILE = "summary_state.json"
MOSCOW_TZ = ZoneInfo("Europe/Moscow")

DEFAULT_CHAT_URL = "https://t.me/+vyrw8Q-AnAlkYWVi"
DEFAULT_CHANNEL_URL = "https://t.me/voice_clubbbb"


# ---------- Storage ----------

def default_events():
    return {
        "networking_10july": {
            "title": "Большой онлайн-нетворкинг предпринимателей и экспертов",
            "date": "10 июля",
            "time": "18:00 МСК",
            "description": "200 предпринимателей, экспертов и руководителей. Живое общение, новые связи, партнёрства и клиенты.",
            "chat_url": DEFAULT_CHAT_URL,
            "channel_url": DEFAULT_CHANNEL_URL,
            "created_at": datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "is_active": True,
        }
    }


def load_json(path, fallback):
    if not os.path.exists(path):
        return fallback
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return fallback


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_events():
    events = load_json(EVENTS_FILE, {})
    if not events:
        events = default_events()
        save_json(EVENTS_FILE, events)
    return events


def save_events(events):
    save_json(EVENTS_FILE, events)


def load_registrations():
    return load_json(REGISTRATIONS_FILE, [])


def save_registrations(data):
    save_json(REGISTRATIONS_FILE, data)


def load_summary_state():
    return load_json(SUMMARY_STATE_FILE, {})


def save_summary_state(data):
    save_json(SUMMARY_STATE_FILE, data)


# ---------- Helpers ----------

def now_moscow() -> datetime:
    return datetime.now(MOSCOW_TZ)


def now_str() -> str:
    return now_moscow().strftime("%Y-%m-%d %H:%M:%S")


def parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=MOSCOW_TZ)
    except ValueError:
        return None


def is_admin(message: Message) -> bool:
    return message.from_user and message.from_user.id in ADMIN_IDS


def make_event_id(title: str) -> str:
    raw = title.lower()
    raw = re.sub(r"[^a-zа-я0-9]+", "_", raw, flags=re.IGNORECASE).strip("_")
    raw = raw[:24] or "event"
    return f"{raw}_{secrets.token_hex(2)}"


def event_link(event_id: str) -> str:
    return f"https://t.me/{BOT_USERNAME}?start={event_id}"


def event_keyboard(event):
    builder = InlineKeyboardBuilder()
    chat_url = event.get("chat_url")
    channel_url = event.get("channel_url")
    if chat_url:
        builder.button(text="💬 Чат участников", url=chat_url)
    if channel_url:
        builder.button(text="📢 Канал сообщества", url=channel_url)
    builder.adjust(1)
    return builder.as_markup()


def admin_menu_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать мероприятие", callback_data="admin_new")],
            [InlineKeyboardButton(text="📅 Все мероприятия", callback_data="admin_events")],
            [InlineKeyboardButton(text="🔗 Ссылка на последний ивент", callback_data="admin_link")],
        ]
    )


def events_list_text(events):
    if not events:
        return "Пока нет мероприятий. Создайте первое через /new"
    text = "📅 <b>Мероприятия</b>\n\n"
    for i, (event_id, event) in enumerate(events.items(), start=1):
        status = "🟢" if event.get("is_active", True) else "⚪️"
        total = count_event_registrations(event_id)
        text += (
            f"{i}. {status} <b>{event['title']}</b>\n"
            f"📅 {event.get('date', '—')}\n"
            f"🕕 {event.get('time', '—')}\n"
            f"👥 Регистраций: {total}\n"
            f"ID: <code>{event_id}</code>\n"
            f"🔗 {event_link(event_id)}\n\n"
        )
    return text


def registrations_for_event(event_id: str):
    return [r for r in load_registrations() if r.get("event_id") == event_id]


def count_event_registrations(event_id: str) -> int:
    return len(registrations_for_event(event_id))


def count_today_registrations(event_id: str) -> int:
    today = now_moscow().strftime("%Y-%m-%d")
    return len([
        r for r in registrations_for_event(event_id)
        if str(r.get("registered_at", "")).startswith(today)
    ])


def format_admin_registration(registration: dict, event: dict) -> str:
    event_id = registration["event_id"]
    total = count_event_registrations(event_id)
    today_count = count_today_registrations(event_id)
    username = registration.get("telegram_username") or "—"

    return (
        "🔥 <b>Новая регистрация</b>\n\n"
        f"👤 <b>Имя:</b> {registration.get('name', '—')}\n"
        f"📱 <b>Телефон:</b> {registration.get('phone', '—')}\n"
        f"💼 <b>Сфера:</b> {registration.get('sphere', '—')}\n"
        f"💬 <b>Telegram:</b> @{username}\n"
        f"📅 <b>Мероприятие:</b> {event.get('title', '—')}\n\n"
        "━━━━━━━━━━━━━━\n"
        f"👥 <b>Всего регистраций:</b> {total}\n"
        f"📈 <b>За сегодня:</b> +{today_count}"
    )


def format_milestone(event: dict, total: int) -> str:
    return (
        f"🎉 <b>Уже {total} регистраций!</b>\n\n"
        f"📅 {event.get('title', '—')}\n"
        "Темп отличный 🚀"
    )


async def send_to_admins(text: str):
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception:
            pass


# ---------- FSM ----------

class Register(StatesGroup):
    name = State()
    phone = State()
    sphere = State()


class NewEvent(StatesGroup):
    title = State()
    date = State()
    time = State()
    description = State()
    chat_url = State()
    channel_url = State()
    confirm = State()


if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Add BOT_TOKEN in Railway Variables.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler(timezone=MOSCOW_TZ)


# ---------- Participant flow ----------

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    args = message.text.split(maxsplit=1)
    event_id = args[1] if len(args) > 1 else None

    events = load_events()

    if not event_id:
        await message.answer(
            "👋 Добро пожаловать в бот регистрации <b>Все свои</b>.\n\n"
            "Для регистрации перейдите по ссылке конкретного мероприятия.",
            parse_mode="HTML",
        )
        return

    if event_id not in events:
        await message.answer("Мероприятие не найдено. Проверьте ссылку.")
        return

    event = events[event_id]
    if not event.get("is_active", True):
        await message.answer("Регистрация на это мероприятие закрыта.")
        return

    await state.update_data(event_id=event_id)

    await message.answer(
        f"👋 Добро пожаловать!\n\n"
        f"Вы регистрируетесь на мероприятие:\n\n"
        f"<b>{event['title']}</b>\n\n"
        f"📅 {event.get('date', '—')}\n"
        f"🕕 {event.get('time', '—')}\n\n"
        f"{event.get('description', '')}\n\n"
        f"Чтобы зарегистрироваться, напишите ваше имя.",
        parse_mode="HTML",
    )
    await state.set_state(Register.name)


@dp.message(Register.name)
async def get_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())

    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поделиться номером", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer("Отправьте номер телефона:", reply_markup=keyboard)
    await state.set_state(Register.phone)


@dp.message(Register.phone)
async def get_phone(message: Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else message.text.strip()
    await state.update_data(phone=phone)

    await message.answer(
        "Чем вы занимаетесь?\n\nНапример: маркетолог, предприниматель, дизайнер, юрист.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(Register.sphere)


@dp.message(Register.sphere)
async def get_sphere(message: Message, state: FSMContext):
    data = await state.get_data()
    events = load_events()
    event = events[data["event_id"]]

    registrations = load_registrations()
    registration = {
        "event_id": data["event_id"],
        "event_title": event["title"],
        "name": data["name"],
        "phone": data["phone"],
        "sphere": message.text.strip(),
        "telegram_id": message.from_user.id,
        "telegram_username": message.from_user.username,
        "registered_at": now_str(),
    }
    registrations.append(registration)
    save_registrations(registrations)

    await message.answer(
        f"🎉 <b>Регистрация подтверждена!</b>\n\n"
        f"Вы записаны на:\n\n"
        f"<b>{event['title']}</b>\n\n"
        f"📅 <b>{event.get('date', '—')}</b>\n"
        f"🕕 <b>{event.get('time', '—')}</b>\n\n"
        f"За сутки и за час до начала мы пришлем вам напоминание.\n\n"
        f"До встречи на мероприятии! 🚀",
        parse_mode="HTML",
        reply_markup=event_keyboard(event),
    )

    await send_to_admins(format_admin_registration(registration, event))

    total = count_event_registrations(data["event_id"])
    if total > 0 and total % 10 == 0:
        await send_to_admins(format_milestone(event, total))

    await state.clear()


# ---------- Admin panel ----------

@dp.message(Command("admin"))
async def admin(message: Message):
    if not is_admin(message):
        await message.answer("У вас нет доступа к этой команде.")
        return
    await message.answer("⚙️ <b>Админ-панель</b>", parse_mode="HTML", reply_markup=admin_menu_keyboard())


@dp.callback_query(F.data == "admin_new")
async def admin_new_callback(callback, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.answer("Введите название мероприятия:")
    await state.set_state(NewEvent.title)
    await callback.answer()


@dp.callback_query(F.data == "admin_events")
async def admin_events_callback(callback):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.answer(events_list_text(load_events()), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "admin_link")
async def admin_link_callback(callback):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    events = load_events()
    if not events:
        await callback.message.answer("Пока нет мероприятий.")
    else:
        event_id = list(events.keys())[-1]
        await callback.message.answer(f"🔗 Ссылка на регистрацию:\n\n{event_link(event_id)}")
    await callback.answer()


@dp.message(Command("new"))
async def new_event(message: Message, state: FSMContext):
    if not is_admin(message):
        await message.answer("У вас нет доступа к этой команде.")
        return
    await message.answer("Введите название мероприятия:")
    await state.set_state(NewEvent.title)


@dp.message(NewEvent.title)
async def new_event_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await message.answer("Введите дату. Например: 23 июля")
    await state.set_state(NewEvent.date)


@dp.message(NewEvent.date)
async def new_event_date(message: Message, state: FSMContext):
    await state.update_data(date=message.text.strip())
    await message.answer("Введите время. Например: 18:00 МСК")
    await state.set_state(NewEvent.time)


@dp.message(NewEvent.time)
async def new_event_time(message: Message, state: FSMContext):
    await state.update_data(time=message.text.strip())
    await message.answer("Введите описание мероприятия:")
    await state.set_state(NewEvent.description)


@dp.message(NewEvent.description)
async def new_event_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await message.answer(
        "Введите ссылку на чат участников.\n\n"
        "Можно отправить '-' чтобы использовать чат по умолчанию."
    )
    await state.set_state(NewEvent.chat_url)


@dp.message(NewEvent.chat_url)
async def new_event_chat(message: Message, state: FSMContext):
    chat_url = DEFAULT_CHAT_URL if message.text.strip() == "-" else message.text.strip()
    await state.update_data(chat_url=chat_url)
    await message.answer(
        "Введите ссылку на канал сообщества.\n\n"
        "Можно отправить '-' чтобы использовать канал по умолчанию."
    )
    await state.set_state(NewEvent.channel_url)


@dp.message(NewEvent.channel_url)
async def new_event_channel(message: Message, state: FSMContext):
    channel_url = DEFAULT_CHANNEL_URL if message.text.strip() == "-" else message.text.strip()
    await state.update_data(channel_url=channel_url)

    data = await state.get_data()
    preview = (
        f"Проверьте мероприятие:\n\n"
        f"<b>{data['title']}</b>\n"
        f"📅 {data['date']}\n"
        f"🕕 {data['time']}\n\n"
        f"{data['description']}\n\n"
        f"Чат: {data['chat_url']}\n"
        f"Канал: {data['channel_url']}\n\n"
        f"Сохранить? Напишите <b>да</b> или <b>нет</b>."
    )
    await message.answer(preview, parse_mode="HTML")
    await state.set_state(NewEvent.confirm)


@dp.message(NewEvent.confirm)
async def new_event_confirm(message: Message, state: FSMContext):
    answer = message.text.strip().lower()
    if answer not in ["да", "yes", "y"]:
        await message.answer("Создание мероприятия отменено.")
        await state.clear()
        return

    data = await state.get_data()
    events = load_events()
    event_id = make_event_id(data["title"])
    while event_id in events:
        event_id = make_event_id(data["title"])

    events[event_id] = {
        "title": data["title"],
        "date": data["date"],
        "time": data["time"],
        "description": data["description"],
        "chat_url": data["chat_url"],
        "channel_url": data["channel_url"],
        "created_at": now_str(),
        "is_active": True,
    }
    save_events(events)

    await message.answer(
        f"✅ Мероприятие создано!\n\n"
        f"<b>{data['title']}</b>\n\n"
        f"🔗 Ссылка на регистрацию:\n{event_link(event_id)}",
        parse_mode="HTML",
    )
    await state.clear()


@dp.message(Command("events"))
async def events_command(message: Message):
    if not is_admin(message):
        await message.answer("У вас нет доступа к этой команде.")
        return
    await message.answer(events_list_text(load_events()), parse_mode="HTML")


@dp.message(Command("link"))
async def link_command(message: Message):
    if not is_admin(message):
        await message.answer("У вас нет доступа к этой команде.")
        return
    events = load_events()
    if not events:
        await message.answer("Пока нет мероприятий.")
        return
    event_id = list(events.keys())[-1]
    await message.answer(f"🔗 Ссылка на регистрацию:\n\n{event_link(event_id)}")


@dp.message(Command("participants"))
async def participants(message: Message):
    if not is_admin(message):
        await message.answer("У вас нет доступа к этой команде.")
        return

    parts = message.text.split(maxsplit=1)
    event_filter = parts[1].strip() if len(parts) > 1 else None
    registrations = load_registrations()

    if event_filter:
        registrations = [r for r in registrations if r.get("event_id") == event_filter]

    if not registrations:
        await message.answer("Пока нет регистраций.")
        return

    text = "👥 <b>Участники</b>\n\n"
    for i, user in enumerate(registrations, start=1):
        username = user.get("telegram_username") or "—"
        text += (
            f"{i}. <b>{user.get('name', '—')}</b>\n"
            f"Мероприятие: {user.get('event_title', '—')}\n"
            f"Телефон: {user.get('phone', '—')}\n"
            f"Сфера: {user.get('sphere', '—')}\n"
            f"Telegram: @{username}\n\n"
        )
        if len(text) > 3500:
            await message.answer(text, parse_mode="HTML")
            text = ""
    if text:
        await message.answer(text, parse_mode="HTML")


@dp.message(Command("summary"))
async def manual_summary(message: Message):
    if not is_admin(message):
        await message.answer("У вас нет доступа к этой команде.")
        return
    text = build_summary_text(hours=3, force=True)
    await message.answer(text, parse_mode="HTML")


# ---------- Summary job ----------

def build_summary_text(hours: int = 3, force: bool = False) -> str:
    events = load_events()
    registrations = load_registrations()
    state = load_summary_state()

    last_summary_at = parse_dt(state.get("last_summary_at"))
    if last_summary_at is None:
        # On first launch do not summarize the entire old history.
        last_summary_at = now_moscow()

    grouped: dict[str, list[dict]] = {}
    for reg in registrations:
        registered_at = parse_dt(reg.get("registered_at"))
        if registered_at is None:
            continue
        if force or registered_at > last_summary_at:
            grouped.setdefault(reg.get("event_id", "unknown"), []).append(reg)

    if not grouped:
        return "📊 За последние 3 часа новых регистраций не было."

    text = f"📊 <b>Сводка за последние {hours} часа</b>\n\n"
    for event_id, items in grouped.items():
        event = events.get(event_id, {})
        total = count_event_registrations(event_id)
        text += (
            f"📅 <b>{event.get('title') or items[0].get('event_title', event_id)}</b>\n"
            f"➕ Новых регистраций: <b>{len(items)}</b>\n"
            f"👥 Всего на мероприятие: <b>{total}</b>\n"
            f"\nПоследние:\n"
        )
        for i, reg in enumerate(items[-5:], start=1):
            text += f"{i}. {reg.get('name', '—')} — {reg.get('sphere', '—')}\n"
        text += "\n"
    return text.strip()


async def send_3_hour_summary():
    state = load_summary_state()
    text = build_summary_text(hours=3, force=False)

    # Do not send empty summaries.
    if "новых регистраций не было" not in text:
        await send_to_admins(text)

    state["last_summary_at"] = now_str()
    save_summary_state(state)


async def main():
    # Initialize summary timestamp to avoid sending all old registrations on first start.
    state = load_summary_state()
    if "last_summary_at" not in state:
        state["last_summary_at"] = now_str()
        save_summary_state(state)

    scheduler.add_job(send_3_hour_summary, IntervalTrigger(hours=3), id="summary_3h", replace_existing=True)
    scheduler.start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

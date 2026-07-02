import asyncio
import os
import sqlite3
from datetime import datetime, timedelta
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from apscheduler.schedulers.asyncio import AsyncIOScheduler

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
DB_PATH = "bot.db"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден. Добавь его в переменные окружения.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

class Registration(StatesGroup):
    name = State()
    phone = State()

class EventCreate(StatesGroup):
    title = State()
    date = State()
    time = State()
    place = State()
    description = State()


def db():
    return sqlite3.connect(DB_PATH)


def init_db():
    con = db()
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            place TEXT NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(event_id, user_id)
        )
    """)
    con.commit()
    con.close()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🗓 Зарегистрироваться")], [KeyboardButton(text="📍 Ближайшие мероприятия")]],
        resize_keyboard=True
    )


def phone_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить телефон", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )


def events_keyboard(prefix="event"):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT id, title, date, time FROM events ORDER BY date, time")
    events = cur.fetchall()
    con.close()

    if not events:
        return None

    buttons = []
    for event_id, title, date, time in events:
        buttons.append([InlineKeyboardButton(text=f"{date} {time} — {title}", callback_data=f"{prefix}:{event_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Добро пожаловать в ВСЕСВОИ\n\nЗдесь можно зарегистрироваться на мероприятия и получить напоминание заранее.",
        reply_markup=main_menu()
    )


@dp.message(Command("admin"))
async def admin(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Эта команда доступна только администратору.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать мероприятие", callback_data="admin:create_event")],
        [InlineKeyboardButton(text="👥 Список регистраций", callback_data="admin:list_events")]
    ])
    await message.answer("Админ-панель:", reply_markup=kb)


@dp.callback_query(F.data == "admin:create_event")
async def create_event_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(EventCreate.title)
    await callback.message.answer("Название мероприятия?")
    await callback.answer()


@dp.message(EventCreate.title)
async def create_event_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(EventCreate.date)
    await message.answer("Дата? Например: 10.07.2026")


@dp.message(EventCreate.date)
async def create_event_date(message: Message, state: FSMContext):
    await state.update_data(date=message.text.strip())
    await state.set_state(EventCreate.time)
    await message.answer("Время? Например: 18:00")


@dp.message(EventCreate.time)
async def create_event_time(message: Message, state: FSMContext):
    await state.update_data(time=message.text.strip())
    await state.set_state(EventCreate.place)
    await message.answer("Место / адрес?")


@dp.message(EventCreate.place)
async def create_event_place(message: Message, state: FSMContext):
    await state.update_data(place=message.text.strip())
    await state.set_state(EventCreate.description)
    await message.answer("Описание мероприятия? Можно коротко. Если не нужно — напиши: -")


@dp.message(EventCreate.description)
async def create_event_finish(message: Message, state: FSMContext):
    data = await state.get_data()
    description = "" if message.text.strip() == "-" else message.text.strip()
    con = db()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO events(title, date, time, place, description, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (data["title"], data["date"], data["time"], data["place"], description, datetime.now().isoformat())
    )
    event_id = cur.lastrowid
    con.commit()
    con.close()
    await state.clear()
    await message.answer(
        f"✅ Мероприятие создано.\n\nID: {event_id}\nНазвание: {data['title']}\nДата: {data['date']} {data['time']}\nМесто: {data['place']}\n\nТеперь участники смогут зарегистрироваться через кнопку «Зарегистрироваться»."
    )


@dp.message(F.text == "🗓 Зарегистрироваться")
async def choose_event(message: Message):
    kb = events_keyboard("register")
    if not kb:
        await message.answer("Пока нет активных мероприятий. Скоро добавим ❤️")
        return
    await message.answer("Выбери мероприятие:", reply_markup=kb)


@dp.message(F.text == "📍 Ближайшие мероприятия")
async def list_events(message: Message):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT title, date, time, place, description FROM events ORDER BY date, time")
    events = cur.fetchall()
    con.close()
    if not events:
        await message.answer("Пока нет активных мероприятий.")
        return
    text = "📍 Ближайшие мероприятия:\n\n"
    for title, date, time, place, description in events:
        text += f"— {title}\n{date} в {time}\n{place}\n"
        if description:
            text += f"{description}\n"
        text += "\n"
    await message.answer(text)


@dp.callback_query(F.data.startswith("register:"))
async def register_event(callback: CallbackQuery, state: FSMContext):
    event_id = int(callback.data.split(":")[1])
    await state.update_data(event_id=event_id)
    await state.set_state(Registration.name)
    await callback.message.answer("Как вас зовут?")
    await callback.answer()


@dp.message(Registration.name)
async def get_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(Registration.phone)
    await message.answer("Оставьте телефон для связи:", reply_markup=phone_keyboard())


@dp.message(Registration.phone)
async def get_phone(message: Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else message.text.strip()
    data = await state.get_data()
    event_id = data["event_id"]
    name = data["name"]
    username = message.from_user.username or ""

    con = db()
    cur = con.cursor()
    try:
        cur.execute(
            "INSERT INTO registrations(event_id, user_id, username, name, phone, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, message.from_user.id, username, name, phone, datetime.now().isoformat())
        )
        con.commit()
    except sqlite3.IntegrityError:
        await message.answer("Вы уже зарегистрированы на это мероприятие ❤️", reply_markup=main_menu())
        con.close()
        await state.clear()
        return

    cur.execute("SELECT title, date, time, place FROM events WHERE id=?", (event_id,))
    event = cur.fetchone()
    con.close()
    await state.clear()

    title, date, time, place = event
    await message.answer(
        f"✅ Вы зарегистрированы!\n\n{title}\n{date} в {time}\n{place}\n\nМы напомним вам заранее.",
        reply_markup=main_menu()
    )


@dp.callback_query(F.data == "admin:list_events")
async def admin_list_events(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    kb = events_keyboard("admin_regs")
    if not kb:
        await callback.message.answer("Пока нет мероприятий.")
    else:
        await callback.message.answer("Выбери мероприятие, чтобы посмотреть регистрации:", reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_regs:"))
async def admin_regs(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    event_id = int(callback.data.split(":")[1])
    con = db()
    cur = con.cursor()
    cur.execute("SELECT title FROM events WHERE id=?", (event_id,))
    event = cur.fetchone()
    cur.execute("SELECT name, phone, username, created_at FROM registrations WHERE event_id=? ORDER BY id", (event_id,))
    regs = cur.fetchall()
    con.close()
    if not regs:
        await callback.message.answer("Пока нет регистраций.")
    else:
        text = f"👥 Регистрации: {event[0]}\nВсего: {len(regs)}\n\n"
        for i, (name, phone, username, created_at) in enumerate(regs, 1):
            user = f"@{username}" if username else "без username"
            text += f"{i}. {name} — {phone} — {user}\n"
        await callback.message.answer(text[:4000])
    await callback.answer()


async def send_reminders():
    # Простая проверка раз в 10 минут. Работает для дат в формате ДД.ММ.ГГГГ и времени ЧЧ:ММ.
    now = datetime.now()
    con = db()
    cur = con.cursor()
    cur.execute("SELECT id, title, date, time, place FROM events")
    events = cur.fetchall()

    for event_id, title, date_str, time_str, place in events:
        try:
            event_dt = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M")
        except ValueError:
            continue
        delta = event_dt - now
        minutes_left = int(delta.total_seconds() // 60)
        if minutes_left in [1440, 180, 60]:
            cur.execute("SELECT user_id FROM registrations WHERE event_id=?", (event_id,))
            users = cur.fetchall()
            for (user_id,) in users:
                try:
                    await bot.send_message(
                        user_id,
                        f"⏰ Напоминание\n\n{title}\n{date_str} в {time_str}\n{place}\n\nДо встречи на мероприятии ❤️"
                    )
                except Exception:
                    pass
    con.close()


async def main():
    init_db()
    scheduler.add_job(send_reminders, "interval", minutes=10)
    scheduler.start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

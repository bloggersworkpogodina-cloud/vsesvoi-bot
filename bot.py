import os
import json
import asyncio

import psycopg2
from psycopg2.extras import Json
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
BOT_USERNAME = os.getenv("BOT_USERNAME", "vsesvoi_event_business_bot")
DATABASE_URL = os.getenv("DATABASE_URL")

DATA_FILE = "data.json"
DOC_VERSION = "1.0"
TZ = ZoneInfo("Europe/Moscow")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")


def now_str():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def empty_data():
    return {"events": {}, "registrations": [], "consents": [], "deleted": []}


def normalize_data(data):
    if not isinstance(data, dict):
        data = empty_data()
    data.setdefault("events", {})
    data.setdefault("registrations", [])
    data.setdefault("consents", [])
    data.setdefault("deleted", [])
    return data


def pg_connect():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    if not DATABASE_URL:
        return
    with pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS app_state (
                    id INTEGER PRIMARY KEY,
                    data JSONB NOT NULL,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("SELECT data FROM app_state WHERE id = 1")
            row = cur.fetchone()
            if row is None:
                initial = empty_data()
                # Если рядом случайно остался старый data.json — переносим его в Postgres один раз.
                if os.path.exists(DATA_FILE):
                    try:
                        with open(DATA_FILE, "r", encoding="utf-8") as f:
                            initial = normalize_data(json.load(f))
                    except Exception:
                        initial = empty_data()
                cur.execute(
                    "INSERT INTO app_state (id, data) VALUES (1, %s)",
                    (Json(initial),),
                )
        conn.commit()


def load_data():
    if DATABASE_URL:
        try:
            with pg_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT data FROM app_state WHERE id = 1")
                    row = cur.fetchone()
                    if row and row[0]:
                        return normalize_data(row[0])
        except Exception as e:
            print(f"PostgreSQL load error: {e}")
    # Резервный режим без PostgreSQL. Для продакшена нужен DATABASE_URL.
    if not os.path.exists(DATA_FILE):
        return empty_data()
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return normalize_data(json.load(f))


def save_data(data):
    data = normalize_data(data)
    if DATABASE_URL:
        try:
            with pg_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO app_state (id, data, updated_at)
                        VALUES (1, %s, NOW())
                        ON CONFLICT (id)
                        DO UPDATE SET data = EXCLUDED.data, updated_at = NOW()
                        """,
                        (Json(data),),
                    )
                conn.commit()
            return
        except Exception as e:
            print(f"PostgreSQL save error: {e}")
    # Резервный режим без PostgreSQL.
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def event_link(event_id: str) -> str:
    return f"https://t.me/{BOT_USERNAME}?start={event_id}"


def event_regs(data, event_id):
    return [r for r in data["registrations"] if r.get("event_id") == event_id]


def main_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="📅 Мероприятия", callback_data="crm:events")
    kb.button(text="📢 Рассылки", callback_data="crm:broadcasts")
    kb.button(text="📊 Аналитика", callback_data="crm:analytics")
    kb.button(text="⚙️ Система", callback_data="crm:system")
    kb.adjust(1)
    return kb.as_markup()


def events_kb(data):
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Создать мероприятие", callback_data="event:new")
    active_events = [(eid, e) for eid, e in data["events"].items() if e.get("status", "open") != "archived"]
    for eid, e in active_events:
        count = len(event_regs(data, eid))
        kb.button(text=f"🟢 {e.get('title','Без названия')} • 👥 {count}", callback_data=f"event:view:{eid}")
    kb.button(text="📂 Архив", callback_data="events:archive")
    kb.button(text="🏠 Главная", callback_data="crm:home")
    kb.adjust(1)
    return kb.as_markup()


def event_card_text(data, event_id):
    event = data["events"].get(event_id)
    if not event:
        return "Мероприятие не найдено."
    count = len(event_regs(data, event_id))
    status = event.get("status", "open")
    status_text = {
        "open": "🟢 Регистрация открыта",
        "paused": "🟡 Регистрация приостановлена",
        "closed": "🔴 Регистрация закрыта",
        "archived": "⚫️ В архиве",
    }.get(status, "🟢 Регистрация открыта")
    return (
        f"📅 <b>{event.get('title','Без названия')}</b>\n\n"
        f"📆 {event.get('date','—')}\n"
        f"🕕 {event.get('time','—')}\n\n"
        f"{status_text}\n\n"
        f"👥 Зарегистрировано: <b>{count}</b>"
    )


def event_card_kb(event_id):
    kb = InlineKeyboardBuilder()
    kb.button(text="👥 Участники", callback_data=f"event:participants:{event_id}")
    kb.button(text="📢 Рассылка", callback_data=f"event:broadcast:{event_id}")
    kb.button(text="⚙️ Управление", callback_data=f"event:manage:{event_id}")
    kb.button(text="⬅️ Назад", callback_data="crm:events")
    kb.button(text="🏠 Главная", callback_data="crm:home")
    kb.adjust(1)
    return kb.as_markup()


def manage_kb(event_id):
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Изменить", callback_data=f"manage:edit:{event_id}")
    kb.button(text="🖼 Афиша", callback_data=f"manage:poster:{event_id}")
    kb.button(text="🔗 Ссылка регистрации", callback_data=f"manage:link:{event_id}")
    kb.button(text="🟢 Статус регистрации", callback_data=f"manage:status:{event_id}")
    kb.button(text="📋 Дублировать", callback_data=f"manage:duplicate:{event_id}")
    kb.button(text="🗄 Архивировать", callback_data=f"manage:archive:{event_id}")
    kb.button(text="⬅️ Назад", callback_data=f"event:view:{event_id}")
    kb.button(text="🏠 Главная", callback_data="crm:home")
    kb.adjust(1)
    return kb.as_markup()


def docs_kb(event_id):
    kb = InlineKeyboardBuilder()
    kb.button(text="📄 Пользовательское соглашение", callback_data="doc:agreement")
    kb.button(text="📄 Политика обработки ПД", callback_data="doc:policy")
    kb.button(text="📄 Согласие на обработку ПД", callback_data="doc:consent_pd")
    kb.button(text="📄 Согласие на инфо и рекламные сообщения", callback_data="doc:consent_news")
    kb.button(text="✅ Ознакомился и принимаю условия", callback_data=f"legal:accept:{event_id}")
    kb.adjust(1)
    return kb.as_markup()


DOCS = {
    "policy": """📄 <b>Политика обработки персональных данных</b>\n\nВерсия 1.0\n\nОператор: ИП Погодина Анастасия Александровна\nИНН: 526333028306\nE-mail: pogodinabrand@ya.ru\n\nМы обрабатываем: имя, фамилию, телефон, сферу деятельности, город, Telegram ID, username, дату регистрации и факт принятия документов.\n\nДанные используются для регистрации на мероприятия, связи с участниками, напоминаний, организационной информации, внутреннего учета и статистики.\n\nУдаление данных: команда /delete_me или письмо на pogodinabrand@ya.ru.""",
    "agreement": """📄 <b>Пользовательское соглашение</b>\n\nВерсия 1.0\n\nБот сообщества «Все свои» предназначен для регистрации на мероприятия, получения информации о мероприятиях и организационных уведомлений.\n\nПользователь обязуется предоставлять достоверные данные, соблюдать правила сообщества и не использовать бот в противоправных целях.\n\nОрганизатор вправе изменять информацию о мероприятиях, переносить или отменять мероприятия, а также ограничивать доступ при нарушении правил.""",
    "consent_pd": """📄 <b>Согласие на обработку персональных данных</b>\n\nВерсия 1.0\n\nНажимая кнопку «Ознакомился и принимаю условия», пользователь дает согласие ИП Погодиной Анастасии Александровне на обработку персональных данных для регистрации на мероприятия, связи, напоминаний и учета участников.\n\nСогласие действует до достижения целей обработки или до отзыва через /delete_me либо email: pogodinabrand@ya.ru.""",
    "consent_news": """📄 <b>Согласие на получение информационных и рекламных сообщений</b>\n\nВерсия 1.0\n\nПользователь соглашается получать через Telegram-бот информацию о мероприятиях, напоминания, уведомления об изменениях, новости, анонсы и приглашения сообщества «Все свои».\n\nОтказ возможен через обращение на email: pogodinabrand@ya.ru.""",
}


class Register(StatesGroup):
    first_name = State()
    last_name = State()
    phone = State()
    sphere = State()
    city = State()


class NewEvent(StatesGroup):
    title = State()
    date = State()
    time = State()
    description = State()
    chat_url = State()
    channel_url = State()


class Broadcast(StatesGroup):
    all_text = State()
    event_text = State()


def admin_reply_kb():
    keyboard = [
        [KeyboardButton(text="🏠 Главная"), KeyboardButton(text="📅 Мероприятия")],
        [KeyboardButton(text="📢 Рассылки"), KeyboardButton(text="📊 Аналитика")],
        [KeyboardButton(text="⚙️ Система")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


async def send_home(message_or_query):
    data = load_data()
    active_count = len([e for e in data["events"].values() if e.get("status", "open") != "archived"])
    total_regs = len(data["registrations"])
    text = (
        "🏠 <b>Все свои CRM</b>\n\n"
        "Выберите раздел:\n\n"
        f"📅 Активных мероприятий: <b>{active_count}</b>\n"
        f"👥 Всего регистраций: <b>{total_regs}</b>"
    )
    if isinstance(message_or_query, CallbackQuery):
        await message_or_query.message.answer(text, parse_mode="HTML", reply_markup=main_menu_kb())
        await message_or_query.answer()
    else:
        await message_or_query.answer(text, parse_mode="HTML", reply_markup=admin_reply_kb())
        await message_or_query.answer("CRM-меню:", reply_markup=main_menu_kb())


@dp.message(Command("admin"))
@dp.message(Command("menu"))
async def admin(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("У вас нет доступа.")
    await send_home(message)


@dp.message(F.text.in_(["🏠 Главная", "📅 Мероприятия", "📢 Рассылки", "📊 Аналитика", "⚙️ Система"]))
async def reply_menu(message: Message):
    if not is_admin(message.from_user.id):
        return
    if message.text == "🏠 Главная":
        return await send_home(message)
    if message.text == "📅 Мероприятия":
        data = load_data()
        return await message.answer("📅 <b>Мероприятия</b>", parse_mode="HTML", reply_markup=events_kb(data))
    if message.text == "📢 Рассылки":
        return await show_broadcasts(message)
    if message.text == "📊 Аналитика":
        return await show_analytics(message)
    if message.text == "⚙️ Система":
        return await show_system(message)


@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    args = message.text.split(maxsplit=1)
    if len(args) == 1:
        if is_admin(message.from_user.id):
            return await send_home(message)
        return await message.answer("Добро пожаловать! Для регистрации используйте ссылку на конкретное мероприятие.")

    event_id = args[1]
    data = load_data()
    event = data["events"].get(event_id)
    if not event:
        return await message.answer("Мероприятие не найдено. Проверьте ссылку.")
    if event.get("status") in ["closed", "paused", "archived"]:
        return await message.answer("Регистрация на это мероприятие сейчас закрыта.")

    await state.update_data(event_id=event_id)
    await message.answer(
        "🤍 <b>Добро пожаловать!</b>\n\n"
        "Для регистрации ознакомьтесь с документами.\n\n"
        "Мы бережно относимся к вашим персональным данным и используем их только для организации мероприятий сообщества «Все свои».\n\n"
        "Нажимая кнопку «Ознакомился и принимаю условия», вы подтверждаете, что ознакомились со всеми указанными документами и принимаете их условия.",
        parse_mode="HTML",
        reply_markup=docs_kb(event_id),
    )


@dp.callback_query(F.data.startswith("doc:"))
async def show_doc(call: CallbackQuery):
    doc_key = call.data.split(":", 1)[1]
    await call.message.answer(DOCS.get(doc_key, "Документ не найден."), parse_mode="HTML")
    await call.answer()


@dp.callback_query(F.data.startswith("legal:accept:"))
async def accept_legal(call: CallbackQuery, state: FSMContext):
    event_id = call.data.split(":", 2)[2]
    data = load_data()
    data["consents"].append({
        "telegram_id": call.from_user.id,
        "telegram_username": call.from_user.username,
        "event_id": event_id,
        "documents_version": DOC_VERSION,
        "accepted_at": now_str(),
    })
    save_data(data)
    await state.update_data(event_id=event_id)
    await call.message.answer("Введите ваше имя:")
    await state.set_state(Register.first_name)
    await call.answer()


@dp.message(Register.first_name)
async def reg_first_name(message: Message, state: FSMContext):
    await state.update_data(first_name=message.text.strip())
    await message.answer("Введите вашу фамилию:")
    await state.set_state(Register.last_name)


@dp.message(Register.last_name)
async def reg_last_name(message: Message, state: FSMContext):
    await state.update_data(last_name=message.text.strip())
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поделиться номером", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer("Отправьте номер телефона:", reply_markup=kb)
    await state.set_state(Register.phone)


@dp.message(Register.phone)
async def reg_phone(message: Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else message.text.strip()
    await state.update_data(phone=phone)
    await message.answer("Чем вы занимаетесь?", reply_markup=ReplyKeyboardRemove())
    await state.set_state(Register.sphere)


@dp.message(Register.sphere)
async def reg_sphere(message: Message, state: FSMContext):
    await state.update_data(sphere=message.text.strip())
    await message.answer("Из какого вы города?")
    await state.set_state(Register.city)


@dp.message(Register.city)
async def reg_city(message: Message, state: FSMContext):
    st = await state.get_data()
    data = load_data()
    event = data["events"].get(st["event_id"], {})
    registration = {
        "event_id": st["event_id"],
        "event_title": event.get("title", ""),
        "first_name": st["first_name"],
        "last_name": st["last_name"],
        "phone": st["phone"],
        "sphere": st["sphere"],
        "city": message.text.strip(),
        "telegram_id": message.from_user.id,
        "telegram_username": message.from_user.username,
        "registered_at": now_str(),
        "documents_version": DOC_VERSION,
    }
    data["registrations"].append(registration)
    save_data(data)
    count = len(event_regs(data, st["event_id"]))

    kb = InlineKeyboardBuilder()
    if event.get("chat_url"):
        kb.button(text="💬 Чат участников", url=event["chat_url"])
    if event.get("channel_url"):
        kb.button(text="📢 Канал сообщества", url=event["channel_url"])
    kb.adjust(1)

    await message.answer(
        f"🎉 <b>Регистрация подтверждена!</b>\n\n"
        f"Вы записаны на:\n\n<b>{event.get('title','Мероприятие')}</b>\n\n"
        f"📅 <b>{event.get('date','—')}</b>\n"
        f"🕕 <b>{event.get('time','—')}</b>\n\n"
        "До встречи на мероприятии! 🚀",
        parse_mode="HTML",
        reply_markup=kb.as_markup() if kb.buttons else None,
    )

    admin_text = (
        "🔥 <b>Новая регистрация</b>\n\n"
        f"👤 {registration['first_name']} {registration['last_name']}\n"
        f"📱 {registration['phone']}\n"
        f"💼 {registration['sphere']}\n"
        f"🌍 {registration['city']}\n"
        f"📅 {event.get('title','')}\n\n"
        f"👥 Всего регистраций: <b>{count}</b>"
    )
    for admin_id in ADMIN_IDS:
        await bot.send_message(admin_id, admin_text, parse_mode="HTML")
        if count % 10 == 0:
            await bot.send_message(admin_id, f"🎊 Уже <b>{count}</b> регистраций на мероприятие «{event.get('title','')}»!", parse_mode="HTML")
    await state.clear()


@dp.callback_query(F.data == "crm:home")
async def cb_home(call: CallbackQuery):
    await send_home(call)


@dp.callback_query(F.data == "crm:events")
async def cb_events(call: CallbackQuery):
    data = load_data()
    await call.message.answer("📅 <b>Мероприятия</b>", parse_mode="HTML", reply_markup=events_kb(data))
    await call.answer()


@dp.callback_query(F.data == "event:new")
async def cb_new_event(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа")
    await call.message.answer("Введите название мероприятия:")
    await state.set_state(NewEvent.title)
    await call.answer()


@dp.message(NewEvent.title)
async def new_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await message.answer("Введите дату мероприятия:")
    await state.set_state(NewEvent.date)


@dp.message(NewEvent.date)
async def new_date(message: Message, state: FSMContext):
    await state.update_data(date=message.text.strip())
    await message.answer("Введите время мероприятия:")
    await state.set_state(NewEvent.time)


@dp.message(NewEvent.time)
async def new_time(message: Message, state: FSMContext):
    await state.update_data(time=message.text.strip())
    await message.answer("Введите короткое описание:")
    await state.set_state(NewEvent.description)


@dp.message(NewEvent.description)
async def new_desc(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await message.answer("Ссылка на чат участников. Если нет — напишите -")
    await state.set_state(NewEvent.chat_url)


@dp.message(NewEvent.chat_url)
async def new_chat(message: Message, state: FSMContext):
    await state.update_data(chat_url="" if message.text.strip() == "-" else message.text.strip())
    await message.answer("Ссылка на канал сообщества. Если нет — напишите -")
    await state.set_state(NewEvent.channel_url)


@dp.message(NewEvent.channel_url)
async def new_channel(message: Message, state: FSMContext):
    st = await state.get_data()
    data = load_data()
    base = st["title"].lower().replace(" ", "_")[:20]
    safe = "".join(ch for ch in base if ch.isalnum() or ch == "_") or "event"
    event_id = f"{safe}_{int(datetime.now(TZ).timestamp())}"
    data["events"][event_id] = {
        "title": st["title"],
        "date": st["date"],
        "time": st["time"],
        "description": st["description"],
        "chat_url": st.get("chat_url", ""),
        "channel_url": "" if message.text.strip() == "-" else message.text.strip(),
        "status": "open",
        "created_at": now_str(),
    }
    save_data(data)
    await message.answer(
        f"✅ <b>Мероприятие создано</b>\n\n"
        f"📅 {st['title']}\n\n"
        f"🔗 Ссылка регистрации:\n{event_link(event_id)}",
        parse_mode="HTML",
    )
    await message.answer(event_card_text(data, event_id), parse_mode="HTML", reply_markup=event_card_kb(event_id))
    await state.clear()


@dp.callback_query(F.data.startswith("event:view:"))
async def cb_event_view(call: CallbackQuery):
    event_id = call.data.split(":", 2)[2]
    data = load_data()
    await call.message.answer(event_card_text(data, event_id), parse_mode="HTML", reply_markup=event_card_kb(event_id))
    await call.answer()


@dp.callback_query(F.data.startswith("event:participants:"))
async def cb_participants(call: CallbackQuery):
    event_id = call.data.split(":", 2)[2]
    data = load_data()
    regs = event_regs(data, event_id)
    if not regs:
        text = "👥 Пока нет участников."
    else:
        lines = [f"👥 <b>{len(regs)} участников</b>\n"]
        for i, r in enumerate(regs[:30], 1):
            lines.append(f"{i}. {r.get('first_name','')} {r.get('last_name','')}\n{r.get('sphere','')} • {r.get('city','')}")
        if len(regs) > 30:
            lines.append("\nПоказаны первые 30 участников.")
        text = "\n\n".join(lines)
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data=f"event:view:{event_id}")
    kb.button(text="🏠 Главная", callback_data="crm:home")
    kb.adjust(1)
    await call.message.answer(text, parse_mode="HTML", reply_markup=kb.as_markup())
    await call.answer()


@dp.callback_query(F.data.startswith("event:manage:"))
async def cb_manage(call: CallbackQuery):
    event_id = call.data.split(":", 2)[2]
    await call.message.answer("⚙️ <b>Управление мероприятием</b>", parse_mode="HTML", reply_markup=manage_kb(event_id))
    await call.answer()


@dp.callback_query(F.data.startswith("manage:link:"))
async def cb_link(call: CallbackQuery):
    event_id = call.data.split(":", 2)[2]
    await call.message.answer(f"🔗 <b>Ссылка регистрации</b>\n\n{event_link(event_id)}", parse_mode="HTML")
    await call.answer()


@dp.callback_query(F.data.startswith("manage:status:"))
async def cb_status(call: CallbackQuery):
    event_id = call.data.split(":", 2)[2]
    kb = InlineKeyboardBuilder()
    kb.button(text="🟢 Открыта", callback_data=f"status:set:{event_id}:open")
    kb.button(text="🟡 Приостановлена", callback_data=f"status:set:{event_id}:paused")
    kb.button(text="🔴 Закрыта", callback_data=f"status:set:{event_id}:closed")
    kb.button(text="⬅️ Назад", callback_data=f"event:manage:{event_id}")
    kb.adjust(1)
    await call.message.answer("Выберите статус регистрации:", reply_markup=kb.as_markup())
    await call.answer()


@dp.callback_query(F.data.startswith("status:set:"))
async def cb_set_status(call: CallbackQuery):
    _, _, event_id, status = call.data.split(":", 3)
    data = load_data()
    if event_id in data["events"]:
        data["events"][event_id]["status"] = status
        save_data(data)
    await call.message.answer("Статус обновлен.")
    await call.message.answer(event_card_text(data, event_id), parse_mode="HTML", reply_markup=event_card_kb(event_id))
    await call.answer()


@dp.callback_query(F.data.startswith("manage:archive:"))
async def cb_archive(call: CallbackQuery):
    event_id = call.data.split(":", 2)[2]
    data = load_data()
    if event_id in data["events"]:
        data["events"][event_id]["status"] = "archived"
        save_data(data)
    await call.message.answer("🗄 Мероприятие отправлено в архив.")
    await call.answer()


@dp.callback_query(F.data.startswith("manage:duplicate:"))
async def cb_duplicate(call: CallbackQuery):
    event_id = call.data.split(":", 2)[2]
    data = load_data()
    event = data["events"].get(event_id)
    if not event:
        return await call.answer("Не найдено")
    new_id = f"copy_{event_id}_{int(datetime.now(TZ).timestamp())}"
    new_event = event.copy()
    new_event["title"] = event.get("title", "") + " — копия"
    new_event["created_at"] = now_str()
    new_event["status"] = "open"
    data["events"][new_id] = new_event
    save_data(data)
    await call.message.answer(f"📋 Дубликат создан.\n\n🔗 {event_link(new_id)}")
    await call.answer()


@dp.callback_query(F.data.startswith("manage:edit:"))
@dp.callback_query(F.data.startswith("manage:poster:"))
async def cb_stub(call: CallbackQuery):
    await call.message.answer("Функция будет добавлена в следующем обновлении.")
    await call.answer()


@dp.callback_query(F.data == "crm:broadcasts")
async def cb_broadcasts(call: CallbackQuery):
    await show_broadcasts(call.message)
    await call.answer()


async def show_broadcasts(message: Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="👥 Всем пользователям", callback_data="broadcast:all")
    kb.button(text="⬅️ Назад", callback_data="crm:home")
    kb.adjust(1)
    await message.answer("📢 <b>Рассылки</b>", parse_mode="HTML", reply_markup=kb.as_markup())


@dp.callback_query(F.data == "broadcast:all")
async def cb_broadcast_all(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Введите сообщение, которое нужно отправить всем пользователям, давшим согласие на получение информационных и рекламных сообщений.")
    await state.set_state(Broadcast.all_text)
    await call.answer()


@dp.message(Broadcast.all_text)
async def send_all_broadcast(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = load_data()
    user_ids = sorted({r["telegram_id"] for r in data["registrations"]})
    ok = 0
    fail = 0
    for uid in user_ids:
        try:
            await bot.send_message(uid, message.text)
            ok += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail += 1
    await message.answer(f"✅ Рассылка завершена\n\nПолучателей: {len(user_ids)}\nДоставлено: {ok}\nОшибки: {fail}")
    await state.clear()


@dp.callback_query(F.data.startswith("event:broadcast:"))
async def cb_event_broadcast(call: CallbackQuery, state: FSMContext):
    event_id = call.data.split(":", 2)[2]
    await state.update_data(event_broadcast_id=event_id)
    await call.message.answer("Введите сообщение для участников этого мероприятия:")
    await state.set_state(Broadcast.event_text)
    await call.answer()


@dp.message(Broadcast.event_text)
async def send_event_broadcast(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    st = await state.get_data()
    event_id = st["event_broadcast_id"]
    data = load_data()
    regs = event_regs(data, event_id)
    user_ids = sorted({r["telegram_id"] for r in regs})
    ok = 0
    fail = 0
    for uid in user_ids:
        try:
            await bot.send_message(uid, message.text)
            ok += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail += 1
    await message.answer(f"✅ Рассылка по мероприятию завершена\n\nПолучателей: {len(user_ids)}\nДоставлено: {ok}\nОшибки: {fail}")
    await state.clear()


@dp.callback_query(F.data == "crm:analytics")
async def cb_analytics(call: CallbackQuery):
    await show_analytics(call.message)
    await call.answer()


async def show_analytics(message: Message):
    data = load_data()
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    regs_today = [r for r in data["registrations"] if r.get("registered_at", "").startswith(today)]
    text = (
        "📊 <b>Аналитика</b>\n\n"
        f"📅 Мероприятий: <b>{len(data['events'])}</b>\n"
        f"👥 Всего регистраций: <b>{len(data['registrations'])}</b>\n"
        f"📈 Сегодня: <b>{len(regs_today)}</b>"
    )
    await message.answer(text, parse_mode="HTML")


@dp.callback_query(F.data == "crm:system")
async def cb_system(call: CallbackQuery):
    await show_system(call.message)
    await call.answer()


async def show_system(message: Message):
    await message.answer(
        "⚙️ <b>Система</b>\n\n"
        f"📄 Версия документов: <b>{DOC_VERSION}</b>\n"
        "🤖 Версия CRM: <b>V3.0.2</b>\n"
        f"💾 Хранилище: <b>{'PostgreSQL' if DATABASE_URL else 'JSON fallback'}</b>\n\n"
        "Следующий этап: Google Sheets.",
        parse_mode="HTML",
    )


@dp.message(Command("participants"))
async def participants_cmd(message: Message):
    if not is_admin(message.from_user.id):
        return
    data = load_data()
    await message.answer(f"Всего регистраций: {len(data['registrations'])}")


@dp.message(Command("delete_me"))
async def delete_me(message: Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 Да, удалить мои данные", callback_data="delete:confirm")
    kb.button(text="❌ Отмена", callback_data="delete:cancel")
    kb.adjust(1)
    await message.answer("Вы действительно хотите удалить свои персональные данные?", reply_markup=kb.as_markup())


@dp.callback_query(F.data == "delete:cancel")
async def delete_cancel(call: CallbackQuery):
    await call.message.answer("Удаление отменено.")
    await call.answer()


@dp.callback_query(F.data == "delete:confirm")
async def delete_confirm(call: CallbackQuery):
    data = load_data()
    before = len(data["registrations"])
    data["registrations"] = [r for r in data["registrations"] if r.get("telegram_id") != call.from_user.id]
    data["deleted"].append({
        "telegram_id": call.from_user.id,
        "telegram_username": call.from_user.username,
        "deleted_at": now_str(),
        "removed_registrations": before - len(data["registrations"]),
    })
    save_data(data)
    await call.message.answer("Ваши персональные данные удалены из системы.")
    for admin_id in ADMIN_IDS:
        await bot.send_message(admin_id, f"🗑 Пользователь удалил данные\n\nTelegram ID: {call.from_user.id}\nUsername: @{call.from_user.username}")
    await call.answer()


async def summary_job():
    # Заглушка для будущих сводок. Оставлена, чтобы APScheduler был подключен безопасно.
    return


async def main():
    init_db()
    scheduler.add_job(summary_job, "interval", hours=3)
    scheduler.start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

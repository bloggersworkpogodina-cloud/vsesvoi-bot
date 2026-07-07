import os
import json
import asyncio
import hashlib
from html import escape

import psycopg2
from psycopg2.extras import Json

try:
    import gspread
except Exception:
    gspread = None
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart, StateFilter
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
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") or os.getenv("GOOGLE_CREDENTIALS")

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


def is_safe_token(value: str) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if len(value.encode("utf-8")) > 50:
        return False
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    return all(ch in allowed for ch in value)


def make_link_id(event_id: str) -> str:
    # Telegram deep-link start parameters and callback_data must be short ASCII.
    # Old event IDs could contain Cyrillic/title text, so we create a stable safe alias.
    digest = hashlib.md5(str(event_id).encode("utf-8")).hexdigest()[:10]
    return f"ev_{digest}"


def normalize_data(data):
    if not isinstance(data, dict):
        data = empty_data()
    data.setdefault("events", {})
    data.setdefault("registrations", [])
    data.setdefault("consents", [])
    data.setdefault("deleted", [])

    # Add safe link_id to every event. This fixes old events with Cyrillic/long IDs.
    for event_id, event in list(data["events"].items()):
        if not isinstance(event, dict):
            data["events"][event_id] = event = {}
        current = event.get("link_id")
        if not is_safe_token(current):
            event["link_id"] = event_id if is_safe_token(event_id) else make_link_id(event_id)
    return data


def resolve_event_id(data, token: str):
    if token in data.get("events", {}):
        return token
    for event_id, event in data.get("events", {}).items():
        if event.get("link_id") == token:
            return event_id
    return None


def event_token(data, event_id: str) -> str:
    event = data.get("events", {}).get(event_id, {})
    token = event.get("link_id")
    if is_safe_token(token):
        return token
    return event_id if is_safe_token(event_id) else make_link_id(event_id)


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
                initial = normalize_data(initial)
                cur.execute(
                    "INSERT INTO app_state (id, data) VALUES (1, %s)",
                    (Json(initial),),
                )
            else:
                # One-time safe migration: add link_id to existing events if missing.
                migrated = normalize_data(row[0])
                cur.execute(
                    "UPDATE app_state SET data = %s, updated_at = NOW() WHERE id = 1",
                    (Json(migrated),),
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
            print(f"PostgreSQL load error: {e}", flush=True)
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
            print(f"PostgreSQL save error: {e}", flush=True)
    # Резервный режим без PostgreSQL.
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def google_sheets_enabled() -> bool:
    return bool(GOOGLE_SHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON and gspread)


def normalize_sheet_title(value: str, fallback: str = "Мероприятие") -> str:
    value = (value or fallback).strip() or fallback
    # Google Sheets sheet title cannot contain these characters.
    for ch in [":", "\\", "/", "?", "*", "[", "]"]:
        value = value.replace(ch, " ")
    value = " ".join(value.split())
    return value[:90] or fallback


def get_google_client():
    if not google_sheets_enabled():
        return None
    try:
        creds = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        return gspread.service_account_from_dict(creds)
    except Exception as e:
        print(f"Google Sheets auth error: {e}", flush=True)
        return None


def get_or_create_worksheet(spreadsheet, title: str, headers: list[str]):
    try:
        ws = spreadsheet.worksheet(title)
    except Exception:
        ws = spreadsheet.add_worksheet(title=title, rows=1000, cols=max(10, len(headers)))
    try:
        first_row = ws.row_values(1)
        if first_row != headers:
            if not first_row:
                ws.append_row(headers, value_input_option="USER_ENTERED")
            else:
                ws.update("1:1", [headers])
    except Exception as e:
        print(f"Google Sheets header error: {e}", flush=True)
    return ws


def append_registration_to_sheets(registration: dict, event: dict):
    # Google Sheets is an additional mirror. PostgreSQL remains the main storage.
    if not google_sheets_enabled():
        return False
    client = get_google_client()
    if not client:
        return False
    try:
        spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)
        headers = [
            "Дата регистрации",
            "Мероприятие",
            "Имя",
            "Фамилия",
            "Телефон",
            "Город",
            "Деятельность",
            "Telegram username",
            "Telegram ID",
            "Пригласил Telegram ID",
            "Пригласил username",
            "Реферальная ссылка",
            "Версия документов",
        ]
        username = registration.get("telegram_username") or ""
        username = f"@{username}" if username else ""
        invited_username = registration.get("invited_by_username") or ""
        invited_username = f"@{invited_username}" if invited_username else ""
        row = [
            registration.get("registered_at", ""),
            registration.get("event_title") or event.get("title", ""),
            registration.get("first_name", ""),
            registration.get("last_name", ""),
            registration.get("phone", ""),
            registration.get("city", ""),
            registration.get("sphere", ""),
            username,
            str(registration.get("telegram_id", "")),
            str(registration.get("invited_by_telegram_id", "")),
            invited_username,
            registration.get("referral_link", ""),
            registration.get("documents_version", ""),
        ]

        master = get_or_create_worksheet(spreadsheet, "Все регистрации", headers)
        master.append_row(row, value_input_option="USER_ENTERED")

        event_title = normalize_sheet_title(registration.get("event_title") or event.get("title") or "Мероприятие")
        event_ws = get_or_create_worksheet(spreadsheet, event_title, headers)
        event_ws.append_row(row, value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        print(f"Google Sheets append error: {e}", flush=True)
        return False


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def event_link(event_id: str, data=None) -> str:
    token = event_token(data, event_id) if data else (event_id if is_safe_token(event_id) else make_link_id(event_id))
    return f"https://t.me/{BOT_USERNAME}?start={token}"


def parse_start_payload(payload: str, data: dict):
    """Return (event_id, invited_by_telegram_id). Supports links like ev_xxx__ref_123."""
    payload = (payload or "").strip()
    invited_by = None
    token = payload
    if "__ref_" in payload:
        token, ref_part = payload.split("__ref_", 1)
        try:
            invited_by = int(ref_part.strip())
        except Exception:
            invited_by = None
    event_id = resolve_event_id(data, token)
    return event_id, invited_by


def referral_link(event_id: str, telegram_id: int, data=None) -> str:
    token = event_token(data, event_id) if data else (event_id if is_safe_token(event_id) else make_link_id(event_id))
    return f"https://t.me/{BOT_USERNAME}?start={token}__ref_{telegram_id}"


def find_inviter(data: dict, invited_by_telegram_id):
    if not invited_by_telegram_id:
        return None
    try:
        invited_by_telegram_id = int(invited_by_telegram_id)
    except Exception:
        return None
    for r in reversed(data.get("registrations", [])):
        if r.get("telegram_id") == invited_by_telegram_id:
            return r
    return None


def normalize_tg_url(value: str) -> str:
    value = (value or "").strip()
    if not value or value == "-":
        return ""
    if value.startswith("@"):
        return "https://t.me/" + value[1:]
    if value.startswith("t.me/"):
        return "https://" + value
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return value


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
        kb.button(text=f"🟢 {e.get('title','Без названия')} • 👥 {count}", callback_data=f"event:view:{event_token(data, eid)}")
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


def event_card_kb(event_id, data=None):
    kb = InlineKeyboardBuilder()
    token = event_token(data, event_id) if data else (event_id if is_safe_token(event_id) else make_link_id(event_id))
    kb.button(text="👥 Участники", callback_data=f"event:participants:{token}")
    kb.button(text="🤝 Рефералы", callback_data=f"event:referrals:{token}")
    kb.button(text="📢 Рассылка", callback_data=f"event:broadcast:{token}")
    kb.button(text="⚙️ Управление", callback_data=f"event:manage:{token}")
    kb.button(text="⬅️ Назад", callback_data="crm:events")
    kb.button(text="🏠 Главная", callback_data="crm:home")
    kb.adjust(1)
    return kb.as_markup()




def participant_card_text(data, event_id, idx):
    regs = event_regs(data, event_id)
    try:
        idx = int(idx)
    except Exception:
        return "Участник не найден."
    if idx < 0 or idx >= len(regs):
        return "Участник не найден."

    r = regs[idx]
    event = data.get("events", {}).get(event_id, {})
    username = (r.get("telegram_username") or "").strip()
    username_text = f"@{username}" if username else "не указан"
    phone = r.get("phone") or "не указан"
    city = r.get("city") or "не указан"
    sphere = r.get("sphere") or "не указано"
    registered_at = r.get("registered_at") or "не указано"
    full_name = f"{r.get('first_name','')} {r.get('last_name','')}".strip() or "Без имени"
    event_title = event.get("title") or r.get("event_title") or "Мероприятие"

    return (
        f"👤 <b>{escape(full_name)}</b>\n\n"
        f"🆔 Telegram\n{escape(username_text)}\n\n"
        f"📱 Телефон\n{escape(str(phone))}\n\n"
        f"🏙 Город\n{escape(str(city))}\n\n"
        f"💼 Деятельность\n{escape(str(sphere))}\n\n"
        f"📅 Зарегистрирован\n{escape(str(registered_at))}\n\n"
        f"🎫 Мероприятие\n{escape(str(event_title))}"
    )


def participant_card_kb(data, event_id, idx):
    regs = event_regs(data, event_id)
    kb = InlineKeyboardBuilder()
    try:
        idx_int = int(idx)
    except Exception:
        idx_int = -1
    if 0 <= idx_int < len(regs):
        username = (regs[idx_int].get("telegram_username") or "").strip()
        if username:
            kb.button(text="💬 Написать", url=f"https://t.me/{username}")
    token = event_token(data, event_id)
    kb.button(text="⬅️ К участникам", callback_data=f"event:participants:{token}")
    kb.button(text="🏠 Главная", callback_data="crm:home")
    kb.adjust(1)
    return kb.as_markup()

def manage_kb(event_id, data=None):
    kb = InlineKeyboardBuilder()
    token = event_token(data, event_id) if data else (event_id if is_safe_token(event_id) else make_link_id(event_id))
    kb.button(text="✏️ Изменить", callback_data=f"manage:edit:{token}")
    kb.button(text="🖼 Афиша", callback_data=f"manage:poster:{token}")
    kb.button(text="🔗 Ссылка регистрации", callback_data=f"manage:link:{token}")
    kb.button(text="🟢 Статус регистрации", callback_data=f"manage:status:{token}")
    kb.button(text="📋 Дублировать", callback_data=f"manage:duplicate:{token}")
    kb.button(text="🗄 Архивировать", callback_data=f"manage:archive:{token}")
    kb.button(text="⬅️ Назад", callback_data=f"event:view:{token}")
    kb.button(text="🏠 Главная", callback_data="crm:home")
    kb.adjust(1)
    return kb.as_markup()


def docs_kb(event_id, data=None):
    kb = InlineKeyboardBuilder()
    token = event_token(data, event_id) if data else (event_id if is_safe_token(event_id) else make_link_id(event_id))
    kb.button(text="📄 Пользовательское соглашение", callback_data="doc:agreement")
    kb.button(text="📄 Политика обработки ПД", callback_data="doc:policy")
    kb.button(text="📄 Согласие на обработку ПД", callback_data="doc:consent_pd")
    kb.button(text="📄 Согласие на инфо и рекламные сообщения", callback_data="doc:consent_news")
    kb.button(text="✅ Ознакомился и принимаю условия", callback_data=f"legal:accept:{token}")
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
    # CRM-меню администратора: без пользовательской кнопки реферальной программы.
    keyboard = [
        [KeyboardButton(text="🏠 Главная"), KeyboardButton(text="📅 Мероприятия")],
        [KeyboardButton(text="📢 Рассылки"), KeyboardButton(text="📊 Аналитика")],
        [KeyboardButton(text="⚙️ Система")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def participant_reply_kb():
    keyboard = [
        [KeyboardButton(text="🤝 Реферальная программа")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def referral_stats_for_user(data, event_id, telegram_id):
    try:
        telegram_id = int(telegram_id)
    except Exception:
        return 0
    count = 0
    for r in event_regs(data, event_id):
        invited_by = r.get("invited_by_telegram_id")
        try:
            invited_by = int(invited_by)
        except Exception:
            continue
        if invited_by == telegram_id:
            count += 1
    return count


def choose_ref_event_for_user(data, telegram_id):
    # 1) Берем последнее мероприятие, на которое человек уже зарегистрирован.
    regs = [r for r in data.get("registrations", []) if r.get("telegram_id") == telegram_id]
    for r in reversed(regs):
        event_id = r.get("event_id")
        event = data.get("events", {}).get(event_id)
        if event and event.get("status", "open") != "archived":
            return event_id

    # 2) Если регистраций нет — берем единственное активное мероприятие.
    active = [
        eid for eid, e in data.get("events", {}).items()
        if e.get("status", "open") not in ["archived", "closed"]
    ]
    if len(active) == 1:
        return active[0]

    # 3) Если активных несколько — пусть пользователь выберет мероприятие.
    return None


def user_referral_text(data, event_id, telegram_id):
    event = data.get("events", {}).get(event_id, {})
    link = referral_link(event_id, telegram_id, data)
    invited_count = referral_stats_for_user(data, event_id, telegram_id)
    return (
        "🤝 <b>Реферальная программа</b>\n\n"
        f"🎫 Мероприятие:\n<b>{escape(str(event.get('title', 'Мероприятие')))}</b>\n\n"
        "Ваша персональная ссылка:\n"
        f"{link}\n\n"
        f"👥 Приглашено по вашей ссылке: <b>{invited_count}</b>\n\n"
        "Отправьте эту ссылку друзьям — если человек зарегистрируется по ней, приглашение засчитается вам."
    )


def user_referral_kb(data, event_id, telegram_id):
    kb = InlineKeyboardBuilder()
    link = referral_link(event_id, telegram_id, data)
    share_text = "Приглашаю на мероприятие сообщества «Все свои»"
    share_url = "https://t.me/share/url?url=" + link + "&text=" + share_text.replace(" ", "%20")
    kb.button(text="📤 Поделиться ссылкой", url=share_url)
    kb.adjust(1)
    return kb.as_markup()


def choose_ref_event_kb(data):
    kb = InlineKeyboardBuilder()
    for eid, e in data.get("events", {}).items():
        if e.get("status", "open") in ["archived", "closed"]:
            continue
        title = e.get("title", "Мероприятие")
        kb.button(text=f"🎫 {title}", callback_data=f"userref:{event_token(data, eid)}")
    kb.adjust(1)
    return kb.as_markup()


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


@dp.message(StateFilter("*"), F.text.func(lambda text: bool(text) and "рефераль" in text.lower()))
@dp.message(Command("ref"))
async def user_referral_program(message: Message, state: FSMContext = None):
    # Кнопка должна работать всегда, даже если у пользователя случайно остался старый FSM-state.
    if state is not None:
        try:
            await state.clear()
        except Exception:
            pass
    data = load_data()
    event_id = choose_ref_event_for_user(data, message.from_user.id)

    if event_id:
        return await message.answer(
            user_referral_text(data, event_id, message.from_user.id),
            parse_mode="HTML",
            reply_markup=user_referral_kb(data, event_id, message.from_user.id),
        )

    active = [
        eid for eid, e in data.get("events", {}).items()
        if e.get("status", "open") not in ["archived", "closed"]
    ]
    if not active:
        return await message.answer(
            "🤝 <b>Реферальная программа</b>\n\n"
            "Сейчас нет активных мероприятий для приглашения.",
            parse_mode="HTML",
            reply_markup=participant_reply_kb(),
        )

    await message.answer(
        "🤝 <b>Реферальная программа</b>\n\n"
        "Выберите мероприятие, на которое хотите пригласить людей:",
        parse_mode="HTML",
        reply_markup=choose_ref_event_kb(data),
    )


@dp.callback_query(F.data.startswith("userref:"))
async def cb_user_referral_program(call: CallbackQuery):
    token = call.data.split(":", 1)[1]
    data = load_data()
    event_id = resolve_event_id(data, token)
    if not event_id:
        return await call.answer("Мероприятие не найдено")
    await call.message.answer(
        user_referral_text(data, event_id, call.from_user.id),
        parse_mode="HTML",
        reply_markup=user_referral_kb(data, event_id, call.from_user.id),
    )
    await call.answer()


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
        return await message.answer(
            "Добро пожаловать! Для регистрации используйте ссылку на конкретное мероприятие.\n\n"
            "Реферальная программа доступна в нижнем меню бота.",
            reply_markup=participant_reply_kb(),
        )

    token = args[1]
    data = load_data()
    event_id, invited_by = parse_start_payload(token, data)
    if invited_by == message.from_user.id:
        invited_by = None
    event = data["events"].get(event_id) if event_id else None
    if not event:
        return await message.answer("Мероприятие не найдено. Проверьте ссылку.")
    if event.get("status") in ["closed", "paused", "archived"]:
        return await message.answer("Регистрация на это мероприятие сейчас закрыта.")

    await state.update_data(event_id=event_id, invited_by_telegram_id=invited_by)
    await message.answer(
        "🤍 <b>Добро пожаловать!</b>\n\n"
        "Для регистрации ознакомьтесь с документами.\n\n"
        "Мы бережно относимся к вашим персональным данным и используем их только для организации мероприятий сообщества «Все свои».\n\n"
        "Нажимая кнопку «Ознакомился и принимаю условия», вы подтверждаете, что ознакомились со всеми указанными документами и принимаете их условия.",
        parse_mode="HTML",
        reply_markup=docs_kb(event_id, data),
    )


@dp.callback_query(F.data.startswith("doc:"))
async def show_doc(call: CallbackQuery):
    doc_key = call.data.split(":", 1)[1]
    await call.message.answer(DOCS.get(doc_key, "Документ не найден."), parse_mode="HTML")
    await call.answer()


@dp.callback_query(F.data.startswith("legal:accept:"))
async def accept_legal(call: CallbackQuery, state: FSMContext):
    token = call.data.split(":", 2)[2]
    data = load_data()
    event_id = resolve_event_id(data, token)
    if not event_id:
        await call.message.answer("Мероприятие не найдено. Попробуйте открыть ссылку регистрации заново.")
        return await call.answer()
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
    invited_by = st.get("invited_by_telegram_id")
    if invited_by == message.from_user.id:
        invited_by = None
    inviter = find_inviter(data, invited_by)
    invited_by_username = (inviter or {}).get("telegram_username") or ""
    invited_by_name = f"{(inviter or {}).get('first_name','')} {(inviter or {}).get('last_name','')}".strip()

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
        "invited_by_telegram_id": invited_by or "",
        "invited_by_username": invited_by_username,
        "invited_by_name": invited_by_name,
    }
    registration["referral_link"] = referral_link(st["event_id"], message.from_user.id, data)
    data["registrations"].append(registration)
    save_data(data)
    append_registration_to_sheets(registration, event)
    count = len(event_regs(data, st["event_id"]))

    # Освобождаем состояние сразу после сохранения, чтобы нижняя кнопка
    # «🤝 Реферальная программа» работала сразу после регистрации.
    await state.clear()

    kb = InlineKeyboardBuilder()
    has_links = False
    chat_url = normalize_tg_url(event.get("chat_url", ""))
    channel_url = normalize_tg_url(event.get("channel_url", ""))
    if chat_url:
        kb.button(text="💬 Чат участников", url=chat_url)
        has_links = True
    if channel_url:
        kb.button(text="📢 Канал сообщества", url=channel_url)
        has_links = True
    if has_links:
        kb.adjust(1)

    await message.answer(
        f"🎉 <b>Регистрация подтверждена!</b>\n\n"
        f"Вы записаны на:\n\n<b>{event.get('title','Мероприятие')}</b>\n\n"
        f"📅 <b>{event.get('date','—')}</b>\n"
        f"🕕 <b>{event.get('time','—')}</b>\n\n"
        "До встречи на мероприятии! 🚀",
        parse_mode="HTML",
        reply_markup=kb.as_markup() if has_links else None,
    )
    await message.answer(
        "🤝 Ваша реферальная программа всегда доступна в нижнем меню бота.",
        reply_markup=participant_reply_kb(),
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
    await state.update_data(chat_url=normalize_tg_url(message.text))
    await message.answer("Ссылка на канал сообщества. Если нет — напишите -")
    await state.set_state(NewEvent.channel_url)


@dp.message(NewEvent.channel_url)
async def new_channel(message: Message, state: FSMContext):
    st = await state.get_data()
    data = load_data()
    event_id = f"ev_{int(datetime.now(TZ).timestamp())}"
    data["events"][event_id] = {
        "title": st["title"],
        "date": st["date"],
        "time": st["time"],
        "description": st["description"],
        "chat_url": normalize_tg_url(st.get("chat_url", "")),
        "channel_url": normalize_tg_url(message.text),
        "status": "open",
        "link_id": event_id,
        "created_at": now_str(),
    }
    save_data(data)
    await message.answer(
        f"✅ <b>Мероприятие создано</b>\n\n"
        f"📅 {st['title']}\n\n"
        f"🔗 Ссылка регистрации:\n{event_link(event_id, data)}",
        parse_mode="HTML",
    )
    await message.answer(event_card_text(data, event_id), parse_mode="HTML", reply_markup=event_card_kb(event_id, data))
    await state.clear()


@dp.callback_query(F.data.startswith("event:view:"))
async def cb_event_view(call: CallbackQuery):
    token = call.data.split(":", 2)[2]
    data = load_data()
    event_id = resolve_event_id(data, token)
    if not event_id:
        return await call.answer("Мероприятие не найдено")
    await call.message.answer(event_card_text(data, event_id), parse_mode="HTML", reply_markup=event_card_kb(event_id, data))
    await call.answer()


@dp.callback_query(F.data.startswith("event:participants:"))
async def cb_participants(call: CallbackQuery):
    token = call.data.split(":", 2)[2]
    data = load_data()
    event_id = resolve_event_id(data, token)
    if not event_id:
        return await call.answer("Мероприятие не найдено")
    regs = event_regs(data, event_id)
    kb = InlineKeyboardBuilder()
    if not regs:
        text = "👥 Пока нет участников."
    else:
        text = f"👥 <b>{len(regs)} участников</b>\n\nВыберите участника, чтобы открыть карточку."
        for i, r in enumerate(regs[:30], 1):
            full_name = f"{r.get('first_name','')} {r.get('last_name','')}".strip() or "Без имени"
            city = r.get("city") or "—"
            username = r.get("telegram_username")
            label_tail = f"@{username}" if username else city
            kb.button(
                text=f"{i}. {full_name} • {label_tail}",
                callback_data=f"event:participant:{event_token(data, event_id)}:{i-1}"
            )
        if len(regs) > 30:
            text += "\n\nПоказаны первые 30 участников."
    kb.button(text="⬅️ Назад", callback_data=f"event:view:{event_token(data, event_id)}")
    kb.button(text="🏠 Главная", callback_data="crm:home")
    kb.adjust(1)
    await call.message.answer(text, parse_mode="HTML", reply_markup=kb.as_markup())
    await call.answer()


@dp.callback_query(F.data.startswith("event:participant:"))
async def cb_participant_card(call: CallbackQuery):
    parts = call.data.split(":", 3)
    if len(parts) != 4:
        return await call.answer("Участник не найден")
    _, _, token, idx = parts
    data = load_data()
    event_id = resolve_event_id(data, token)
    if not event_id:
        return await call.answer("Мероприятие не найдено")
    await call.message.answer(
        participant_card_text(data, event_id, idx),
        parse_mode="HTML",
        reply_markup=participant_card_kb(data, event_id, idx),
    )
    await call.answer()


@dp.callback_query(F.data.startswith("event:referrals:"))
async def cb_event_referrals(call: CallbackQuery):
    token = call.data.split(":", 2)[2]
    data = load_data()
    event_id = resolve_event_id(data, token)
    if not event_id:
        return await call.answer("Мероприятие не найдено")

    regs = event_regs(data, event_id)
    counts = {}
    names = {}
    for r in regs:
        inviter_id = r.get("invited_by_telegram_id")
        if not inviter_id:
            continue
        try:
            inviter_id = int(inviter_id)
        except Exception:
            continue
        counts[inviter_id] = counts.get(inviter_id, 0) + 1
        inviter = find_inviter(data, inviter_id) or {}
        name = f"{inviter.get('first_name','')} {inviter.get('last_name','')}".strip()
        username = inviter.get("telegram_username")
        names[inviter_id] = f"@{username}" if username else (name or str(inviter_id))

    lines = ["🤝 <b>Реферальная программа</b>", ""]
    lines.append(f"Всего приглашено: <b>{sum(counts.values())}</b>")
    lines.append("")
    if counts:
        lines.append("🏆 <b>Топ участников:</b>")
        for i, (uid, cnt) in enumerate(sorted(counts.items(), key=lambda x: x[1], reverse=True)[:10], 1):
            lines.append(f"{i}. {escape(names.get(uid, str(uid)))} — {cnt}")
    else:
        lines.append("Пока никто не зарегистрировался по реферальной ссылке.")

    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data=f"event:view:{event_token(data, event_id)}")
    kb.button(text="🏠 Главная", callback_data="crm:home")
    kb.adjust(1)
    await call.message.answer("\n".join(lines), parse_mode="HTML", reply_markup=kb.as_markup())
    await call.answer()


@dp.callback_query(F.data.startswith("event:manage:"))
async def cb_manage(call: CallbackQuery):
    token = call.data.split(":", 2)[2]
    data = load_data()
    event_id = resolve_event_id(data, token)
    if not event_id:
        return await call.answer("Мероприятие не найдено")
    await call.message.answer("⚙️ <b>Управление мероприятием</b>", parse_mode="HTML", reply_markup=manage_kb(event_id, data))
    await call.answer()


@dp.callback_query(F.data.startswith("manage:link:"))
async def cb_link(call: CallbackQuery):
    token = call.data.split(":", 2)[2]
    data = load_data()
    event_id = resolve_event_id(data, token)
    if not event_id:
        return await call.answer("Мероприятие не найдено")
    await call.message.answer(f"🔗 <b>Ссылка регистрации</b>\n\n{event_link(event_id, data)}", parse_mode="HTML")
    await call.answer()


@dp.callback_query(F.data.startswith("manage:status:"))
async def cb_status(call: CallbackQuery):
    token = call.data.split(":", 2)[2]
    data = load_data()
    event_id = resolve_event_id(data, token)
    if not event_id:
        return await call.answer("Мероприятие не найдено")
    token = event_token(data, event_id)
    kb = InlineKeyboardBuilder()
    kb.button(text="🟢 Открыта", callback_data=f"status:set:{token}:open")
    kb.button(text="🟡 Приостановлена", callback_data=f"status:set:{token}:paused")
    kb.button(text="🔴 Закрыта", callback_data=f"status:set:{token}:closed")
    kb.button(text="⬅️ Назад", callback_data=f"event:manage:{token}")
    kb.adjust(1)
    await call.message.answer("Выберите статус регистрации:", reply_markup=kb.as_markup())
    await call.answer()


@dp.callback_query(F.data.startswith("status:set:"))
async def cb_set_status(call: CallbackQuery):
    _, _, token, status = call.data.split(":", 3)
    data = load_data()
    event_id = resolve_event_id(data, token)
    if not event_id:
        return await call.answer("Мероприятие не найдено")
    data["events"][event_id]["status"] = status
    save_data(data)
    await call.message.answer("Статус обновлен.")
    await call.message.answer(event_card_text(data, event_id), parse_mode="HTML", reply_markup=event_card_kb(event_id, data))
    await call.answer()


@dp.callback_query(F.data.startswith("manage:archive:"))
async def cb_archive(call: CallbackQuery):
    token = call.data.split(":", 2)[2]
    data = load_data()
    event_id = resolve_event_id(data, token)
    if event_id:
        data["events"][event_id]["status"] = "archived"
        save_data(data)
    await call.message.answer("🗄 Мероприятие отправлено в архив.")
    await call.answer()


@dp.callback_query(F.data.startswith("manage:duplicate:"))
async def cb_duplicate(call: CallbackQuery):
    token = call.data.split(":", 2)[2]
    data = load_data()
    event_id = resolve_event_id(data, token)
    event = data["events"].get(event_id) if event_id else None
    if not event:
        return await call.answer("Не найдено")
    new_id = f"ev_{int(datetime.now(TZ).timestamp())}"
    new_event = event.copy()
    new_event["title"] = event.get("title", "") + " — копия"
    new_event["created_at"] = now_str()
    new_event["status"] = "open"
    new_event["link_id"] = new_id
    data["events"][new_id] = new_event
    save_data(data)
    await call.message.answer(f"📋 Дубликат создан.\n\n🔗 {event_link(new_id, data)}")
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
    token = call.data.split(":", 2)[2]
    data = load_data()
    event_id = resolve_event_id(data, token)
    if not event_id:
        return await call.answer("Мероприятие не найдено")
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
        "🤖 Версия CRM: <b>V3.3.4 Referral Menu Separation</b>\n"
        f"💾 Хранилище: <b>{'PostgreSQL' if DATABASE_URL else 'JSON fallback'}</b>\n"
        f"📊 Google Sheets: <b>{'подключен' if google_sheets_enabled() else 'не подключен'}</b>\n\n"
        "Следующий этап: Google Sheets 2.0 и отметка посещения.",
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
    print("Starting Все свои CRM V3.3.4 Referral Menu Separation", flush=True)
    print(f"Storage mode: {'PostgreSQL' if DATABASE_URL else 'JSON fallback'}", flush=True)
    print(f"Google Sheets configured: {'yes' if GOOGLE_SHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON else 'no'}", flush=True)
    init_db()
    print("Database initialized", flush=True)
    scheduler.add_job(summary_job, "interval", hours=3)
    scheduler.start()
    print("Bot polling started", flush=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

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
DELETIONS_FILE = "deletions_log.json"
MOSCOW_TZ = ZoneInfo("Europe/Moscow")

DEFAULT_CHAT_URL = "https://t.me/+vyrw8Q-AnAlkYWVi"
DEFAULT_CHANNEL_URL = "https://t.me/voice_clubbbb"
DOC_VERSION = "1.0"
DOC_DATE = "03 июля 2026 года"
OPERATOR = "ИП Погодина Анастасия Александровна"
OPERATOR_INN = "526333028306"
OPERATOR_EMAIL = "pogodinabrand@ya.ru"

DOCUMENTS = {
    "agreement": {
        "title": "Пользовательское соглашение",
        "short": "📄 Пользовательское соглашение",
        "text": f"""
📄 <b>Пользовательское соглашение</b>

<b>Версия:</b> {DOC_VERSION}
<b>Дата вступления в силу:</b> {DOC_DATE}

<b>1. Общие положения</b>

Настоящее Пользовательское соглашение регулирует порядок использования Telegram-бота сообщества «Все свои».

Оператором Бота является:
{OPERATOR}
E-mail: {OPERATOR_EMAIL}

Используя Бот, пользователь подтверждает ознакомление и согласие с условиями настоящего Соглашения.

<b>2. Назначение Бота</b>

Бот предназначен для:
• регистрации пользователей на мероприятия сообщества «Все свои»;
• информирования о мероприятиях;
• направления организационных уведомлений;
• взаимодействия между организатором и участниками мероприятий.

<b>3. Регистрация</b>

Для регистрации пользователь предоставляет достоверные сведения:
• имя;
• фамилию;
• номер телефона;
• сферу деятельности;
• город.

Пользователь самостоятельно несет ответственность за достоверность предоставленной информации.

<b>4. Правила сообщества</b>

Используя Бот и участвуя в мероприятиях сообщества «Все свои», пользователь обязуется:
• уважительно относиться к другим участникам;
• соблюдать нормы делового и корректного общения;
• не распространять спам, навязчивую рекламу и недостоверную информацию;
• не использовать Бот в противоправных целях;
• соблюдать правила проведения мероприятий.

Организатор вправе ограничить доступ к Боту или участию в мероприятиях пользователям, нарушающим настоящее Соглашение или правила сообщества.

<b>5. Изменение и отмена мероприятий</b>

Организатор вправе изменять дату, время, место проведения и программу мероприятий, а также отменять мероприятия при наличии объективных обстоятельств.

При изменении существенных условий зарегистрированные участники уведомляются через Telegram-бот или иным доступным способом.

<b>6. Права и обязанности организатора</b>

Организатор вправе:
• изменять функционал Бота;
• направлять пользователям организационные уведомления;
• ограничивать использование Бота при нарушении настоящего Соглашения;
• совершенствовать сервис без предварительного уведомления пользователей.

<b>7. Ограничение ответственности</b>

Организатор не несет ответственности за:
• временную недоступность Telegram или иных сторонних сервисов;
• технические сбои, не зависящие от организатора;
• невозможность участия пользователя в мероприятии по причинам, не зависящим от организатора;
• последствия предоставления пользователем недостоверной информации.

<b>8. Изменение настоящего Соглашения</b>

Организатор вправе изменять настоящее Соглашение.

При внесении существенных изменений пользователю будет предложено ознакомиться с новой редакцией перед дальнейшим использованием Бота.

<b>9. Контактная информация</b>

Оператор Telegram-бота:
{OPERATOR}
E-mail: {OPERATOR_EMAIL}
""".strip(),
    },
    "privacy": {
        "title": "Политика обработки персональных данных",
        "short": "📄 Политика обработки ПД",
        "text": f"""
📄 <b>Политика обработки персональных данных</b>

<b>Версия:</b> {DOC_VERSION}
<b>Дата вступления в силу:</b> {DOC_DATE}

<b>1. Общие положения</b>

Настоящая Политика обработки персональных данных определяет порядок обработки персональных данных пользователей Telegram-бота сообщества «Все свои».

Оператор персональных данных:
{OPERATOR}
ИНН: {OPERATOR_INN}
E-mail: {OPERATOR_EMAIL}

Используя Telegram-бот и предоставляя персональные данные, пользователь подтверждает ознакомление с настоящей Политикой.

<b>2. Какие данные мы собираем</b>

При регистрации на мероприятия мы можем обрабатывать:
• имя;
• фамилию;
• номер телефона;
• сферу деятельности;
• город.

Также автоматически фиксируются:
• Telegram ID;
• Telegram username при наличии;
• дата и время регистрации;
• информация о принятии документов и согласий.

<b>3. Цели обработки персональных данных</b>

Персональные данные используются исключительно для:
• регистрации на мероприятия сообщества «Все свои»;
• связи с участниками;
• отправки организационной информации;
• отправки напоминаний о мероприятиях;
• ведения внутреннего учета участников;
• формирования статистики мероприятий;
• направления информации о новых мероприятиях сообщества при наличии согласия пользователя.

<b>4. Правовые основания обработки</b>

Обработка персональных данных осуществляется на основании согласия пользователя, выраженного при регистрации в Telegram-боте, а также в иных случаях, предусмотренных законодательством Российской Федерации.

<b>5. Какие действия мы совершаем с персональными данными</b>

Мы можем осуществлять следующие действия:
• сбор;
• запись;
• систематизацию;
• хранение;
• уточнение;
• использование;
• обезличивание при необходимости;
• удаление;
• уничтожение.

<b>6. Передача персональных данных</b>

Мы не продаем и не передаем персональные данные третьим лицам.

Данные могут обрабатываться с использованием сервисов, необходимых для работы Telegram-бота, исключительно в объеме, необходимом для их функционирования.

<b>7. Срок хранения персональных данных</b>

Персональные данные хранятся до достижения целей обработки либо до получения запроса пользователя на их удаление, если более длительный срок хранения не установлен законодательством Российской Федерации.

<b>8. Права пользователя</b>

Пользователь вправе:
• получать информацию об обработке своих персональных данных;
• требовать уточнения своих персональных данных;
• отозвать согласие на обработку персональных данных;
• потребовать удаления своих персональных данных.

Для удаления данных пользователь может воспользоваться командой /delete_me в Telegram-боте либо направить запрос на электронную почту {OPERATOR_EMAIL}.

<b>9. Защита персональных данных</b>

Оператор принимает необходимые организационные и технические меры для защиты персональных данных от неправомерного доступа, изменения, распространения, удаления и иных неправомерных действий.

<b>10. Изменение Политики</b>

Оператор вправе вносить изменения в настоящую Политику.

При существенном изменении условий обработки персональных данных пользователям будет предложено ознакомиться с новой редакцией документов при следующем использовании Telegram-бота.

<b>11. Контактная информация</b>

{OPERATOR}
E-mail: {OPERATOR_EMAIL}
""".strip(),
    },
    "consent_pd": {
        "title": "Согласие на обработку персональных данных",
        "short": "📄 Согласие на обработку ПД",
        "text": f"""
📄 <b>Согласие на обработку персональных данных</b>

<b>Версия:</b> {DOC_VERSION}
<b>Дата вступления в силу:</b> {DOC_DATE}

<b>1. Согласие пользователя</b>

Нажимая кнопку «Ознакомился и принимаю условия» в Telegram-боте сообщества «Все свои», пользователь дает согласие на обработку своих персональных данных.

Оператор персональных данных:
{OPERATOR}
ИНН: {OPERATOR_INN}
E-mail: {OPERATOR_EMAIL}

<b>2. Какие данные обрабатываются</b>

Пользователь дает согласие на обработку следующих данных:
• имя;
• фамилия;
• номер телефона;
• сфера деятельности;
• город;
• Telegram ID;
• Telegram username при наличии;
• дата и время регистрации;
• информация о принятии документов и согласий.

<b>3. Цели обработки</b>

Персональные данные обрабатываются для:
• регистрации на мероприятия сообщества «Все свои»;
• связи с участником;
• отправки организационной информации;
• отправки напоминаний о мероприятиях;
• ведения учета участников;
• формирования внутренней статистики мероприятий.

<b>4. Действия с персональными данными</b>

Пользователь дает согласие на следующие действия:
• сбор;
• запись;
• систематизацию;
• хранение;
• уточнение;
• использование;
• обезличивание;
• удаление;
• уничтожение.

<b>5. Срок действия согласия</b>

Согласие действует до достижения целей обработки персональных данных либо до момента его отзыва пользователем.

Пользователь может отозвать согласие и запросить удаление данных через команду /delete_me в Telegram-боте или по электронной почте {OPERATOR_EMAIL}.

<b>6. Подтверждение согласия</b>

Факт согласия фиксируется в Telegram-боте с указанием:
• Telegram ID пользователя;
• даты и времени принятия;
• версии настоящего согласия.

<b>7. Контакты оператора</b>

{OPERATOR}
E-mail: {OPERATOR_EMAIL}
""".strip(),
    },
    "consent_messages": {
        "title": "Согласие на получение информационных и рекламных сообщений",
        "short": "📄 Согласие на сообщения",
        "text": f"""
📄 <b>Согласие на получение информационных и рекламных сообщений</b>

<b>Версия:</b> {DOC_VERSION}
<b>Дата вступления в силу:</b> {DOC_DATE}

<b>1. Согласие пользователя</b>

Нажимая кнопку «Ознакомился и принимаю условия» в Telegram-боте сообщества «Все свои», пользователь дает согласие на получение информационных и рекламных сообщений от сообщества «Все свои».

<b>2. Какие сообщения могут направляться</b>

Пользователь может получать:
• информацию о предстоящих мероприятиях;
• напоминания о регистрации и начале мероприятий;
• уведомления об изменении даты, времени или места проведения мероприятий;
• новости и анонсы сообщества;
• приглашения на новые мероприятия.

<b>3. Способ направления сообщений</b>

Информационные и рекламные сообщения могут направляться через Telegram-бот, а также иными способами связи, если пользователь самостоятельно предоставил соответствующие контактные данные.

<b>4. Отказ от получения сообщений</b>

Пользователь вправе в любое время отказаться от получения информационных и рекламных сообщений, обратившись к оператору по электронной почте {OPERATOR_EMAIL} или воспользовавшись предусмотренными в сервисе способами отказа от рассылки при их появлении.

<b>5. Контактная информация</b>

{OPERATOR}
E-mail: {OPERATOR_EMAIL}
""".strip(),
    },
}


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


def load_deletions():
    return load_json(DELETIONS_FILE, [])


def save_deletions(data):
    save_json(DELETIONS_FILE, data)


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


def legal_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=DOCUMENTS["agreement"]["short"], callback_data="legal_doc:agreement")],
            [InlineKeyboardButton(text=DOCUMENTS["privacy"]["short"], callback_data="legal_doc:privacy")],
            [InlineKeyboardButton(text=DOCUMENTS["consent_pd"]["short"], callback_data="legal_doc:consent_pd")],
            [InlineKeyboardButton(text=DOCUMENTS["consent_messages"]["short"], callback_data="legal_doc:consent_messages")],
            [InlineKeyboardButton(text="✅ Ознакомился и принимаю условия", callback_data="legal_accept")],
        ]
    )


def delete_confirm_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Да, удалить мои данные", callback_data="delete_confirm")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="delete_cancel")],
        ]
    )


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


def format_full_name(registration: dict) -> str:
    name = registration.get("name", "—")
    surname = registration.get("surname", "")
    return f"{name} {surname}".strip()


def format_admin_registration(registration: dict, event: dict) -> str:
    event_id = registration["event_id"]
    total = count_event_registrations(event_id)
    today_count = count_today_registrations(event_id)
    username = registration.get("telegram_username") or "—"

    return (
        "🔥 <b>Новая регистрация</b>\n\n"
        f"👤 <b>Имя:</b> {format_full_name(registration)}\n"
        f"📱 <b>Телефон:</b> {registration.get('phone', '—')}\n"
        f"💼 <b>Сфера:</b> {registration.get('sphere', '—')}\n"
        f"🌍 <b>Город:</b> {registration.get('city', '—')}\n"
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


async def send_long_message(target, text: str, **kwargs):
    # Telegram message limit is 4096 characters.
    chunk_size = 3600
    if len(text) <= chunk_size:
        await target.answer(text, **kwargs)
        return
    for i in range(0, len(text), chunk_size):
        await target.answer(text[i:i + chunk_size], **kwargs)


async def show_legal_screen(message: Message):
    await message.answer(
        "🤍 <b>Добро пожаловать!</b>\n\n"
        "Для регистрации ознакомьтесь с документами.\n\n"
        "Мы бережно относимся к вашим персональным данным и используем их только для организации мероприятий сообщества «Все свои».\n\n"
        "Нажимая кнопку «Ознакомился и принимаю условия», вы подтверждаете, что ознакомились со всеми указанными документами и принимаете их условия.\n\n"
        f"<b>Версия документов:</b> {DOC_VERSION}",
        parse_mode="HTML",
        reply_markup=legal_keyboard(),
    )


# ---------- FSM ----------

class Register(StatesGroup):
    legal = State()
    name = State()
    surname = State()
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
    await show_legal_screen(message)
    await state.set_state(Register.legal)


@dp.callback_query(F.data.startswith("legal_doc:"))
async def legal_doc_callback(callback):
    key = callback.data.split(":", 1)[1]
    doc = DOCUMENTS.get(key)
    if not doc:
        await callback.answer("Документ не найден", show_alert=True)
        return
    await send_long_message(callback.message, doc["text"], parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "legal_accept")
async def legal_accept_callback(callback, state: FSMContext):
    data = await state.get_data()
    if not data.get("event_id"):
        await callback.message.answer("Сначала перейдите по ссылке конкретного мероприятия.")
        await callback.answer()
        return

    await state.update_data(
        legal_accepted_at=now_str(),
        legal_version=DOC_VERSION,
        agreement_version=DOC_VERSION,
        privacy_version=DOC_VERSION,
        consent_pd_version=DOC_VERSION,
        consent_messages_version=DOC_VERSION,
    )
    await callback.message.answer("Как вас зовут?")
    await state.set_state(Register.name)
    await callback.answer()


@dp.message(Register.legal)
async def legal_wait(message: Message):
    await message.answer(
        "Перед регистрацией нужно ознакомиться с документами и нажать кнопку «Ознакомился и принимаю условия».",
        reply_markup=legal_keyboard(),
    )


@dp.message(Register.name)
async def get_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("Введите вашу фамилию:")
    await state.set_state(Register.surname)


@dp.message(Register.surname)
async def get_surname(message: Message, state: FSMContext):
    await state.update_data(surname=message.text.strip())

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
    await state.update_data(sphere=message.text.strip())
    await message.answer("Из какого вы города?")
    await state.set_state(Register.city)


@dp.message(Register.city)
async def get_city(message: Message, state: FSMContext):
    data = await state.get_data()
    events = load_events()
    event = events[data["event_id"]]

    registrations = load_registrations()
    registration = {
        "event_id": data["event_id"],
        "event_title": event["title"],
        "name": data["name"],
        "surname": data.get("surname", ""),
        "phone": data["phone"],
        "sphere": data.get("sphere", ""),
        "city": message.text.strip(),
        "telegram_id": message.from_user.id,
        "telegram_username": message.from_user.username,
        "registered_at": now_str(),
        "legal_accepted_at": data.get("legal_accepted_at"),
        "legal_version": DOC_VERSION,
        "agreement_version": DOC_VERSION,
        "privacy_version": DOC_VERSION,
        "consent_pd_version": DOC_VERSION,
        "consent_messages_version": DOC_VERSION,
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


# ---------- Delete data ----------

@dp.message(Command("delete_me"))
async def delete_me(message: Message):
    await message.answer(
        "Вы действительно хотите удалить свои персональные данные?\n\n"
        "После удаления вы будете исключены из регистраций и рассылок.",
        reply_markup=delete_confirm_keyboard(),
    )


@dp.callback_query(F.data == "delete_cancel")
async def delete_cancel(callback):
    await callback.message.answer("Удаление данных отменено.")
    await callback.answer()


@dp.callback_query(F.data == "delete_confirm")
async def delete_confirm(callback):
    telegram_id = callback.from_user.id
    registrations = load_registrations()
    to_delete = [r for r in registrations if r.get("telegram_id") == telegram_id]
    remaining = [r for r in registrations if r.get("telegram_id") != telegram_id]
    save_registrations(remaining)

    deletions = load_deletions()
    deletions.append({
        "telegram_id": telegram_id,
        "telegram_username": callback.from_user.username,
        "deleted_at": now_str(),
        "removed_registrations": len(to_delete),
    })
    save_deletions(deletions)

    await callback.message.answer(
        "Ваши персональные данные удалены из системы регистрации."
        if to_delete else "В системе не найдено ваших регистраций."
    )

    username = callback.from_user.username or "—"
    await send_to_admins(
        "🗑 <b>Пользователь запросил удаление данных</b>\n\n"
        f"Telegram ID: <code>{telegram_id}</code>\n"
        f"Telegram: @{username}\n"
        f"Удалено регистраций: {len(to_delete)}\n"
        f"Дата: {now_str()}"
    )
    await callback.answer()


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
            f"{i}. <b>{format_full_name(user)}</b>\n"
            f"Мероприятие: {user.get('event_title', '—')}\n"
            f"Телефон: {user.get('phone', '—')}\n"
            f"Сфера: {user.get('sphere', '—')}\n"
            f"Город: {user.get('city', '—')}\n"
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
            text += f"{i}. {format_full_name(reg)} — {reg.get('sphere', '—')}\n"
        text += "\n"
    return text.strip()


async def send_3_hour_summary():
    state = load_summary_state()
    text = build_summary_text(hours=3, force=False)

    if "новых регистраций не было" not in text:
        await send_to_admins(text)

    state["last_summary_at"] = now_str()
    save_summary_state(state)


async def main():
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

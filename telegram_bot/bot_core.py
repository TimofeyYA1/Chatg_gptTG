from __future__ import annotations

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, Update, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, ReplyKeyboardMarkup, KeyboardButton,
)
import httpx
from aiogram.types import FSInputFile
import os
from io import BytesIO
import base64
from aiogram.types import Message, BufferedInputFile
from common.config import settings

# -------------------- Bot & DP --------------------
bot = Bot(
    token=settings.TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

API_BASE = "http://api:8000"
API_TIMEOUT = httpx.Timeout(connect=5.0, read=25.0, write=10.0, pool=5.0)


# -------------------- Pricing --------------------
PRICE_PLAN_LIGHT = 275_00
PRICE_PLAN_MAX   = 450_00
PRICE_PLAN_ULTRA = 1333_00

ADDON_PRICES = {
    "messages": {50: 50_00, 200: 180_00, 500: 400_00},
    "images":   {100: 120_00, 500: 500_00, 1000: 900_00},
    "video":    {5: 150_00, 20: 500_00, 50: 1000_00},
}

# -------------------- FSM --------------------
class ImgFlow(StatesGroup):
    waiting_prompt = State()

class ChatCreateFlow(StatesGroup):
    waiting_title = State()

# -------------------- Keyboards --------------------
def bottom_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="💬 Мои чаты")],
            [KeyboardButton(text="📄 Моя подписка"), KeyboardButton(text="🖼 Генерация изображений")],
            [KeyboardButton(text="🎁 Премиум бесплатно"), KeyboardButton(text="💰 Пополнить баланс")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )

def sub_card_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Докупить сообщения", callback_data="addon:pick:messages")],
        [InlineKeyboardButton(text="🖼 Докупить изображения", callback_data="addon:pick:images")],
        [InlineKeyboardButton(text="🎬 Докупить видео",      callback_data="addon:pick:video")],
        [InlineKeyboardButton(text="⚙️ Изменить план",       callback_data="sub:change")],
        [InlineKeyboardButton(text="❌ Завершить подписку",  callback_data="sub:cancel")],
    ])

def addon_options_kb(kind: str) -> InlineKeyboardMarkup:
    rows = []
    for qty, price in ADDON_PRICES[kind].items():
        rows.append([InlineKeyboardButton(text=f"+{qty} за {price//100}⭐", callback_data=f"addon:buy:{kind}:{qty}:{price}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="sub:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def plans_inline_kb_with_text() -> tuple[str, InlineKeyboardMarkup]:
    text = (
        "🔁 Изменение тарифного плана.\n\n"
        "Выбери новый план:\n\n"
        "💠 Light\n"
        "• 50 запросов/день\n• 500 изображений/мес\n• 0 видео/мес\n"
        "• Голосовые до 1 мин\n• Голосовые ответы: нет\n• Экспорт в .docx/.pdf: нет\n"
        f"• Цена: {PRICE_PLAN_LIGHT//100}⭐/мес\n\n"
        "💠 Max\n"
        "• 100 запросов/день\n• 1000 изображений/мес\n• 10 видео/мес\n"
        "• Голосовые до 10 мин\n• Голосовые ответы: да\n• Экспорт в .docx/.pdf: да\n"
        f"• Цена: {PRICE_PLAN_MAX//100}⭐/мес\n\n"
        "💠 Ultra\n"
        "• 500 запросов/день\n• 2500 изображений/мес\n• 100 видео/мес\n"
        "• Голосовые до 20 мин\n• Голосовые ответы: да\n• Экспорт в .docx/.pdf: да\n"
        f"• Цена: {PRICE_PLAN_ULTRA//100}⭐/мес"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💠 Light", callback_data=f"sub:buyplan:Light:{PRICE_PLAN_LIGHT}")],
        [InlineKeyboardButton(text="💠 Max",   callback_data=f"sub:buyplan:Max:{PRICE_PLAN_MAX}")],
        [InlineKeyboardButton(text="⚡ Ultra", callback_data=f"sub:buyplan:Ultra:{PRICE_PLAN_ULTRA}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="sub:open")],
    ])
    return text, kb

def chats_inline_kb(items: list[dict]) -> InlineKeyboardMarkup:
    """
    Каждая строка: [активация чата] [удалить]
    Активный помечаем ⭐, неактивный — 🟢
    """
    rows = []
    for s in items:
        icon = "⭐" if s["is_active"] else "🟢"
        rows.append([
            InlineKeyboardButton(text=f"{icon} {s['title']}", callback_data=f"chats:activate:{s['id']}"),
            InlineKeyboardButton(text="🗑",                    callback_data=f"chats:delete:{s['id']}")
        ])
    rows.append([InlineKeyboardButton(text="➕ Добавить новый чат", callback_data="chats:create")])
    rows.append([InlineKeyboardButton(text="🗑 Удалить все чаты",   callback_data="chats:clear")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def topup_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пополнить +100",  callback_data="balance:topup:10000")],
        [InlineKeyboardButton(text="Пополнить +500",  callback_data="balance:topup:50000")],
        [InlineKeyboardButton(text="Пополнить +1000", callback_data="balance:topup:100000")],
    ])

def chat_create_prompt_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Пропустить", callback_data="chat:new:skip")],
        [InlineKeyboardButton(text="❌ Отмена",     callback_data="chat:new:cancel")],
    ])


# -------------------- helpers --------------------
async def _refresh_chats_markup(chat_id: int, list_msg_id: int):
    """Перерисовать клавиатуру у СТАРОГО сообщения со списком чатов."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{API_BASE}/chats/{chat_id}")
    items = r.json().get("items", [])
    await bot.edit_message_reply_markup(
        chat_id=chat_id,
        message_id=list_msg_id,
        reply_markup=chats_inline_kb(items),
    )

async def _safe_delete(chat_id: int, message_id: int):
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass


# -------------------- helpers: build subscription view --------------------
async def build_subscription_view(chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{API_BASE}/subscriptions/summary/{chat_id}")
    r.raise_for_status()
    data = r.json()

    role = data.get("role", "free")
    bal  = (data.get("balance_cents") or 0) / 100

    # Новая схема: limits + active_until + auto_renew
    limits = data.get("limits") or {"messages": 0, "images": 0, "video": 0}
    active_until = data.get("active_until")  # ISO строка или None
    auto_renew = data.get("auto_renew", False)

    # Старые поля (если бэкенд их вернёт — используем; если нет — даём дефолты)
    usage = data.get("usage") or {"messages": 0, "images": 0, "video": 0}
    addons = data.get("addons") or {"messages": 0, "images": 0, "video": 0}
    totals = data.get("totals") or {
        "messages": (limits.get("messages", 0) + addons.get("messages", 0)),
        "images":   (limits.get("images", 0)   + addons.get("images", 0)),
        "video":    (limits.get("video", 0)    + addons.get("video", 0)),
    }

    if active_until:
        au_human = active_until.replace("T", " ").split(".")[0]
        renew_str = "Вкл" if auto_renew else "Выкл"
        header = (
            f"💎 Подписка: {role}\n"
            f"⏳ Действует до: {au_human}\n"
            f"🔁 Автопродление: {renew_str}\n"
            f"💰 Баланс: {bal:.0f}⭐\n\n"
        )
    else:
        header = (
            f"💎 Подписка: {role}\n"
            f"💰 Баланс: {bal:.0f}⭐\n\n"
        )

    text = (
        header +
        "📊 Использование и лимиты:\n"
        f"— Сообщения: {usage.get('messages',0)}/{totals.get('messages',0)} "
        f"(базовый лимит {limits.get('messages',0)}"
        + (f", докуплено {addons.get('messages',0)}" if addons.get("messages") else "") + ")\n"
        f"— Изображения: {usage.get('images',0)}/{totals.get('images',0)} "
        f"(базовый лимит {limits.get('images',0)}"
        + (f", докуплено {addons.get('images',0)}" if addons.get("images") else "") + ")\n"
        f"— Видео: {usage.get('video',0)}/{totals.get('video',0)} "
        f"(базовый лимит {limits.get('video',0)}"
        + (f", докуплено {addons.get('video',0)}" if addons.get("video") else "") + ")\n\n"
        "Можешь докупить лимиты или изменить/завершить план:"
    )

    return text, sub_card_kb()

# -------------------- /start --------------------
@router.message(Command("start"))
async def cmd_start(m: Message):
    intro = (
        "Рад видеть! 👋\n\n"
        "<b>Давайте начнём и сделаем задачи быстрее в 2 раза.</b>\n\n"
        "— Я — ваш ассистент бота <b>AI SuperBot</b> с подписками, лимитами и докупками.\n"
        "— Отвечаю коротко и по делу, умею вести <u>несколько чатов</u> (переключение, переименование, удаление).\n"
        "— Генерирую изображения (есть экономный режим), а текст — через OpenAI с минимальными токенами.\n"
        "— Учитываю лимиты плана и сразу записываю использование в статистику.\n\n"
        "<b>Что конкретно умею:</b>\n"
        "• Показываю профиль: баланс/статус/подписка\n"
        "• Карточку «Моя подписка»: докупить сообщения/изображения/видео, сменить или отменить план\n"
        "• Управляю чатами: создание, переименование, выбор активного, удаление\n"
        "• Генерирую изображения по описанию (пока с заглушкой при недоступности сервиса)\n\n"
        "<b>Попробуйте готовые запросы 🚀</b>\n"
        "— «Подскажи, чем отличается Max от Ultra?»\n"
        "— «Сгенерируй постер в стиле ретро с роботом и городом будущего»\n"
        "— «Переименуй активный чат в: Математика»\n"
        "— «Сколько сообщений у меня из лимита осталось?»\n\n"
        "Или просто напишите свой запрос 👇"
    )
    await m.answer(intro, reply_markup=bottom_menu_kb())


# -------------------- Profile --------------------
@router.message(Command("account"))
@router.message(F.text == "👤 Мой профиль")
async def cmd_account(m: Message):
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{API_BASE}/account/profile/{m.chat.id}")
    if r.status_code != 200:
        await m.answer("API недоступен.")
        return
    data = r.json()
    bal = data.get("balance_cents", 0) / 100
    role = data.get("role", "free")

    text = (
        "👤 Мой профиль\n"
        f"👤 @{(m.from_user.username or 'unknown')}\n"
        f"💰 Баланс: {bal:.2f}⭐️\n"
        f"🔖 Подписка: {role}\n\n"
        "📊 Статистика использования (за текущий период):\n"
        "— Сообщения (текст): 0\n"
        "— Изображения: 0\n"
        "— Видео: 0\n\n"
        "👥 Реферальная программа:\n"
        "— Приглашено друзей: 0\n"
        "— Оформили подписку: 0\n\n"
        f"🔗 Твоя реферальная ссылка:\nhttps://t.me/{settings.BOT_NAME}?start={m.chat.id}"
    )
    await m.answer(text, reply_markup=bottom_menu_kb())



# -------------------- Subscription --------------------
@router.message(Command("premium"))
@router.message(Command("subscription"))
@router.message(F.text == "📄 Моя подписка")
async def open_subscription(m: Message):
    try:
        text, kb = await build_subscription_view(m.chat.id)
    except Exception:
        await m.answer("API недоступен.")
        return
    await m.answer(text, reply_markup=kb)

@router.callback_query(F.data == "sub:open")
async def cb_sub_open(c: CallbackQuery):
    try:
        text, kb = await build_subscription_view(c.message.chat.id)
        await c.message.edit_text(text, reply_markup=kb)
    except Exception:
        text, kb = await build_subscription_view(c.message.chat.id)
        await bot.send_message(c.message.chat.id, text, reply_markup=kb)
    await c.answer()

@router.callback_query(F.data == "sub:change")
async def cb_sub_change(c: CallbackQuery):
    text, kb = plans_inline_kb_with_text()
    try:
        await c.message.edit_text(text, reply_markup=kb)
    except Exception:
        await bot.send_message(c.message.chat.id, text, reply_markup=kb)
    await c.answer()

@router.callback_query(F.data.startswith("sub:buyplan:"))
async def cb_plan_buy(c: CallbackQuery):
    _, _, plan, amount = c.data.split(":")
    amount = int(amount)
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{API_BASE}/subscriptions/set_plan",
            json={"chat_id": c.message.chat.id, "plan": plan, "price_cents": amount},
        )
    if r.status_code == 200:
        await c.answer(f"Подписка обновлена: {plan}.", show_alert=True)
        text, kb = await build_subscription_view(c.message.chat.id)
        try:
            await c.message.edit_text(text, reply_markup=kb)
        except Exception:
            await bot.send_message(c.message.chat.id, text, reply_markup=kb)
    elif r.status_code == 402:
        await c.answer("Недостаточно средств. Пополни баланс.", show_alert=True)
    else:
        await c.answer("Ошибка при изменении плана.", show_alert=True)

@router.callback_query(F.data == "sub:cancel")
async def cb_plan_cancel(c: CallbackQuery):
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{API_BASE}/subscriptions/cancel", json={"chat_id": c.message.chat.id})
    if r.status_code == 200:
        await c.answer("Подписка отменена. Текущий план: free", show_alert=True)
        text, kb = await build_subscription_view(c.message.chat.id)
        try:
            await c.message.edit_text(text, reply_markup=kb)
        except Exception:
            await bot.send_message(c.message.chat.id, text, reply_markup=kb)
    else:
        await c.answer("Ошибка при отмене.", show_alert=True)

# -------------------- Addons --------------------
@router.callback_query(F.data.startswith("addon:pick:"))
async def cb_addon_pick(c: CallbackQuery):
    kind = c.data.split(":")[2]
    try:
        await c.message.edit_text("Выбери пакет докупки:", reply_markup=addon_options_kb(kind))
    except Exception:
        await bot.send_message(c.message.chat.id, "Выбери пакет докупки:", reply_markup=addon_options_kb(kind))
    await c.answer()

@router.callback_query(F.data.startswith("addon:buy:"))
async def cb_addon_buy(c: CallbackQuery):
    _, _, kind, qty, price = c.data.split(":")
    qty, price = int(qty), int(price)
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{API_BASE}/payments/addons/buy",
            json={"chat_id": c.message.chat.id, "kind": kind, "qty": qty, "price_cents": price},
        )
    if r.status_code == 200:
        await c.answer("Лимиты докуплены ✅", show_alert=True)
        text, kb = await build_subscription_view(c.message.chat.id)
        try:
            await c.message.edit_text(text, reply_markup=kb)
        except Exception:
            await bot.send_message(c.message.chat.id, text, reply_markup=kb)
    elif r.status_code == 402:
        await c.answer("Недостаточно средств.", show_alert=True)
    else:
        await c.answer("Ошибка докупки.", show_alert=True)

# -------------------- Balance topup --------------------
@router.message(F.text == "💰 Пополнить баланс")
async def topup_menu(m: Message):
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{API_BASE}/payments/balance/{m.chat.id}")
    bal = r.json().get("balance_cents", 0) / 100
    await m.answer(
        f"💰 Текущий баланс: <b>{bal:.2f}⭐</b>\nВыбери сумму пополнения:",
        reply_markup=topup_inline_kb(),
    )

@router.callback_query(F.data.startswith("balance:topup:"))
async def cb_topup(c: CallbackQuery):
    amount = int(c.data.split(":")[2])
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{API_BASE}/payments/balance/topup",
            json={"chat_id": c.message.chat.id, "amount": amount},
        )
    if r.status_code == 200:
        await c.answer("Баланс пополнен.", show_alert=True)
        text, kb = await build_subscription_view(c.message.chat.id)
        try:
            await c.message.edit_text(text, reply_markup=kb)
        except Exception:
            await bot.send_message(c.message.chat.id, text, reply_markup=kb)
    else:
        await c.answer("Ошибка пополнения", show_alert=True)

@router.message(F.text == "🎁 Премиум бесплатно")
async def premium_free(m: Message):
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{API_BASE}/referrals/summary/{m.chat.id}")
        data = r.json()
        invited = data.get("invited", 0)
        subscribed = data.get("subscribed", 0)
        ref_link = data.get("ref_link") or f"https://t.me/{getattr(settings, 'BOT_NAME', 'ai_superbot')}?start={m.chat.id}"
    except Exception:
        invited = 0
        subscribed = 0
        ref_link = f"https://t.me/{getattr(settings, 'BOT_NAME', 'ai_superbot')}?start={m.chat.id}"

    text = (
        "🎁 <b>Премиум бесплатно — реферальная программа</b>\n\n"
        "<b>Как это работает:</b>\n"
        "1️⃣ Поделись своей уникальной ссылкой с друзьями.\n"
        "2️⃣ За каждого друга (до 20), который просто начнёт пользоваться ботом —\n"
        "   ты получаешь +1 день доступа уровня <b>Light</b> (в реальном боте).\n"
        "3️⃣ Если друг оформит любую платную подписку по твоей ссылке —\n"
        "   вы оба получите:\n"
        "   • <b>1 месяц</b> подписки уровня <b>Max</b> (симуляция)\n"
        "   • <b>3</b> бонусных генерации видео (симуляция)\n\n"
        "<b>Статистика:</b>\n"
        f"👥 Приглашено друзей: <b>{invited}</b>\n"
        f"✅ Оформили подписку: <b>{subscribed}</b>\n\n"
        "<b>Твоя ссылка:</b>\n"
        f"{ref_link}"
    )
    await m.answer(text, reply_markup=bottom_menu_kb())

    
# -------------------- Chats --------------------
@router.message(F.text == "💬 Мои чаты")
async def chats_btn(m: Message):
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{API_BASE}/chats/{m.chat.id}")
    kb = chats_inline_kb(r.json()["items"])
    await m.answer("💬 <b>Твои чаты</b>", reply_markup=kb)

# Создание нового чата — показываем запрос имени, помним id списка
@router.callback_query(F.data == "chats:create")
async def cb_create_chat_start(c: CallbackQuery, state: FSMContext):
    await state.set_state(ChatCreateFlow.waiting_title)
    await state.update_data(list_msg_id=c.message.message_id)  # помним СТАРОЕ сообщение со списком
    msg = await c.message.answer(
        "🆕 Введите название нового чата (до 100 символов).\n"
        "Можно нажать «➡️ Пропустить», чтобы использовать имя по умолчанию.",
        reply_markup=chat_create_prompt_kb(),
    )
    await state.update_data(prompt_msg_id=msg.message_id)
    await c.answer()

@router.callback_query(F.data == "chat:new:cancel")
async def cb_create_chat_cancel(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    prompt_msg_id = data.get("prompt_msg_id")
    if prompt_msg_id:
        await _safe_delete(c.message.chat.id, prompt_msg_id)
    await state.clear()

@router.callback_query(F.data == "chat:new:skip")
async def cb_create_chat_skip(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    list_msg_id = data.get("list_msg_id")
    prompt_msg_id = data.get("prompt_msg_id")

    async with httpx.AsyncClient() as client:
        await client.post(f"{API_BASE}/chats/{c.message.chat.id}/create")  # без названия
    if list_msg_id:
        await _refresh_chats_markup(c.message.chat.id, list_msg_id)
    if prompt_msg_id:
        await _safe_delete(c.message.chat.id, prompt_msg_id)

    await state.clear()
    await c.answer("Чат создан")

@router.message(ChatCreateFlow.waiting_title)
async def receive_new_chat_title(m: Message, state: FSMContext):
    data = await state.get_data()
    list_msg_id = data.get("list_msg_id")
    prompt_msg_id = data.get("prompt_msg_id")

    title = (m.text or "").strip()
    if len(title) > 100:
        await m.answer(
            "Название слишком длинное. До 100 символов, либо «➡️ Пропустить».",
            reply_markup=chat_create_prompt_kb(),
        )
        return

    async with httpx.AsyncClient() as client:
        await client.post(f"{API_BASE}/chats/{m.chat.id}/create", json={"title": title or None})

    if list_msg_id:
        await _refresh_chats_markup(m.chat.id, list_msg_id)
    if prompt_msg_id:
        await _safe_delete(m.chat.id, prompt_msg_id)
    # удалим сообщение с введённым именем
    await _safe_delete(m.chat.id, m.message_id)

    await state.clear()

# Активация
@router.callback_query(F.data.startswith("chats:activate:"))
async def cb_activate_chat(c: CallbackQuery):
    sid = int(c.data.split(":")[2])
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{API_BASE}/chats/{c.message.chat.id}/{sid}/activate")
        if r.status_code != 200:
            await c.answer("Не удалось активировать чат (API 500).", show_alert=True)
            return
        payload = r.json()
        r2 = await client.get(f"{API_BASE}/chats/{c.message.chat.id}")
    try:
        await c.message.edit_reply_markup(
            reply_markup=chats_inline_kb(r2.json()["items"])
        )
    except Exception:
        await c.message.answer("Список чатов обновлён.", reply_markup=chats_inline_kb(r2.json()["items"]))
    last = payload.get("last_message")
    title = payload.get("title")
    preview = f"Последнее сообщение в <b>{title}</b>:\n<i>{last}</i>" if last else f"<b>{title}</b> пока пустой."
    await c.message.answer(preview)
    await c.answer("Сделан активным")

# Удаление конкретного чата
@router.callback_query(F.data.startswith("chats:delete:"))
async def cb_delete_chat(c: CallbackQuery):
    sid = int(c.data.split(":")[2])
    async with httpx.AsyncClient(timeout=8.0) as client:
        await client.post(f"{API_BASE}/chats/{c.message.chat.id}/{sid}/delete")
        r2 = await client.get(f"{API_BASE}/chats/{c.message.chat.id}")
    await c.message.edit_reply_markup(reply_markup=chats_inline_kb(r2.json()["items"]))

@router.callback_query(F.data.startswith("chats:clear"))
async def cb_clear_chats(c: CallbackQuery):
    chat_id = c.message.chat.id
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{API_BASE}/chats/{chat_id}/clear")
        ok = r.status_code == 200
        data = r.json() if ok else {}
        items = (data.get("items") or [])
        if not items:
            r2 = await client.get(f"{API_BASE}/chats/{chat_id}")
            if r2.status_code == 200:
                items = r2.json().get("items", [])

    kb = chats_inline_kb(items) if items else chats_inline_kb([])

    try:
        await c.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        await c.message.answer("💬 <b>Твои чаты</b>", reply_markup=kb)

    await c.answer("Все чаты удалены")

# -------------------- Image (stub) --------------------
@router.message(Command("image"))
@router.message(F.text == "🖼 Генерация изображений")
async def cmd_image(m: Message, state: FSMContext):
    await state.set_state(ImgFlow.waiting_prompt)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить генерацию", callback_data="img:cancel")]
    ])

    await m.answer(
        "🖼 Введите текстовое описание изображения.\n\n"
        "• Чтобы <b>сгенерировать новое</b> изображение — просто напишите промпт.\n",
        reply_markup=kb
    )
     
@router.callback_query(F.data == "img:cancel")
async def img_cancel(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await _safe_delete(c.message.chat.id, c.message.message_id)
    await c.answer()

@router.message(ImgFlow.waiting_prompt, F.text)
async def on_image_generate_prompt(m: Message, state: FSMContext):
    user_prompt = (m.text or "").strip()
    if not user_prompt:
        await m.answer("Опиши, что нужно сгенерировать.")
        return

    await state.clear()

    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
            usage_r = await client.post(
                f"{API_BASE}/usage/increment",
                json={"chat_id": m.chat.id, "kind": "images", "value": 1},
                timeout=10,
            )

            if usage_r.status_code == 402:
                await m.answer(
                    "Лимит генераций изображений исчерпан.\n"
                    "Открой «📄 Моя подписка», чтобы докупить лимиты или сменить план."
                )
                return

            if usage_r.status_code != 200:
                await m.answer("Не удалось проверить лимит изображений. Попробуй чуть позже.")
                return

            r = await client.post(
                f"{API_BASE}/image/generate",
                json={
                    "chat_id": m.chat.id,
                    "prompt": user_prompt,
                    "size": "1024x1024",
                },
                timeout=60,
            )
    except httpx.ReadTimeout:
        await m.answer("🤖 (таймаут API) Не удалось сгенерировать изображение.")
        return
    except Exception as e:
        await m.answer(f"🤖 (ошибка сети) Не удалось отправить запрос на генерацию: {e}")
        return

    if r.status_code != 200:
        await m.answer("🤖 (сбой API) Не удалось сгенерировать изображение.")
        return

    data = r.json()

    if data.get("stub"):
        await m.answer(
            data.get("caption") or "🧪 (симуляция) Картинка сгенерирована."
        )
        return

    b64_out = data.get("b64")
    if not b64_out:
        await m.answer("🤖 (ошибка API) Пустой ответ при генерации изображения.")
        return

    try:
        out_bytes = base64.b64decode(b64_out)
    except Exception:
        await m.answer("🤖 (ошибка декодирования base64) Не удалось собрать картинку.")
        return

    photo_file = BufferedInputFile(out_bytes, filename="generated.png")
    caption = data.get("caption") or user_prompt[:200]

    await m.answer_photo(photo=photo_file, caption=caption)

# -------------------- Photo -> API (image edit) --------------------
@router.message(F.photo)
async def on_photo_edit(m: Message, state: FSMContext):
    await state.clear()

    user_prompt = (m.caption or "").strip()
    if not user_prompt:
        await m.answer(
            "Добавьте подпись к фото с инструкцией, например:\n"
            "<i>сделай так, как будто этот человек с розовыми волосами</i>"
        )
        return

    try:
        photo = m.photo[-1]
        tg_file = await bot.get_file(photo.file_id)
        buf = await bot.download_file(tg_file.file_path)
        if buf is None:
            raise RuntimeError("bot.download_file вернул None")

        buf.seek(0)
        image_bytes = buf.read()
        if not image_bytes:
            raise RuntimeError("скачанные данные пустые")

        image_b64 = base64.b64encode(image_bytes).decode("ascii")
    except Exception as e:
        await m.answer(
            f"Ошибка при получении фото из Telegram: {e.__class__.__name__}: {e}"
        )
        return

    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
            usage_r = await client.post(
                f"{API_BASE}/usage/increment",
                json={"chat_id": m.chat.id, "kind": "images", "value": 1},
                timeout=10,
            )

            if usage_r.status_code == 402:
                await m.answer(
                    "Лимит редактирования изображений исчерпан.\n"
                    "Открой «📄 Моя подписка», чтобы докупить лимиты или сменить план."
                )
                return

            if usage_r.status_code != 200:
                await m.answer("Не удалось проверить лимит изображений. Попробуй чуть позже.")
                return

            r = await client.post(
                f"{API_BASE}/image/edit",
                json={
                    "chat_id": m.chat.id,
                    "prompt": user_prompt,
                    "image_b64": image_b64,
                    "size": "1024x1024",
                },
                timeout=60,
            )
    except httpx.ReadTimeout:
        await m.answer("🤖 (таймаут API) Не удалось обработать фото.")
        return
    except Exception as e:
        await m.answer(f"🤖 (ошибка сети) Не удалось отправить фото в API: {e}")
        return

    if r.status_code != 200:
        await m.answer("🤖 (сбой API) Не удалось обработать фото.")
        return

    data = r.json()

    if data.get("stub"):
        await m.answer(
            data.get("caption") or "🧪 (симуляция) Изображение обработано."
        )
        return

    b64_out = data.get("b64")
    if not b64_out:
        await m.answer("🤖 (ошибка API) Пустой ответ при обработке фото.")
        return

    try:
        out_bytes = base64.b64decode(b64_out)
    except Exception:
        await m.answer("🤖 (ошибка декодирования base64) Не удалось собрать картинку.")
        return

    photo_file = BufferedInputFile(out_bytes, filename="edited.png")
    caption = data.get("caption") or user_prompt[:200]

    await m.answer_photo(photo=photo_file, caption=caption)
@router.message(F.text & ~F.text.startswith("/"))
async def any_text(m: Message, state: FSMContext):
    # если пользователь сейчас в режиме ввода промпта для генерации картинок — сюда не лезем
    if await state.get_state() == ImgFlow.waiting_prompt.state:
        return

    text = (m.text or "").strip()
    if not text:
        return

    # не шлём в ИИ системные кнопки нижнего меню
    if text in {
        "👤 Мой профиль",
        "💬 Мои чаты",
        "📄 Моя подписка",
        "🖼 Генерация изображений",
        "🎁 Премиум бесплатно",
        "💰 Пополнить баланс",
    }:
        return

    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
            # сначала проверяем /списываем лимит текстовых сообщений
            try:
                usage_r = await client.post(
                    f"{API_BASE}/usage/increment",
                    json={"chat_id": m.chat.id, "kind": "messages", "value": 1},
                    timeout=10,
                )
            except Exception:
                usage_r = None

            if usage_r is not None:
                if usage_r.status_code == 402:
                    await m.answer(
                        "Лимит текстовых сообщений исчерпан.\n"
                        "Открой «📄 Моя подписка», чтобы докупить лимиты или сменить план."
                    )
                    return
                if usage_r.status_code not in (200, 204):
                    await m.answer("Не удалось проверить лимит сообщений. Попробуй чуть позже.")
                    return

            # всё ок по лимитам — шлём сообщение в бэкенд-чаты (там уже и история, и OpenAI)
            r = await client.post(
                f"{API_BASE}/chats/{m.chat.id}/message",
                json={"text": text},
                timeout=60,
            )
    except httpx.ReadTimeout:
        await m.answer("🤖 (таймаут API) Не удалось получить ответ.")
        return
    except Exception as e:
        await m.answer(f"🤖 (ошибка сети) Не удалось отправить запрос в API: {e}")
        return

    if r.status_code == 200:
        reply = r.json().get("reply", "🤖 (симуляция) Ответ.")
        await m.answer(reply)
    else:
        await m.answer("Не удалось сохранить сообщение. API недоступен?")

# -------------------- Webhook glue --------------------
async def process_update_fastapi(body: dict):
    update = Update.model_validate(body)
    await dp.feed_update(bot, update)

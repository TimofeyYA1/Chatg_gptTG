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

# -------------------- helpers: build subscription view --------------------
async def build_subscription_view(chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{API_BASE}/subscriptions/summary/{chat_id}")
    r.raise_for_status()
    data = r.json()
    role = data["role"]
    bal = data["balance_cents"] / 100
    u, L, A, T = data["usage"], data["limits"], data["addons"], data["totals"]

    text = (
         f"💎 Подписка: {role}\n" +
    (
        f"📅 Активна до: {data['active_until'][:10]} "
        f"{'(автопродление выключено)' if not data.get('auto_renew', True) and role!='free' else ''}\n"
        if role != "free" and data.get("active_until") else
        "📅 Активна: отсутствует (free)\n"
    ) +
        f"💰 Баланс: {bal:.0f}⭐\n\n"
        "📊 Использование и лимиты:\n"
        f"— Сообщения: {u['messages']}/{T['messages']} "
        f"(базовый лимит {L['messages']}" + (f", докуплено {A['messages']}" if A['messages'] else "") + ")\n"
        f"— Изображения: {u['images']}/{T['images']} "
        f"(базовый лимит {L['images']}" + (f", докуплено {A['images']}" if A['images'] else "") + ")\n"
        f"— Видео: {u['video']}/{T['video']} "
        f"(базовый лимит {L['video']}" + (f", докуплено {A['video']}" if A['video'] else "") + ")\n\n"
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

# Создание нового чата (с именем)
@router.callback_query(F.data == "chats:create")
async def cb_create_chat_start(c: CallbackQuery, state: FSMContext):
    await state.set_state(ChatCreateFlow.waiting_title)
    await c.message.answer(
        "🆕 Введите название нового чата (до 100 символов).\n"
        "Можно нажать «➡️ Пропустить», чтобы использовать имя по умолчанию.",
        reply_markup=chat_create_prompt_kb(),
    )
    await c.answer()

@router.callback_query(F.data == "chat:new:cancel")
async def cb_create_chat_cancel(c: CallbackQuery, state: FSMContext):
    await state.clear()
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{API_BASE}/chats/{c.message.chat.id}")
    await c.message.answer("Отмена. Список чатов:", reply_markup=chats_inline_kb(r.json()["items"]))
    await c.answer("Отменено")

@router.callback_query(F.data == "chat:new:skip")
async def cb_create_chat_skip(c: CallbackQuery, state: FSMContext):
    await state.clear()
    async with httpx.AsyncClient() as client:
        await client.post(f"{API_BASE}/chats/{c.message.chat.id}/create", json={"title": None})
        r = await client.get(f"{API_BASE}/chats/{c.message.chat.id}")
    await c.message.answer("Чат создан ✅", reply_markup=chats_inline_kb(r.json()["items"]))
    await c.answer("Готово")

@router.message(ChatCreateFlow.waiting_title)
async def receive_new_chat_title(m: Message, state: FSMContext):
    title = (m.text or "").strip()
    if len(title) > 100:
        await m.answer("Название слишком длинное. До 100 символов, либо «➡️ Пропустить».", reply_markup=chat_create_prompt_kb())
        return
    async with httpx.AsyncClient() as client:
        await client.post(f"{API_BASE}/chats/{m.chat.id}/create", json={"title": title or None})
        r = await client.get(f"{API_BASE}/chats/{m.chat.id}")
    await m.answer(f"Чат «<b>{title or 'Чат'}</b>» создан ✅", reply_markup=chats_inline_kb(r.json()["items"]))
    await state.clear()

# Активация
@router.callback_query(F.data.startswith("chats:activate:"))
async def cb_activate_chat(c: CallbackQuery):
    sid = int(c.data.split(":")[2])
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{API_BASE}/chats/{c.message.chat.id}/{sid}/activate")
        # если 500 — r.json() упадёт; отдаём понятное сообщение
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

# Удаление конкретного чата (НОВОЕ)
@router.callback_query(F.data.startswith("chats:delete:"))
async def cb_delete_chat(c: CallbackQuery):
    sid = int(c.data.split(":")[2])

    # удаляем чат и просто обновляем список, без доп. сообщений
    async with httpx.AsyncClient(timeout=8.0) as client:
        await client.post(f"{API_BASE}/chats/{c.message.chat.id}/{sid}/delete")
        r2 = await client.get(f"{API_BASE}/chats/{c.message.chat.id}")

    await c.message.edit_reply_markup(reply_markup=chats_inline_kb(r2.json()["items"]))
    await c.answer("Чат удалён")  # короткий toast, НИЧЕГО в чат не отправляем

@router.callback_query(F.data.startswith("chats:clear"))
async def cb_clear_chats(c: CallbackQuery):
    chat_id = c.message.chat.id
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{API_BASE}/chats/{chat_id}/clear")
        ok = r.status_code == 200
        data = r.json() if ok else {}
        items = (data.get("items") or [])
        # если по какой-то причине items не пришёл, добираем свежий список
        if not items:
            r2 = await client.get(f"{API_BASE}/chats/{chat_id}")
            if r2.status_code == 200:
                items = r2.json().get("items", [])

    kb = chats_inline_kb(items) if items else chats_inline_kb([])

    # безопасно обновляем клавиатуру: если нельзя редактировать — шлём новое сообщение
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
    await m.answer("🖼 Введите описание изображения. (Сейчас заглушка вернёт текст)")

@router.message(ImgFlow.waiting_prompt)
async def receive_image_prompt(m: Message, state: FSMContext):
    prompt = (m.text or "").strip()
    if not prompt:
        await m.answer("Опишите изображение текстом.")
        return

    img_bytes: BytesIO | None = None
    api_status = None

    try:
        async with httpx.AsyncClient() as client:
            # пробуем увеличить usage (не критично при сбое)
            try:
                await client.post(
                    f"{API_BASE}/usage/increment",
                    json={"chat_id": m.chat.id, "kind": "images", "value": 1},
                    timeout=10,
                )
            except Exception:
                pass

            # вызываем API генерации
            r = await client.post(
                f"{API_BASE}/image/generate",
                json={"chat_id": m.chat.id, "prompt": prompt, "size": "512x512"},
                timeout=60,
            )
            api_status = r.status_code

        if api_status == 200:
            data = r.json()
            if "b64" in data and data["b64"]:
                raw = base64.b64decode(data["b64"])
                img_bytes = BytesIO(raw)
            elif "url" in data and data["url"]:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(data["url"], timeout=60)
                if resp.status_code == 200:
                    img_bytes = BytesIO(resp.content)
    except Exception:
        img_bytes = None

    # путь к твоей заглушке
    fallback_path = os.path.join(os.path.dirname(__file__), "topper.jpg")

    if img_bytes is None:
        # если генерация не удалась — отправляем topper.jpg
        photo = FSInputFile(fallback_path)
        caption = (
            "🧪 (не удалось подключиться к сервису изображений) "
            "Возвращаю заглушку.\n"
            f"Prompt: <i>{prompt}</i>"
        )
        await m.answer_photo(photo=photo, caption=caption)
    else:
        # если всё получилось — отправляем сгенерированное изображение
        img_bytes.seek(0)
        await m.answer_photo(photo=img_bytes, caption=f"🧪 Изображение сгенерировано.\nPrompt: <i>{prompt}</i>")

    await state.clear()

# -------------------- Text -> API --------------------
@router.message(F.text & ~F.text.startswith("/"))
async def any_text(m: Message):
    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
            r = await client.post(f"{API_BASE}/chats/{m.chat.id}/message", json={"text": m.text})
        if r.status_code == 200:
            reply = r.json().get("reply", "🤖 (симуляция) Ответ.")
            await m.answer(reply)
        else:
            await m.answer("🤖 (сбой API) Отправил заглушку.")
    except httpx.ReadTimeout:
        await m.answer("🤖 (таймаут API) Отправляю заглушку: я получил ваше сообщение и обработаю его короче.")
    except Exception:
        await m.answer("🤖 (ошибка сети) Пока вернул заглушку.")

# -------------------- Webhook glue --------------------
async def process_update_fastapi(body: dict):
    update = Update.model_validate(body)
    await dp.feed_update(bot, update)

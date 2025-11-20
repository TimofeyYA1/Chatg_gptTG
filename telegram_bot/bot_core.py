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
from aiogram.types import BufferedInputFile
import os
import base64
import re
from common.config import settings
from io import BytesIO
from pypdf import PdfReader

from openai import OpenAI

# PDF-генерация
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY


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

DEEPGRAM_API_KEY = getattr(settings, "DEEPGRAM_API_KEY", "")

MAX_CONTEXT_CHARS = 12_000
MAX_DOC_CHARS = 8000      # сколько символов максимум берём из документа в контекст
MAX_EXPORT_CHARS = 8000   # сколько максимум текста вывозим в голос/PDF

# OpenAI TTS
OPENAI_TTS_API_KEY = getattr(settings, "OPENAI_API_KEY", "")
OPENAI_TTS_MODEL = getattr(settings, "OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
TTS_CLIENT = OpenAI(api_key=OPENAI_TTS_API_KEY) if OPENAI_TTS_API_KEY else None

# -------------------- PDF font --------------------
PDF_FONT_PATH = "/app/fonts/ARIALBD.TTF"  # скопирован через Dockerfile
PDF_FONT_NAME = "BotArial"

if pdf_canvas is not None:
    if os.path.exists(PDF_FONT_PATH):
        try:
            pdfmetrics.registerFont(TTFont(PDF_FONT_NAME, PDF_FONT_PATH))
            print(f"PDF: зарегистрирован шрифт {PDF_FONT_NAME} из {PDF_FONT_PATH}")
        except Exception as e:
            print(f"PDF: не удалось зарегистрировать шрифт {PDF_FONT_PATH}: {e}")
            PDF_FONT_NAME = "Helvetica"
    else:
        print(f"PDF: файл шрифта не найден: {PDF_FONT_PATH}")
        PDF_FONT_NAME = "Helvetica"
else:
    PDF_FONT_NAME = None

# хранение текстов ответов ИИ по сообщению бота
LAST_AI_MESSAGES: dict[tuple[int, int], str] = {}

# -------------------- Pricing --------------------
PRICE_PLAN_LIGHT = 275_00
PRICE_PLAN_MAX = 450_00
PRICE_PLAN_ULTRA = 1333_00

ADDON_PRICES = {
    "messages": {50: 50_00, 200: 180_00, 500: 400_00},
    "images": {100: 120_00, 500: 500_00, 1000: 900_00},
}

# -------------------- FSM --------------------
class ImgFlow(StatesGroup):
    waiting_prompt = State()


class ChatCreateFlow(StatesGroup):
    waiting_title = State()


class ChatRenameFlow(StatesGroup):
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
        [InlineKeyboardButton(text="⚙️ Изменить план", callback_data="sub:change")],
        [InlineKeyboardButton(text="❌ Завершить подписку", callback_data="sub:cancel")],
    ])


def addon_options_kb(kind: str) -> InlineKeyboardMarkup:
    rows = []
    for qty, price in ADDON_PRICES[kind].items():
        rows.append([
            InlineKeyboardButton(
                text=f"+{qty} за {price // 100}⭐",
                callback_data=f"addon:buy:{kind}:{qty}:{price}",
            )
        ])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="sub:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def plans_inline_kb_with_text() -> tuple[str, InlineKeyboardMarkup]:
    text = (
        "🔁 Изменение тарифного плана.\n\n"
        "Выбирайте подходящий вариант работы с ботом:\n\n"
        "💠 Light\n"
        "• До 50 текстовых запросов в день\n"
        "• До 500 изображений в месяц\n"
        "• Голосовые до 1 минуты\n"
        "• Голосовые ответы: нет\n"
        "• Экспорт в .docx/.pdf: нет\n"
        f"• Стоимость: {PRICE_PLAN_LIGHT // 100}⭐ в месяц\n\n"
        "💠 Max\n"
        "• До 100 текстовых запросов в день\n"
        "• До 1000 изображений в месяц\n"
        "• Голосовые до 10 минут\n"
        "• Голосовые ответы: да\n"
        "• Экспорт в .docx/.pdf: да\n"
        f"• Стоимость: {PRICE_PLAN_MAX // 100}⭐ в месяц\n\n"
        "💠 Ultra\n"
        "• До 500 текстовых запросов в день\n"
        "• До 2500 изображений в месяц\n"
        "• Голосовые до 20 минут\n"
        "• Голосовые ответы: да\n"
        "• Экспорт в .docx/.pdf: да\n"
        f"• Стоимость: {PRICE_PLAN_ULTRA // 100}⭐ в месяц\n\n"
        "После смены плана лимиты и использование будут пересчитываться от нового тарифа."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💠 Light", callback_data=f"sub:buyplan:Light:{PRICE_PLAN_LIGHT}")],
        [InlineKeyboardButton(text="💠 Max", callback_data=f"sub:buyplan:Max:{PRICE_PLAN_MAX}")],
        [InlineKeyboardButton(text="⚡ Ultra", callback_data=f"sub:buyplan:Ultra:{PRICE_PLAN_ULTRA}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="sub:open")],
    ])
    return text, kb

def chats_inline_kb(items: list[dict]) -> InlineKeyboardMarkup:
    """
    Каждая строка: [активация чата] [переименовать] [удалить]
    Активный помечаем ⭐, неактивный — 🟢
    """
    rows = []
    for s in items:
        icon = "⭐" if s["is_active"] else "🟢"
        rows.append([
            InlineKeyboardButton(text=f"{icon} {s['title']}", callback_data=f"chats:activate:{s['id']}"),
            InlineKeyboardButton(text="✏️", callback_data=f"chats:rename:{s['id']}"),
            InlineKeyboardButton(text="🗑", callback_data=f"chats:delete:{s['id']}"),
        ])
    rows.append([InlineKeyboardButton(text="➕ Добавить новый чат", callback_data="chats:create")])
    rows.append([InlineKeyboardButton(text="🗑 Удалить все чаты", callback_data="chats:clear")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def topup_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пополнить +100", callback_data="balance:topup:10000")],
        [InlineKeyboardButton(text="Пополнить +500", callback_data="balance:topup:50000")],
        [InlineKeyboardButton(text="Пополнить +1000", callback_data="balance:topup:100000")],
    ])


def chat_create_prompt_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Пропустить", callback_data="chat:new:skip")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="chat:new:cancel")],
    ])

def chat_rename_prompt_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="chat:rename:cancel")],
    ])

@router.callback_query(F.data.startswith("chats:rename:"))
async def cb_rename_chat_start(c: CallbackQuery, state: FSMContext):
    sid = int(c.data.split(":")[2])

    await state.set_state(ChatRenameFlow.waiting_title)
    await state.update_data(
        rename_chat_id=sid,
        list_msg_id=c.message.message_id,
    )

    msg = await c.message.answer(
        "✏️ Введите новое название для чата (до 100 символов).",
        reply_markup=chat_rename_prompt_kb(),
    )
    await state.update_data(prompt_msg_id=msg.message_id)
    await c.answer()


@router.message(ChatRenameFlow.waiting_title)
async def receive_renamed_chat_title(m: Message, state: FSMContext):
    data = await state.get_data()
    sid = data.get("rename_chat_id")
    list_msg_id = data.get("list_msg_id")
    prompt_msg_id = data.get("prompt_msg_id")

    title = (m.text or "").strip()

    if not title:
        await m.answer(
            "Название не может быть пустым. Введите новое название или нажмите «Отмена».",
            reply_markup=chat_rename_prompt_kb(),
        )
        return

    if len(title) > 100:
        await m.answer(
            "Название слишком длинное. До 100 символов.",
            reply_markup=chat_rename_prompt_kb(),
        )
        return

    # вызываем API для переименования
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{API_BASE}/chats/{m.chat.id}/{sid}/rename",
            json={"title": title},
        )

    if r.status_code != 200:
        await m.answer("Не удалось переименовать чат (ошибка API). Попробуй позже.")
    else:
        # обновляем список чатов в старом сообщении
        if list_msg_id:
            await _refresh_chats_markup(m.chat.id, list_msg_id)
    # чистим лишнее
    if prompt_msg_id:
        await _safe_delete(m.chat.id, prompt_msg_id)
    await _safe_delete(m.chat.id, m.message_id)

    await state.clear()


def export_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔊 Получить голосовое",
                    callback_data="export:voice",
                ),
                InlineKeyboardButton(
                    text="📄 Экспорт в PDF",
                    callback_data="export:pdf",
                ),
            ]
        ]
    )


# -------------------- helpers --------------------
async def _refresh_chats_markup(chat_id: int, list_msg_id: int):
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


async def transcribe_voice_with_deepgram(audio_bytes: bytes) -> str:
    if not DEEPGRAM_API_KEY:
        return ""

    dg_url = "https://api.deepgram.com/v1/listen?model=general&language=ru"

    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        r = await client.post(
            dg_url,
            headers={
                "Authorization": f"Token {DEEPGRAM_API_KEY}",
                "Content-Type": "audio/ogg",
            },
            content=audio_bytes,
        )

    if r.status_code != 200:
        return ""

    try:
        data = r.json()
        return (
            data.get("results", {})
            .get("channels", [{}])[0]
            .get("alternatives", [{}])[0]
            .get("transcript", "")
            .strip()
        )
    except Exception:
        return ""


def _extract_text_from_document(filename: str, mime_type: str | None, data: bytes) -> str:
    name_lower = (filename or "").lower()
    mime = (mime_type or "").lower()

    if "pdf" in mime or name_lower.endswith(".pdf"):
        if not PdfReader:
            return ""
        try:
            reader = PdfReader(BytesIO(data))
            parts: list[str] = []
            for page in reader.pages:
                try:
                    parts.append(page.extract_text() or "")
                except Exception:
                    continue
            return "\n".join(parts)
        except Exception:
            return ""

    if "text" in mime or name_lower.endswith(".txt"):
        try:
            return data.decode("utf-8", errors="ignore")
        except Exception:
            return ""

    return ""


def _strip_html(text: str) -> str:
    if not text:
        return ""
    # выкидываем простые HTML-теги <...>
    return re.sub(r"<[^>]+>", "", text)


def make_pdf_from_text(text: str) -> bytes | None:
    """
    Рендер текста в PDF с автоматическим переносом строк и пагинацией.
    Используем Platypus (SimpleDocTemplate + Paragraph), чтобы ничего не вылезало за рамки.
    """
    if pdf_canvas is None or PDF_FONT_NAME is None:
        return None

    safe_text = _strip_html(text or "")[:MAX_EXPORT_CHARS]
    if not safe_text:
        return None

    buf = BytesIO()

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=40,
        bottomMargin=40,
    )

    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontName=PDF_FONT_NAME,
        fontSize=11,
        leading=14,
        alignment=TA_JUSTIFY,
    )

    # переводим \n в <br/>, спецсимволы экранируем
    txt = safe_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    txt = txt.replace("\n", "<br/>")

    story = [Paragraph(txt, body_style)]

    doc.build(story)
    buf.seek(0)
    return buf.read()


# -------------------- helpers: build subscription view --------------------
async def build_subscription_view(chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{API_BASE}/subscriptions/summary/{chat_id}")
    r.raise_for_status()
    data = r.json()

    role = data.get("role", "free")
    bal = (data.get("balance_cents") or 0) / 100

    limits = data.get("limits") or {"messages": 0, "images": 0, "video": 0}
    active_until = data.get("active_until")
    auto_renew = data.get("auto_renew", False)

    usage = data.get("usage") or {"messages": 0, "images": 0, "video": 0}
    addons = data.get("addons") or {"messages": 0, "images": 0, "video": 0}
    totals = data.get("totals") or {
        "messages": (limits.get("messages", 0) + addons.get("messages", 0)),
        "images": (limits.get("images", 0) + addons.get("images", 0)),
        "video": limits.get("video", 0) + addons.get("video", 0),
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
        header
        + "📊 Использование и лимиты:\n"
        f"— Сообщения: {usage.get('messages', 0)}/{totals.get('messages', 0)} "
        f"(базовый лимит {limits.get('messages', 0)}"
        + (f", докуплено {addons.get('messages', 0)}" if addons.get("messages") else "")
        + ")\n"
        f"— Изображения: {usage.get('images', 0)}/{totals.get('images', 0)} "
        f"(базовый лимит {limits.get('images', 0)}"
        + (f", докуплено {addons.get('images', 0)}" if addons.get("images") else "")
        + ")\n"
        "Можешь докупить лимиты или изменить/завершить план:"
    )

    return text, sub_card_kb()


# -------------------- /start --------------------
@router.message(Command("start"))
async def cmd_start(m: Message):
    # ---------- Блок рефералки /start <referrer_chat_id> ----------
    referrer_chat_id: int | None = None
    raw = (m.text or "").strip()
    parts = raw.split(maxsplit=1)
    if len(parts) == 2:
        try:
            referrer_chat_id = int(parts[1])
        except ValueError:
            referrer_chat_id = None

    if referrer_chat_id and referrer_chat_id != m.chat.id:
        try:
            async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
                r = await client.post(
                    f"{API_BASE}/referrals/register",
                    json={
                        "referrer_chat_id": referrer_chat_id,
                        "invited_chat_id": m.chat.id,
                    },
                )
            if r.status_code == 200:
                data = r.json()
                if data.get("ok") and data.get("bonus_cents", 0) > 0:
                    bonus_stars = data["bonus_cents"] // 100
                    try:
                        await bot.send_message(
                            referrer_chat_id,
                            (
                                "🎁 По твоей реферальной ссылке пришёл новый пользователь!\n"
                                f"Тебе начислено <b>+{bonus_stars}⭐</b> на баланс."
                            ),
                        )
                    except Exception:
                        # не ломаем /start для приглашённого, если пуш не доставился
                        pass
        except Exception:
            # тихо игнорируем ошибки рефералки, чтобы не ломать флоу старта
            pass

    # ---------- Дальше твой текущий intro-текст ----------
    intro = (
        "Рад видеть! 👋\n\n"
        "<b>Как пользоваться ботом:</b>\n\n"
        "📝 <b>Текстовые запросы</b>\n"
        "— Просто напишите сообщение в этот чат: вопрос, задачу, идею.\n"
        "— Бот ответит текстом и будет учитывать предыдущие сообщения в этом чате, "
        "поэтому контекст сохраняется.\n"
        "— Чтобы разделить разные темы, можно создавать отдельные чаты в разделе «💬 Мои чаты».\n\n"
        "🎙 <b>Голосовые сообщения</b>\n"
        "— Отправьте голосовое сообщение — бот автоматически распознает речь.\n"
        "— Распознанный текст покажет вам и отправит в ИИ как обычный текстовый запрос.\n"
        "— Лимит сообщений расходуется так же, как при обычных текстах.\n\n"
        "🖼 <b>Генерация изображений</b>\n"
        "— Нажмите кнопку «🖼 Генерация изображений» в нижнем меню.\n"
        "— Бот переведет вас в режим генерации и попросит ввести <b>промпт</b> — текстовое описание картинки.\n"
        "— Просто напишите, что хотите увидеть (например: «кот в костюме астронавта на Луне»).\n"
        "— Бот покажет статус «идёт генерация», а после — отправит готовое изображение.\n\n"
        "✏️ <b>Редактирование изображений</b>\n"
        "— Отправьте фото или картинку в чат.\n"
        "— В подписи к изображению добавьте текстовую инструкцию, что нужно изменить "
        "(например: «сделай фон размытым» или «добавь неоновую подсветку»).\n"
        "— Бот обработает изображение и пришлёт новую версию.\n\n"
        "📎 <b>Документы (PDF, TXT)</b>\n"
        "— Можно отправить файл (например, PDF или текстовый .txt) прямо в чат.\n"
        "— Бот прочитает документ и добавит его содержимое в контекст текущего чата.\n"
        "— После этого можно задавать вопросы по файлу: просить объяснить, кратко пересказать, "
        "выделить главное, придумать конспект и т.д.\n"
        "— Если файл большой, бот сохранит только первую часть, чтобы не перегружать контекст.\n\n"
        "📄 <b>Подписка и лимиты</b>\n"
        "— В разделе «📄 Моя подписка» можно посмотреть текущий тариф, лимиты сообщений и изображений.\n"
        "— Там же можно докупить сообщения или изображения, изменить план или отключить автопродление.\n\n"
        "💬 <b>Итого</b>\n"
        "— Хотите общаться с ИИ текстом, голосом или через документы — просто пишите, говорите или отправляйте файлы в этот чат.\n"
        "— История сообщений в каждом чате учитывается, поэтому ИИ помнит контекст внутри выбранного чата.\n\n"
        "Готов, когда будешь ты — просто отправь первый запрос 👇"
    )
    await m.answer(intro, reply_markup=bottom_menu_kb())


# -------------------- Profile --------------------
@router.message(Command("account"))
@router.message(F.text == "👤 Мой профиль")
async def cmd_account(m: Message):
    async with httpx.AsyncClient() as client:
        # профиль
        r = await client.get(f"{API_BASE}/account/profile/{m.chat.id}")
        # рефералка
        r_ref = await client.get(f"{API_BASE}/referrals/summary/{m.chat.id}")

    if r.status_code != 200:
        await m.answer("API недоступен.")
        return

    data = r.json()
    bal = (data.get("balance_cents") or 0) / 100
    role = data.get("role", "free")

    usage = data.get("usage") or {}
    used_msg = usage.get("messages", 0)
    used_img = usage.get("images", 0)
    used_video = usage.get("video", 0)

    # рефералка
    if r_ref.status_code == 200:
        ref_data = r_ref.json()
        invited = ref_data.get("invited", 0)
        subscribed = ref_data.get("subscribed", 0)
        ref_link = ref_data.get(
            "ref_link",
            f"https://t.me/{settings.BOT_NAME}?start={m.chat.id}",
        )
    else:
        invited = 0
        subscribed = 0
        ref_link = f"https://t.me/{settings.BOT_NAME}?start={m.chat.id}"

    text = (
        "👤 Мой профиль\n"
        f"👤 @{(m.from_user.username or 'unknown')}\n"
        f"💰 Баланс: {bal:.2f}⭐️\n"
        f"🔖 Подписка: {role}\n\n"
        "📊 Статистика использования (за текущий период):\n"
        f"— Сообщения (текст): {used_msg}\n"
        f"— Изображения: {used_img}\n\n"
        "👥 Реферальная программа:\n"
        f"— Приглашено друзей: {invited}\n"
        f"— Оформили подписку: {subscribed}\n\n"
        f"🔗 Твоя реферальная ссылка:\n{ref_link}"
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
        data = r.json()

        await c.answer(f"Подписка обновлена: {plan}.", show_alert=True)
        text, kb = await build_subscription_view(c.message.chat.id)
        try:
            await c.message.edit_text(text, reply_markup=kb)
        except Exception:
            await bot.send_message(c.message.chat.id, text, reply_markup=kb)

        # 🔔 Проверяем, был ли реферальный бонус за подписку
        ref_bonus = (data or {}).get("referral_bonus") or {}
        if ref_bonus.get("applied"):
            bonus_cents = ref_bonus.get("bonus_cents") or 0
            bonus_stars = bonus_cents // 100
            referrer_chat_id = ref_bonus.get("referrer_chat_id")
            invited_chat_id = ref_bonus.get("invited_chat_id")

            # Сообщение тому, кто только что купил подписку
            if invited_chat_id:
                await bot.send_message(
                    invited_chat_id,
                    (
                        "🎉 Ты оформил платную подписку по реферальной ссылке!\n"
                        f"Тебе начислено <b>+{bonus_stars}⭐</b>, "
                        "и столько же получил твой друг."
                    ),
                )

            # Сообщение рефереру
            if referrer_chat_id and referrer_chat_id != invited_chat_id:
                await bot.send_message(
                    referrer_chat_id,
                    (
                        "🎉 По твоей реферальной ссылке оформили платную подписку!\n"
                        f"Тебе начислено <b>+{bonus_stars}⭐</b> на баланс."
                    ),
                )

    elif r.status_code == 402:
        await c.answer("Недостаточно средств. Пополни баланс.", show_alert=True)
    else:
        await c.answer("Ошибка при изменении плана.", show_alert=True)


@router.callback_query(F.data == "sub:cancel")
async def cb_plan_cancel(c: CallbackQuery):
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{API_BASE}/subscriptions/cancel", json={"chat_id": c.message.chat.id})
    if r.status_code == 200:
        await c.answer("Подписка активна до окончания оплаченного периода.", show_alert=True)
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

        if r.status_code == 200:
            data = r.json()
            invited = data.get("invited", 0)
            subscribed = data.get("subscribed", 0)
            ref_link = data.get(
                "ref_link",
                f"https://t.me/{getattr(settings, 'BOT_NAME', 'ai_superbot')}?start={m.chat.id}",
            )
        else:
            invited = 0
            subscribed = 0
            ref_link = f"https://t.me/{getattr(settings, 'BOT_NAME', 'ai_superbot')}?start={m.chat.id}"
    except Exception:
        invited = 0
        subscribed = 0
        ref_link = f"https://t.me/{getattr(settings, 'BOT_NAME', 'ai_superbot')}?start={m.chat.id}"

    text = (
        "🎁 <b>Реферальная программа</b>\n\n"
        "<b>Как это работает:</b>\n"
        "1️⃣ Поделись своей уникальной ссылкой с друзьями.\n"
        "2️⃣ За каждого друга (до 20), который просто начнёт пользоваться ботом —\n"
        "   ты получаешь +10 звезд на аккаунт в ботею.\n"
        "3️⃣ Если друг оформит любую платную подписку по твоей ссылке —\n"
        "   вы оба получите:\n"
        "   • <b>+100 звезд</b>\n"
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


@router.callback_query(F.data == "chats:create")
async def cb_create_chat_start(c: CallbackQuery, state: FSMContext):
    await state.set_state(ChatCreateFlow.waiting_title)
    await state.update_data(list_msg_id=c.message.message_id)
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
    await c.answer("Создание чата отменено")


@router.callback_query(F.data == "chat:new:skip")
async def cb_create_chat_skip(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    list_msg_id = data.get("list_msg_id")
    prompt_msg_id = data.get("prompt_msg_id")

    async with httpx.AsyncClient() as client:
        await client.post(f"{API_BASE}/chats/{c.message.chat.id}/create")

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
    await _safe_delete(m.chat.id, m.message_id)

    await state.clear()


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
    preview = (
        f"Последнее сообщение в <b>{title}</b>:\n<i>{last}</i>"
        if last
        else f"<b>{title}</b> пока пустой."
    )
    await c.message.answer(preview)
    await c.answer("Сделан активным")


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


# -------------------- Image: generate --------------------
@router.message(Command("image"))
@router.message(F.text == "🖼 Генерация изображений")
async def cmd_image(m: Message, state: FSMContext):
    await state.set_state(ImgFlow.waiting_prompt)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить генерацию", callback_data="img:cancel")]
    ])

    await m.answer(
        "🖼 Введите текстовое описание изображения.\n\n"
        "• Чтобы сгенерировать новое изображение — просто напишите промпт.\n",
        reply_markup=kb,
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

    status_msg = None
    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
            status_msg = await m.answer("🖼 Генерирую ваше изображение, подождите…")

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
    finally:
        if status_msg:
            await _safe_delete(m.chat.id, status_msg.message_id)

    if r.status_code != 200:
        await m.answer("🤖 (сбой API) Не удалось сгенерировать изображение.")
        return

    data = r.json()

    if data.get("stub"):
        await m.answer(
            "⚠️ Провайдер не смог выдать изображение по этому запросу — "
            "либо запрос временно отклонён их модерацией, либо сервис перегружен.\n"
            "Попробуй немного переформулировать текст более нейтрально или убрать спорные детали "
            "и отправь запрос ещё раз.\n\n"
            f"📝 Текущий промпт:\n{user_prompt}"
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

    # --- 1) Фото с подписью ---

    photo_file = BufferedInputFile(out_bytes, filename="generated.png")
    made_caption = f"Made with ❤️ by @{getattr(settings, 'BOT_NAME', 'BeatyAIMasterHelpBot')}"
 
    await m.answer_photo(photo=photo_file, caption=made_caption)

    # --- 2) Отдельный файл для скачивания ---

    file_doc = BufferedInputFile(out_bytes, filename="generated.png")
    await m.answer_document(document=file_doc)

# -------------------- Photo -> API (image edit) --------------------
@router.edited_message(F.photo)
async def process_photo_edit(msg: Message, state: FSMContext):
    await state.clear()

    user_prompt = (msg.caption or "").strip()
    if not user_prompt:
        await msg.answer(
            "Добавьте подпись к фото с инструкцией, например:\n"
            "<i>сделай так, как будто этот человек с розовыми волосами</i>"
        )
        return

    # 1. тянем фото из Telegram
    try:
        photo = msg.photo[-1]
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
        await msg.answer(
            f"Ошибка при получении фото из Telegram: {e.__class__.__name__}: {e}"
        )
        return

    # 2. отправляем в API
    status_msg = None
    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
            status_msg = await msg.answer(
                "🖼 Генерирую изображение…\n"
                "Генерация обычно занимает 3–5 минут."
            )

            usage_r = await client.post(
                f"{API_BASE}/usage/increment",
                json={"chat_id": msg.chat.id, "kind": "images", "value": 1},
                timeout=10,
            )

            if usage_r.status_code == 402:
                await msg.answer(
                    "Лимит редактирования изображений исчерпан.\n"
                    "Открой «📄 Моя подписка», чтобы докупить лимиты или сменить план."
                )
                return

            if usage_r.status_code != 200:
                await msg.answer("Не удалось проверить лимит изображений. Попробуй чуть позже.")
                return

            r = await client.post(
                f"{API_BASE}/image/edit",
                json={
                    "chat_id": msg.chat.id,
                    "prompt": user_prompt,
                    "image_b64": image_b64,
                    "size": "1024x1024",
                },
                timeout=60,
            )
    except httpx.ReadTimeout:
        await msg.answer("🤖 (таймаут API) Не удалось обработать фото.")
        return
    except Exception as e:
        await msg.answer(f"🤖 (ошибка сети) Не удалось отправить фото в API: {e}")
        return
    finally:
        if status_msg:
            await _safe_delete(msg.chat.id, status_msg.message_id)

    # 3. разбираем ответ
    if r.status_code != 200:
        await msg.answer("🤖 (сбой API) Не удалось обработать фото.")
        return

    data = r.json()

    if data.get("stub"):
        await msg.answer(
            "⚠️ Провайдер отклонил этот запрос — похоже, часть промпта не проходит их модерацию.\n"
            "Попробуй переформулировать запрос более нейтрально или убрать чувствительные детали.\n\n"
            f"📝 Текущий промпт:\n{user_prompt}"
        )
        return

    b64_out = data.get("b64")
    if not b64_out:
        await msg.answer("🤖 (ошибка API) Пустой ответ при обработке фото.")
        return

    try:
        out_bytes = base64.b64decode(b64_out)
    except Exception:
        await msg.answer("🤖 (ошибка декодирования base64) Не удалось собрать картинку.")
        return

    # --- 1) Фото с подписью ---
    photo_file = BufferedInputFile(out_bytes, filename="edited.png")
    made_caption = f"Made with ❤️ by @{getattr(settings, 'BOT_NAME', 'BeatyAIMasterHelpBot')}"

    await msg.answer_photo(photo=photo_file, caption=made_caption)

    # --- 2) Отдельный файл для скачивания ---
    file_doc = BufferedInputFile(out_bytes, filename="edited.png")
    await msg.answer_document(document=file_doc)

@router.message(F.photo)
async def process_photo_edit(msg: Message, state: FSMContext):
    await state.clear()

    user_prompt = (msg.caption or "").strip()
    if not user_prompt:
        await msg.answer(
            "Добавьте подпись к фото с инструкцией, например:\n"
            "<i>сделай так, как будто этот человек с розовыми волосами</i>"
        )
        return

    # 1. тянем фото из Telegram
    try:
        photo = msg.photo[-1]
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
        await msg.answer(
            f"Ошибка при получении фото из Telegram: {e.__class__.__name__}: {e}"
        )
        return

    # 2. отправляем в API
    status_msg = None
    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
            status_msg = await msg.answer(
                "🖼 Генерирую изображение…\n"
                "Генерация обычно занимает 3–5 минут."
            )

            usage_r = await client.post(
                f"{API_BASE}/usage/increment",
                json={"chat_id": msg.chat.id, "kind": "images", "value": 1},
                timeout=10,
            )

            if usage_r.status_code == 402:
                await msg.answer(
                    "Лимит редактирования изображений исчерпан.\n"
                    "Открой «📄 Моя подписка», чтобы докупить лимиты или сменить план."
                )
                return

            if usage_r.status_code != 200:
                await msg.answer("Не удалось проверить лимит изображений. Попробуй чуть позже.")
                return

            r = await client.post(
                f"{API_BASE}/image/edit",
                json={
                    "chat_id": msg.chat.id,
                    "prompt": user_prompt,
                    "image_b64": image_b64,
                    "size": "1024x1024",
                },
                timeout=60,
            )
    except httpx.ReadTimeout:
        await msg.answer("🤖 (таймаут API) Не удалось обработать фото.")
        return
    except Exception as e:
        await msg.answer(f"🤖 (ошибка сети) Не удалось отправить фото в API: {e}")
        return
    finally:
        if status_msg:
            await _safe_delete(msg.chat.id, status_msg.message_id)

    # 3. разбираем ответ
    if r.status_code != 200:
        await msg.answer("🤖 (сбой API) Не удалось обработать фото.")
        return

    data = r.json()

    if data.get("stub"):
        await msg.answer(
            "⚠️ Провайдер отклонил этот запрос — кажется, формулировка промпта не проходит их модерацию.\n"
            "Попробуй упростить или перефразировать запрос, убрав потенциально запрещённые формулировки.\n\n"
            f"📝 Текущий промпт:\n{user_prompt}"
        )
        return

    b64_out = data.get("b64")
    if not b64_out:
        await msg.answer("🤖 (ошибка API) Пустой ответ при обработке фото.")
        return

    try:
        out_bytes = base64.b64decode(b64_out)
    except Exception:
        await msg.answer("🤖 (ошибка декодирования base64) Не удалось собрать картинку.")
        return

    # --- 1) Фото с подписью ---
    photo_file = BufferedInputFile(out_bytes, filename="edited.png")
    made_caption = f"Made with ❤️ by @{getattr(settings, 'BOT_NAME', 'BeatyAIMasterHelpBot')}"

    await msg.answer_photo(photo=photo_file, caption=made_caption)

    # --- 2) Отдельный файл для скачивания ---
    file_doc = BufferedInputFile(out_bytes, filename="edited.png")
    await msg.answer_document(document=file_doc)


@router.message(F.voice)
async def on_voice_message(m: Message, state: FSMContext):
    if await state.get_state() == ImgFlow.waiting_prompt.state:
        return

    if not DEEPGRAM_API_KEY:
        await m.answer(
            "Голосовой ввод пока не настроен (отсутствует ключ Deepgram). "
            "Пожалуйста, напишите текстом."
        )
        return

    try:
        tg_file = await bot.get_file(m.voice.file_id)
        buf = await bot.download_file(tg_file.file_path)
        if buf is None:
            raise RuntimeError("bot.download_file вернул None")

        buf.seek(0)
        audio_bytes = buf.read()
        if not audio_bytes:
            raise RuntimeError("скачанные данные пустые")
    except Exception as e:
        await m.answer(
            f"Не удалось получить голосовое из Telegram: {e.__class__.__name__}: {e}"
        )
        return

    status_msg = await m.answer("🎙 Распознаю голосовое сообщение, подождите…")

    try:
        text = await transcribe_voice_with_deepgram(audio_bytes)
    except Exception as e:
        await _safe_delete(m.chat.id, status_msg.message_id)
        await m.answer(f"Ошибка распознавания голоса: {e}")
        return

    await _safe_delete(m.chat.id, status_msg.message_id)

    if not text:
        await m.answer(
            "Не удалось распознать голосовое сообщение.\n"
            "Попробуй говорить чуть чётче или напиши текстом 🙂"
        )
        return

    await m.answer(f"🎙 Распознал запрос:\n<b>{text}</b>")

    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
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
                    await m.answer(
                        "Не удалось проверить лимит сообщений. Попробуй чуть позже."
                    )
                    return

            r = await client.post(
                f"{API_BASE}/chats/{m.chat.id}/message",
                json={"text": text},
                timeout=60,
            )
    except httpx.ReadTimeout:
        await m.answer("🤖 (таймаут API) Не удалось получить ответ на голосовой запрос.")
        return
    except Exception as e:
        await m.answer(
            f"🤖 (ошибка сети) Не удалось отправить голосовой запрос в API: {e}"
        )
        return

    if r.status_code == 200:
        reply = r.json().get("reply", "🤖 (симуляция) Ответ.")
        sent = await m.answer(reply, reply_markup=export_kb())
        LAST_AI_MESSAGES[(m.chat.id, sent.message_id)] = reply
    else:
        await m.answer("Не удалось сохранить сообщение. API недоступен?")


# -------------------- Text messages --------------------
@router.message(F.text & ~F.text.startswith("/"))
async def any_text(m: Message, state: FSMContext):
    if await state.get_state() == ImgFlow.waiting_prompt.state:
        return

    text = (m.text or "").strip()
    if not text:
        return

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
        sent = await m.answer(reply, reply_markup=export_kb())
        LAST_AI_MESSAGES[(m.chat.id, sent.message_id)] = reply
    else:
        await m.answer("Не удалось сохранить сообщение. API недоступен?")


@router.message(F.document)
async def on_document(m: Message, state: FSMContext):
    if await state.get_state() == ImgFlow.waiting_prompt.state:
        return

    doc = m.document
    if not doc:
        return

    try:
        tg_file = await bot.get_file(doc.file_id)
        buf = await bot.download_file(tg_file.file_path)
        if buf is None:
            raise RuntimeError("bot.download_file вернул None")

        buf.seek(0)
        data = buf.read()
        if not data:
            raise RuntimeError("скачанные данные пустые")
    except Exception as e:
        await m.answer(
            f"Не удалось получить файл из Telegram: {e.__class__.__name__}: {e}"
        )
        return

    status_msg = await m.answer("📎 Обрабатываю файл, подождите…")

    text_full = _extract_text_from_document(
        doc.file_name or "document",
        doc.mime_type,
        data,
    )

    await _safe_delete(m.chat.id, status_msg.message_id)

    if not text_full:
        await m.answer(
            "Не удалось прочитать этот тип файла.\n"
            "Сейчас поддерживаются PDF и текстовые файлы (.txt)."
        )
        return

    truncated = False
    if len(text_full) > MAX_DOC_CHARS:
        text = text_full[:MAX_DOC_CHARS]
        truncated = True
    else:
        text = text_full

    await m.answer(
        "📎 Файл прочитан и добавлен в контекст текущего чата.\n"
        "Теперь можно задавать вопросы по его содержимому."
        + ("\n\n(Документ большой, я сохранил только первую часть.)" if truncated else "")
    )

    meta_header = f"[Документ: {doc.file_name}] Ниже содержимое файла:\n\n"
    text_for_ai = meta_header + text

    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
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
                    await m.answer(
                        "Не удалось проверить лимит сообщений. Попробуй чуть позже."
                    )
                    return

            r = await client.post(
                f"{API_BASE}/chats/{m.chat.id}/message",
                json={"text": text_for_ai},
                timeout=60,
            )
            if r.status_code != 200:
                await m.answer(
                    "Файл прочитан, но не удалось сохранить его в историю чата (ошибка API)."
                )
    except httpx.ReadTimeout:
        await m.answer(
            "Файл прочитан, но при сохранении в историю чата произошёл таймаут API."
        )
    except Exception as e:
        await m.answer(
            f"Файл прочитан, но не удалось сохранить его в историю чата: {e}"
        )


# -------------------- Export callbacks --------------------
@router.callback_query(F.data == "export:voice")
async def cb_export_voice(c: CallbackQuery):
    chat_id = c.message.chat.id
    msg_id = c.message.message_id
    text = LAST_AI_MESSAGES.get((chat_id, msg_id)) or (c.message.text or "").strip()

    if not text:
        await c.answer("Нет текста для озвучки.", show_alert=True)
        return

    if not TTS_CLIENT or not OPENAI_TTS_API_KEY:
        await c.answer("Голосовой экспорт сейчас недоступен.", show_alert=True)
        return

    await c.answer()
    status = await c.message.reply("🔊 Собираю голосовой ответ…")

    try:
        resp = TTS_CLIENT.audio.speech.create(
            model=OPENAI_TTS_MODEL,
            voice="alloy",
            input=text[:MAX_EXPORT_CHARS],
        )
        audio_bytes = resp.read()
        voice_file = BufferedInputFile(audio_bytes, filename="answer.mp3")
        await c.message.reply_voice(voice_file)
    except Exception as e:
        await c.message.reply(f"Не удалось сгенерировать голосовой ответ: {e}")
    finally:
        await _safe_delete(chat_id, status.message_id)


@router.callback_query(F.data == "export:pdf")
async def cb_export_pdf(c: CallbackQuery):
    chat_id = c.message.chat.id
    msg_id = c.message.message_id
    text = LAST_AI_MESSAGES.get((chat_id, msg_id)) or (c.message.text or "").strip()

    if not text:
        await c.answer("Нет текста для экспорта.", show_alert=True)
        return

    if pdf_canvas is None or PDF_FONT_NAME is None:
        await c.answer("PDF-экспорт сейчас недоступен (нет подходящего шрифта).", show_alert=True)
        return

    await c.answer()
    status = await c.message.reply("📄 Формирую PDF-файл…")

    try:
        pdf_bytes = make_pdf_from_text(text)
        if not pdf_bytes:
            await c.message.reply("Не получилось сформировать PDF.")
        else:
            pdf_file = BufferedInputFile(pdf_bytes, filename="answer.pdf")
            await c.message.reply_document(pdf_file)
    finally:
        await _safe_delete(chat_id, status.message_id)


# -------------------- Webhook glue --------------------
async def process_update_fastapi(body: dict):
    update = Update.model_validate(body)
    await dp.feed_update(bot, update)

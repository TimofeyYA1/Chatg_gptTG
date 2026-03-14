from __future__ import annotations
import glob
import re
import os
import io
import base64
import asyncio
import sys
from datetime import date, datetime
from typing import Dict, Any, Optional
from urllib.parse import urlparse, urlunparse, urlencode

from telegram_bot import api_client
from telegram_bot import ui_elements as ui
from common.config import settings
from common.subscriptions import (
    ADDON_PRICE_RUB_BY_TIER,
    ADDON_PRICE_STARS_BY_TIER,
    ADDON_QTY as SUB_ADDON_QTY,
    PLAN_BY_KEY,
    get_plan_spec,
    normalize_plan_key,
    plan_title_ru,
    tier_code_from_plan,
    tier_name_ru,
)

from aiogram import Router, F, html 
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    Message, CallbackQuery,
    FSInputFile, BufferedInputFile, 
    ReplyKeyboardRemove, InputMediaPhoto,
    LabeledPrice, PreCheckoutQuery, ContentType,
    InlineKeyboardMarkup, InlineKeyboardButton,
    BotCommand, BotCommandScopeDefault, BotCommandScopeAllPrivateChats
)
from aiogram.exceptions import TelegramNetworkError, TelegramBadRequest
from datetime import timedelta 
import logging

router = Router()
logger = logging.getLogger(__name__)

# -------------------- CONFIG --------------------

BUY_LOCK: set[int] = set()
_MEDIA_CACHE: Dict[str, str] = {}

# Canonical subscription config, shared with API.
PLAN_TRANSLATE = {key: spec.title_ru for key, spec in PLAN_BY_KEY.items()}
PLAN_TRANSLATE.update(
    {
        "Week": "7 дней (Элит, legacy)",
        "Month": "месяц (Элит, legacy)",
        "Year": "год (Элит, legacy)",
        "Light": "7 дней (Старт, legacy)",
        "Max": "месяц (Про, legacy)",
        "Ultra": "месяц (Элит, legacy)",
        "free": "нет",
    }
)
PLAN_PRICES = {key: str(spec.price_rub) for key, spec in PLAN_BY_KEY.items()}
STARS_PRICES_SUB = {key: int(spec.price_stars) for key, spec in PLAN_BY_KEY.items()}
PKG_TOPUP_QTY = SUB_ADDON_QTY
RUB_PKG_BY_TIER = dict(ADDON_PRICE_RUB_BY_TIER)
STARS_PKG_BY_TIER = dict(ADDON_PRICE_STARS_BY_TIER)

ADMIN_IDS = settings.admin_id_list


def _plan_key_from_choice(period: str, tier: str) -> str:
    tier_norm = (tier or "start").lower()
    period_norm = (period or "month").lower()

    if period_norm == "month":
        if tier_norm in {"std", "start"}:
            return "Month_Std"
        if tier_norm == "pro":
            return "Month_Std2"
        return "Month_Pro"

    if period_norm == "week":
        return "Week_Std" if tier_norm in {"std", "start"} else "Week_Pro"

    if period_norm == "year":
        return "Year_Std" if tier_norm in {"std", "start"} else "Year_Pro"

    return normalize_plan_key(period) or "Month_Std"


def _tier_name_for_plan(plan_key: str) -> str:
    spec = get_plan_spec(plan_key)
    if spec:
        return tier_name_ru(spec.tier)
    return tier_name_ru(tier_code_from_plan(plan_key))


def _tier_code_for_plan(plan_key: str) -> str:
    return tier_code_from_plan(plan_key)


def _tier_name_for_code(code: str) -> str:
    return tier_name_ru(code)


async def _current_pkg_offer(uid: int) -> tuple[str, str, int, int]:
    summary = await api_client.get_sub_summary(uid)
    role = (summary.get("role") or "free").strip()
    tier_code = _tier_code_for_plan(role)
    tier_name = _tier_name_for_code(tier_code)
    return tier_code, tier_name, RUB_PKG_BY_TIER[tier_code], STARS_PKG_BY_TIER[tier_code]

# -------------------- Utils --------------------

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "api"}


def _is_local_host(host: str | None) -> bool:
    if not host:
        return False
    host = host.strip("[]").lower()
    return host in _LOCAL_HOSTS or host.endswith(".local")


def _checkout_base_url() -> str:
    raw = (settings.PAYMENTS_PUBLIC_URL or settings.API_PUBLIC_URL or "").strip()
    if not raw:
        return "http://localhost:8000"

    if "://" not in raw:
        raw = f"https://{raw}"

    parsed = urlparse(raw)
    if not parsed.netloc:
        return "http://localhost:8000"

    if parsed.scheme == "http" and not _is_local_host(parsed.hostname):
        parsed = parsed._replace(scheme="https")

    return urlunparse(parsed).rstrip("/")

def _format_ru_date(iso: str | None) -> str:
    if not iso: return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y, %H:%M MSK")
    except:
        if "T" in iso: return iso.split("T")[0]
        return iso

async def has_generations_async(uid: int) -> bool:
    try:
        summary = await api_client.get_sub_summary(uid)
        role = (summary.get("role") or "free").strip()
        totals = summary.get("totals", {})
        usage = summary.get("usage", {})
        
        available = max(0, totals.get("images", 0) - usage.get("images", 0))
        return (role.lower() != "free") or (available > 0)
    except:
        return False


async def has_active_subscription_async(uid: int) -> bool:
    try:
        summary = await api_client.get_sub_summary(uid)
        role = (summary.get("role") or "free").strip().lower()
        return role != "free"
    except:
        return False

def _assets(*parts: str) -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", *parts))

def _find(base_no_ext: str) -> Optional[str]:
    for ext in (".jpg", ".png", ".jpeg", ".webp"):
        p = base_no_ext + ext
        if os.path.exists(p): return p
    return None

def img_ui(name: str) -> str:
    p = _find(_assets("ui", name))
    if p: return p
    fallback = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "topper.jpg"))
    if os.path.exists(fallback): return fallback
    return ""

def img_shoot(gender: str, cat: str, page: int) -> str:
    p = _find(_assets("shoots", gender, cat, f"p{page}"))
    if p: return p
    p1 = _find(_assets("shoots", gender, cat, "p1"))
    if p1: return p1
    if gender == 'f': return img_ui("female_shoots")
    return img_ui("shoots_home")

def img_editor(gender: str, cat: str, page: int) -> str:
    p = _find(_assets("editor", gender, cat, f"p{page}"))
    if p: return p
    p1 = _find(_assets("editor", gender, cat, "p1"))
    if p1: return p1
    if gender == 'f': return img_ui("female_editor")
    return img_ui("editor_home")

def _pages_count(folder: str) -> int:
    if not os.path.exists(folder): return 1
    files = os.listdir(folder)
    max_p = 1
    for f in files:
        if f.startswith("p") and f[1].isdigit():
            try:
                num = int(re.findall(r'\d+', f)[0])
                if num > max_p: max_p = num
            except: pass
    return max_p

async def _get_status_text(editor_sel: dict, gender: str) -> str:
    if not editor_sel: return ""
    titles = await api_client.get_catalog_titles(gender, editor_sel)
    lines = ["<b>Вы выбрали:</b>"]
    for cat_slug, idx in editor_sel.items():
        cat_name = ui.CATALOG_NAMES.get(cat_slug, cat_slug.capitalize())
        item_name = titles.get(cat_slug, f"#{idx}")
        lines.append(f"- {cat_name}: {item_name}")
    return "\n".join(lines) + "\n\n"


def _prompt_source_caption() -> str:
    return (
        "📸 Фото загружено\n\n"
        "Как будем генерировать?"
    )

def _promo_user_label(entry: dict) -> str:
    chat_id = entry.get("chat_id")
    username = str(entry.get("username") or "").strip().lstrip("@")
    if username:
        return f"@{html.quote(username)}"
    if chat_id is not None:
        return f"<code>{chat_id}</code>"
    return "<code>unknown</code>"


def _promo_users_line(prefix: str, users: list[dict], truncated: bool, total: int) -> str:
    if not users:
        return f"{prefix}: -"
    labels = ", ".join(_promo_user_label(u) for u in users)
    if truncated and total > len(users):
        labels += f" (+{total - len(users)})"
    return f"{prefix}: {labels}"


async def _answer_html_chunks(message: Message, lines: list[str], max_len: int = 3900) -> None:
    chunk = ""
    for line in lines:
        candidate = f"{chunk}\n{line}" if chunk else line
        if len(candidate) <= max_len:
            chunk = candidate
            continue

        if chunk:
            await message.answer(chunk, disable_web_page_preview=True)

        if len(line) <= max_len:
            chunk = line
            continue

        start = 0
        while start < len(line):
            await message.answer(line[start:start + max_len], disable_web_page_preview=True)
            start += max_len
        chunk = ""

    if chunk:
        await message.answer(chunk, disable_web_page_preview=True)

# --- PANEL HELPERS (MOVED UP FOR SCOPE VISIBILITY) ---

async def panel_send(message: Message | CallbackQuery, state: FSMContext, img_path: str, caption: str, kb=None) -> None:
    """Универсальная отправка панели. Принимает Message или CallbackQuery."""
    # Получаем объект message для ответа
    if isinstance(message, CallbackQuery):
        msg = message.message
    else:
        msg = message

    if not img_path or not os.path.exists(img_path):
        sent = await msg.answer(caption, reply_markup=kb)
        await state.update_data(panel_id=sent.message_id)
        return
    
    cached_id = _MEDIA_CACHE.get(img_path)
    if cached_id: photo_obj = cached_id
    else: photo_obj = FSInputFile(img_path)
    
    try:
        sent = await msg.answer_photo(photo_obj, caption=caption, reply_markup=kb)
        if not cached_id and sent.photo: _MEDIA_CACHE[img_path] = sent.photo[-1].file_id
        await state.update_data(panel_id=sent.message_id)
    except Exception:
        if cached_id: del _MEDIA_CACHE[img_path]
        try:
             photo_obj = FSInputFile(img_path)
             sent = await msg.answer_photo(photo_obj, caption=caption, reply_markup=kb)
             await state.update_data(panel_id=sent.message_id)
        except Exception as e:
             print(f"Panel send error: {e}")

async def panel_edit_media(message_obj: Message | CallbackQuery, state: FSMContext, img_path: str, caption: str, kb=None) -> None:
    """Редактирует медиа в существующем сообщении."""
    
    if isinstance(message_obj, CallbackQuery):
        message = message_obj.message
        chat_id = message.chat.id
    else:
        message = message_obj
        chat_id = message.chat.id

    data = await state.get_data()
    msg_id = data.get("panel_id") or message.message_id
    
    if not img_path or not os.path.exists(img_path): img_path = img_ui("start")
    
    cached_id = _MEDIA_CACHE.get(img_path)
    if cached_id: media = InputMediaPhoto(media=cached_id, caption=caption)
    else: media = InputMediaPhoto(media=FSInputFile(img_path), caption=caption)
    
    try:
        res = await message.bot.edit_message_media(chat_id=chat_id, message_id=msg_id, media=media, reply_markup=kb)
        if not cached_id and isinstance(res, Message) and res.photo: _MEDIA_CACHE[img_path] = res.photo[-1].file_id
    except TelegramBadRequest: 
        # Если сообщение не изменилось или удалено
        pass
    except Exception: 
        if cached_id: del _MEDIA_CACHE[img_path]

# -------------------- FSM --------------------
class Flow(StatesGroup):
    waiting_photo = State()
    choosing_gender = State()
    main_menu = State()
    editor_home = State()
    picker = State()
    shoots_home = State()
    waiting_custom_prompt = State()


    @router.edited_message(F.caption)
    async def handle_edited_caption(message: Message, state: FSMContext):
        """
        Сценарий 1: Пользователь изменил подпись ПОД фото.
        """
        # 1. Проверяем подписку
        if not await has_generations_async(message.chat.id):
            return

        # 2. Получаем новый текст подписи
        new_prompt = message.caption
        if not new_prompt:
            return

        # 3. ВАЖНЫЙ МОМЕНТ:
        # Если редактируется сообщение с фото, значит фото точно есть в этом сообщении.
        # Обновляем photo_file_id в стейте, чтобы генерация шла именно по этому фото,
        # даже если в памяти "висело" другое.
        if message.photo:
            await state.update_data(photo_file_id=message.photo[-1].file_id)

        # 4. Обновляем промпт и генерируем
        await state.update_data(last_custom_prompt=new_prompt)
        
        # is_new_message=True — пришлет результат новым сообщением
        await _process_generation(message, state, prompt=new_prompt, is_new_message=True)
    # -------------------- COMMANDS --------------------


    @router.edited_message(F.text & ~F.text.startswith("/"))
    async def handle_edited_message(message: Message, state: FSMContext):
        """
        Обработка редактирования сообщения.
        Если пользователь изменил текст промпта — запускаем генерацию заново с новым текстом.
        """
        # 1. Проверяем подписку/лимиты
        if not await has_generations_async(message.chat.id):
            return  # Игнорируем эдиты, если нет подписки (чтобы не спамить пейволлом на каждый чих)

        # 2. Проверяем, есть ли активное фото в стейте
        data = await state.get_data()
        if not data.get("photo_file_id"):
            return  # Если фото нет, редактирование текста нас не интересует

        # 3. Обновляем промпт и запускаем генерацию
        new_prompt = message.text.strip()
        if not new_prompt:
            return

        await state.update_data(last_custom_prompt=new_prompt)
        
        # Сообщаем пользователю (опционально) и генерируем
        # is_new_message=True заставит бота прислать свежий результат отдельным сообщением
        await _process_generation(message, state, prompt=new_prompt, is_new_message=True)

@router.message(Command("set_menu"))
async def set_menu_command(message: Message):
    commands = [
        BotCommand(command="start", description="🚀 Главное меню"),
        BotCommand(command="premium", description="⭐ Купить подписку"),
        BotCommand(command="account", description="🎁 Баланс и реферальная система"),
        BotCommand(command="packages", description="⭐️ Дополнительные генерации"),
        BotCommand(command="help", description="❓ Помощь"),
    ]
    scopes = [BotCommandScopeDefault(), BotCommandScopeAllPrivateChats()]
    languages = [None, "ru", "en"]

    for scope in scopes:
        for language_code in languages:
            try:
                await message.bot.delete_my_commands(scope=scope, language_code=language_code)
            except Exception:
                pass
            await message.bot.set_my_commands(
                commands,
                scope=scope,
                language_code=language_code,
            )

    await message.answer("✅ Меню бота обновлено! Нажмите на кнопку 'Меню' слева внизу, чтобы проверить.")


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    
    # Обработка промо-ссылок
    command_parts = message.text.split()
    if len(command_parts) > 1:
        token = command_parts[1].strip()
        if token:
            should_try_promo = True

            # Отдельные трекинг-ссылки (без бонусов).
            if token.startswith("trk_"):
                should_try_promo = False
                track_res = await api_client.register_track_click(message.chat.id, token)
                if not track_res.get("ok"):
                    # Фоллбэк на случай коллизии префикса со старым промо-токеном.
                    if track_res.get("error") == "token_not_found":
                        should_try_promo = True
                    else:
                        logger.warning(f"Track link click register failed: token={token} err={track_res.get('error')}")

            if should_try_promo:
                res = await api_client.use_promo(message.chat.id, token)
                if res.get("ok"):
                    credits = res.get("credits_added", 50)
                    await message.answer(f"🎁 <b>Поздравляем!</b>\nВам начислено {credits} бесплатных генераций по пригласительной ссылке!")
                else:
                    err = res.get("error")
                    if err == "token_already_used":
                        await message.answer("⚠️ Эта ссылка уже была использована.")
                    elif err == "token_fully_used":
                        await message.answer("⚠️ Эта ссылка уже исчерпала лимит активаций.")
                    elif err == "already_had_subscription":
                        await message.answer("⚠️ Простите, эта ссылка только для новых пользователей, которые еще не покупали подписку.")
                    elif err == "promo_already_used_by_user":
                        await message.answer("⚠️ Вы уже активировали подобную ссылку ранее. Повторная активация невозможна.")
                    # token_not_found: это может быть внешняя/неизвестная ссылка, игнорируем.

    await api_client.ensure_user(message.chat.id)
    
    # ЛОГИКА СТАРТА
    if await has_generations_async(message.chat.id):
        await state.set_state(Flow.waiting_photo)
        path = img_ui("start")
        caption = ui.TEXTS["ru"]["start_title"]
        await panel_send(message, state, path, caption, kb=None)
    else:
        # ПЕЙВОЛЛ (ВЫБОР ВЕРСИИ) -> Картинка compare
        path = img_ui("compare") 
        caption = ui.TEXT_TIER_SELECTION
        kb = ui.kb_tier_selection()
        await panel_send(message, state, path, caption, kb=kb)

@router.message(Command("update_prompts"))
async def cmd_update_prompts(message: Message):
    if message.from_user.id not in ADMIN_IDS: return

    status_msg = await message.answer("⏳ <b>Синхронизация...</b>\nКачаю таблицу и обновляю базу.")
    current_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.abspath(os.path.join(current_dir, "..", ".."))
    script_path = os.path.join(root_dir, "tools", "sync_from_sheet.py")
    
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable, script_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        output = html.quote(stdout.decode())
        error = html.quote(stderr.decode())
        if process.returncode == 0: await status_msg.edit_text(f"✅ <b>Успешно!</b>\n<pre>{output[-500:]}</pre>")
        else: await status_msg.edit_text(f"❌ <b>Ошибка:</b>\n<pre>{error}</pre>\n<pre>{output}</pre>")
    except Exception as e: await status_msg.edit_text(f"❌ <b>Критическая ошибка:</b>\n{html.quote(str(e))}")
    
@router.message(Command("gen"))
async def cmd_gen_promo(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    args = message.text.split()
    count = 1
    credits = 50
    max_uses = 1

    if len(args) > 4:
        await message.answer("Использование: <code>/gen [count] [generations=50] [max_uses=1]</code>")
        return

    try:
        if len(args) > 1:
            count = int(args[1])
        if len(args) > 2:
            credits = int(args[2])
        if len(args) > 3:
            max_uses = int(args[3])
    except ValueError:
        await message.answer("Ошибка: count, generations и max_uses должны быть числами.")
        return

    if count < 1 or count > 50:
        await message.answer("Максимум 50 ссылок за один запрос.")
        return
    if credits < 1 or credits > 100000:
        await message.answer("Генераций на ссылку: от 1 до 100000.")
        return
    if max_uses < 1 or max_uses > 100000:
        await message.answer("Лимит активаций на код: от 1 до 100000.")
        return

    res = await api_client.generate_promo(count=count, credits=credits, max_uses=max_uses)

    if res.get("ok"):
        tokens = res.get("tokens", [])
        if not tokens:
            await message.answer("API не вернуло ни одной ссылки.")
            return

        bot_info = await message.bot.get_me()
        lines = []
        for i, t in enumerate(tokens, 1):
            link = f"https://t.me/{bot_info.username}?start={t}"
            lines.append(f"{i}. {link}")

        await message.answer(
            f"✅ <b>Сгенерировано ссылок: {len(tokens)}</b>\n"
            f"Генераций по ссылке: {credits}\n"
            f"Лимит активаций на код: {max_uses}\n\n" + "\n".join(lines),
            disable_web_page_preview=True,
        )
    else:
        await message.answer(f"❌ <b>Ошибка API:</b>\n{res.get('error')}")


@router.message(Command("promo_stats"))
async def cmd_promo_stats(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    stats = await api_client.get_promo_stats()
    promos = await api_client.get_promo_list(limit=20, include_users=True, users_limit=8)

    if not stats and not promos:
        await message.answer("❌ Не удалось получить статистику промокодов.")
        return

    total_tokens = stats.get("total_tokens_created", 0)
    total_redemptions = stats.get("total_redemptions", 0)
    total_unique_users = stats.get("total_unique_users", total_redemptions)
    total_converted = stats.get("total_conversions_to_sub", 0)
    total_not_converted = stats.get("total_without_subscription", max(0, total_unique_users - total_converted))
    conversion_rate = stats.get("conversion_rate_percent", 0)
    total_credits_granted = stats.get("total_credits_granted", 0)

    lines: list[str] = [
        "📊 <b>Статистика промокодов</b>",
        "",
        f"Всего создано кодов: {total_tokens}",
        f"Всего активаций: {total_redemptions}",
        f"Уникальных пользователей: {total_unique_users}",
        f"Купили подписку после промо: {total_converted}",
        f"Не купили подписку: {total_not_converted}",
        f"Конверсия: {conversion_rate}%",
        f"Выдано генераций по промо: {total_credits_granted}",
        "",
        "<b>Последние 20 кодов</b>",
        "<code>Код..     | Ген. | Исп.  | Купил/Нет</code>",
    ]

    for p in promos:
        token_full = p.get("token", "???")
        code_short = token_full[:8]
        credits = p.get("credits", 0)
        current = p.get("current_uses", 0)
        max_uses = p.get("max_uses", 1)
        buyers = p.get("converted_subs", 0)
        non_buyers = p.get("not_converted_subs", max(0, current - buyers))
        lines.append(f"<code>{code_short}.. | {credits:<4} | {current:>2}/{max_uses:<2} | {buyers}/{non_buyers}</code>")

    detail_promos = [p for p in promos if (p.get("buyers") or p.get("non_buyers"))]
    if detail_promos:
        lines.append("")
        lines.append("<b>Кто купил / не купил</b>")

    for idx, p in enumerate(detail_promos, 1):
        token_full = p.get("token", "")
        code_short = html.quote((token_full[:10] + "...") if token_full else "unknown")

        buyers = p.get("buyers", [])
        non_buyers = p.get("non_buyers", [])
        buyers_total = int(p.get("buyers_total", len(buyers)))
        non_buyers_total = int(p.get("non_buyers_total", len(non_buyers)))

        lines.append(f"{idx}. <code>{code_short}</code>")
        lines.append(_promo_users_line("✅ Купили", buyers, bool(p.get("buyers_truncated")), buyers_total))
        lines.append(_promo_users_line("❌ Не купили", non_buyers, bool(p.get("non_buyers_truncated")), non_buyers_total))
        lines.append("")

    await _answer_html_chunks(message, lines)


@router.message(Command("gen_track"))
async def cmd_gen_track(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    args = message.text.split()
    if len(args) > 2:
        await message.answer("Использование: <code>/gen_track [count=1]</code>")
        return

    count = 1
    if len(args) > 1:
        try:
            count = int(args[1])
        except ValueError:
            await message.answer("Ошибка: count должен быть числом.")
            return

    if count < 1 or count > 50:
        await message.answer("Максимум 50 ссылок за один запрос.")
        return

    res = await api_client.generate_track_links(count=count)
    if not res.get("ok"):
        await message.answer(f"❌ <b>Ошибка API:</b>\n{res.get('error')}")
        return

    tokens = res.get("tokens", [])
    if not tokens:
        await message.answer("API не вернуло ни одной ссылки.")
        return

    bot_info = await message.bot.get_me()
    lines = []
    for i, token in enumerate(tokens, 1):
        link = f"https://t.me/{bot_info.username}?start={token}"
        lines.append(f"{i}. {link}")

    await message.answer(
        f"✅ <b>Сгенерировано трекинг-ссылок: {len(tokens)}</b>\n"
        f"Лимит активаций: без ограничений\n\n" + "\n".join(lines),
        disable_web_page_preview=True,
    )


@router.message(Command("track_stats"))
async def cmd_track_stats(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    stats = await api_client.get_track_stats()
    links = await api_client.get_track_links(limit=20, include_users=True, users_limit=8)

    if not stats and not links:
        await message.answer("❌ Не удалось получить статистику трекинг-ссылок.")
        return

    total_links = stats.get("total_links_created", 0)
    total_clicks = stats.get("total_clicks", 0)
    total_unique_users = stats.get("total_unique_users", total_clicks)
    total_converted = stats.get("total_conversions_to_sub", 0)
    total_not_converted = stats.get("total_without_subscription", max(0, total_unique_users - total_converted))
    conversion_rate = stats.get("conversion_rate_percent", 0)

    lines: list[str] = [
        "📈 <b>Статистика трекинг-ссылок</b>",
        "",
        f"Всего создано ссылок: {total_links}",
        f"Всего кликов: {total_clicks}",
        f"Уникальных пользователей: {total_unique_users}",
        f"Купили подписку после перехода: {total_converted}",
        f"Не купили подписку: {total_not_converted}",
        f"Конверсия: {conversion_rate}%",
        "",
        "<b>Последние 20 ссылок</b>",
        "<code>Код..     | Клики | Уник. | Купил/Нет</code>",
    ]

    for item in links:
        token_full = item.get("token", "???")
        token_short = token_full[:8]
        clicks = item.get("total_clicks", 0)
        unique_users = item.get("unique_users", 0)
        buyers = item.get("converted_subs", 0)
        non_buyers = item.get("not_converted_subs", max(0, unique_users - buyers))
        lines.append(f"<code>{token_short}.. | {clicks:<5} | {unique_users:<5} | {buyers}/{non_buyers}</code>")

    detail_links = [item for item in links if (item.get("buyers") or item.get("non_buyers"))]
    if detail_links:
        lines.append("")
        lines.append("<b>Кто купил / не купил</b>")

    for idx, item in enumerate(detail_links, 1):
        token_full = item.get("token", "")
        token_short = html.quote((token_full[:10] + "...") if token_full else "unknown")

        buyers = item.get("buyers", [])
        non_buyers = item.get("non_buyers", [])
        buyers_total = int(item.get("buyers_total", len(buyers)))
        non_buyers_total = int(item.get("non_buyers_total", len(non_buyers)))

        lines.append(f"{idx}. <code>{token_short}</code>")
        lines.append(_promo_users_line("✅ Купили", buyers, bool(item.get("buyers_truncated")), buyers_total))
        lines.append(_promo_users_line("❌ Не купили", non_buyers, bool(item.get("non_buyers_truncated")), non_buyers_total))
        lines.append("")

    await _answer_html_chunks(message, lines)


@router.message(Command("export"))
async def cmd_export_stats(message: Message):
    if message.from_user.id not in ADMIN_IDS: return

    status_msg = await message.answer("⏳ <b>Собираю статистику...</b>\nЭто может занять некоторое время.")
    
    try:
        # Используем токен бота как секрет для доступа к API
        file_bytes = await api_client.export_stats(settings.TELEGRAM_BOT_TOKEN)
        
        if file_bytes:
            current_date = datetime.now().strftime("%Y-%m-%d")
            filename = f"users_stats_{current_date}.xlsx"
            
            await message.answer_document(
                BufferedInputFile(file_bytes, filename=filename),
                caption=f"📊 <b>Статистика пользователей</b>\nНа {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            )
            await status_msg.delete()
        else:
            await status_msg.edit_text("❌ Не удалось получить файл от сервера.")
            
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {e}")


@router.message(Command("give_subscription"), F.from_user.id.in_(ADMIN_IDS))
@router.message(Command("add_subscription"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_give_subscription(message: Message):
    """
    Выдача подписки админом: /give_subscription <telegram_id> <days> <generations>
    """
    args = message.text.split()
    if len(args) < 4:
        await message.answer("Использование: <code>/give_subscription &lt;telegram_id&gt; &lt;days&gt; &lt;generations&gt;</code>")
        return

    try:
        target_id = int(args[1])
        days = int(args[2])
        gens = int(args[3])
    except ValueError:
        await message.answer("❌ Ошибка: ID, дни и генерации должны быть числами.")
        return

    res = await api_client.admin_give_sub(target_id, days, gens)
    if res.get("ok"):
        until_str = _format_ru_date(res.get("active_until"))
        await message.answer(
            f"✅ <b>Подписка выдана!</b>\n\n"
            f"👤 ID: <code>{target_id}</code>\n"
            f"вЏі РЎСЂРѕРє: {days} РґРЅ. (РґРѕ {until_str})\n"
            f"✨ Лимит: {res.get('generations')} (использовано: {res.get('used')})"
        )
    else:
        await message.answer(f"❌ <b>Ошибка API:</b>\n{res.get('error')}")


@router.message(Command("reset_subscription"), F.from_user.id.in_(ADMIN_IDS))
@router.message(Command("cancel_subscription"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_reset_subscription(message: Message):
    """
    Сброс подписки админом: /reset_subscription <telegram_id>
    """
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: <code>/reset_subscription &lt;telegram_id&gt;</code>")
        return

    try:
        target_id = int(args[1])
    except ValueError:
        await message.answer("❌ Ошибка: ID должен быть числом.")
        return

    res = await api_client.admin_cancel_sub(target_id)
    if res.get("ok"):
        await message.answer(f"✅ Подписка пользователя <code>{target_id}</code> успешно аннулирована.")
    else:
        await message.answer(f"❌ <b>Ошибка API:</b>\n{res.get('error')}")


@router.message(F.photo, F.caption)
async def handle_photo_with_prompt(message: Message, state: FSMContext):
    if not await has_generations_async(message.chat.id):
        # ПЕЙВОЛЛ -> compare
        path = img_ui("compare")
        await panel_send(message, state, path, ui.TEXT_TIER_SELECTION, ui.kb_tier_selection())
        return
    photo = message.photo[-1]
    await state.update_data(photo_file_id=photo.file_id)
    await state.update_data(last_custom_prompt=message.caption)
    await _process_generation(message, state, prompt=message.caption, is_new_message=True)

@router.callback_query(F.data == ui.CB_RESTART)
async def restart_callback(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if await has_generations_async(call.from_user.id):
        await state.set_state(Flow.waiting_photo)
        path = img_ui("start")
        caption = ui.TEXTS["ru"]["start_title"]
        try: await panel_edit_media(call, state, path, caption, kb=None)
        except: await panel_send(call.message, state, path, caption, kb=None)
    else:
        # ПЕЙВОЛЛ -> compare
        path = img_ui("compare")
        caption = ui.TEXT_TIER_SELECTION
        kb = ui.kb_tier_selection()
        try: await panel_edit_media(call, state, path, caption, kb=kb)
        except: await panel_send(call.message, state, path, caption, kb=kb)
    await call.answer()

@router.message(F.text & ~F.text.startswith("/"))
async def handle_any_text_prompt(message: Message, state: FSMContext):
    """
    Задача 1: Если человек скинул фото без подписи (мы его сохранили),
    а следующим сообщением пишет текст — считаем это промптом.
    """
    # 1. Проверяем подписку
    if not await has_generations_async(message.chat.id):
        path = img_ui("compare")
        await panel_send(message, state, path, ui.TEXT_TIER_SELECTION, ui.kb_tier_selection())
        return

    # 2. Проверяем, есть ли фото в состоянии
    data = await state.get_data()
    if not data.get("photo_file_id"):
        # Если фото нет, возможно это просто чат или ошибка.
        # Можно отправить help или проигнорировать.
        # Для UX лучше сказать "Сначала фото".
        await message.answer("📸 Сначала отправьте фото, которое хотите изменить.")
        return

    # 3. Если фото есть — считаем текст промптом
    prompt = message.text
    await state.update_data(last_custom_prompt=prompt)
    await _process_generation(message, state, prompt=prompt, is_new_message=True)

# -------------------- PREMIUM / ACCOUNT / HELP / PACKAGES --------------------

@router.message(Command("premium"))
@router.message(Command("account"))
@router.callback_query(F.data == "account:info")
async def premium_cmd(message: Message | CallbackQuery, state: FSMContext, is_edit: bool = False, show_edit_btn: bool = False) -> None:
    
    if isinstance(message, CallbackQuery):
        call = message
        message = call.message
        uid = call.from_user.id
        is_edit = True
    else:
        uid = message.chat.id

    try: summary = await api_client.get_sub_summary(uid)
    except: summary = {}
    role = (summary.get("role") or "free").strip()
    
    if role.lower() == "free":
        caption = ui.TEXT_TIER_SELECTION
        kb = ui.kb_tier_selection()
        img = img_ui("compare")
    else:
        totals = summary.get("totals", {})
        usage = summary.get("usage", {})
        available = max(0, totals.get("images", 0) - usage.get("images", 0))
        
        plan_period = plan_title_ru(role)
        base_limit = summary.get("limits", {}).get("images", 0)
        
        plan_name = f"Премиум, {plan_period} ({base_limit} генераций)"
        
        spec = get_plan_spec(role)
        price = str(spec.price_rub) if spec else "---"
        active_until_str = _format_ru_date(summary.get("active_until"))
        auto_renew = summary.get("auto_renew", True)
        
        if auto_renew:
            renewal_info = f"💳 Следующее списание: {active_until_str} ({price}₽)"
        else:
            # Если автопродление выключено, добавляем статус "Отменена" и показываем до какого числа действует
            plan_name += " (Отменена)"
            renewal_info = f"⏳ Действует до: {active_until_str}"
        
        caption = ui.TEXT_PREMIUM_ACTIVE_TEMPLATE.format(
            available=available,
            plan_name=plan_name,
            renewal_info=renewal_info
        )
        
        bot_info = await message.bot.get_me()
        kb = ui.kb_premium_active(uid, bot_info.username, auto_renew=auto_renew, show_edit_btn=show_edit_btn)
        img = img_ui("premium")
    
    if not img or not os.path.exists(img): img = img_ui("premium")
    
    if is_edit:
        await panel_edit_media(message, state, img, caption, kb)
        if isinstance(message, CallbackQuery):
             await message.answer()
    else:
        await panel_send(message, state, img_path=img, caption=caption, kb=kb)

@router.message(Command("help"))
@router.callback_query(F.data == "help:show")
async def help_cmd(message: Message | CallbackQuery, state: FSMContext) -> None:
    text = ui.TEXT_HELP_RU
    kb = ui.kb_help("ru")
    
    if isinstance(message, CallbackQuery):
        await message.message.answer(text, reply_markup=kb, disable_web_page_preview=True)
        await message.answer()
    else:
        await message.answer(text, reply_markup=kb, disable_web_page_preview=True)


@router.callback_query(F.data == ui.CB_LANG_TOGGLE)
async def help_lang_toggle(call: CallbackQuery, state: FSMContext) -> None:
    current_text = call.message.text or call.message.caption or ""
    if "Как пользоваться" in current_text: new_text = ui.TEXT_HELP_EN; new_kb = ui.kb_help("en")
    else: new_text = ui.TEXT_HELP_RU; new_kb = ui.kb_help("ru")
    await call.message.edit_text(new_text, reply_markup=new_kb, disable_web_page_preview=True)
    await call.answer()

@router.message(Command("packages"))
async def packages_cmd(message: Message, state: FSMContext) -> None:
    if not await has_active_subscription_async(message.chat.id):
        await message.answer("⚠️ Пакеты генераций доступны только при активной подписке.")
        return
    _, tier_name, price_rub, price_stars = await _current_pkg_offer(message.chat.id)
    await panel_send(
        message,
        state,
        img_ui("packages"),
        ui.TEXT_PACKAGES_CAPTION,
        ui.kb_packages(price_rub, price_stars, tier_name),
    )

@router.callback_query(F.data == ui.CB_CANCEL_SUB)
async def cancel_sub(call: CallbackQuery, state: FSMContext):
    res = await api_client.cancel_plan(call.from_user.id)
    if res.get("ok"): await call.answer("Автопродление отключено.", show_alert=True); await premium_cmd(call, state, is_edit=True)
    else: await call.answer("Ошибка отмены.", show_alert=True)

@router.callback_query(F.data == ui.CB_RESUME_SUB)
async def resume_sub(call: CallbackQuery, state: FSMContext):
    """
    Возобновление подписки (включение автопродления).
    """
    try:
        res = await api_client.resume_plan(call.from_user.id) 
        
        if res.get("ok"):
            await call.answer("Автопродление возобновлено! ✅", show_alert=True)
            # Обновляем сообщение (кнопка сменится на "Отменить")
            await premium_cmd(call, state, is_edit=True)
        else:
            await call.answer(f"Ошибка: {res.get('detail', 'Сбой')}", show_alert=True)
    except Exception as e:
        print(f"Resume Error: {e}")
        await call.answer("Не удалось возобновить подписку.", show_alert=True)

# -------------------- TIER SELECTION --------------------

@router.callback_query(F.data == ui.CB_TIER_STD)
async def on_tier_std(call: CallbackQuery, state: FSMContext):
    kb = ui.kb_premium_paywall("ru", tier="start")
    await panel_edit_media(call, state, img_ui("man"), caption='', kb=kb)
    await call.answer()

@router.callback_query(F.data == ui.CB_TIER_PRO)
async def on_tier_pro(call: CallbackQuery, state: FSMContext):
    kb = ui.kb_premium_paywall("ru", tier="pro")
    await panel_edit_media(call, state, img_ui("man1"), caption='', kb=kb)
    await call.answer()

@router.callback_query(F.data == ui.CB_TIER_ELITE)
async def on_tier_elite(call: CallbackQuery, state: FSMContext):
    kb = ui.kb_premium_paywall("ru", tier="elite")
    await panel_edit_media(call, state, img_ui("man2"), caption='', kb=kb)
    await call.answer()

@router.callback_query(F.data == "nav:back_to_tiers")
async def on_back_to_tiers(call: CallbackQuery, state: FSMContext):
    # Возврат к выбору версии -> compare.jpg
    await panel_edit_media(call, state, img_ui("compare"), caption=ui.TEXT_TIER_SELECTION, kb=ui.kb_tier_selection())
    await call.answer()

# -------------------- PAYMENT FLOW (RU + STARS) --------------------

@router.callback_query(F.data.startswith("premium:buy:"))
async def ask_payment_method_sub(call: CallbackQuery, state: FSMContext):
    # call.data пример: premium:buy:month:pro / premium:buy:month:start / premium:buy:month:elite
    parts = call.data.split(":")
    period = parts[2] 
    tier = parts[3] if len(parts) > 3 else "start" 
    plan_key = _plan_key_from_choice(period, tier)
    
    price_rub = PLAN_PRICES.get(plan_key, "0")
    price_stars = STARS_PRICES_SUB.get(plan_key, 0)
    
    payload_data = f"plan:{plan_key}"
    
    await call.message.edit_reply_markup(
        reply_markup=ui.payment_choice_kb(price_rub, price_stars, payload_data)
    )
    await call.answer()

@router.callback_query(F.data.startswith("pkg:"))
async def ask_payment_method_pkg(call: CallbackQuery, state: FSMContext):
    pkg_id = call.data.split(":")[-1] 

    if not await has_active_subscription_async(call.from_user.id):
        await call.answer("Нужна активная подписка!", show_alert=True)
        return

    if pkg_id != str(PKG_TOPUP_QTY):
        await call.answer("Доступен только пакет 300 генераций.", show_alert=True)
        return

    _, _, price_rub, price_stars = await _current_pkg_offer(call.from_user.id)
    payload_data = f"pkg:{PKG_TOPUP_QTY}"

    await call.message.edit_reply_markup(
        reply_markup=ui.payment_choice_kb(price_rub, price_stars, payload_data)
    )
    await call.answer()

@router.callback_query(F.data == "cancel_payment")
async def cancel_payment_click(call: CallbackQuery, state: FSMContext):
    # При отмене возвращаемся на экран аккаунта/премиума
    await premium_cmd(call, state, is_edit=True)
    await call.answer("Отменено")

# -------------------- 3. Handle RUB Selection --------------------

@router.callback_query(F.data.startswith("pay_rub:"))
async def on_pay_choice_rub(call: CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    price_rub = int(parts[1])
    payload = ":".join(parts[2:]) 
    
    uid = call.from_user.id
    
    try:
        ptype, pvalue = payload.split(":", 1)
    except ValueError:
        await call.answer("Ошибка данных", show_alert=True)
        return
    
    message_id = call.message.message_id
    api_url = _checkout_base_url()
    query = urlencode({
        "chat_id": uid,
        "type": ptype,
        "value": pvalue,
        "message_id": message_id,
    })
    payment_link = f"{api_url}/payments/checkout?{query}"
    
    caption = ""
    
    if ptype == "plan":
        plan_key = pvalue
        now = datetime.now()
        tier_name = _tier_name_for_plan(plan_key)
        
        if "Week" in plan_key:
            next_date = now + timedelta(days=7)
            period_str = "7 дней"
            count_str = "150"
        elif "Month" in plan_key:
            next_date = now + timedelta(days=30)
            period_str = "месяц"
            count_str = "300"
        elif "Year" in plan_key:
            next_date = now + timedelta(days=365)
            period_str = "РіРѕРґ"
            count_str = "7200"
        else:
            next_date = now + timedelta(days=30)
            period_str = "период"
            count_str = "---"

        next_date_str = next_date.strftime("%d.%m.%Y %H:%M MSK")
        
        caption = ui.TEXT_PAYMENT_CONFIRMATION_RUB.format(
            tier_name=tier_name,
            period=period_str,
            count=count_str,
            price=price_rub,
            next_date=next_date_str,
            link_recurring=ui.LINK_RECURRING_RULES
        )
        
    elif ptype == "pkg":
        if not await has_active_subscription_async(uid):
            await call.answer("Пакет доступен только при активной подписке.", show_alert=True)
            return
        if pvalue != str(PKG_TOPUP_QTY):
            await call.answer("Доступен только пакет 300 генераций.", show_alert=True)
            return
        _, tier_name, price_rub, _ = await _current_pkg_offer(uid)
        caption = (
            f"Вы приобретаете пакет: <b>{PKG_TOPUP_QTY} генераций ({tier_name}) - {price_rub}₽</b>\n\n"
            f"Нажимая «Оплатить», вы переходите к безопасной оплате.\n\n"
            f"🔒 Платеж через сервис CloudPayments."
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Оплатить", url=payment_link)], 
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="cancel_payment")]
    ])

    await panel_edit_media(
        call, state, 
        img_ui("premium"), 
        caption, 
        kb=kb
    )
    await call.answer()

@router.callback_query(F.data.startswith("pay_stars:"))
async def on_pay_choice_stars(call: CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    price_stars = int(parts[1])
    payload = ":".join(parts[2:])
    
    title = "Оплата"
    description = "РџРѕРєСѓРїРєР°"
    
    if payload.startswith("plan:"):
        p_name = payload.split(":")[1]
        spec = get_plan_spec(p_name)
        if not spec:
            await call.answer("Неизвестный тариф.", show_alert=True)
            return
        price_stars = int(spec.price_stars)
        title = f"РџРѕРґРїРёСЃРєР° {p_name.replace('_', ' ')}"
        description = f"Премиум доступ на {PLAN_TRANSLATE.get(p_name, p_name)}"
        
    elif payload.startswith("pkg:"):
        if not await has_active_subscription_async(call.from_user.id):
            await call.answer("Пакет доступен только при активной подписке.", show_alert=True)
            return
        qty = payload.split(":")[1]
        if qty != str(PKG_TOPUP_QTY):
            await call.answer("Доступен только пакет 300 генераций.", show_alert=True)
            return
        _, tier_name, _, expected_stars = await _current_pkg_offer(call.from_user.id)
        price_stars = expected_stars
        title = f"{PKG_TOPUP_QTY} генераций ({tier_name})"
        description = (
            f"Вы приобретаете пакет: {PKG_TOPUP_QTY} генераций ({tier_name}) - {price_stars} ⭐️\n\n"
            "⚠️ Пакет активен до конца действия премиум-подписки. "
            "При отмене премиума неиспользованные генерации сгорают."
        )

    prices = [LabeledPrice(label="XTR", amount=price_stars)]
    
    try: await call.message.delete()
    except: pass

    await call.message.answer_invoice(
        title=title,
        description=description,
        prices=prices,
        provider_token="",
        payload=payload,
        currency="XTR",
        start_parameter="pay",
        reply_markup=ui.kb_cancel_transaction(payload, price_stars) 
    )
    await call.answer()

@router.callback_query(F.data.startswith("inv_cancel:"))
async def on_invoice_cancel(call: CallbackQuery, state: FSMContext):
    payload = call.data.split(":", 1)[1]
    
    try: await call.message.delete()
    except: pass
    
    if payload.startswith("plan:"):
        # Если отменили подписку -> Возврат к выбору версии (compare)
        caption = ui.TEXT_TIER_SELECTION
        img_path = img_ui("compare")
        await panel_send(call.message, state, img_path, caption, kb=ui.kb_tier_selection())
        await call.answer("Возврат к выбору")
        return
        
    elif payload.startswith("pkg:"):
        caption = ui.TEXT_PACKAGES_CAPTION
        img_path = img_ui("packages")
        _, _, price_rub, price_stars = await _current_pkg_offer(call.from_user.id)
        pkg_payload = f"pkg:{PKG_TOPUP_QTY}"

        await panel_send(
            call.message, state, 
            img_path, caption, 
            kb=ui.payment_choice_kb(price_rub, price_stars, pkg_payload)
        )
        await call.answer("Возврат к выбору метода")

@router.pre_checkout_query()
async def on_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)

@router.message(F.content_type == ContentType.SUCCESSFUL_PAYMENT)
async def on_successful_payment(message: Message, state: FSMContext):
    pmt = message.successful_payment
    payload = pmt.invoice_payload 
    uid = message.chat.id
    
    rub_val = 0
    if payload.startswith("plan:"):
        pk = payload.split(":")[1]
        spec = get_plan_spec(pk)
        rub_val = int(spec.price_rub) if spec else 0
    elif payload.startswith("pkg:"):
        qk = payload.split(":")[1]
        if qk == str(PKG_TOPUP_QTY):
            _, _, rub_val, _ = await _current_pkg_offer(uid)

    try:
        if payload.startswith("plan:"):
            plan_key = payload.split(":")[1]
            res = await api_client.set_plan(uid, plan=plan_key)
            if res.get("ok"):
                await message.answer(f"✅ Оплата Звездами прошла успешно! Подписка активирована.")
            else:
                await message.answer(f"⚠️ Оплата прошла, но активация сбойнула: {res.get('detail')}")
                
        elif payload.startswith("pkg:"):
            if not await has_active_subscription_async(uid):
                await message.answer(
                    "⚠️ Пакет доступен только при активной подписке. "
                    "Оплата получена, но пакет не зачислен. Напишите в поддержку: @Facelab_Help"
                )
                return
            qty = int(payload.split(":")[1])
            if qty != PKG_TOPUP_QTY:
                await message.answer("⚠️ Доступен только пакет 300 генераций.")
                return
            res = await api_client.buy_addon(uid, qty, rub_val * 100)
            if res.get("ok"):
                await message.answer(f"✅ Оплата Звездами прошла успешно! Добавлено {qty} генераций.")
            else:
                await message.answer(f"⚠️ Оплата прошла, но начисление сбойнуло: {res.get('detail')}")
        
        await premium_cmd(message, state, is_edit=False, show_edit_btn=True)
        
    except Exception as e:
        await message.answer(f"❌ Критическая ошибка обработки: {e}")


# -------------------- Navigation & Render --------------------

@router.callback_query(F.data == ui.CB_GOTO_EDIT)
async def on_goto_edit(call: CallbackQuery, state: FSMContext):
    await state.set_state(Flow.waiting_photo)
    await panel_send(call.message, state, img_ui("start"), ui.TEXTS["ru"]["start_title"], kb=None)
    await call.answer()

@router.message(F.photo)
async def got_photo(message: Message, state: FSMContext) -> None:
    # Если нет подписки/лимитов — пейволл
    if not await has_generations_async(message.chat.id):
        path = img_ui("compare")
        await panel_send(message, state, path, ui.TEXT_TIER_SELECTION, ui.kb_tier_selection())
        return

    photo = message.photo[-1]
    await state.update_data(photo_file_id=photo.file_id)

    # Всегда ведём пользователя в "после фото"
    await _after_photo_received(message, state)

@router.message(F.document)
async def got_document_photo(message: Message, state: FSMContext) -> None:
    if not await has_generations_async(message.chat.id):
        path = img_ui("compare")
        await panel_send(message, state, path, ui.TEXT_TIER_SELECTION, ui.kb_tier_selection())
        return

    doc = message.document
    if not doc.mime_type or not doc.mime_type.startswith("image/"):
        await message.answer("❌ Пожалуйста, отправьте именно изображение (JPG/PNG).")
        return

    await state.update_data(photo_file_id=doc.file_id)
    await _after_photo_received(message, state)

async def _after_photo_received(message: Message, state: FSMContext):
    await state.set_state(Flow.waiting_custom_prompt)
    await state.update_data(editor_sel={}, shoot_sel={})
    await panel_send(
        message,
        state,
        img_path="",
        caption=_prompt_source_caption(),
        kb=ui.kb_prompt_source("ru"),
    )

@router.callback_query(F.data.in_({ui.CB_STYLES_M, ui.CB_STYLES_F}))
async def choose_gender(call: CallbackQuery, state: FSMContext) -> None:
    gender = "m" if call.data == ui.CB_STYLES_M else "f"
    await state.update_data(styles_gender=gender)
    if not await has_generations_async(call.from_user.id):
        # ПЕЙВОЛЛ -> compare
        img = img_ui("compare")
        await panel_edit_media(call, state, img, ui.TEXT_TIER_SELECTION, ui.kb_tier_selection())
        await call.answer(); return
    await state.set_state(Flow.main_menu)
    await state.update_data(editor_sel={}, shoot_sel={}) 
    await _show_main_menu(call, state)
    await call.answer()

@router.callback_query(F.data == ui.CB_BACK_TO_GENDER)
async def back_to_gender(call: CallbackQuery, state: FSMContext) -> None:
    if not await has_generations_async(call.from_user.id):
        await call.answer("Нужна подписка", show_alert=True)
        return

    await state.set_state(Flow.waiting_custom_prompt)
    try:
        await call.message.edit_text(
            _prompt_source_caption(),
            reply_markup=ui.kb_prompt_source("ru"),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        await state.update_data(panel_id=call.message.message_id)
    except TelegramBadRequest:
        await panel_send(call.message, state, img_path="", caption=_prompt_source_caption(), kb=ui.kb_prompt_source("ru"))

    await call.answer()

@router.callback_query(F.data == ui.CB_CUSTOM_PROMPT)
async def custom_prompt_click(call: CallbackQuery, state: FSMContext) -> None:
    if not await has_generations_async(call.from_user.id):
        # ПЕЙВОЛЛ -> compare
        path = img_ui("compare")
        await panel_send(call.message, state, path, ui.TEXT_TIER_SELECTION, ui.kb_tier_selection())
        await call.answer()
        return

    await state.set_state(Flow.waiting_custom_prompt)
    prompt_caption = "✍️ <b>Вставьте свой промпт одним сообщением.</b>"
    try:
        await call.message.edit_text(
            prompt_caption,
            reply_markup=ui.kb_back_to_gender("ru"),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        await state.update_data(panel_id=call.message.message_id)
    except TelegramBadRequest:
        await panel_send(
            call.message,
            state,
            img_path="",
            caption=prompt_caption,
            kb=ui.kb_back_to_gender("ru"),
        )

    await call.answer()

@router.message(Flow.waiting_custom_prompt)
async def handle_custom_prompt_text(message: Message, state: FSMContext) -> None:
    prompt = message.text
    if not prompt: return
    if not await has_generations_async(message.chat.id):
        # ПЕЙВОЛЛ -> compare
        path = img_ui("compare")
        await panel_send(message, state, path, ui.TEXT_TIER_SELECTION, ui.kb_tier_selection())
        return
    await state.update_data(last_custom_prompt=prompt)
    await _process_generation(message, state, prompt=prompt, is_new_message=True)

@router.callback_query(F.data == ui.CB_MENU)
async def back_to_main_menu(call: CallbackQuery, state: FSMContext) -> None:
    if not await has_generations_async(call.from_user.id):
        # ПЕЙВОЛЛ -> compare
        img = img_ui("compare")
        await panel_edit_media(call, state, img, ui.TEXT_TIER_SELECTION, ui.kb_tier_selection())
        await call.answer(); return
    await state.set_state(Flow.main_menu)
    await _show_main_menu(call, state)
    await call.answer()

async def _show_main_menu(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data(); gender = data.get("styles_gender", "m")
    menu_caption = "🧊 <b>Редактор внешности</b> — точечные изменения...\n\n📸 <b>Фотосессии</b> — готовые образы."
    img = img_ui("female_menu") if gender == "f" else img_ui("menu")
    await panel_edit_media(call, state, img_path=img, caption=menu_caption, kb=ui.kb_main_menu("ru"))

@router.callback_query(F.data == ui.CB_BACK_TO_PHOTO)
async def back_to_photo(call: CallbackQuery, state: FSMContext) -> None:
    if not await has_generations_async(call.from_user.id):
        await call.answer("РќСѓР¶РЅР° РїРѕРґРїРёСЃРєР°"); return
    await state.set_state(Flow.waiting_photo)
    await panel_edit_media(call, state, img_ui("start"), ui.TEXTS["ru"]["start_title"], None)
    await call.answer()

@router.callback_query(F.data == ui.CB_EDITOR_HOME)
async def editor_home(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Flow.editor_home)
    data = await state.get_data(); gender = data.get("styles_gender", "m")
    status_text = await _get_status_text(data.get("editor_sel", {}), gender)
    img = img_ui("female_editor") if gender == "f" else img_ui("editor_home")
    await panel_edit_media(call, state, img, f"{status_text}🧊 Редактор:", ui.kb_editor_home("ru", gender))
    await call.answer()

@router.callback_query(F.data.startswith("editor:open:"))
async def editor_open_cat(call: CallbackQuery, state: FSMContext) -> None:
    cat = call.data.split(":")[-1]
    await state.set_state(Flow.picker)
    await state.update_data(picker_mode="editor", picker_cat=cat, picker_page=1)
    await _render_page(call, state, "editor", cat, 1)

@router.callback_query(F.data.startswith("editor:pick:"))
async def editor_pick(call: CallbackQuery, state: FSMContext) -> None:
    parts = call.data.split(":"); cat, page, idx = parts[2], int(parts[3]), int(parts[4])
    global_idx = (page - 1) * 9 + idx
    data = await state.get_data(); editor_sel = data.get("editor_sel", {})
    if editor_sel.get(cat) == global_idx: del editor_sel[cat]
    else: editor_sel[cat] = global_idx
    await state.update_data(editor_sel=editor_sel)
    # Авто-возврат в меню редактора
    await editor_home(call, state)

@router.callback_query(F.data.startswith("editor:none:"))
async def editor_none(call: CallbackQuery, state: FSMContext) -> None:
    cat = call.data.split(":")[-1]
    data = await state.get_data(); editor_sel = data.get("editor_sel", {})
    if cat in editor_sel: del editor_sel[cat]
    await state.update_data(editor_sel=editor_sel)
    await editor_home(call, state)

@router.callback_query(F.data == ui.CB_SHOOT_HOME)
async def shoots_home(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Flow.shoots_home)
    data = await state.get_data(); gender = data.get("styles_gender", "m")
    img = img_ui("female_shoots") if gender == "f" else img_ui("shoots_home")
    await panel_edit_media(call, state, img, "📸 Фотосессии:", ui.kb_shoots_home("ru"))
    await call.answer()

@router.callback_query(F.data.startswith("shoot:open:"))
async def shoot_open(call: CallbackQuery, state: FSMContext) -> None:
    cat = call.data.split(":")[-1]
    await state.set_state(Flow.picker)
    await state.update_data(picker_mode="shoot", picker_cat=cat, picker_page=1)
    await _render_page(call, state, "shoot", cat, 1)

@router.callback_query(F.data.startswith("shoot:pick:"))
async def shoot_pick(call: CallbackQuery, state: FSMContext) -> None:
    parts = call.data.split(":"); cat, page, idx = parts[2], int(parts[3]), int(parts[4])
    global_idx = (page - 1) * 9 + idx
    await state.update_data(shoot_sel={"cat": cat, "idx": global_idx, "page": page, "sub_idx": idx})
    await _render_page(call, state, "shoot", cat, page)

@router.callback_query(F.data.startswith(ui.CB_NEXT))
async def nav_next(call: CallbackQuery, state: FSMContext) -> None:
    parts = call.data.split(":"); mode, cat, page = parts[2], parts[3], int(parts[4])
    await state.update_data(picker_page=page + 1)
    await _render_page(call, state, mode, cat, page + 1)

@router.callback_query(F.data.startswith(ui.CB_PREV))
async def nav_prev(call: CallbackQuery, state: FSMContext) -> None:
    parts = call.data.split(":"); mode, cat, page = parts[2], parts[3], int(parts[4])
    await state.update_data(picker_page=max(1, page - 1))
    await _render_page(call, state, mode, cat, max(1, page - 1))

async def _render_page(call: CallbackQuery, state: FSMContext, mode: str, cat: str, page: int):
    data = await state.get_data(); gender = data.get("styles_gender", "m")
    selected = None
    count = await api_client.get_catalog_page_info(gender, cat, page)
    title_text = ui.get_cat_title(cat)
    status_prefix = await _get_status_text(data.get("editor_sel", {}), gender) if mode == "editor" else ""

    if mode == "editor":
        img = img_editor(gender, cat, page)
        show_none = True
        g_idx = data.get("editor_sel", {}).get(cat)
        if g_idx:
            start_offset = 9 * (page - 1)
            if start_offset < g_idx <= start_offset + count: selected = g_idx - start_offset
    else:
        img = img_shoot(gender, cat, page)
        show_none = False
        if data.get("shoot_sel", {}).get("cat") == cat:
            g_idx = data.get("shoot_sel", {}).get("idx")
            if g_idx and data.get("shoot_sel", {}).get("page") == page: selected = data.get("shoot_sel", {}).get("sub_idx")

    folder = _assets("editor", gender, cat) if mode == "editor" else _assets("shoots", gender, cat)
    total_pages = _pages_count(folder)
    kb = ui.kb_picker("ru", mode, cat, page, count, set(), (page < total_pages), (page > 1), show_none, selected)
    await panel_edit_media(call, state, img, f"{status_prefix}{title_text}:", kb)
    try: await call.answer()
    except: pass


# -------------------- GENERATION --------------------

@router.callback_query(F.data == ui.CB_GENERATE)
async def generate(call: CallbackQuery, state: FSMContext) -> None:
    if not await has_generations_async(call.from_user.id):
        # ПЕЙВОЛЛ -> compare
        path = img_ui("compare")
        await panel_send(call.message, state, path, ui.TEXT_TIER_SELECTION, ui.kb_tier_selection())
        await call.answer()
        return

    data = await state.get_data()
    file_id = data.get("photo_file_id")
    if not file_id: await call.answer("Нет фото", show_alert=True); return
    if not data.get("shoot_sel") and not data.get("editor_sel"): await call.answer("Ничего не выбрано!", show_alert=True); return

    await call.answer()
    
    await state.update_data(last_custom_prompt=None)
    await _process_generation(call.message, state, is_new_message=False)


@router.callback_query(F.data == ui.CB_REGENERATE)
async def on_regenerate(call: CallbackQuery, state: FSMContext):
    """
    Пользователь нажал 'Сделать снова'
    """
    # 1. Проверяем лимиты
    if not await has_generations_async(call.from_user.id):
        path = img_ui("compare")
        await panel_send(call.message, state, path, ui.TEXT_TIER_SELECTION, ui.kb_tier_selection())
        await call.answer()
        return
    
    # 2. Проверяем, есть ли данные для регенерации
    data = await state.get_data()
    photo_file_id = data.get("photo_file_id")
    
    # Если данных нет (например, после 'Новый образ' стейт очистился или перезагрузка), просим фото
    if not photo_file_id:
        await call.answer()
        # Переводим в ожидание фото
        await state.set_state(Flow.waiting_photo)
        await call.message.answer(ui.TEXTS["ru"]["new_photo_req"])
        return

    # 3. Если данные есть -> запускаем регенерацию
    await call.answer()
    prompt = data.get("last_custom_prompt")
    await _process_generation(call.message, state, prompt=prompt, is_new_message=True)


async def _process_generation(message: Message, state: FSMContext, prompt: str = None, is_new_message: bool = False):
    wait_msg = None
    if is_new_message:
        wait_msg = await message.answer(ui.TEXTS["ru"]["gen_wait"])
    else:
        try: await message.edit_caption(caption=ui.TEXTS["ru"]["gen_wait"], reply_markup=None)
        except: pass

    # Запускаем задачу "обновления" сообщения, если долго
    async def _update_wait_message():
        await asyncio.sleep(15) # Ждем 15 сек перед первым предупреждением
        if is_new_message and wait_msg:
             try: await wait_msg.edit_text(ui.TEXTS["ru"]["gen_wait_long"])
             except: pass
        elif not is_new_message:
             try: await message.edit_caption(caption=ui.TEXTS["ru"]["gen_wait_long"], reply_markup=None)
             except: pass

    # Создаем таску, но не await'им её, чтобы не блокировать генерацию
    long_wait_task = asyncio.create_task(_update_wait_message())

    try:
        data = await state.get_data()
        file_id = data.get("photo_file_id")
        file = await message.bot.get_file(file_id)
        file_io = io.BytesIO()
        await message.bot.download_file(file.file_path, file_io)
        image_b64 = base64.b64encode(file_io.getvalue()).decode("utf-8")

        if prompt:
            res = await api_client.edit_image(message.chat.id, prompt, image_b64)
        else:
            res = await api_client.generate_from_catalog(
                chat_id=message.chat.id,
                image_b64=image_b64,
                gender=data.get("styles_gender", "m"),
                editor_sel=data.get("editor_sel", {}),
                shoot_sel=data.get("shoot_sel", {})
            )

        # Отменяем таску ожидания, если успели
        long_wait_task.cancel()
        
        if wait_msg:
            try:
                await wait_msg.delete()
            except:
                pass

        if res.get("ok"):
            res_b64 = res.get("b64")
            if res_b64:
                file_bytes = base64.b64decode(res_b64)
                image_ext = str(res.get("image_ext") or "jpg").lower()
                if image_ext == "jpeg":
                    image_ext = "jpg"
                if image_ext not in {"jpg", "png", "webp"}:
                    image_ext = "jpg"

                input_file = BufferedInputFile(file_bytes, filename=f"result.{image_ext}")
                
                # --- ЛОГИКА ПОДПИСИ ДЛЯ БЕСПЛАТНЫХ ЮЗЕРОВ ---
                summary = await api_client.get_sub_summary(message.chat.id)
                role = (summary.get("role") or "free").strip().lower()
                
                final_caption = ui.TEXTS["ru"]["result_caption"]
                if role == "free":
                    final_caption += "\n\n✨ Создано с помощью Pro-версии"

                if is_new_message:
                    try:
                        await message.answer_photo(input_file, caption=final_caption, reply_markup=ui.kb_result_actions("ru"))
                    except TelegramBadRequest as photo_err:
                        if "too big for a photo" in str(photo_err).lower():
                            await message.answer_document(
                                BufferedInputFile(file_bytes, filename=f"result.{image_ext}"),
                                caption=final_caption,
                                reply_markup=ui.kb_result_actions("ru"),
                            )
                        else:
                            raise
                else:
                    media = InputMediaPhoto(media=input_file, caption=final_caption)
                    try:
                        await message.edit_media(media=media, reply_markup=ui.kb_result_actions("ru"))
                    except TelegramBadRequest:
                        try:
                            await message.answer_photo(
                                BufferedInputFile(file_bytes, filename=f"result.{image_ext}"),
                                caption=final_caption,
                                reply_markup=ui.kb_result_actions("ru"),
                            )
                        except TelegramBadRequest as photo_err:
                            if "too big for a photo" in str(photo_err).lower():
                                await message.answer_document(
                                    BufferedInputFile(file_bytes, filename=f"result.{image_ext}"),
                                    caption=final_caption,
                                    reply_markup=ui.kb_result_actions("ru"),
                                )
                            else:
                                raise
                
                await state.update_data(last_result_b64=res_b64, last_result_ext=image_ext)
                doc_file = BufferedInputFile(file_bytes, filename=f"facelab_result.{image_ext}")
                await message.answer_document(doc_file)

            else:
                # === ОБРАБОТКА ОШИБКИ ГЕНЕРАЦИИ ===
                is_stub = res.get("stub")
                fail_reason = res.get("reason") or res.get("fail_reason", "unknown")
                
                error_messages = {
                    "safety_filter": "🔄 Запрос не был обработан.\nПопробуйте отправить его ещё 3 раза.\nПри необходимости немного измените формулировку промпта и повторите попытку.",
                    "model_refusal": "🔄 Не удалось обработать запрос.\nПопробуйте ещё 3 раза.\nЕсли результат всё равно не появляется — немного измените промпт и отправьте снова.",
                    "limit_exceeded": "⏳ Сервер перегружен запросами к нейросети. Попробуйте через минуту.",
                    "timeout": "⚡️ Сейчас модель временно перегружена.\nПожалуйста, попробуйте повторить генерацию немного позже.",
                    "server_overloaded": "⚡️ Сейчас модель временно перегружена.\nПожалуйста, попробуйте повторить генерацию немного позже.",
                    "api_error": "🛠 Внутренняя ошибка нейросети. Попробуйте еще раз.",
                    "invalid_image_file": "❌ Не удалось прочитать файл изображения.",
                    "unknown": "⚠️ Не удалось сгенерировать изображение по техническим причинам."
                }
                
                user_text = error_messages.get(fail_reason, error_messages["unknown"])
                
                if is_stub:
                    await message.answer(user_text)
                else:
                    await message.answer(user_text) # Просто выводим текст ошибки
        else:
            err = res.get("error", "unknown")
            if err == "limit_exceeded":
                # ПЕЙВОЛЛ -> compare
                path = img_ui("compare")
                caption = ui.TEXT_TIER_SELECTION
                kb = ui.kb_tier_selection()
                await panel_send(message, state, path, caption, kb)
            else:
                await message.answer(f"❌ Ошибка API: {err}")

    except Exception as e:
        chat_id = message.chat.id
        data = await state.get_data()
        prompt_info = prompt or data.get("last_custom_prompt") or "no prompt"
        logger.error(f"вќЊ Gen Error for user {chat_id} | Prompt: {prompt_info} | Error: {e}", exc_info=True)
        
        # Отменяем таску при ошибке
        try: long_wait_task.cancel()
        except: pass

        if wait_msg: 
            try: await wait_msg.delete()
            except: pass
        await message.answer("❌ Произошла ошибка.")


@router.callback_query(F.data == ui.CB_SAVE_FILE)
async def on_save_file(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    b64_data = data.get("last_result_b64")
    result_ext = str(data.get("last_result_ext") or "jpg").lower()
    if result_ext == "jpeg":
        result_ext = "jpg"
    if result_ext not in {"jpg", "png", "webp"}:
        result_ext = "jpg"
    if not b64_data: await call.answer("Файл устарел", show_alert=True); return
    await call.answer("Отправляю...")
    try:
        file_bytes = base64.b64decode(b64_data)
        await call.message.answer_document(
            BufferedInputFile(file_bytes, filename=f"facelab_result.{result_ext}"),
            caption="Вот ваш файл 💾",
        )
    except Exception: await call.answer("Ошибка отправки", show_alert=True)

@router.callback_query(F.data == ui.CB_GEN_SAME_PHOTO)
async def on_gen_same_photo(call: CallbackQuery, state: FSMContext):
    if not await has_generations_async(call.from_user.id):
        # ПЕЙВОЛЛ -> compare
        path = img_ui("compare")
        await panel_send(call.message, state, path, ui.TEXT_TIER_SELECTION, ui.kb_tier_selection())
        await call.answer(); return

    await state.update_data(shoot_sel={}, editor_sel={})
    await state.set_state(Flow.main_menu)
    data = await state.get_data(); gender = data.get("styles_gender", "m")
    menu_caption = "🧊 <b>Редактор внешности</b> — точечные изменения.\n\n📸 <b>Фотосессии</b> — готовые образы."
    img = img_ui("female_menu") if gender == "f" else img_ui("menu")
    await panel_send(call.message, state, img_path=img, caption=menu_caption, kb=ui.kb_main_menu("ru"))
    await call.answer()

@router.callback_query(F.data == ui.CB_GEN_NEW_PHOTO)
async def on_gen_new_photo(call: CallbackQuery, state: FSMContext):
    """
    Пользователь хочет сгенерировать новое фото.
    Мы не сразу показываем пейволл, а просим прислать новое фото.
    """
    # 1. Проверяем лимиты
    if not await has_generations_async(call.from_user.id):
        # Если лимитов нет -> ПЕЙВОЛЛ (compare)
        path = img_ui("compare")
        caption = ui.TEXT_TIER_SELECTION
        kb = ui.kb_tier_selection()
        await panel_send(call.message, state, path, caption, kb=kb)
        await call.answer()
        return

    # 2. Если лимиты есть -> Сбрасываем стейт и просим фото
    # НЕ делаем state.clear() сразу, чтобы сохранить старые данные на случай "отмены", 
    # но в данном контексте "Новый образ" подразумевает полный сброс.
    # Чтобы "Сделать снова" не падало, нужно, чтобы пользователь НЕ нажимал "Новый образ" если хочет перегенерировать старое.
    # Но если он нажал, а потом передумал и нажал "Сделать снова" на СТАРОМ сообщении...
    # То у нас проблема: state уже очищен.
    
    # РЕШЕНИЕ: Мы не делаем state.clear() здесь. Мы просто переводим в waiting_photo.
    # Старые данные (photo_file_id) останутся в state, пока не придет новое фото.
    # Новое фото перезапишет photo_file_id.
    
    await state.set_state(Flow.waiting_photo)
    
    # Отправляем сообщение-просьбу
    await call.message.answer(ui.TEXTS["ru"]["new_photo_req"])
    await call.answer()

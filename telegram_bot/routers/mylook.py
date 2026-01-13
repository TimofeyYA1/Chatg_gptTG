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

from telegram_bot import api_client
from telegram_bot import ui_elements as ui
from common.config import settings

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
    BotCommand
)
from aiogram.exceptions import TelegramNetworkError, TelegramBadRequest
from datetime import timedelta 

router = Router()

# -------------------- CONFIG --------------------

BUY_LOCK: set[int] = set()
_MEDIA_CACHE: Dict[str, str] = {}

PLAN_TRANSLATE = {
    "Week_Std": "7 дней (Обычная)", "Week_Pro": "7 дней (Pro)",
    "Month_Std": "месяц (Обычная)", "Month_Pro": "месяц (Pro)",
    "Year_Std": "год (Обычная)",    "Year_Pro": "год (Pro)",
    "free": "нет",
}
PLAN_PRICES = {
    "Week_Std": "399",  "Week_Pro": "799",
    "Month_Std": "1199", "Month_Pro": "2399",
    "Year_Std": "5999",  "Year_Pro": "11999",
}

STARS_PRICES_SUB = {
    "Week_Std": 300,  "Week_Pro": 600,
    "Month_Std": 900, "Month_Pro": 1800,
    "Year_Std": 4500, "Year_Pro": 9000,
}
STARS_PRICES_PKG = {
    "150": 260,
    "1000": 1500,
    "5000": 4500,
}

RUB_PKG_MAP = {"150": 349, "1000": 1999, "5000": 5999}

ADMIN_IDS = [847867090,370260285] 

# -------------------- Utils --------------------

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
        BotCommand(command="start", description="🏠 Главное"),
        BotCommand(command="premium", description="💳 Подписка"),
        BotCommand(command="account", description="💎 Баланс и бонусы"),
        BotCommand(command="help", description="🆘 Нужна помощь?"),
    ]
    await message.bot.set_my_commands(commands)
    await message.answer("✅ Меню бота обновлено! Нажмите на кнопку 'Меню' слева внизу, чтобы проверить.")


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
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
        # Если Free -> compare
        caption = ui.TEXT_TIER_SELECTION
        kb = ui.kb_tier_selection()
        img = img_ui("compare")
    else:
        totals = summary.get("totals", {})
        usage = summary.get("usage", {})
        available = max(0, totals.get("images", 0) - usage.get("images", 0))
        
        plan_period = PLAN_TRANSLATE.get(role, role)
        base_limit = summary.get("limits", {}).get("images", 0)
        
        plan_type = "Pro" if "Pro" in role else "Обычная"
        plan_name = f"Премиум {plan_type}, {plan_period} ({base_limit} генераций)"
        
        price = PLAN_PRICES.get(role, "---")
        active_until_str = _format_ru_date(summary.get("active_until"))
        auto_renew = summary.get("auto_renew", True)
        
        if auto_renew:
            renewal_info = f"💳 Следующее списание: {active_until_str} ({price}₽)"
        else:
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
    if not await has_generations_async(message.chat.id):
        await message.answer("⚠️ Пакеты генераций доступны только при активной подписке.")
        return
    await panel_send(message, state, img_ui("packages"), ui.TEXT_PACKAGES_CAPTION, ui.kb_packages("ru"))

@router.callback_query(F.data == ui.CB_CANCEL_SUB)
async def cancel_sub(call: CallbackQuery, state: FSMContext):
    res = await api_client.cancel_plan(call.from_user.id)
    if res.get("ok"): await call.answer("Автопродление отключено.", show_alert=True); await premium_cmd(call, state, is_edit=True)
    else: await call.answer("Ошибка отмены.", show_alert=True)

# -------------------- TIER SELECTION --------------------

@router.callback_query(F.data == ui.CB_TIER_STD)
async def on_tier_std(call: CallbackQuery, state: FSMContext):
    # ОБЫЧНАЯ ВЕРСИЯ -> man.jpg
    # ПЕРЕДАЕМ CAPTION (можно пустой или ui.PREMIUM_PAYWALL_CAPTION_RU)
    caption = ui.PREMIUM_PAYWALL_CAPTION_RU 
    kb = ui.kb_premium_paywall("ru", tier="std")
    await panel_edit_media(call, state, img_ui("man"), caption='', kb=kb)
    await call.answer()

@router.callback_query(F.data == ui.CB_TIER_PRO)
async def on_tier_pro(call: CallbackQuery, state: FSMContext):
    # PRO ВЕРСИЯ
    caption = ui.PREMIUM_PAYWALL_CAPTION_RU
    kb = ui.kb_premium_paywall("ru", tier="pro")
    await panel_edit_media(call, state, img_ui("man"), caption='', kb=kb)
    await call.answer()

@router.callback_query(F.data == "nav:back_to_tiers")
async def on_back_to_tiers(call: CallbackQuery, state: FSMContext):
    # Возврат к выбору версии -> compare.jpg
    await panel_edit_media(call, state, img_ui("compare"), caption=ui.TEXT_TIER_SELECTION, kb=ui.kb_tier_selection())
    await call.answer()

# -------------------- PAYMENT FLOW (RU + STARS) --------------------

@router.callback_query(F.data.startswith("premium:buy:"))
async def ask_payment_method_sub(call: CallbackQuery, state: FSMContext):
    # call.data пример: premium:buy:week:pro или premium:buy:week:std
    parts = call.data.split(":")
    period = parts[2] 
    tier = parts[3] if len(parts) > 3 else "std" 
    
    period_cap = period.capitalize()
    tier_cap = tier.capitalize()
    plan_key = f"{period_cap}_{tier_cap}"
    
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
    
    price_rub = RUB_PKG_MAP.get(pkg_id, 0)
    price_stars = STARS_PRICES_PKG.get(pkg_id, 0)
    
    payload_data = f"pkg:{pkg_id}"
    
    if not await has_generations_async(call.from_user.id):
        await call.answer("Нужна активная подписка!", show_alert=True)
        return

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
    api_url = settings.API_PUBLIC_URL 
    if not api_url.startswith("http"):
        api_url = "http://localhost:8000"
        
    payment_link = f"{api_url}/payments/checkout?chat_id={uid}&type={ptype}&value={pvalue}&message_id={message_id}"
    
    caption = ""
    
    if ptype == "plan":
        plan_key = pvalue
        now = datetime.now()
        
        tier_name = "Pro" if "Pro" in plan_key else "Обычная"
        
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
            period_str = "год"
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
        caption = (
            f"Вы приобретаете пакет: <b>{pvalue} генераций - {price_rub}₽</b>\n\n"
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
    description = "Покупка"
    
    if payload.startswith("plan:"):
        p_name = payload.split(":")[1]
        title = f"Подписка {p_name.replace('_', ' ')}"
        description = f"Премиум доступ на {PLAN_TRANSLATE.get(p_name, p_name)}"
        
    elif payload.startswith("pkg:"):
        qty = payload.split(":")[1]
        title = f"{qty} генераций"
        description = (
            f"Вы приобретаете пакет: {qty} генераций - {price_stars} ⭐️\n\n"
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
        
        pkg_id = payload.split(":")[1]
        price_rub = RUB_PKG_MAP.get(pkg_id, 0)
        price_stars = STARS_PRICES_PKG.get(pkg_id, 0)

        await panel_send(
            call.message, state, 
            img_path, caption, 
            kb=ui.payment_choice_kb(price_rub, price_stars, payload)
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
        rub_val = int(PLAN_PRICES.get(pk, 0))
    elif payload.startswith("pkg:"):
        qk = payload.split(":")[1]
        rub_val = RUB_PKG_MAP.get(qk, 0)

    if rub_val > 0:
        await api_client.balance_topup(uid, rub_val * 100)

    try:
        if payload.startswith("plan:"):
            period = payload.split(":")[1]
            res = await api_client.set_plan(uid, period=period)
            if res.get("ok"):
                await message.answer(f"✅ Оплата Звездами прошла успешно! Подписка активирована.")
            else:
                await message.answer(f"⚠️ Оплата прошла, но активация сбойнула: {res.get('detail')}")
                
        elif payload.startswith("pkg:"):
            qty = int(payload.split(":")[1])
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

@router.message(Flow.waiting_photo, F.photo)
async def got_photo(message: Message, state: FSMContext) -> None:
    photo = message.photo[-1]
    await state.update_data(photo_file_id=photo.file_id)
    await _after_photo_received(message, state)

@router.message(Flow.waiting_photo, F.document)
async def got_document_photo(message: Message, state: FSMContext) -> None:
    doc = message.document
    if not doc.mime_type or not doc.mime_type.startswith("image/"):
        await message.answer("❌ Пожалуйста, отправьте именно изображение (JPG/PNG).")
        return
    await state.update_data(photo_file_id=doc.file_id)
    await _after_photo_received(message, state)

async def _after_photo_received(message: Message, state: FSMContext):
    await state.set_state(Flow.choosing_gender)
    await panel_send(
        message, state,
        img_ui("gender"),
        caption="Выберите пол для корректного применения стилей:",
        kb=ui.kb_gender_or_prompt("ru"),
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
        await call.answer("Нужна подписка", show_alert=True); return
    await state.set_state(Flow.choosing_gender)
    await panel_edit_media(call, state, img_ui("gender"), "Выберите пол для корректного применения стилей:", ui.kb_gender_or_prompt("ru"))
    await call.answer()

@router.callback_query(F.data == ui.CB_CUSTOM_PROMPT)
async def custom_prompt_click(call: CallbackQuery, state: FSMContext) -> None:
    if not await has_generations_async(call.from_user.id):
        # ПЕЙВОЛЛ -> compare
        path = img_ui("compare")
        await panel_edit_media(call, state, path, ui.TEXT_TIER_SELECTION, ui.kb_tier_selection())
        await call.answer()
        return
    
    await state.set_state(Flow.waiting_custom_prompt)
    await panel_edit_media(call, state, img_ui("gender"), "✍️ <b>Напишите свой запрос.</b>\n\n...", ui.kb_back_to_gender("ru"))
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
        await call.answer("Нужна подписка"); return
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

        if wait_msg:
            try:
                await wait_msg.delete()
            except:
                pass

        if res.get("ok"):
            res_b64 = res.get("b64")
            if res_b64:
                file_bytes = base64.b64decode(res_b64)
                input_file = BufferedInputFile(file_bytes, filename="result.jpg")
                
                # --- ЛОГИКА ПОДПИСИ ДЛЯ БЕСПЛАТНЫХ ЮЗЕРОВ ---
                summary = await api_client.get_sub_summary(message.chat.id)
                role = (summary.get("role") or "free").strip().lower()
                
                final_caption = ui.TEXTS["ru"]["result_caption"]
                if role == "free":
                    final_caption += "\n\n✨ Создано с помощью Pro-версии"

                if is_new_message:
                    await message.answer_photo(input_file, caption=final_caption, reply_markup=ui.kb_result_actions("ru"))
                else:
                    media = InputMediaPhoto(media=input_file, caption=final_caption)
                    try:
                        await message.edit_media(media=media, reply_markup=ui.kb_result_actions("ru"))
                    except TelegramBadRequest:
                        await message.answer_photo(input_file, caption=final_caption, reply_markup=ui.kb_result_actions("ru"))
                
                await state.update_data(last_result_b64=res_b64)
                doc_file = BufferedInputFile(file_bytes, filename="mylook_result.jpg")
                await message.answer_document(doc_file)

            else:
                # === ОБРАБОТКА ОШИБКИ ГЕНЕРАЦИИ ===
                is_stub = res.get("stub")
                fail_reason = res.get("fail_reason", "unknown")
                
                error_messages = {
                    "safety_filter": "🔞 <b>Нейросеть заблокировала генерацию.</b>\nПохоже, фото содержит лицо, которое алгоритмы Google сочли небезопасным (Safety Filter). Попробуйте другое фото или менее вызывающий стиль.",
                    "model_refusal": "🤖 Нейросеть отказалась обрабатывать этот запрос.",
                    "limit_exceeded": "⏳ Сервер перегружен запросами к нейросети. Попробуйте через минуту.",
                    "api_error": "🛠 Внутренняя ошибка нейросети. Попробуйте еще раз.",
                    "invalid_image_file": "❌ Не удалось прочитать файл изображения.",
                    "unknown": "⚠️ Не удалось сгенерировать изображение по техническим причинам."
                }
                
                user_text = error_messages.get(fail_reason, error_messages["unknown"])
                
                if is_stub:
                    await message.answer(user_text)
                else:
                    await message.answer("⚠️ Пустой результат.")
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
        print(f"Gen Error: {e}")
        if wait_msg: 
            try: await wait_msg.delete()
            except: pass
        await message.answer("❌ Произошла ошибка.")


@router.callback_query(F.data == ui.CB_SAVE_FILE)
async def on_save_file(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    b64_data = data.get("last_result_b64")
    if not b64_data: await call.answer("Файл устарел", show_alert=True); return
    await call.answer("Отправляю...")
    try:
        file_bytes = base64.b64decode(b64_data)
        await call.message.answer_document(BufferedInputFile(file_bytes, filename="mylook_result.jpg"), caption="Вот ваш файл 💾")
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
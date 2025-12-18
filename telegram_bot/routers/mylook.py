from __future__ import annotations
import glob
import re
import os
import io
import base64
import asyncio
from datetime import date, datetime
from typing import Dict, Any, Optional

from telegram_bot import api_client
from telegram_bot import ui_elements as ui
from common.config import settings

from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    Message, CallbackQuery,
    FSInputFile, BufferedInputFile, 
    ReplyKeyboardRemove, InputMediaPhoto,
)
from aiogram.exceptions import TelegramNetworkError, TelegramBadRequest

router = Router()

# -------------------- CONFIG --------------------

BUY_LOCK: set[int] = set()
_MEDIA_CACHE: Dict[str, str] = {}

PLAN_TRANSLATE = {
    "Week": "7 дней",
    "Month": "месяц",
    "Year": "год",
    "free": "нет",
}
PLAN_PRICES = {
    "Week": "399",
    "Month": "1199",
    "Year": "5999",
}

# -------------------- Utils --------------------

def _format_ru_date(iso: str | None) -> str:
    if not iso: return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y %H:%M MSK")
    except:
        if "T" in iso: return iso.split("T")[0]
        return iso

async def is_premium_async(uid: int) -> bool:
    try:
        return await api_client.is_premium(uid)
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

def img_shoot(cat: str, page: int) -> str:
    p = _find(_assets("shoots", cat, f"p{page}"))
    return p or img_ui("shoots_home")

def img_editor(gender: str, cat: str, page: int) -> str:
    p = _find(_assets("editor", gender, cat, f"p{page}"))
    return p or img_ui("menu")

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

# -------------------- FSM --------------------
class Flow(StatesGroup):
    waiting_photo = State()
    choosing_gender = State()
    main_menu = State()
    editor_home = State()
    picker = State()
    shoots_home = State()
    waiting_custom_prompt = State()

# -------------------- COMMANDS --------------------

@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    try: await api_client.ensure_user(message.chat.id)
    except: pass

    if await is_premium_async(message.chat.id):
        await state.set_state(Flow.waiting_photo)
        path = img_ui("start")
        caption = ui.TEXTS["ru"]["start_title"] + "\n" + ui.TEXTS["ru"]["send_photo"]
        await panel_send(message, state, path, caption, kb=None)
    else:
        path = img_ui("premium_paywall")
        caption = ui.PREMIUM_PAYWALL_CAPTION_RU
        kb = ui.kb_premium_paywall("ru")
        await panel_send(message, state, path, caption, kb=kb)

@router.callback_query(F.data == ui.CB_RESTART)
async def restart_callback(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if await is_premium_async(call.from_user.id):
        await state.set_state(Flow.waiting_photo)
        path = img_ui("start")
        caption = ui.TEXTS["ru"]["start_title"] + "\n" + ui.TEXTS["ru"]["send_photo"]
        try: await panel_edit_media(call, state, path, caption, kb=None)
        except: await panel_send(call.message, state, path, caption, kb=None)
    else:
        path = img_ui("premium_paywall")
        caption = ui.PREMIUM_PAYWALL_CAPTION_RU
        kb = ui.kb_premium_paywall("ru")
        try: await panel_edit_media(call, state, path, caption, kb=kb)
        except: await panel_send(call.message, state, path, caption, kb=kb)
    await call.answer()


# -------------------- PREMIUM / ACCOUNT / HELP / PACKAGES --------------------

@router.message(Command("premium"))
@router.message(Command("account"))
async def premium_cmd(message: Message, state: FSMContext, is_edit: bool = False) -> None:
    uid = message.chat.id
    try: summary = await api_client.get_sub_summary(uid)
    except: summary = {}

    role = (summary.get("role") or "free").strip()
    
    if role.lower() == "free":
        caption = ui.PREMIUM_PAYWALL_CAPTION_RU
        kb = ui.kb_premium_paywall("ru")
        img = img_ui("premium_paywall")
    else:
        totals = summary.get("totals", {})
        usage = summary.get("usage", {})
        available = max(0, totals.get("images", 0) - usage.get("images", 0))
        
        plan_name = PLAN_TRANSLATE.get(role, role)
        base_limit = summary.get("limits", {}).get("images", 0)
        price = PLAN_PRICES.get(role, "---")
        active_until_str = _format_ru_date(summary.get("active_until"))
        
        auto_renew = summary.get("auto_renew", True)
        
        if auto_renew:
            renewal_info = f"💳 Следующее списание: <b>{active_until_str} ({price}₽)</b>"
        else:
            renewal_info = f"⏳ Действует до: <b>{active_until_str}</b>"
        
        invited = 0 

        caption = ui.TEXT_PREMIUM_ACTIVE_TEMPLATE.format(
            available=available,
            plan_name=plan_name,
            limit=base_limit,
            renewal_info=renewal_info,
            price=price,
            invited_count=invited
        )
        
        bot_info = await message.bot.get_me()
        kb = ui.kb_premium_active(uid, bot_info.username, auto_renew=auto_renew)
        img = img_ui("premium")

    if not img or not os.path.exists(img): img = img_ui("premium")
    
    if is_edit:
        data = await state.get_data()
        msg_id = data.get("panel_id") or message.message_id
        
        cached_id = _MEDIA_CACHE.get(img)
        if cached_id: media = InputMediaPhoto(media=cached_id, caption=caption)
        else: media = InputMediaPhoto(media=FSInputFile(img), caption=caption)
        
        try:
            res = await message.bot.edit_message_media(
                chat_id=message.chat.id,
                message_id=msg_id,
                media=media,
                reply_markup=kb
            )
            if not cached_id and isinstance(res, Message) and res.photo:
                _MEDIA_CACHE[img] = res.photo[-1].file_id
        except TelegramBadRequest:
            pass
        except Exception:
            await panel_send(message, state, img, caption, kb)
            
    else:
        await panel_send(message, state, img_path=img, caption=caption, kb=kb)


@router.message(Command("help"))
async def help_cmd(message: Message, state: FSMContext) -> None:
    await message.answer(ui.TEXT_HELP_RU, reply_markup=ui.kb_help("ru"), disable_web_page_preview=True)

@router.callback_query(F.data == ui.CB_LANG_TOGGLE)
async def help_lang_toggle(call: CallbackQuery, state: FSMContext) -> None:
    current_text = call.message.text or call.message.caption or ""
    if "Как использовать" in current_text:
        new_text = ui.TEXT_HELP_EN
        new_kb = ui.kb_help("en")
    else:
        new_text = ui.TEXT_HELP_RU
        new_kb = ui.kb_help("ru")
    await call.message.edit_text(new_text, reply_markup=new_kb, disable_web_page_preview=True)
    await call.answer()


@router.message(Command("packages"))
async def packages_cmd(message: Message, state: FSMContext) -> None:
    if not await is_premium_async(message.chat.id):
        await message.answer("⚠️ Пакеты генераций доступны только при активной подписке.\nСначала оформите /premium")
        return

    await panel_send(message, state, img_ui("packages"), ui.TEXT_PACKAGES_CAPTION, ui.kb_packages("ru"))

@router.callback_query(F.data.startswith("pkg:"))
async def buy_package_click(call: CallbackQuery, state: FSMContext):
    pkg_map = {
        ui.CB_PKG_150: {"qty": 150, "price": 349_00},
        ui.CB_PKG_1000: {"qty": 1000, "price": 1999_00},
        ui.CB_PKG_5000: {"qty": 5000, "price": 5999_00},
    }
    
    info = pkg_map.get(call.data)
    if not info: return

    if not await is_premium_async(call.from_user.id):
        await call.answer("Нужна активная подписка!", show_alert=True)
        return
    
    res = await api_client.buy_addon(call.from_user.id, info["qty"], info["price"])
    
    if res.get("ok"):
        await call.answer(f"✅ Успешно добавлено {info['qty']} генераций!", show_alert=True)
        await premium_cmd(call.message, state, is_edit=True)
    else:
        await call.answer(f"Ошибка: {res.get('detail', 'Error')}", show_alert=True)


# -------------------- PAYMENTS --------------------

@router.callback_query(F.data.startswith("premium:buy:"))
async def premium_buy(call: CallbackQuery, state: FSMContext) -> None:
    uid = call.from_user.id
    period = call.data.split(":")[-1]
    if uid in BUY_LOCK:
        await call.answer("⏳ Обработка...", show_alert=True)
        return
    BUY_LOCK.add(uid)

    try:
        res = await api_client.set_plan(uid, period=period)
        if res.get("error"):
            msg = res.get("detail", "")
            if msg == "subscription_already_active":
                await call.answer("У вас уже есть активная подписка!", show_alert=True)
            else:
                await call.answer(f"Ошибка: {msg}", show_alert=True)
            return
        
        await call.answer("Оплата успешна! ✅", show_alert=True)
        try: await call.message.delete()
        except: pass
        await premium_cmd(call.message, state, is_edit=False)

    except Exception as e:
        print(f"Payment Error: {e}")
    finally:
        BUY_LOCK.discard(uid)

@router.callback_query(F.data == ui.CB_CANCEL_SUB)
async def cancel_sub(call: CallbackQuery, state: FSMContext):
    res = await api_client.cancel_plan(call.from_user.id)
    if res.get("ok"):
        await call.answer("Автопродление отключено.", show_alert=True)
        await premium_cmd(call.message, state, is_edit=True)
    else:
        await call.answer("Ошибка отмены.", show_alert=True)


# -------------------- Navigation & Render --------------------

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
        img_path=img_ui("gender"),
        caption="Выберите пол для корректного применения стилей:",
        kb=ui.kb_gender_or_prompt("ru"),
    )

@router.callback_query(F.data.in_({ui.CB_STYLES_M, ui.CB_STYLES_F}))
async def choose_gender(call: CallbackQuery, state: FSMContext) -> None:
    gender = "m" if call.data == ui.CB_STYLES_M else "f"
    await state.update_data(styles_gender=gender)
    
    if not await is_premium_async(call.from_user.id):
        img = img_ui("premium_paywall")
        if not img or not os.path.exists(img): img = img_ui("premium")
        await panel_edit_media(call, state, img_path=img, caption=ui.PREMIUM_PAYWALL_CAPTION_RU, kb=ui.kb_premium_paywall("ru"))
        await call.answer()
        return

    await state.set_state(Flow.main_menu)
    await state.update_data(editor_sel={}, shoot_sel={}) 
    await _show_main_menu(call, state)
    await call.answer()

@router.callback_query(F.data == ui.CB_BACK_TO_GENDER)
async def back_to_gender(call: CallbackQuery, state: FSMContext) -> None:
    if not await is_premium_async(call.from_user.id):
        await call.answer("Нужна подписка", show_alert=True)
        return

    await state.set_state(Flow.choosing_gender)
    await panel_edit_media(
        call, state,
        img_path=img_ui("gender"),
        caption="Выберите пол для корректного применения стилей:",
        kb=ui.kb_gender_or_prompt("ru")
    )
    await call.answer()

@router.callback_query(F.data == ui.CB_CUSTOM_PROMPT)
async def custom_prompt_click(call: CallbackQuery, state: FSMContext) -> None:
    if not await is_premium_async(call.from_user.id):
        await call.answer("Нужна подписка 🔒", show_alert=True)
        return
    
    await state.set_state(Flow.waiting_custom_prompt)
    await panel_edit_media(
        call, state,
        img_path=img_ui("gender"), 
        caption=(
            "✍️ <b>Напишите свой запрос.</b>\n\n"
            "Например:\n"
            "<i>— Сделай меня киборгом в стиле киберпанк</i>\n"
            "<i>— Фото в костюме супергероя на крыше</i>\n"
            "<i>— Нарисуй меня в стиле аниме 90-х</i>\n\n"
            "Чем детальнее описание, тем лучше результат! 👇"
        ),
        kb=ui.kb_back_to_gender("ru")
    )
    await call.answer()

@router.message(Flow.waiting_custom_prompt)
async def handle_custom_prompt_text(message: Message, state: FSMContext) -> None:
    prompt = message.text
    if not prompt: return
    if not await is_premium_async(message.chat.id):
        await message.answer("🔒 Ваша подписка истекла.")
        return
    await _process_generation(message, state, prompt)

@router.callback_query(F.data == ui.CB_MENU)
async def back_to_main_menu(call: CallbackQuery, state: FSMContext) -> None:
    if not await is_premium_async(call.from_user.id):
        img = img_ui("premium_paywall") or img_ui("premium")
        await panel_edit_media(call, state, img_path=img, caption=ui.PREMIUM_PAYWALL_CAPTION_RU, kb=ui.kb_premium_paywall("ru"))
        await call.answer("Срок подписки истек")
        return

    await state.set_state(Flow.main_menu)
    await _show_main_menu(call, state)
    await call.answer()

async def _show_main_menu(call: CallbackQuery, state: FSMContext) -> None:
    menu_caption = (
        "🧊 <b>Редактор внешности</b> — точечные изменения вашего образа:\n"
        "прически, цвет волос, пирсинг и многое другое.\n\n"
        "📸 <b>Фотосессии</b> — готовые стилизованные образы и\n"
        "профессиональные AI-съёмки в один клик."
    )
    await panel_edit_media(call, state, img_path=img_ui("menu"), caption=menu_caption, kb=ui.kb_main_menu("ru"))

@router.callback_query(F.data == ui.CB_BACK_TO_PHOTO)
async def back_to_photo(call: CallbackQuery, state: FSMContext) -> None:
    if not await is_premium_async(call.from_user.id):
        await call.answer("Нужна подписка")
        return

    await state.set_state(Flow.waiting_photo)
    caption = ui.TEXTS["ru"]["start_title"] + "\n" + ui.TEXTS["ru"]["send_photo"]
    await panel_edit_media(call, state, img_path=img_ui("start"), caption=caption, kb=None)
    await call.answer()

@router.callback_query(F.data == ui.CB_EDITOR_HOME)
async def editor_home(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Flow.editor_home)
    await panel_edit_media(call, state, img_path=img_ui("editor_home"), caption="🧊 Редактор:", kb=ui.kb_editor_home("ru"))
    await call.answer()

@router.callback_query(F.data.startswith("editor:open:"))
async def editor_open_cat(call: CallbackQuery, state: FSMContext) -> None:
    cat = call.data.split(":")[-1]
    await state.set_state(Flow.picker)
    await state.update_data(picker_mode="editor", picker_cat=cat, picker_page=1)
    await _render_page(call, state, "editor", cat, 1)

@router.callback_query(F.data.startswith("editor:pick:"))
async def editor_pick(call: CallbackQuery, state: FSMContext) -> None:
    parts = call.data.split(":")
    cat, page, idx = parts[2], int(parts[3]), int(parts[4])
    global_idx = (page - 1) * 9 + idx
    
    data = await state.get_data()
    editor_sel = data.get("editor_sel", {})
    editor_sel[cat] = global_idx
    await state.update_data(editor_sel=editor_sel)
    await _render_page(call, state, "editor", cat, page)

@router.callback_query(F.data.startswith("editor:none:"))
async def editor_none(call: CallbackQuery, state: FSMContext) -> None:
    cat = call.data.split(":")[-1]
    data = await state.get_data()
    editor_sel = data.get("editor_sel", {})
    if cat in editor_sel: del editor_sel[cat]
    await state.update_data(editor_sel=editor_sel)
    await _render_page(call, state, "editor", cat, data.get("picker_page", 1))

@router.callback_query(F.data == ui.CB_SHOOT_HOME)
async def shoots_home(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Flow.shoots_home)
    await panel_edit_media(call, state, img_path=img_ui("shoots_home"), caption="📸 Фотосессии:", kb=ui.kb_shoots_home("ru"))
    await call.answer()

@router.callback_query(F.data.startswith("shoot:open:"))
async def shoot_open(call: CallbackQuery, state: FSMContext) -> None:
    cat = call.data.split(":")[-1]
    await state.set_state(Flow.picker)
    await state.update_data(picker_mode="shoot", picker_cat=cat, picker_page=1)
    await _render_page(call, state, "shoot", cat, 1)

@router.callback_query(F.data.startswith("shoot:pick:"))
async def shoot_pick(call: CallbackQuery, state: FSMContext) -> None:
    parts = call.data.split(":")
    cat, page, idx = parts[2], int(parts[3]), int(parts[4])
    global_idx = (page - 1) * 9 + idx
    await state.update_data(shoot_sel={"cat": cat, "idx": global_idx, "page": page, "sub_idx": idx})
    await _render_page(call, state, "shoot", cat, page)

@router.callback_query(F.data.startswith(ui.CB_NEXT))
async def nav_next(call: CallbackQuery, state: FSMContext) -> None:
    parts = call.data.split(":")
    mode, cat, page = parts[2], parts[3], int(parts[4])
    await state.update_data(picker_page=page + 1)
    await _render_page(call, state, mode, cat, page + 1)

@router.callback_query(F.data.startswith(ui.CB_PREV))
async def nav_prev(call: CallbackQuery, state: FSMContext) -> None:
    parts = call.data.split(":")
    mode, cat, page = parts[2], parts[3], int(parts[4])
    await state.update_data(picker_page=max(1, page - 1))
    await _render_page(call, state, mode, cat, max(1, page - 1))

async def _render_page(call: CallbackQuery, state: FSMContext, mode: str, cat: str, page: int):
    data = await state.get_data()
    gender = data.get("styles_gender", "m")
    selected = None
    
    # Запрашиваем у сервера актуальное количество кнопок
    count = await api_client.get_catalog_page_info(gender, cat, page)

    title_text = ui.get_cat_title(cat)

    if mode == "editor":
        folder = _assets("editor", gender, cat)
        img = img_editor(gender, cat, page)
        show_none = True
        g_idx = data.get("editor_sel", {}).get(cat)
        if g_idx:
            # Расчет смещения для определения selection
            # Важно: это работает только если мы идем последовательно по страницам
            # Для упрощения пока считаем локальный индекс на странице
            # Если сложная логика с разными count на разных страницах, тут надо бы тоже спрашивать сервер
            # Но для визуала кнопки "selected" можно временно оставить упрощенную логику 
            # или (правильнее) запросить у сервера: "на какой странице и каком слоте лежит global_idx?"
            # Пока оставим как есть, но используем правильный count для генерации кнопок
            
            # Приблизительный расчет для подсветки (может быть неточным на 2+ странице)
            start_offset = 9 * (page - 1) 
            if start_offset < g_idx <= start_offset + count:
                selected = g_idx - start_offset

    else:
        folder = _assets("shoots", cat)
        img = img_shoot(cat, page)
        show_none = False
        if data.get("shoot_sel", {}).get("cat") == cat:
            g_idx = data.get("shoot_sel", {}).get("idx")
            if g_idx and data.get("shoot_sel", {}).get("page") == page:
                selected = data.get("shoot_sel", {}).get("sub_idx")

    total_pages = _pages_count(folder)
    
    kb = ui.kb_picker(
        lang="ru", 
        mode=mode, 
        cat=cat, 
        page=page, 
        count=count, 
        locked=set(), 
        has_next=(page < total_pages), 
        has_prev=(page > 1), 
        show_none=show_none, 
        selected_idx=selected
    )
    
    await panel_edit_media(call, state, img_path=img, caption=f"{title_text}:", kb=kb)
    try: await call.answer()
    except: pass

@router.callback_query(F.data == ui.CB_GENERATE)
async def generate(call: CallbackQuery, state: FSMContext) -> None:
    if not await is_premium_async(call.from_user.id):
        await call.answer("Подписка истекла!", show_alert=True)
        return

    data = await state.get_data()
    file_id = data.get("photo_file_id")
    shoot_sel = data.get("shoot_sel", {})
    editor_sel = data.get("editor_sel", {})

    if not file_id:
        await call.answer("Нет фото. Начните заново /start", show_alert=True)
        return
    
    if not shoot_sel and not editor_sel:
        await call.answer("Выберите стиль или прическу!", show_alert=True)
        return

    await call.answer()
    
    wait_msg = await call.message.answer("⏳ <b>Генерирую...</b>\n\n<i>Подбираем лучший образ...</i>")

    try:
        file = await call.bot.get_file(file_id)
        file_io = io.BytesIO()
        await call.bot.download_file(file.file_path, file_io)
        image_b64 = base64.b64encode(file_io.getvalue()).decode("utf-8")

        res = await api_client.generate_from_catalog(
            chat_id=call.from_user.id,
            image_b64=image_b64,
            gender=data.get("styles_gender", "m"),
            editor_sel=editor_sel,
            shoot_sel=shoot_sel
        )

        try: await wait_msg.delete()
        except: pass

        if res.get("ok"):
            res_b64 = res.get("b64")
            if res_b64:
                file_bytes = base64.b64decode(res_b64)
                await call.message.answer_photo(
                    BufferedInputFile(file_bytes, filename="result.jpg"), 
                    caption="✨ Ваш новый образ!", 
                    reply_markup=ui.kb_result_actions("ru")
                )
                await state.update_data(last_result_b64=res_b64)
            else:
                await call.message.answer("⚠️ Пустой результат.")
        else:
            err = res.get("error", "unknown")
            if err == "limit_exceeded":
                await call.message.answer("🚫 <b>Лимит генераций исчерпан.</b>")
            else:
                await call.message.answer(f"❌ Ошибка API: {err}")
    
    except Exception as e:
        print(f"Gen Catalog Error: {e}")
        try: await wait_msg.delete()
        except: pass
        await call.message.answer("❌ Произошла ошибка.")


async def _process_generation(message: Message, state: FSMContext, prompt: str):
    wait_msg = await message.answer(f"⏳ <b>Генерирую...</b>\n\n<i>Запрос: {prompt[:50]}...</i>")
    
    try:
        data = await state.get_data()
        file_id = data.get("photo_file_id")
        
        file = await message.bot.get_file(file_id)
        file_io = io.BytesIO()
        await message.bot.download_file(file.file_path, file_io)
        
        image_b64 = base64.b64encode(file_io.getvalue()).decode("utf-8")

        res = await api_client.edit_image(
            chat_id=message.chat.id,
            prompt=prompt,
            image_b64=image_b64
        )
        
        try: await wait_msg.delete()
        except: pass

        if not res.get("ok"):
            err = res.get("error", "Unknown")
            if err == "limit_exceeded":
                await message.answer("🚫 <b>Лимит генераций исчерпан.</b>")
            else:
                await message.answer(f"❌ Ошибка API: {err}")
            return

        result_b64 = res.get("b64")
        if result_b64:
            result_bytes = base64.b64decode(result_b64)
            result_file = BufferedInputFile(result_bytes, filename="result.jpg")
            
            await message.answer_photo(
                result_file, 
                caption="✨ Ваш новый образ!",
                reply_markup=ui.kb_result_actions("ru")
            )
            await state.update_data(last_result_b64=result_b64)
        else:
            await message.answer("⚠️ Сервер вернул пустой результат.")
            
    except Exception as e:
        print(f"[GEN ERROR] {e}")
        try: await wait_msg.delete()
        except: pass
        await message.answer("❌ Произошла системная ошибка.")


@router.callback_query(F.data == ui.CB_SAVE_FILE)
async def on_save_file(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    b64_data = data.get("last_result_b64")
    if not b64_data:
        await call.answer("Файл устарел", show_alert=True)
        return
    await call.answer("Отправляю...")
    try:
        file_bytes = base64.b64decode(b64_data)
        await call.message.answer_document(BufferedInputFile(file_bytes, filename="mylook_result.jpg"), caption="Вот ваш файл 💾")
    except Exception:
        await call.answer("Ошибка отправки", show_alert=True)

@router.callback_query(F.data == ui.CB_GEN_SAME_PHOTO)
async def on_gen_same_photo(call: CallbackQuery, state: FSMContext):
    """
    Пользователь хочет сгенерировать новый образ по тому же фото.
    Сбрасываем выбор стилей, но оставляем фото и пол.
    Перекидываем в Главное меню.
    """
    # Сбрасываем выбранные стили
    await state.update_data(shoot_sel={}, editor_sel={})
    
    await state.set_state(Flow.main_menu)
    
    # Отправляем НОВОЕ сообщение с меню (так как это результат генерации)
    menu_caption = "🧊 <b>Редактор внешности</b> — точечные изменения.\n\n📸 <b>Фотосессии</b> — готовые стилизованные образы."
    await panel_send(call.message, state, img_ui("menu"), menu_caption, ui.kb_main_menu("ru"))
    
    await call.answer()

@router.callback_query(F.data == ui.CB_GEN_NEW_PHOTO)
async def on_gen_new_photo(call: CallbackQuery, state: FSMContext):
    """
    Пользователь хочет загрузить новое фото.
    Полный сброс стейта.
    """
    await state.clear()
    
    # Проверяем подписку (на всякий случай, хотя она уже есть раз дошли сюда)
    if await is_premium_async(call.from_user.id):
        await state.set_state(Flow.waiting_photo)
        path = img_ui("start")
        caption = ui.TEXTS["ru"]["start_title"] + "\n" + ui.TEXTS["ru"]["send_photo"]
        await panel_send(call.message, state, path, caption, kb=None)
    else:
        # Если вдруг подписка кончилась пока он смотрел на результат
        path = img_ui("premium_paywall")
        caption = ui.PREMIUM_PAYWALL_CAPTION_RU
        kb = ui.kb_premium_paywall("ru")
        await panel_send(call.message, state, path, caption, kb=kb)
        
    await call.answer()


# --- PANEL HELPERS ---
async def panel_send(message: Message, state: FSMContext, img_path: str, caption: str, kb=None) -> None:
    if not img_path or not os.path.exists(img_path):
        sent = await message.answer(caption, reply_markup=kb)
        await state.update_data(panel_id=sent.message_id)
        return
    
    cached_id = _MEDIA_CACHE.get(img_path)
    if cached_id: photo_obj = cached_id
    else: photo_obj = FSInputFile(img_path)

    try:
        sent = await message.answer_photo(photo_obj, caption=caption, reply_markup=kb)
        if not cached_id and sent.photo: _MEDIA_CACHE[img_path] = sent.photo[-1].file_id
        await state.update_data(panel_id=sent.message_id)
    except Exception:
        if cached_id: del _MEDIA_CACHE[img_path]; await panel_send(message, state, img_path, caption, kb)

async def panel_edit_media(call: CallbackQuery, state: FSMContext, img_path: str, caption: str, kb=None) -> None:
    data = await state.get_data()
    msg_id = data.get("panel_id") or call.message.message_id
    if not img_path or not os.path.exists(img_path): img_path = img_ui("start")
    
    cached_id = _MEDIA_CACHE.get(img_path)
    if cached_id: media = InputMediaPhoto(media=cached_id, caption=caption)
    else: media = InputMediaPhoto(media=FSInputFile(img_path), caption=caption)
    
    try:
        res = await call.bot.edit_message_media(chat_id=call.message.chat.id, message_id=msg_id, media=media, reply_markup=kb)
        if not cached_id and isinstance(res, Message) and res.photo: _MEDIA_CACHE[img_path] = res.photo[-1].file_id
    except TelegramBadRequest: pass
    except Exception: 
        if cached_id: del _MEDIA_CACHE[img_path]
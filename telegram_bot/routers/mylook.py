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

# -------------------- Utils & Helpers --------------------

BUY_LOCK: set[int] = set()
_MEDIA_CACHE: Dict[str, str] = {}

PLAN_RU = {
    "Week": "Неделя",
    "Month": "Месяц",
    "Year": "Год",
    "free": "Нет",
}

def _format_ru_date(iso: str | None) -> str:
    if not iso: return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y")
    except:
        if "T" in iso: return iso.split("T")[0]
        return iso

def _premium_active_caption(summary: dict) -> str:
    role = (summary.get("role") or "free")
    role_ru = PLAN_RU.get(role, role)
    active_until = _format_ru_date(summary.get("active_until"))
    
    usage = summary.get("usage", {})
    limits = summary.get("limits", {})
    
    used = usage.get("images", 0)
    total = limits.get("images", 0)
    
    if total > 0:
        progress_text = f"Использовано генераций: <b>{used} из {total}</b>"
    else:
        progress_text = "Генерации недоступны"

    return (
        "⭐ <b>Подписка активна!</b>\n\n"
        f"Ваш план: <b>{role_ru}</b>\n"
        f"Действует до: <b>{active_until}</b>\n\n"
        f"{progress_text}\n\n"
        "✅ Вам доступны все функции бота.\n"
        "Вы можете докупить время (срок суммируется):"
    )

async def is_premium_async(uid: int) -> bool:
    try:
        return await api_client.is_premium(uid)
    except:
        return False

# -------------------- Assets Helpers --------------------

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

# -------------------- Handlers: Start & Auth --------------------

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
        if not path: path = img_ui("premium")
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
        try:
            await panel_edit_media(call, state, path, caption, kb=None)
        except:
            await panel_send(call.message, state, path, caption, kb=None)
    else:
        path = img_ui("premium_paywall")
        caption = ui.PREMIUM_PAYWALL_CAPTION_RU
        kb = ui.kb_premium_paywall("ru")
        try:
            await panel_edit_media(call, state, path, caption, kb=kb)
        except:
            await panel_send(call.message, state, path, caption, kb=kb)
            
    await call.answer()

# -------------------- Photo Upload --------------------

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

# -------------------- Gender Selection (The Hub) --------------------

@router.message(Command("premium"))
async def premium_cmd(message: Message, state: FSMContext) -> None:
    uid = message.chat.id
    try: summary = await api_client.get_sub_summary(uid)
    except: summary = {}

    role = (summary.get("role") or "free").lower()
    if role != "free":
        caption = _premium_active_caption(summary)
        kb = ui.kb_premium_active("ru")
        img = img_ui("premium")
    else:
        caption = ui.PREMIUM_PAYWALL_CAPTION_RU
        kb = ui.kb_premium_paywall("ru")
        img = img_ui("premium_paywall")
    
    if not img or not os.path.exists(img): img = img_ui("premium")
    await panel_send(message, state, img_path=img, caption=caption, kb=kb)

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

# -------------------- Custom Prompt Logic --------------------

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
    if not prompt:
        await message.answer("Пожалуйста, отправьте текстовое описание.")
        return

    if not await is_premium_async(message.chat.id):
        await message.answer("🔒 Ваша подписка истекла.")
        return

    data = await state.get_data()
    file_id = data.get("photo_file_id")
    if not file_id:
        await message.answer("Ошибка: фото не найдено. Нажмите /start и загрузите фото заново.")
        return

    wait_msg = await message.answer("⏳ <b>Генерирую... Подождите, это может занять минуту.</b>")
    
    try:
        file = await message.bot.get_file(file_id)
        file_io = io.BytesIO()
        await message.bot.download_file(file.file_path, file_io)
        
        file_bytes = file_io.getvalue()
        image_b64 = base64.b64encode(file_bytes).decode("utf-8")
        
        res = await api_client.edit_image(message.chat.id, prompt, image_b64)
        
        try: await wait_msg.delete()
        except: pass

        if not res.get("ok"):
            if res.get("error") == "limit_exceeded":
                await message.answer("🚫 <b>Лимит генераций исчерпан!</b>\n\nПожалуйста, продлите подписку или дождитесь нового периода.")
                return
            
            error_text = res.get("error", "Unknown error")
            await message.answer(f"❌ Ошибка генерации: {error_text}")
            return
        
        result_b64 = res.get("b64")
        if not result_b64:
            await message.answer("❌ API вернул пустой результат.")
            return
            
        result_bytes = base64.b64decode(result_b64)
        result_file = BufferedInputFile(result_bytes, filename="result.jpg")
        
        caption = res.get("caption", "✨ Готово!")
        
        await message.answer_photo(
            result_file, 
            caption=caption, 
            reply_markup=ui.kb_result_actions("ru")
        )
        
        await state.update_data(last_result_b64=result_b64)

    except Exception as e:
        print(f"Generate Error: {e}")
        try: await wait_msg.delete() 
        except: pass
        await message.answer("❌ Произошла ошибка при обработке. Попробуйте позже.")


# --- Handlers for Result Actions ---

@router.callback_query(F.data == ui.CB_SAVE_FILE)
async def on_save_file(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    b64_data = data.get("last_result_b64")
    
    if not b64_data:
        await call.answer("Файл устарел или не найден.", show_alert=True)
        return
        
    await call.answer("Отправляю файл...")
    try:
        file_bytes = base64.b64decode(b64_data)
        doc_file = BufferedInputFile(file_bytes, filename="mylook_result.jpg")
        await call.message.answer_document(doc_file, caption="Вот ваш файл 💾")
    except Exception as e:
        print(f"File send error: {e}")
        await call.answer("Ошибка при отправке файла", show_alert=True)


@router.callback_query(F.data == ui.CB_GEN_NEW)
async def on_gen_new(call: CallbackQuery, state: FSMContext):
    await restart_callback(call, state)


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
            BUY_LOCK.discard(uid)
            # Если вернулась ошибка "subscription_already_active", говорим об этом юзеру
            if res.get("detail") == "subscription_already_active":
                await call.answer("У вас уже есть активная подписка!", show_alert=True)
            else:
                await call.answer(f"Ошибка: {res.get('detail')}", show_alert=True)
            return

        summary = await api_client.get_sub_summary(uid)
        active_caption = _premium_active_caption(summary)
        active_kb = ui.kb_premium_active("ru")
        active_img = img_ui("premium")

        await panel_edit_media(call, state, img_path=active_img, caption=active_caption, kb=active_kb)
        try: await call.answer("Оплата успешна! ✅", show_alert=True)
        except: pass

    except Exception as e:
        print(f"Payment Error: {e}")
        try: await call.answer("Ошибка при обновлении статуса.", show_alert=True)
        except: pass
    finally:
        BUY_LOCK.discard(uid)

# -------------------- Navigation & Render --------------------

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
        img = img_ui("premium_paywall") or img_ui("premium")
        await panel_edit_media(call, state, img_path=img, caption=ui.PREMIUM_PAYWALL_CAPTION_RU, kb=ui.kb_premium_paywall("ru"))
        await call.answer("Нужна подписка")
        return

    await state.set_state(Flow.waiting_photo)
    caption = ui.TEXTS["ru"]["start_title"] + "\n" + ui.TEXTS["ru"]["send_photo"]
    await panel_edit_media(call, state, img_path=img_ui("start"), caption=caption, kb=None)
    await call.answer()

# -------------------- Common Panels --------------------

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
        if not cached_id and sent.photo:
            _MEDIA_CACHE[img_path] = sent.photo[-1].file_id
        await state.update_data(panel_id=sent.message_id)
    except Exception as e:
        if cached_id:
            del _MEDIA_CACHE[img_path]
            return await panel_send(message, state, img_path, caption, kb)

async def panel_edit_media(call: CallbackQuery, state: FSMContext, img_path: str, caption: str, kb=None) -> None:
    data = await state.get_data()
    msg_id = data.get("panel_id") or call.message.message_id
    
    if not img_path or not os.path.exists(img_path): img_path = img_ui("start")
    
    cached_id = _MEDIA_CACHE.get(img_path)
    if cached_id: media = InputMediaPhoto(media=cached_id, caption=caption)
    else: media = InputMediaPhoto(media=FSInputFile(img_path), caption=caption)
    
    try:
        edited_msg = await call.bot.edit_message_media(chat_id=call.message.chat.id, message_id=msg_id, media=media, reply_markup=kb)
        if not cached_id and isinstance(edited_msg, Message) and edited_msg.photo:
            _MEDIA_CACHE[img_path] = edited_msg.photo[-1].file_id
    except TelegramBadRequest as e:
        if "message is not modified" in str(e): return
    except Exception as e:
        if cached_id: del _MEDIA_CACHE[img_path]

# -------------------- Editor/Shoots Stubs --------------------

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
    
    data = await state.get_data()
    gender = data.get("styles_gender", "m")
    editor_sel = data.get("editor_sel", {})
    current_global_idx = editor_sel.get(cat)
    
    page = 1
    selected = current_global_idx if (current_global_idx and 1 <= current_global_idx <= 9) else None
    
    kb = ui.kb_picker("ru", "editor", cat, page, 9, set(), 
                      has_next=_pages_count(_assets("editor", gender, cat)) > 1, 
                      has_prev=False, show_none=True, selected_idx=selected)
    await panel_edit_media(call, state, img_path=img_editor(gender, cat, 1), caption=f"{cat}:", kb=kb)
    await call.answer()

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
    
    data = await state.get_data()
    shoot_sel = data.get("shoot_sel", {})
    selected = None
    if shoot_sel.get("cat") == cat:
        g_idx = shoot_sel.get("idx")
        if g_idx and 1 <= g_idx <= 9: selected = g_idx
    
    kb = ui.kb_picker("ru", "shoot", cat, 1, 9, set(), 
                      has_next=_pages_count(_assets("shoots", cat)) > 1, 
                      has_prev=False, show_none=False, selected_idx=selected)
    await panel_edit_media(call, state, img_path=img_shoot(cat, 1), caption=f"{cat}:", kb=kb)
    await call.answer()

@router.callback_query(F.data.startswith("shoot:pick:"))
async def shoot_pick(call: CallbackQuery, state: FSMContext) -> None:
    parts = call.data.split(":")
    cat, page, idx = parts[2], int(parts[3]), int(parts[4])
    global_idx = (page - 1) * 9 + idx
    await state.update_data(shoot_sel={"cat": cat, "idx": global_idx})
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

async def _render_page(call, state, mode, cat, page):
    data = await state.get_data()
    gender = data.get("styles_gender", "m")
    selected = None
    
    if mode == "editor":
        folder = _assets("editor", gender, cat)
        img = img_editor(gender, cat, page)
        show_none = True
        g_idx = data.get("editor_sel", {}).get(cat)
        if g_idx:
            s_idx, e_idx = (page-1)*9+1, page*9
            if s_idx <= g_idx <= e_idx: selected = g_idx - (s_idx - 1)
    else:
        folder = _assets("shoots", cat)
        img = img_shoot(cat, page)
        show_none = False
        if data.get("shoot_sel", {}).get("cat") == cat:
            g_idx = data.get("shoot_sel", {}).get("idx")
            if g_idx:
                s_idx, e_idx = (page-1)*9+1, page*9
                if s_idx <= g_idx <= e_idx: selected = g_idx - (s_idx - 1)
    
    total = _pages_count(folder)
    if page > total: page = total
    
    kb = ui.kb_picker("ru", mode, cat, page, 9, set(), has_next=(page < total), has_prev=(page > 1), show_none=show_none, selected_idx=selected)
    await panel_edit_media(call, state, img_path=img, caption=f"{cat}:", kb=kb)
    try: await call.answer()
    except: pass

@router.callback_query(F.data == ui.CB_GENERATE)
async def generate(call: CallbackQuery, state: FSMContext) -> None:
    if not await is_premium_async(call.from_user.id):
        await call.answer("Подписка истекла!", show_alert=True)
        return
    # Тут пока заглушка для кнопочной генерации
    # Основная магия "Своего промпта" выше
    data = await state.get_data()
    file_id = data.get("photo_file_id")
    await call.message.answer_photo(photo=file_id, caption="✨ Готово. Сделано с любовью.")
    await panel_edit_media(call, state, img_path=img_ui("menu"), caption="Меню", kb=ui.kb_main_menu("ru"))
    await call.answer()

@router.callback_query(F.data == ui.CB_GENERATE)
async def generate(call: CallbackQuery, state: FSMContext) -> None:
    # 1. Проверка подписки
    if not await is_premium_async(call.from_user.id):
        await call.answer("Подписка истекла!", show_alert=True)
        # Можно кинуть paywall в чат
        return

    # 2. Получаем данные
    data = await state.get_data()
    file_id = data.get("photo_file_id")
    editor_sel = data.get("editor_sel", {})
    shoot_sel = data.get("shoot_sel", {})
    gender = data.get("styles_gender", "m")

    # Проверка: выбрано ли хоть что-то?
    if not file_id:
        await call.answer("Нет фото. Начните заново /start", show_alert=True)
        return
    
    # Если и редактор пуст, и фотосессии нет
    if not editor_sel and not shoot_sel:
        await call.answer("Выберите хотя бы один стиль!", show_alert=True)
        return

    # 3. Визуальная реакция
    await call.answer()
    wait_msg = await call.message.answer("⏳ <b>Генерирую... Это займет около минуты.</b>")

    try:
        # 4. Скачиваем фото и в base64
        file = await call.bot.get_file(file_id)
        file_io = io.BytesIO()
        await call.bot.download_file(file.file_path, file_io)
        
        image_b64 = base64.b64encode(file_io.getvalue()).decode("utf-8")

        # 5. Отправляем на API
        res = await api_client.generate_from_catalog(
            chat_id=call.from_user.id,
            image_b64=image_b64,
            gender=gender,
            editor_sel=editor_sel,
            shoot_sel=shoot_sel
        )

        # 6. Удаляем "Генерирую..."
        try: await wait_msg.delete()
        except: pass

        # 7. Обработка ответа
        if not res.get("ok"):
            err = res.get("error", "Unknown")
            if err == "limit_exceeded":
                await call.message.answer("🚫 <b>Лимит генераций исчерпан.</b>\nПродлите подписку для новых попыток.")
            elif err == "no_selection":
                await call.message.answer("⚠️ Вы ничего не выбрали.")
            else:
                await call.message.answer(f"❌ Ошибка: {err}")
            return

        result_b64 = res.get("b64")
        caption = res.get("caption", "Готово")

        if result_b64:
            # Декодируем и отправляем
            result_bytes = base64.b64decode(result_b64)
            result_file = BufferedInputFile(result_bytes, filename="result.jpg")
            
            # Отправляем фото с кнопками действий (Сохранить/Дальше)
            await call.message.answer_photo(
                result_file, 
                caption=caption,
                reply_markup=ui.kb_result_actions("ru")
            )
            
            # Сохраняем результат для кнопки "Скачать файл"
            await state.update_data(last_result_b64=result_b64)
            
            # Сбрасываем выбор редактора (по желанию), чтобы не мешал следующей генерации
            # await state.update_data(editor_sel={}, shoot_sel={})
            
            # Возвращаем меню
            await panel_send(call.message, state, img_ui("menu"), caption="Главное меню:", kb=ui.kb_main_menu("ru"))
        else:
            await call.message.answer("⚠️ Сервер вернул пустой результат (Stub mode?)")

    except Exception as e:
        print(f"Catalog Gen Error: {e}")
        try: await wait_msg.delete() 
        except: pass
        await call.message.answer("❌ Произошла ошибка. Попробуйте позже.")
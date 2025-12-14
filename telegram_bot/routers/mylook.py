from __future__ import annotations
import glob
import re
import os
from datetime import date
from typing import Dict, Any, Optional
from aiogram.filters import Command


from telegram_bot import api_client
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    Message, CallbackQuery,
    FSInputFile, ReplyKeyboardRemove,
    InputMediaPhoto,
)

from telegram_bot import ui_elements as ui

router = Router()

# -------------------- simple credits + premium stubs --------------------
CREDITS: Dict[int, Dict[str, Any]] = {}

def _ensure_daily_bucket(uid: int) -> Dict[str, Any]:
    today = date.today().isoformat()
    b = CREDITS.get(uid)
    if not b or b.get("day") != today:
        b = {"day": today, "used": 0}
        CREDITS[uid] = b
    return b

def _has_free(uid: int) -> bool:
    return _ensure_daily_bucket(uid)["used"] < 1

def _use_free(uid: int) -> None:
    _ensure_daily_bucket(uid)["used"] += 1

async def is_premium_async(uid: int) -> bool:
    try:
        return await api_client.is_premium(uid)
    except Exception:
        return False


# -------------------- FSM --------------------
class Flow(StatesGroup):
    waiting_photo = State()
    choosing_gender = State()
    main_menu = State()
    editor_home = State()
    picker = State()
    shoots_home = State()
    waiting_custom_prompt = State()


# -------------------- assets helpers --------------------
def _assets(*parts: str) -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", *parts))

def _find(base_no_ext: str) -> Optional[str]:
    for ext in (".jpg", ".png", ".jpeg", ".webp"):
        p = base_no_ext + ext
        if os.path.exists(p):
            return p
    return None

def img_ui(name: str) -> str:
    p = _find(_assets("ui", name))
    if p:
        return p
    # fallback
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "topper.jpg"))

def img_shoot(cat: str, page: int) -> str:
    p = _find(_assets("shoots", cat, f"p{page}"))
    return p or img_ui("shoots_home")

def img_editor(gender: str, cat: str, page: int) -> str:
    p = _find(_assets("editor", gender, cat, f"p{page}"))
    # если нет гендерного — можно сделать общий fallback (если захочешь)
    return p or img_ui("menu")

_PAGE_RE = re.compile(r"p(\d+)\.(jpg|jpeg|png|webp)$", re.IGNORECASE)

def _list_pages(folder: str) -> list[int]:
    """
    Возвращает отсортированный список страниц по файлам pN.jpg/png...
    """
    if not os.path.isdir(folder):
        return []
    pages = []
    for fn in os.listdir(folder):
        m = _PAGE_RE.match(fn)
        if m:
            pages.append(int(m.group(1)))
    return sorted(set(pages))

def _pages_count(folder: str) -> int:
    pages = _list_pages(folder)
    return max(pages) if pages else 1

def _count_default(mode: str, cat: str) -> int:
    """
    Сколько кнопок показывать 1..N на странице (по твоему UX).
    Это НЕ страницы, это количество вариантов на ОДНОМ коллаже.
    """
    if mode == "shoot":
        # фотосессии
        return {
            "trends": 4,
            "winter": 6,
            "looks": 9,
            "sets": 9,   # у тебя sets p1..p4, обычно там 9
        }.get(cat, 9)

    # editor
    return {
        "hair": 9,
        "color": 9,
        "piercing": 9,
        "moustache": 6,
        "beard": 6,
        "glasses": 4,
    }.get(cat, 9)

def _free_open_default(mode: str, cat: str) -> set[int]:
    """
    Какие номера (на странице) открыты бесплатно.
    Остальные получат 🔒.
    """
    if mode == "shoot":
        return {
            "looks": {1, 2, 3},
            "sets": {1},
            "winter": {1},
            "trends": {1},
        }.get(cat, {1})

    # editor
    return {
        "hair": {1},
        "color": {1, 2},
        "piercing": {1, 2},
        "moustache": {1},
        "beard": {1},
        "glasses": {1},
    }.get(cat, {1})

def _locked_set(mode: str, cat: str, page: int, premium: bool) -> set[int]:
    """
    Возвращает локальные номера 1..N, которые должны быть с 🔒
    """
    if premium:
        return set()
    count = _count_default(mode, cat)
    open_set = _free_open_default(mode, cat)
    return {i for i in range(1, count + 1) if i not in open_set}

def _has_next_page(folder: str, page: int) -> bool:
    total = _pages_count(folder)
    return page < total

def _has_prev_page(page: int) -> bool:
    return page > 1
# -------------------- labels (optional) --------------------
_LABEL_CACHE: Dict[str, list[str]] = {}

def _labels_key(mode: str, gender: str, cat: str) -> str:
    return f"{mode}:{gender}:{cat}"

def _labels_path(mode: str, gender: str, cat: str) -> str:
    if mode == "editor":
        return _assets("editor", gender, cat, "labels_ru.txt")
    return _assets("shoots", cat, "labels_ru.txt")

def _load_labels(mode: str, gender: str, cat: str) -> list[str]:
    key = _labels_key(mode, gender, cat)
    if key in _LABEL_CACHE:
        return _LABEL_CACHE[key]

    path = _labels_path(mode, gender, cat)
    labels: list[str] = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                t = line.strip()
                if t:
                    labels.append(t)

    _LABEL_CACHE[key] = labels
    return labels

def _option_label(mode: str, gender: str, cat: str, global_idx: int) -> str:
    labels = _load_labels(mode, gender, cat)
    if 1 <= global_idx <= len(labels):
        return labels[global_idx - 1]
    return f"#{global_idx}"
def _render_selected_editor_ru(data: dict) -> str:
    out: list[str] = []
    gender = data.get("styles_gender", "m")
    editor_sel: dict = data.get("editor_sel") or {}

    for cat, val in editor_sel.items():
        if val is None:
            continue
        title = CAT_TITLES_RU.get(cat, cat)
        out.append(f"- {title}: {_option_label('editor', gender, cat, int(val))}")

    return ("Вы выбрали:\n" + "\n".join(out)) if out else ""


def _render_selected_shoot_ru(data: dict) -> str:
    out: list[str] = []
    gender = data.get("styles_gender", "m")
    shoot_sel: dict | None = data.get("shoot_sel")

    if shoot_sel:
        cat = shoot_sel.get("cat")
        val = shoot_sel.get("val")
        if cat and val:
            title = CAT_TITLES_RU.get(cat, cat)
            out.append(f"- {title}: {_option_label('shoot', gender, cat, int(val))}")

    return ("Вы выбрали:\n" + "\n".join(out)) if out else ""

# -------------------- catalog (настрой прямо под свои коллажи) --------------------
# Сколько кнопок на странице и сколько страниц у каждой категории.
SHOOTS_META = {
    "trends": {"pages": 1, "count": {1: 4}, "free_open": {1}},
    "winter": {"pages": 1, "count": {1: 6}, "free_open": {1}},
    "sets":   {"pages": 1, "count": {1: 6}, "free_open": {1}},
    "looks":  {"pages": 2, "count": {1: 9, 2: 9}, "free_open": {1,2,3}},
}

EDITOR_META = {
    "hair":      {"pages": 2, "count": {1: 9, 2: 9}, "free_open": {1}},
    "color":     {"pages": 1, "count": {1: 9}, "free_open": {1,2}},
    "piercing":  {"pages": 1, "count": {1: 9}, "free_open": {1,2}},
    "moustache": {"pages": 1, "count": {1: 6}, "free_open": {1}},
    "beard":     {"pages": 1, "count": {1: 6}, "free_open": {1}},
    "glasses":   {"pages": 1, "count": {1: 4}, "free_open": {1}},
}

CAT_TITLES_RU = {
    "hair": "Прическа",
    "color": "Цвет волос",
    "piercing": "Пирсинг",
    "moustache": "Усы",
    "beard": "Борода",
    "glasses": "Очки",
    "trends": "Тренды",
    "winter": "Зимние стили",
    "sets": "Фотосеты",
    "looks": "Готовые образы",
}

def locked_set(meta: dict, page: int, premium: bool) -> set[int]:
    if premium:
        return set()
    open_set = meta.get("free_open", {1})
    count = meta.get("count", {}).get(page, 0)
    return {i for i in range(1, count + 1) if i not in open_set}


async def panel_send(message: Message, state: FSMContext, img_path: str, caption: str, kb=None) -> None:
    sent = await message.answer_photo(FSInputFile(img_path), caption=caption, reply_markup=kb)
    await state.update_data(panel_id=sent.message_id)

async def panel_edit_media(call: CallbackQuery, state: FSMContext, img_path: str, caption: str, kb=None) -> None:
    data = await state.get_data()
    msg_id = data.get("panel_id") or call.message.message_id
    media = InputMediaPhoto(media=FSInputFile(img_path), caption=caption)
    await call.bot.edit_message_media(
        chat_id=call.message.chat.id,
        message_id=msg_id,
        media=media,
        reply_markup=kb,
    )



# -------------------- copy-like captions (ты можешь править) --------------------
START_CAPTION_RU = (
    "📸 Отправьте фото, где хорошо видно ваше лицо — как на примере выше. "
    "Это нужно для корректной генерации образа."
)

GENDER_CAPTION_RU = "Выберите пол для корректного применения стилей:"
MENU_CAPTION_RU = (
    "🧊 <b>Редактор внешности</b> — точечные изменения вашего образа:\n"
    "прически, цвет волос, пирсинг и многое другое.\n\n"
    "📸 <b>Фотосессии</b> — готовые стилизованные образы и\n"
    "профессиональные AI-съёмки в один клик."
)


# -------------------- handlers --------------------
@router.message(Command("premium"))
async def premium_cmd(message: Message, state: FSMContext) -> None:
    text = (
        "🚀 <b>Разблокируйте все возможности прямо сейчас!</b>\n\n"
        "🎨 Более 100 шаблонов из каталога\n"
        "🧑‍🎤 Новые стили каждую неделю\n"
        "🖼 Скачивание в HD качестве\n\n"
        "⏱ Скидка действует 10 минут."
    )
    await message.answer_photo(
        FSInputFile(img_ui("premium")),
        caption=text,
        reply_markup=ui.kb_premium_paywall("ru"),
    )

@router.callback_query(F.data.startswith(ui.CB_PREMIUM_BUY))
async def premium_buy(call: CallbackQuery, state: FSMContext) -> None:
    # premium:buy:week/month/year
    period = call.data.split(":")[-1]

    # маппинг периодов на планы твоей API
    plan_by_period = {
        "week": "Light",
        "month": "Max",
        "year": "Ultra",
    }
    plan = plan_by_period.get(period)
    if not plan:
        await call.answer("bad plan", show_alert=True)
        return

    res = await api_client.set_plan(call.from_user.id, plan=plan)
    if res.get("error"):
        await call.answer(
            f"API ошибка ({res.get('step')}): {res.get('detail')}",
            show_alert=True
        )
        return


    await call.answer(f"Подписка активирована: {plan} ✅", show_alert=True)

    # после покупки сразу пускаем в меню, если пользователь уже в потоке (есть panel_id)
    data = await state.get_data()
    if data.get("panel_id") and data.get("styles_gender"):
        await state.set_state(Flow.main_menu)
        await _show_main_menu(call, state)



@router.message(Command("account"))
async def account_cmd(message: Message, state: FSMContext) -> None:
    await message.answer("🎁 Баланс и реферальная система — скоро подключим. Пока заглушка.")


@router.message(Command("help"))
async def help_cmd(message: Message, state: FSMContext) -> None:
    await message.answer("❓ Помощь — скоро подключим. Пока заглушка.")


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(Flow.waiting_photo)

        # регаем пользователя в API (создаст в БД запись users/premium_credits)
    try:
        await api_client.ensure_user(message.chat.id)
    except Exception:
        pass


    # 1) стартовая картинка + кнопка "ЗАГРУЗИТЬ ФОТО" (inline)
    await panel_send(
        message,
        state,
        img_path=img_ui("start"),
        caption=START_CAPTION_RU,
        kb=None,
    )

@router.callback_query(F.data == ui.CB_MENU)
async def back_to_main_menu(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Flow.main_menu)
    await panel_edit_media(
        call,
        state,
        img_path=img_ui("menu"),
        caption=MENU_CAPTION_RU,
        kb=ui.kb_main_menu("ru"),
    )
    await call.answer()




@router.message(Flow.waiting_photo, F.photo)
async def got_photo(message: Message, state: FSMContext) -> None:
    photo = message.photo[-1]
    await state.update_data(photo_file_id=photo.file_id)


    # 2) новый экран: выбор "мужские/женские/свой промпт" (как на скрине)
    await state.set_state(Flow.choosing_gender)

    # ВАЖНО: это НОВОЕ сообщение (как ты просил “приходит новое сообщение”)
    await panel_send(
        message,
        state,
        img_path=img_ui("gender"),
        caption=GENDER_CAPTION_RU,
        kb=ui.kb_gender_or_prompt("ru"),
        
    )


@router.callback_query(F.data.in_({ui.CB_STYLES_M, ui.CB_STYLES_F}))
async def choose_gender(call: CallbackQuery, state: FSMContext) -> None:
    gender = "m" if call.data == ui.CB_STYLES_M else "f"
    await state.update_data(styles_gender=gender)
    if not await is_premium_async(call.from_user.id):
        # не пускаем дальше — показываем paywall
        await call.message.answer_photo(
            FSInputFile(img_ui("premium")),
            caption="🔒 Доступ только по подписке. Выберите план:",
            reply_markup=ui.kb_premium_paywall("ru"),
        )
        await call.answer()
        return

    # 3) экран-меню (картинка menu.jpg + кнопки редактор/фотосессии/назад)
    await state.set_state(Flow.main_menu)
    await _show_main_menu(call, state)
    await state.update_data(editor_sel={}, shoot_sel=None)
    await call.answer()


@router.callback_query(F.data == ui.CB_CUSTOM_PROMPT)
async def custom_prompt_stub(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Flow.waiting_custom_prompt)
    await call.message.answer("✏️ Пришли свой промпт текстом (пока заглушка, потом подключим).")
    await call.answer()


@router.message(Flow.waiting_custom_prompt)
async def receive_custom_prompt(message: Message, state: FSMContext) -> None:
    # заглушка: сохраним и вернём в меню
    await state.update_data(custom_prompt=message.text, styles_gender="m")  # можно default
    await state.set_state(Flow.main_menu)

    # вернём панель-меню
    data = await state.get_data()
    panel_id = data.get("panel_id")
    if panel_id:
        media = InputMediaPhoto(media=FSInputFile(img_ui("menu")), caption=MENU_CAPTION_RU)
        await message.bot.edit_message_media(chat_id=message.chat.id, message_id=panel_id, media=media, reply_markup=ui.kb_main_menu("ru"))
    else:
        await message.answer("Ок.", reply_markup=ReplyKeyboardRemove())


@router.callback_query(F.data == ui.CB_BACK_TO_PHOTO)
async def back_to_photo(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Flow.waiting_photo)
    await panel_edit_media(call, state, img_path=img_ui("start"), caption=START_CAPTION_RU, kb=None)
    await call.answer()


async def _show_main_menu(call: CallbackQuery, state: FSMContext) -> None:
    await panel_edit_media(call, state, img_path=img_ui("menu"), caption=MENU_CAPTION_RU, kb=ui.kb_main_menu("ru"))
async def _show_editor_home(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    sel = _render_selected_editor_ru(data)
    caption = "🧙 Используйте кнопки ниже, чтобы создать свой уникальный стиль.\n"
    if sel:
        caption += f"\n{sel}"
    img = img_ui("editor_home") if os.path.exists(_assets("ui", "editor_home.jpg")) or os.path.exists(_assets("ui", "editor_home.png")) else img_ui("menu")
    await panel_edit_media(call, state, img_path=img, caption=caption, kb=ui.kb_editor_home("ru"))

async def _show_shoots_home(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    sel = _render_selected_shoot_ru(data)
    caption = "📸 Используйте кнопки ниже для выбора AI-фотосессии.\n"
    if sel:
        caption += f"\n{sel}"
    await panel_edit_media(call, state, img_path=img_ui("shoots_home"), caption=caption, kb=ui.kb_shoots_home("ru"))


# -------------------- Editor --------------------
@router.callback_query(F.data == ui.CB_EDITOR_HOME)
async def editor_home(call: CallbackQuery, state: FSMContext) -> None:
    if not await is_premium_async(call.from_user.id):
        await call.message.answer_photo(
            FSInputFile(img_ui("premium")),
            caption="🔒 Доступ только по подписке. Выберите план:",
            reply_markup=ui.kb_premium_paywall("ru"),
        )
        await call.answer()
        return

    await state.set_state(Flow.editor_home)
    await state.update_data(shoot_sel=None)
    await _show_editor_home(call, state)
    await call.answer()


@router.callback_query(F.data.startswith("editor:open:"))
async def editor_open_cat(call: CallbackQuery, state: FSMContext) -> None:
    cat = call.data.split(":")[-1]
    await state.set_state(Flow.picker)
    await state.update_data(picker_mode="editor", picker_cat=cat, picker_page=1)

    data = await state.get_data()
    gender = data.get("styles_gender", "m")

    page = 1
    premium = await is_premium_async(call.from_user.id)


    folder = _assets("editor", gender, cat)
    count = _count_default("editor", cat)
    locked = _locked_set("editor", cat, page, premium)

    caption = f"{CAT_TITLES_RU.get(cat, cat)}:"
    kb = ui.kb_picker(
        "ru",
        "editor",
        cat,
        page,
        count,
        locked,
        has_next=_has_next_page(folder, page),
        has_prev=_has_prev_page(page),
        show_none=True,
    )

    await panel_edit_media(call, state, img_path=img_editor(gender, cat, page), caption=caption, kb=kb)
    await call.answer()



@router.callback_query(F.data.startswith(ui.CB_EDITOR_NONE))
async def editor_none(call: CallbackQuery, state: FSMContext) -> None:
    _, cat = call.data.split(":")
    data = await state.get_data()
    sel = dict(data.get("editor_sel") or {})
    sel[cat] = None
    await state.update_data(editor_sel=sel)
    await _show_editor_home(call, state)
    await call.answer("Ок, без изменений ✅")


@router.callback_query(F.data.startswith("editor:pick:"))
async def editor_pick(call: CallbackQuery, state: FSMContext) -> None:
    _, _, cat, page_s, idx_s = call.data.split(":")
    page = int(page_s)
    idx = int(idx_s)

    premium = await is_premium_async(call.from_user.id)

    locked = idx in _locked_set("editor", cat, page, premium)
    if locked:
        await call.answer("Нужно премиум 🔒", show_alert=True)
        await call.message.answer(
            "🔒 Этот стиль доступен по подписке.\nВыберите план:",
            reply_markup=ui.kb_sub_plans("ru"),
        )
        return


    global_idx = (page - 1) * 9 + idx
    data = await state.get_data()
    sel = dict(data.get("editor_sel") or {})
    sel[cat] = global_idx
    await state.update_data(editor_sel=sel)

    # ключевая строчка:
    await _show_editor_home(call, state)

    await call.answer("Выбрано ✅")

# -------------------- Shoots --------------------
@router.callback_query(F.data.startswith("shoot:pick:"))
async def shoot_pick(call: CallbackQuery, state: FSMContext) -> None:
    # формат: shoot:pick:<cat>:<page>:<idx>
    parts = call.data.split(":")
    # parts = ["shoot", "pick", cat, page, idx]
    if len(parts) != 5:
        await call.answer("bad data", show_alert=True)
        return

    _, _, cat, page_s, idx_s = parts
    page = int(page_s)
    idx = int(idx_s)

    premium = await is_premium_async(call.from_user.id)

    locked = idx in _locked_set("shoot", cat, page, premium)
    if locked:
        await call.answer("Нужно премиум 🔒", show_alert=True)
        await call.message.answer(
            "🔒 Этот стиль доступен по подписке.\nВыберите план:",
            reply_markup=ui.kb_sub_plans("ru"),
        )
        return


    # global idx: p1 1..9 => 1..9, p2 1..9 => 10..18 ...
    global_idx = (page - 1) * 9 + idx

    # сохраним выбор
    await state.update_data(shoot_sel={"cat": cat, "val": global_idx})

    # обновим панель и вернем на экран фотосессий (как на скрине)
    await _show_shoots_home(call, state)

    await call.answer("Выбрано ✅")


@router.callback_query(F.data == ui.CB_SHOOT_HOME)
async def shoots_home(call: CallbackQuery, state: FSMContext) -> None:
    if not await is_premium_async(call.from_user.id):
        await call.message.answer_photo(
            FSInputFile(img_ui("premium")),
            caption="🔒 Доступ только по подписке. Выберите план:",
            reply_markup=ui.kb_premium_paywall("ru"),
        )
        await call.answer()
        return

    await state.set_state(Flow.shoots_home)
    await state.update_data(editor_sel={})
    await _show_shoots_home(call, state)
    await call.answer()


@router.callback_query(F.data.startswith("shoot:open:"))
async def shoot_open(call: CallbackQuery, state: FSMContext) -> None:
    cat = call.data.split(":")[-1]
    await state.set_state(Flow.picker)
    await state.update_data(picker_mode="shoot", picker_cat=cat, picker_page=1)

    page = 1
    premium = await is_premium_async(call.from_user.id)


    folder = _assets("shoots", cat)
    count = _count_default("shoot", cat)
    locked = _locked_set("shoot", cat, page, premium)

    caption = f"{CAT_TITLES_RU.get(cat, cat)}:"
    kb = ui.kb_picker(
        "ru",
        "shoot",
        cat,
        page,
        count,
        locked,
        has_next=_has_next_page(folder, page),
        has_prev=_has_prev_page(page),
        show_none=False,
    )

    await panel_edit_media(call, state, img_path=img_shoot(cat, page), caption=caption, kb=kb)
    await call.answer()


@router.callback_query(F.data.startswith(ui.CB_NEXT))
async def nav_next(call: CallbackQuery, state: FSMContext) -> None:
    prefix, mode, cat, page_s = call.data.rsplit(":", 3)
    page = int(page_s) + 1
    await _open_page(call, state, mode, cat, page)

@router.callback_query(F.data.startswith(ui.CB_PREV))
async def nav_prev(call: CallbackQuery, state: FSMContext) -> None:
    prefix, mode, cat, page_s = call.data.rsplit(":", 3)
    page = max(1, int(page_s) - 1)
    await _open_page(call, state, mode, cat, page)


async def _open_page(call: CallbackQuery, state: FSMContext, mode: str, cat: str, page: int) -> None:
    data = await state.get_data()
    gender = data.get("styles_gender", "m")
    premium = await is_premium_async(call.from_user.id)


    if mode == "editor":
        folder = _assets("editor", gender, cat)
        img = img_editor(gender, cat, page)
    else:
        folder = _assets("shoots", cat)
        img = img_shoot(cat, page)

    total = _pages_count(folder)
    if page < 1: page = 1
    if page > total: page = total

    count = _count_default(mode, cat)
    locked = _locked_set(mode, cat, page, premium)

    caption = f"{CAT_TITLES_RU.get(cat, cat)}:"
    kb = ui.kb_picker(
        "ru",
        mode,
        cat,
        page,
        count,
        locked,
        has_next=(page < total),
        has_prev=(page > 1),
        show_none=(mode == "editor"),
    )

    await state.update_data(picker_mode=mode, picker_cat=cat, picker_page=page)
    await panel_edit_media(call, state, img_path=img, caption=caption, kb=kb)
    await call.answer()



# -------------------- Generate --------------------
@router.callback_query(F.data == ui.CB_GENERATE)
async def generate(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    file_id = data.get("photo_file_id")
    if not file_id:
        await call.answer("Нет фото", show_alert=True)
        return

    if not await is_premium_async(call.from_user.id):
        await call.answer("Нужна подписка 🔒", show_alert=True)
        await call.message.answer_photo(
            FSInputFile(img_ui("premium")),
            caption="🔒 Генерация доступна только по подписке. Выберите план:",
            reply_markup=ui.kb_premium_paywall("ru"),
        )
        return

    await call.answer()
    await call.message.answer_photo(photo=file_id, caption="✨ Готово. Сделано с любовью.")

    # вернём пользователя в меню
    await panel_edit_media(call, state, img_path=img_ui("menu"), caption=MENU_CAPTION_RU, kb=ui.kb_main_menu("ru"))


def _fmt_sub_text(s: dict) -> str:
    if not s:
        return "⭐ Подписка\n\nAPI недоступен или нет данных."

    role = s.get("role") or "free"
    active_until = s.get("active_until") or "—"
    auto_renew = s.get("auto_renew")
    limits = s.get("limits") or {}
    usage = s.get("usage") or {}
    addons = s.get("addons") or {}
    totals = s.get("totals") or {}

    return (
        "⭐ <b>Подписка</b>\n\n"
        f"План: <b>{role}</b>\n"
        f"Активна до: <b>{active_until}</b>\n"
        f"Автопродление: <b>{'да' if auto_renew else 'нет'}</b>\n\n"
        "Лимиты (база):\n"
        f"— Сообщения: {limits.get('messages',0)}\n"
        f"— Картинки: {limits.get('images',0)}\n"
        f"— Видео: {limits.get('video',0)}\n\n"
        "Докупки:\n"
        f"— Сообщения: {addons.get('messages',0)}\n"
        f"— Картинки: {addons.get('images',0)}\n"
        f"— Видео: {addons.get('video',0)}\n\n"
        "Итого доступно:\n"
        f"— Сообщения: {totals.get('messages',0)}\n"
        f"— Картинки: {totals.get('images',0)}\n"
        f"— Видео: {totals.get('video',0)}\n\n"
        "Использовано:\n"
        f"— Сообщения: {usage.get('messages',0)}\n"
        f"— Картинки: {usage.get('images',0)}\n"
        f"— Видео: {usage.get('video',0)}\n"
    )


@router.callback_query(F.data == ui.CB_SUB_OPEN)
async def sub_open(call: CallbackQuery, state: FSMContext) -> None:
    try:
        s = await api_client.get_sub_summary(call.from_user.id)
    except Exception:
        s = {}
    await call.message.answer(_fmt_sub_text(s), reply_markup=ui.kb_sub_card("ru"))
    await call.answer()


@router.callback_query(F.data == ui.CB_SUB_CHANGE)
async def sub_change(call: CallbackQuery, state: FSMContext) -> None:
    await call.message.answer("Выберите новый план:", reply_markup=ui.kb_sub_plans("ru"))
    await call.answer()


@router.callback_query(F.data.startswith(ui.CB_SUB_BUY_PREFIX))
async def sub_buy(call: CallbackQuery, state: FSMContext) -> None:
    # mylook:sub:buy:<Plan>:<price>
    parts = call.data.split(":")
    if len(parts) != 5:
        await call.answer("bad data", show_alert=True)
        return
    plan = parts[3]
    price = int(parts[4])

    res = await api_client.set_plan(call.from_user.id, plan=plan, price_cents=price, auto_topup=True)
    if res.get("error"):
        await call.answer("Не удалось оформить план (API).", show_alert=True)
        return

    await call.answer(f"План активирован: {plan} ✅", show_alert=True)
    s = await api_client.get_sub_summary(call.from_user.id)
    await call.message.answer(_fmt_sub_text(s), reply_markup=ui.kb_sub_card("ru"))


@router.callback_query(F.data == ui.CB_SUB_CANCEL)
async def sub_cancel(call: CallbackQuery, state: FSMContext) -> None:
    ok = await api_client.cancel_plan(call.from_user.id)
    await call.answer("Ок ✅" if ok else "Ошибка отмены", show_alert=True)

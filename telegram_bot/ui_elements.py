from __future__ import annotations 

from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)

# ---------- callback keys ----------
CB_LANG_RU = "lang:ru"
CB_LANG_EN = "lang:en"

CB_GENDER_M = "gender:m"
CB_GENDER_F = "gender:f"

CB_HOME = "nav:home"
CB_BACK = "nav:back"

CB_EDITOR = "mode:editor"
CB_SHOOTS = "mode:shoots"

CB_TOGGLE_HAIR = "edit:toggle:hair"
CB_TOGGLE_COLOR = "edit:toggle:color"
CB_TOGGLE_PIERCING = "edit:toggle:piercing"
CB_TOGGLE_MOUSTACHE = "edit:toggle:moustache"
CB_TOGGLE_BEARD = "edit:toggle:beard"
CB_TOGGLE_GLASSES = "edit:toggle:glasses"

CB_RESET = "edit:reset"
CB_GENERATE = "gen:go"

CB_SHOOT_TRENDS = "shoot:cat:trends"
CB_SHOOT_WINTER = "shoot:cat:winter"
CB_SHOOT_SETS = "shoot:cat:sets"
CB_SHOOT_LOOKS = "shoot:cat:looks"

# Keys for payment
CB_PAY_WEEK = "premium:buy:week"
CB_PAY_MONTH = "premium:buy:month"
CB_PAY_YEAR = "premium:buy:year"

# Keys for Result Actions (New)
CB_SAVE_FILE = "res:save_file"
CB_GEN_NEW = "res:gen_new"

# ---------- texts ----------
TEXTS = {
    "ru": {
        "start_title": "✨ <b>MyLook</b> — AI-лаборатория внешности в Telegram.",
        "start_sub": "Примеряй стили и тренды за пару кликов — без промптов и приложений.",
        "pick_lang": "Выберите язык / Choose language:",
        "pick_gender": "🟡 Выбери свой пол:",
        "send_photo": "📸 Отправьте фото, где хорошо видно лицо — это нужно для корректной генерации образа.",
        "photo_ok": "Фото принято ✅ Теперь выбирай режим:",
        "home_hint": "Можно собрать стиль точечно или выбрать готовую фотосессию.",
        "editor_hint": "🎛 <b>Редактор внешности</b> — точечные изменения образа.",
        "shoots_hint": "📸 <b>Фотосессии</b> — готовые стилизованные AI-съёмки в один клик.",
        "gen_wait": "⏳ Генерирую… секундочку.",
        "gen_done": "✨ Готово. <i>Сделано с любовью</i>.",
        "status_prefix": "Твои выбранные изменения:",
    },
}

PREMIUM_PAYWALL_CAPTION_RU = (
    "🚀 <b>Для продолжения нужна подписка</b>\n\n"
    "Бесплатной версии больше нет. Оформите доступ, чтобы пользоваться всеми возможностями:\n\n"
    "🎨 Более 100 шаблонов\n"
    "🧑‍🎤 Новые стили каждую неделю\n"
    "🖼 Скачивание в HD качестве\n"
)

# ---------- keyboards ----------
def kb_lang() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data=CB_LANG_RU),
                InlineKeyboardButton(text="🇬🇧 English", callback_data=CB_LANG_EN),
            ]
        ]
    )

def kb_gender(lang: str = "ru") -> InlineKeyboardMarkup:
    if lang == "en":
        m, f = "👨 Male", "👩 Female"
    else:
        m, f = "👨 Мужской", "👩 Женский"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f, callback_data=CB_GENDER_F),
                InlineKeyboardButton(text=m, callback_data=CB_GENDER_M),
            ],
        ]
    )

def kb_request_photo(lang: str = "ru") -> ReplyKeyboardMarkup:
    text = "📸 Загрузить фото" if lang == "ru" else "📸 Upload photo"
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=text, request_photo=True)]],
        resize_keyboard=True,
        is_persistent=True,
    )

def kb_home(lang: str = "ru") -> InlineKeyboardMarkup:
    if lang == "en":
        a, b = "🎛 Look editor", "📸 Photoshoots"
    else:
        a, b = "🎛 Редактор внешности", "📸 Фотосессии"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=a, callback_data=CB_EDITOR)],
            [InlineKeyboardButton(text=b, callback_data=CB_SHOOTS)],
        ]
    )

# --------- extra callbacks for panels ----------
CB_BACK_TO_PHOTO = "nav:photo"
CB_RESTART = "nav:restart"

# --- extra callbacks ---
CB_UPLOAD = "nav:upload"
CB_STYLES_M = "styles:m"
CB_STYLES_F = "styles:f"
CB_CUSTOM_PROMPT = "styles:prompt"

CB_MENU = "nav:menu"
CB_EDITOR_HOME = "editor:home"
CB_EDITOR_CAT = "editor:cat"
CB_EDITOR_PICK = "editor:pick"
CB_EDITOR_NONE = "editor:none"
CB_NEXT = "nav:next"
CB_PREV = "nav:prev"

CB_SHOOT_HOME = "shoot:home"
CB_SHOOT_CAT = "shoot:cat"
CB_SHOOT_PAGE = "shoot:page"
CB_SHOOT_PICK = "shoot:pick"


def kb_start_upload(lang: str = "ru") -> InlineKeyboardMarkup:
    txt = "🟡 ЗАГРУЗИТЬ ФОТО" if lang == "ru" else "🟡 UPLOAD PHOTO"
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=txt, callback_data=CB_UPLOAD)]])


def kb_request_photo_one(lang: str = "ru") -> ReplyKeyboardMarkup:
    txt = "📸 Загрузить фото" if lang == "ru" else "📸 Upload photo"
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=txt, request_photo=True)]],
        resize_keyboard=True,
        is_persistent=True,
    )


def kb_gender_or_prompt(lang: str = "ru") -> InlineKeyboardMarkup:
    if lang == "ru":
        a, b, c = "🧔 Мужские стили", "👩 Женские стили", "✏️ Свой промпт"
    else:
        a, b, c = "🧔 Male styles", "👩 Female styles", "✏️ Custom prompt"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=a, callback_data=CB_STYLES_M),
             InlineKeyboardButton(text=b, callback_data=CB_STYLES_F)],
            [InlineKeyboardButton(text=c, callback_data=CB_CUSTOM_PROMPT)],
        ]
    )


def kb_main_menu(lang: str = "ru") -> InlineKeyboardMarkup:
    if lang == "ru":
        a, b, c = "🧊 Редактор внешности", "📸 Фотосессии", "⬅️ Назад"
    else:
        a, b, c = "🧊 Look editor", "📸 Photoshoots", "⬅️ Back"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=a, callback_data=CB_EDITOR_HOME)],
            [InlineKeyboardButton(text=b, callback_data=CB_SHOOT_HOME)],
            [InlineKeyboardButton(text=c, callback_data=CB_BACK_TO_PHOTO)],
        ]
    )


def kb_editor_home(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✂️ Прическа" if lang=="ru" else "✂️ Hairstyle", callback_data="editor:open:hair"),
                InlineKeyboardButton(text="🎨 Цвет волос" if lang=="ru" else "🎨 Hair color", callback_data="editor:open:color"),
            ],
            [
                InlineKeyboardButton(text="📌 Пирсинг" if lang=="ru" else "📌 Piercing", callback_data="editor:open:piercing"),
                InlineKeyboardButton(text="🥸 Усы" if lang=="ru" else "🥸 Moustache", callback_data="editor:open:moustache"),
            ],
            [
                InlineKeyboardButton(text="🧔 Борода" if lang=="ru" else "🧔 Beard", callback_data="editor:open:beard"),
                InlineKeyboardButton(text="👓 Очки" if lang=="ru" else "👓 Glasses", callback_data="editor:open:glasses"),
            ],
            [InlineKeyboardButton(text="✅ Сгенерировать" if lang=="ru" else "✅ Generate", callback_data=CB_GENERATE)],
            [InlineKeyboardButton(text="⬅️ Назад" if lang=="ru" else "⬅️ Back", callback_data=CB_MENU)],
        ]
    )


def kb_picker(
    lang: str,
    mode: str,
    cat: str,
    page: int,
    count: int,
    locked: set[int],
    has_next: bool,
    has_prev: bool,
    show_none: bool,
    selected_idx: int | None = None
) -> InlineKeyboardMarkup:
    rows = []
    
    if show_none:
        txt_none = "✳️ Без изменений" if lang=="ru" else "✳️ No changes"
        if selected_idx is None:
            txt_none = "✅ " + txt_none
        rows.append([InlineKeyboardButton(text=txt_none, callback_data=f"{CB_EDITOR_NONE}:{cat}")])

    row = []
    for i in range(1, count + 1):
        t = f"{i}"
        
        if selected_idx == i:
            t = f"✅ {t}"
        elif i in locked:
            t += " 🔒"
            
        cb = f"{'editor:pick' if mode=='editor' else 'shoot:pick'}:{cat}:{page}:{i}"
        row.append(InlineKeyboardButton(text=t, callback_data=cb))
        
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    nav = []
    if has_prev:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"{CB_PREV}:{mode}:{cat}:{page}"))
    
    if lang == "ru":
        back_text = "⬅️ Назад"
    else:
        back_text = "⬅️ Back"
    
    back_cb = CB_EDITOR_HOME if mode=="editor" else CB_SHOOT_HOME
    nav.append(InlineKeyboardButton(text=back_text, callback_data=back_cb))
    
    if has_next:
        nav.append(InlineKeyboardButton(text="Дальше ➡️", callback_data=f"{CB_NEXT}:{mode}:{cat}:{page}"))
    rows.append(nav)

    gen_txt = "✅ Сгенерировать" if lang=="ru" else "✅ Generate"
    rows.append([InlineKeyboardButton(text=gen_txt, callback_data=CB_GENERATE)])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_shoots_home(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔥 Тренды" if lang=="ru" else "🔥 Trends", callback_data="shoot:open:trends")],
            [InlineKeyboardButton(text="❄️ Зимние стили" if lang=="ru" else "❄️ Winter styles", callback_data="shoot:open:winter")],
            [InlineKeyboardButton(text="📷 Фотосеты" if lang=="ru" else "📷 Photosets", callback_data="shoot:open:sets")],
            [InlineKeyboardButton(text="🧩 Готовые образы" if lang=="ru" else "🧩 Ready looks", callback_data="shoot:open:looks")],
            [InlineKeyboardButton(text="✅ Сгенерировать" if lang=="ru" else "✅ Generate", callback_data=CB_GENERATE)],
            [InlineKeyboardButton(text="⬅️ Назад" if lang=="ru" else "⬅️ Back", callback_data=CB_MENU)],
        ]
    )

# --- PREMIUM KEYBOARDS ---

def kb_premium_paywall(lang: str = "ru") -> InlineKeyboardMarkup:
    if lang == "en":
        w, m, y = "⭐ Buy week", "✨ Buy month", "👑 Buy year"
    else:
        w, m, y = "⭐ Купить на неделю", "✨ Купить на месяц", "👑 Купить на год"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{w} — 399₽", callback_data=CB_PAY_WEEK)],
            [InlineKeyboardButton(text=f"{m} — 1199₽", callback_data=CB_PAY_MONTH)],
            [InlineKeyboardButton(text=f"{y} — 5999₽", callback_data=CB_PAY_YEAR)],
        ]
    )

def kb_premium_active(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⭐ Продлить на неделю", callback_data=CB_PAY_WEEK)],
            [InlineKeyboardButton(text="✨ Продлить на месяц", callback_data=CB_PAY_MONTH)],
            [InlineKeyboardButton(text="👑 Продлить на год", callback_data=CB_PAY_YEAR)],
            [InlineKeyboardButton(text="✅ Перейти к созданию", callback_data=CB_RESTART)],
        ]
    )

def kb_result_actions(lang: str = "ru") -> InlineKeyboardMarkup:
    """Кнопки под готовым результатом (Свой промпт)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💾 Сохранить в файле", callback_data=CB_SAVE_FILE)],
            [InlineKeyboardButton(text="🔄 Генерировать дальше", callback_data=CB_GEN_NEW)],
        ]
    )
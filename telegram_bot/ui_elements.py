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

CB_PAY_WEEK = "pay:week"
CB_PAY_MONTH = "pay:month"
CB_PAY_YEAR = "pay:year"
CB_CONTINUE_LIMITS = "pay:continue"


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
        "no_credits": "🔥 Почти! Бесплатный лимит закончился. Открой доступ ко всем возможностям:",
        "pay_stub": "Платежи пока не подключены (заглушка). Кнопка есть — проводку доделаем следующим шагом.",
        "limits_continue": "Ок, продолжаем с ограничениями ✅",
        "status_prefix": "Твои выбранные изменения:",
    },
    "en": {
        "start_title": "✨ <b>MyLook</b> — AI look editor in Telegram.",
        "start_sub": "Try styles & trends in a couple clicks — no prompts, no apps.",
        "pick_lang": "Choose language:",
        "pick_gender": "Select your gender:",
        "send_photo": "📸 Send a photo where your face is clearly visible — this is needed for correct generation.",
        "photo_ok": "Photo received ✅ Now pick a mode:",
        "home_hint": "Build edits step-by-step or choose a ready photoshoot.",
        "editor_hint": "🎛 <b>Look editor</b> — precise edits.",
        "shoots_hint": "📸 <b>Photoshoots</b> — ready stylized AI sets in one click.",
        "gen_wait": "⏳ Generating…",
        "gen_done": "✨ Done. <i>Made with love</i>.",
        "no_credits": "🔥 You’re close! Free limit is over. Unlock all features:",
        "pay_stub": "Payments are not connected yet (stub). We’ll wire it next.",
        "limits_continue": "Ok, continuing with limits ✅",
        "status_prefix": "Your selected edits:",
    },
}


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


def kb_editor(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✂️ Прическа" if lang == "ru" else "✂️ Hairstyle", callback_data=CB_TOGGLE_HAIR),
                InlineKeyboardButton(text="🎨 Цвет волос" if lang == "ru" else "🎨 Hair color", callback_data=CB_TOGGLE_COLOR),
            ],
            [
                InlineKeyboardButton(text="📌 Пирсинг" if lang == "ru" else "📌 Piercing", callback_data=CB_TOGGLE_PIERCING),
                InlineKeyboardButton(text="🥸 Усы" if lang == "ru" else "🥸 Moustache", callback_data=CB_TOGGLE_MOUSTACHE),
            ],
            [
                InlineKeyboardButton(text="🧔 Борода" if lang == "ru" else "🧔 Beard", callback_data=CB_TOGGLE_BEARD),
                InlineKeyboardButton(text="👓 Очки" if lang == "ru" else "👓 Glasses", callback_data=CB_TOGGLE_GLASSES),
            ],
            [InlineKeyboardButton(text="🔁 Сбросить все" if lang == "ru" else "🔁 Reset all", callback_data=CB_RESET)],
            [InlineKeyboardButton(text="✅ Сгенерировать" if lang == "ru" else "✅ Generate", callback_data=CB_GENERATE)],
            [InlineKeyboardButton(text="⬅️ Назад" if lang == "ru" else "⬅️ Back", callback_data=CB_HOME)],
        ]
    )


def kb_shoots(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔥 Тренды" if lang == "ru" else "🔥 Trends", callback_data=CB_SHOOT_TRENDS)],
            [InlineKeyboardButton(text="❄️ Зимние стили" if lang == "ru" else "❄️ Winter styles", callback_data=CB_SHOOT_WINTER)],
            [InlineKeyboardButton(text="📷 Фотосеты" if lang == "ru" else "📷 Photosets", callback_data=CB_SHOOT_SETS)],
            [InlineKeyboardButton(text="🧩 Готовые образы" if lang == "ru" else "🧩 Ready looks", callback_data=CB_SHOOT_LOOKS)],
            [InlineKeyboardButton(text="✅ Сгенерировать" if lang == "ru" else "✅ Generate", callback_data=CB_GENERATE)],
            [InlineKeyboardButton(text="⬅️ Назад" if lang == "ru" else "⬅️ Back", callback_data=CB_HOME)],
        ]
    )


def kb_paywall(lang: str = "ru") -> InlineKeyboardMarkup:
    if lang == "en":
        w, m, y, c = "⭐ Buy week", "✨ Buy month", "👑 Buy year", "Continue with limits"
    else:
        w, m, y, c = "⭐ Купить на неделю", "✨ Купить на месяц", "👑 Купить на год", "Продолжить с ограничениями"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{w} — 399₽ / 300⭐", callback_data=CB_PAY_WEEK)],
            [InlineKeyboardButton(text=f"{m} — 1199₽ / 900⭐", callback_data=CB_PAY_MONTH)],
            [InlineKeyboardButton(text=f"{y} — 5999₽ / 4500⭐", callback_data=CB_PAY_YEAR)],
            [InlineKeyboardButton(text=c, callback_data=CB_CONTINUE_LIMITS)],
        ]
    )

# --------- extra callbacks for panels ----------
CB_BACK_TO_PHOTO = "nav:photo"

CB_SHOOT_HOME = "shoot:home"
CB_SHOOT_PAGE = "shoot:page"      # shoot:page:<cat>:<page>
CB_SHOOT_PICK = "shoot:pick"      # shoot:pick:<cat>:<page>:<local_idx>

def kb_modes(lang: str = "ru") -> InlineKeyboardMarkup:
    # экран "Редактор / Фотосессии" как на твоём скрине + Назад
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🧊 Редактор внешности" if lang=="ru" else "🧊 Look editor", callback_data=CB_EDITOR)],
            [InlineKeyboardButton(text="📸 Фотосессии" if lang=="ru" else "📸 Photoshoots", callback_data=CB_SHOOTS)],
            [InlineKeyboardButton(text="⬅️ Назад" if lang=="ru" else "⬅️ Back", callback_data=CB_BACK_TO_PHOTO)],
        ]
    )

def kb_shoots_home_full(lang: str = "ru") -> InlineKeyboardMarkup:
    # как в MyLook: категории + Сгенерировать + Назад
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔥 Тренды" if lang=="ru" else "🔥 Trends", callback_data="shoot:cat:trends")],
            [InlineKeyboardButton(text="❄️ Зимние стили" if lang=="ru" else "❄️ Winter styles", callback_data="shoot:cat:winter")],
            [InlineKeyboardButton(text="📷 Фотосеты" if lang=="ru" else "📷 Photosets", callback_data="shoot:cat:sets")],
            [InlineKeyboardButton(text="🧩 Готовые образы" if lang=="ru" else "🧩 Ready looks", callback_data="shoot:cat:looks")],
            [InlineKeyboardButton(text="✅ Сгенерировать" if lang=="ru" else "✅ Generate", callback_data=CB_GENERATE)],
            [InlineKeyboardButton(text="⬅️ Назад" if lang=="ru" else "⬅️ Back", callback_data=CB_HOME)],
        ]
    )

def kb_shoots_category_numbers(
    lang: str,
    cat: str,
    page: int,
    count_on_page: int,
    locked_locals: set[int],
) -> InlineKeyboardMarkup:
    """
    Рисуем кнопки 1..count_on_page (локальная нумерация на странице),
    как на твоих скринах. Замок — если local_idx в locked_locals.
    """
    rows = []
    row = []
    for local_idx in range(1, count_on_page + 1):
        text = str(local_idx)
        if local_idx in locked_locals:
            text += " 🔒"
        row.append(InlineKeyboardButton(text=text, callback_data=f"shoot:pick:{cat}:{page}:{local_idx}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    # навигация (переопределим в роутере: показывать/не показывать next/prev)
    nav = [
        InlineKeyboardButton(text="⬅️ Назад" if lang=="ru" else "⬅️ Back", callback_data=CB_SHOOT_HOME)
    ]
    rows.append(nav)

    return InlineKeyboardMarkup(inline_keyboard=rows)

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# --- extra callbacks ---
CB_UPLOAD = "nav:upload"
CB_STYLES_M = "styles:m"
CB_STYLES_F = "styles:f"
CB_CUSTOM_PROMPT = "styles:prompt"

CB_MENU = "nav:menu"
CB_EDITOR_HOME = "editor:home"
CB_EDITOR_CAT = "editor:cat"      # editor:cat:<cat>:<page>
CB_EDITOR_PICK = "editor:pick"    # editor:pick:<cat>:<page>:<idx>
CB_EDITOR_NONE = "editor:none"    # editor:none:<cat>
CB_NEXT = "nav:next"              # nav:next:<mode>:<cat>:<page>
CB_PREV = "nav:prev"              # nav:prev:<mode>:<cat>:<page>

CB_SHOOT_HOME = "shoot:home"
CB_SHOOT_CAT = "shoot:cat"        # shoot:cat:<cat>
CB_SHOOT_PAGE = "shoot:page"      # shoot:page:<cat>:<page>
CB_SHOOT_PICK = "shoot:pick"      # shoot:pick:<cat>:<page>:<idx>


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
    # как у тебя: кнопки категорий + generate + назад в меню
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
    mode: str,      # "editor" или "shoot"
    cat: str,
    page: int,
    count: int,
    locked: set[int],
    has_next: bool,
    has_prev: bool,
    show_none: bool,
) -> InlineKeyboardMarkup:
    rows = []
    if show_none:
        rows.append([InlineKeyboardButton(text="✳️ Без изменений" if lang=="ru" else "✳️ No changes",
                                          callback_data=f"{CB_EDITOR_NONE}:{cat}")])

    row = []
    for i in range(1, count + 1):
        t = f"{i}" + (" 🔒" if i in locked else "")
        cb = f"{'editor:pick' if mode=='editor' else 'shoot:pick'}:{cat}:{page}:{i}"
        row.append(InlineKeyboardButton(text=t, callback_data=cb))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    nav = []
    if has_prev:
        nav.append(InlineKeyboardButton(text="⬅️" if lang=="ru" else "⬅️", callback_data=f"{CB_PREV}:{mode}:{cat}:{page}"))
    if lang == "ru":
        nav.append(InlineKeyboardButton(text="⬅️ Назад в меню", callback_data=(CB_EDITOR_HOME if mode=="editor" else CB_SHOOT_HOME)))
    else:
        nav.append(InlineKeyboardButton(text="⬅️ Back to menu", callback_data=(CB_EDITOR_HOME if mode=="editor" else CB_SHOOT_HOME)))
    if has_next:
        nav.append(InlineKeyboardButton(text="Дальше ➡️" if lang=="ru" else "Next ➡️", callback_data=f"{CB_NEXT}:{mode}:{cat}:{page}"))
    rows.append(nav)

    # только на picker-экранах оставляем generate
    rows.append([InlineKeyboardButton(text="✅ Сгенерировать" if lang=="ru" else "✅ Generate", callback_data=CB_GENERATE)])

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


# это callback уже использовали раньше, оставляем
CB_BACK_TO_PHOTO = "nav:photo"


from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- mylook subscription callbacks ---
CB_SUB_OPEN = "mylook:sub:open"
CB_SUB_CHANGE = "mylook:sub:change"
CB_SUB_CANCEL = "mylook:sub:cancel"
CB_SUB_BACK = "mylook:sub:back"
CB_SUB_BUY_PREFIX = "mylook:sub:buy"   # mylook:sub:buy:<Plan>:<price_cents>

# цены = как в твоём API (PLANS в subscriptions.py)
PRICE_LIGHT = 275_00
PRICE_MAX = 450_00
PRICE_ULTRA = 1333_00

def kb_sub_open(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Подписка", callback_data=CB_SUB_OPEN)],
    ])

def kb_sub_card(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Сменить план", callback_data=CB_SUB_CHANGE)],
        [InlineKeyboardButton(text="❌ Отменить автопродление", callback_data=CB_SUB_CANCEL)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=CB_SUB_BACK)],
    ])

def kb_premium_paywall(lang: str = "ru") -> InlineKeyboardMarkup:
    if lang == "en":
        w, m, y, c = "⭐ Buy week", "✨ Buy month", "👑 Buy year", "Continue with limits"
    else:
        w, m, y, c = "⭐ Купить на неделю", "✨ Купить на месяц", "👑 Купить на год", "Продолжить с ограничениями"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{w} — 399₽ / 300⭐", callback_data=CB_PAY_WEEK)],
            [InlineKeyboardButton(text=f"{m} — 1199₽ / 900⭐", callback_data=CB_PAY_MONTH)],
            [InlineKeyboardButton(text=f"{y} — 5999₽ / 4500⭐", callback_data=CB_PAY_YEAR)],
        ]
    )


from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

CB_PREMIUM_BUY = "premium:buy"  # premium:buy:<period>

def kb_premium_active(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=1)

    # кнопки для продления/прокачки
    kb.add(
        InlineKeyboardButton("⭐ Продлить на неделю", callback_data="premium:buy:week"),
        InlineKeyboardButton("✨ Продлить на месяц", callback_data="premium:buy:month"),
        InlineKeyboardButton("🔥 Продлить на год", callback_data="premium:buy:year")
    )

    kb.add(InlineKeyboardButton("❌ Отмена", callback_data="premium:cancel"))

    return kb
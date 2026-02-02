from __future__ import annotations 
import os
from typing import Optional

from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

# ---------- ASSETS HELPERS ----------

def _assets(*parts: str) -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", *parts))

def _find(base_no_ext: str) -> Optional[str]:
    for ext in (".jpg", ".png", ".jpeg", ".webp"):
        p = base_no_ext + ext
        if os.path.exists(p):
            return p
    return None

def img_ui(name: str) -> str:
    """Ищет картинку интерфейса в assets/ui/name.*"""
    p = _find(_assets("ui", name))
    if p:
        return p
    # Fallback
    fallback = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "topper.jpg"))
    if os.path.exists(fallback):
        return fallback
    return ""

LINK_USER_AGREEMENT = "https://docs.google.com/document/d/e/2PACX-1vSk-6MJ0-J-Q0li06vMRvGLC0YOYszxxLSUpGj3qCn4a9EpMJ0fLYpBYGbZCNbNTyP498wBCNkcEBEf/pub"
LINK_RECURRING_RULES = "https://docs.google.com/document/d/e/2PACX-1vQq270OfXzscST6ppkbOFYu7Qni6hw7PiHp_-Tj6bhcS8U7uD4HlBMLxwgM3V0BUIMf0izCFbMM4ZW3/pub"
# ---------- NAMES & TITLES ----------

CATALOG_NAMES = {
    "hair": "✂️ Прическа",
    "color": "🎨 Цвет волос",
    "piercing": "📌 Пирсинг",
    "moustache": "🥸 Усы",
    "beard": "🧔 Борода",
    "glasses": "👓 Очки",
    "makeup": "💄 Макияж",
    "trends": "🔥 Тренды",
    "winter": "❄️ Зимние стили",
    "sets": "📷 Фотосеты",
    "looks": "🧩 Готовые образы",
}

def get_cat_title(cat: str) -> str:
    return CATALOG_NAMES.get(cat, cat.capitalize())


# ---------- callback keys ----------
CB_LANG_RU = "lang:ru"
CB_LANG_EN = "lang:en"

CB_GENDER_M = "gender:m"
CB_GENDER_F = "gender:f"

CB_HOME = "nav:home"
CB_BACK = "nav:back"

CB_EDITOR = "mode:editor"
CB_SHOOTS = "mode:shoots"

CB_RESET = "edit:reset"
CB_GENERATE = "gen:go"

# --- НОВЫЕ КЛЮЧИ ДЛЯ ВЫБОРА ВЕРСИИ ---
CB_TIER_STD = "tier:std"
CB_TIER_PRO = "tier:pro"

# Keys for payment plans (Initial click)
CB_PAY_WEEK = "premium:buy:week"
CB_PAY_MONTH = "premium:buy:month"
CB_PAY_YEAR = "premium:buy:year"
CB_CANCEL_SUB = "premium:cancel"
CB_RESUME_SUB = "premium:resume" # <--- НОВАЯ КНОПКА

# Keys for packages (Initial click)
CB_PKG_150 = "pkg:150"
CB_PKG_1000 = "pkg:1000"
CB_PKG_5000 = "pkg:5000"

# Keys for Result Actions
CB_SAVE_FILE = "res:save_file"
CB_GEN_SAME_PHOTO = "res:same_photo" 
CB_GEN_NEW_PHOTO = "res:new_photo"   
CB_REGENERATE = "res:regen"

# Help
CB_LANG_TOGGLE = "help:lang"

# Navigation
CB_BACK_TO_PHOTO = "nav:photo"
CB_BACK_TO_GENDER = "nav:gender"
CB_RESTART = "nav:restart"
CB_GOTO_EDIT = "nav:goto_edit"

# Extra
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


# ---------- TEXTS ----------

TEXTS = {
    "ru": {
        "start_title": (
            "✨ <b>FaceLab — меняй образ за секунды!</b>\n"
            "📸 Загрузи фото с лицом и наш ИИ предложит уникальный стиль, причёску, макияж и невероятные образы.\n"
            "💎 Просто, быстро и красиво — будь версией себя, которой ты гордишься!"
        ),
        "start_sub": "", 
        "pick_lang": "Выберите язык / Choose language:",
        "pick_gender": "🟡 Выбери свой пол:",
        "send_photo": "", 
        "photo_ok": "Фото принято ✅ Теперь выбирай режим:",
        "gen_wait": "⏳ <b>Обрабатываем ваше фото...</b>",
        "new_photo_req": "📸 Пожалуйста, пришлите новую фотографию.",
        "result_caption": "От 🌟 @FacelabXbot",
    },
}

TEXT_TIER_SELECTION = (
    "😍 <b>Тебе понравился результат?</b>\n\n"
    "Продолжай создавать новые образы без ограничений — выбери версию 👇"
)

PREMIUM_PAYWALL_CAPTION_RU = (
    "🚀 <b>Для продолжения нужна подписка</b>\n\n"
    "Бесплатной версии больше нет. Оформите доступ, чтобы пользоваться всеми возможностями:\n\n"
    "🎨 Более 100 шаблонов\n"
    "🧑‍🎤 Новые стили каждую неделю\n"
    "🖼 Скачивание в HD качестве\n"
)

TEXT_FREE_TRIAL_ENDED = (
    "<b>😢 Бесплатная попытка закончилась</b>\n\n"
    "Хочешь такие же фото, но без ограничений?\n"
    "Оформи подписку и генерируй сотни образов!"
)

# ОБНОВЛЕННЫЙ ШАБЛОН АКТИВНОЙ ПОДПИСКИ
TEXT_PREMIUM_ACTIVE_TEMPLATE = (
    "✅ <b>Максимальный доступ включён!</b>\n\n"
    "✨ Генераций осталось: <b>{available}</b>\n"
    "🌸 Текущая подписка: <b>{plan_name}</b>\n"
    "{renewal_info}\n\n"
    "💡 Хочешь ещё больше крутых образов? Посмотри /packages и пополняй генерации!"
)

TEXT_HELP_RU = (
    "💡 <b>Как пользоваться FaceLab:</b>\n"
    "1. 📸 Отправьте фото с хорошо видимым лицом\n"
    "2. 👤 Выберите пол\n"
    "3. 🎨 Настройте стиль и образ\n"
    "4. 🔄 Нажмите «Сгенерировать»\n"
    "5. 🌟 Получите новый уникальный образ!\n\n"
    "⚠️ <b>Важно:</b>\n"
    "• Применение готовых образов (стилей, фотосессий, трендов) сбрасывает все текущие изменения\n"
    "• Отправляйте фото, где лицо хорошо видно\n\n"
    "💬 Если есть вопросы или предложения, пишите администратору: @FaceLabHelp\n\n"
    f"<a href='{LINK_USER_AGREEMENT}'>Пользовательское соглашение</a>"
)

TEXT_HELP_EN = (
    "💡 <b>How to use FaceLab:</b>\n"
    "1. 📸 Send a photo with a clearly visible face\n"
    "2. 👤 Select gender\n"
    "3. 🎨 Customize style and look\n"
    "4. 🔄 Click \"Generate\"\n"
    "5. 🌟 Get a unique new look!\n\n"
    "⚠️ <b>Important:</b>\n"
    "• Applying ready-made looks resets current edits\n"
    "• Send a photo where the face is clearly visible\n\n"
    "💬 Contact support: @FaceLabHelp\n\n"
    f"<a href='{LINK_USER_AGREEMENT}'>Terms of Service</a>"
)

TEXT_PACKAGES_CAPTION = (
    "<b>Дополнительные генерации</b> 🔥\n\n"
    "Пакет является дополнением к действующей премиум подписке\n\n"
    "⚠️ Пакет активен до конца действия премиум-подписки. "
    "При отмене премиума неиспользованные генерации сгорают, "
    "при продлении подписки — переносятся на следующий период."
)

TEXT_PAYMENT_CONFIRMATION_RUB = (
    "Вы приобретаете пакет: <b>Премиум {tier_name} на {period} ({count} генераций) - {price}₽</b>\n"
    "Следующее списание: {next_date} - {price}₽\n\n"
    "Нажимая «Оплатить», вы соглашаетесь с <a href='{link_recurring}'>Правилами приема рекуррентных платежей</a>. Подписку можно отменить в любой момент.\n\n"
    "🔒 Платёж безопасен и защищён сервисом CloudPayments."
)
# ---------- KEYBOARDS ----------

def kb_tier_selection() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✨ Обычная версия", callback_data=CB_TIER_STD)],
            [InlineKeyboardButton(text="👑 Pro-версия", callback_data=CB_TIER_PRO)],
        ]
    )

def kb_pay_rub_confirm(price_rub: int, payload_data: str) -> InlineKeyboardMarkup:
    """Кнопка Оплатить для рублевых платежей (имитация перехода на шлюз)"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Оплатить", callback_data=f"do_pay_rub:{price_rub}:{payload_data}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="cancel_payment")]
    ])


def payment_choice_kb(price_rub: int, price_stars: int, payload_data: str):
    """
    Клавиатура выбора метода оплаты.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🇷🇺 Карта ({price_rub}₽)",
                    callback_data=f"pay_rub:{price_rub}:{payload_data}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"⭐️ Telegram Stars ({price_stars}⭐️)",
                    callback_data=f"pay_stars:{price_stars}:{payload_data}"
                )
            ],
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="cancel_payment")
            ]
        ]
    )

def kb_cancel_transaction(payload: str, price_stars: int) -> InlineKeyboardMarkup:
    """
    Кнопка отмены под инвойсом. 
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Оплатить {price_stars} ⭐️", pay=True)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"inv_cancel:{payload}")]
    ])


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
            [InlineKeyboardButton(text=c, callback_data=CB_BACK_TO_GENDER)],
        ]
    )

def kb_back_to_gender(lang: str = "ru") -> InlineKeyboardMarkup:
    txt = "⬅️ Назад" if lang == "ru" else "⬅️ Back"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=txt, callback_data=CB_BACK_TO_GENDER)],
        ]
    )


def kb_editor_home(lang: str = "ru", gender: str = "m") -> InlineKeyboardMarkup:
    rows = []
    
    rows.append([
        InlineKeyboardButton(text="✂️ Прическа", callback_data="editor:open:hair"),
        InlineKeyboardButton(text="🎨 Цвет волос", callback_data="editor:open:color"),
    ])
    
    if gender == "f":
        rows.append([
            InlineKeyboardButton(text="💄 Макияж", callback_data="editor:open:makeup"),
            InlineKeyboardButton(text="📌 Пирсинг", callback_data="editor:open:piercing"),
        ])
        rows.append([
            InlineKeyboardButton(text="👓 Очки", callback_data="editor:open:glasses"),
        ])
    else:
        rows.append([
            InlineKeyboardButton(text="📌 Пирсинг", callback_data="editor:open:piercing"),
            InlineKeyboardButton(text="🥸 Усы", callback_data="editor:open:moustache"),
        ])
        rows.append([
            InlineKeyboardButton(text="🧔 Борода", callback_data="editor:open:beard"),
            InlineKeyboardButton(text="👓 Очки", callback_data="editor:open:glasses"),
        ])

    rows.append([InlineKeyboardButton(text="✅ Сгенерировать" if lang=="ru" else "✅ Generate", callback_data=CB_GENERATE)])
    rows.append([InlineKeyboardButton(text="⬅️ Назад" if lang=="ru" else "⬅️ Back", callback_data=CB_MENU)])

    return InlineKeyboardMarkup(inline_keyboard=rows)


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

def kb_premium_paywall(lang: str = "ru", tier: str = "std") -> InlineKeyboardMarkup:
    # Динамические цены в зависимости от выбранного тарифа (tier)
    if tier == "pro":
        # Pro Цены
        p_week = "799₽"
        p_month = "1599₽"
        p_year = "11999₽"
    else:
        # Standard Цены
        p_week = "399₽"
        p_month = "799₽"
        p_year = "5999₽"

    # Суффикс для колбэка, чтобы хендлер знал, какой тариф выбран
    sfx = f":{tier}"

    if lang == "en":
        w, m, y = "⭐ Weekly", "✨ Monthly", "👑 Yearly"
    else:
        w = "🔓 Неделя — попробовать"
        m = "✨ Месяц — лучший выбор"
        y = "👑 Год — максимум выгоды"

    # ВРЕМЕННО: Оставляем только Месяц
    return InlineKeyboardMarkup(
        inline_keyboard=[
            # [InlineKeyboardButton(text=f"{w} · {p_week}", callback_data=f"{CB_PAY_WEEK}{sfx}")],
            [InlineKeyboardButton(text=f"{m} · {p_month}", callback_data=f"{CB_PAY_MONTH}{sfx}")],
            # [InlineKeyboardButton(text=f"{y} · {p_year}", callback_data=f"{CB_PAY_YEAR}{sfx}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav:back_to_tiers")]
        ]
    )


def kb_premium_active(user_id: int, bot_name: str = "FacelabXbot", auto_renew: bool = True, show_edit_btn: bool = False) -> InlineKeyboardMarkup:
    """Кнопки под активной подпиской."""
    ref_link = f"https://t.me/{bot_name}?start={user_id}"
    rows = []
    
    rows.append([InlineKeyboardButton(text="• 💌 Отправить друзьям", url=f"https://t.me/share/url?url={ref_link}")])
    
    if auto_renew:
        # Если включено автопродление - кнопка ОТМЕНИТЬ
        rows.append([InlineKeyboardButton(text="• ✖️ Отменить подписку", callback_data=CB_CANCEL_SUB)])
    else:
        # Если выключено (отменена) - кнопка ВОЗОБНОВИТЬ
        rows.append([InlineKeyboardButton(text="• ▶️ Возобновить подписку", callback_data=CB_RESUME_SUB)])
        
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_result_actions(lang: str = "ru") -> InlineKeyboardMarkup:
    """Кнопки под результатом генерации"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Сделать снова", callback_data=CB_REGENERATE)],
            [InlineKeyboardButton(text="✨ Новый образ", callback_data=CB_GEN_NEW_PHOTO)],
        ]
    )

def kb_help(lang: str = "ru") -> InlineKeyboardMarkup:
    lbl = "Change Language 🇺🇸" if lang == "ru" else "Сменить язык 🇷🇺"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=lbl, callback_data=CB_LANG_TOGGLE)]
    ])

def kb_packages(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Купить 150 генераций — 349₽ / 260⭐", callback_data=CB_PKG_150)],
        [InlineKeyboardButton(text="✨ Купить 1000 генераций — 1999₽ / 1500⭐", callback_data=CB_PKG_1000)],
        [InlineKeyboardButton(text="🤩 Купить 5000 генераций — 5999₽ / 4500⭐", callback_data=CB_PKG_5000)],
    ])
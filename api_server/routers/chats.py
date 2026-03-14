from __future__ import annotations

from typing import Optional, List, Dict
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func, update
from sqlalchemy.orm import Session

from db_adapter.database import get_db
from db_adapter.models import User, ChatSession, ChatMessage
from api_server.providers.gemini_provider import GeminiProvider
from api_server.services.costs import record_generation_cost

MAX_CONTEXT_CHARS = 6_000  # примерно 3–4k токенов на историю, нормальный эконом-режим

router = APIRouter()

# --------- Pydantic ---------
class MessageIn(BaseModel):
    text: str


class ChatCreateIn(BaseModel):
    title: Optional[str] = None


class ChatRenameIn(BaseModel):
    title: str


# --------- helpers ---------
def _get_or_create_user(db: Session, chat_id: int) -> User:
    user = db.execute(select(User).where(User.chat_id == chat_id)).scalar_one_or_none()
    if user:
        return user
    user = User(chat_id=chat_id)
    db.add(user)
    db.flush()  # get user.id
    session = ChatSession(user_id=user.id, title="Чат 1", is_active=True)
    db.add(session)
    db.commit()
    return user


def _get_active_session(db: Session, user_id: int) -> ChatSession:
    sess = db.execute(
        select(ChatSession).where(
            ChatSession.user_id == user_id,
            ChatSession.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if sess:
        return sess
    # если нет активного — создаём дефолтный
    sess = ChatSession(user_id=user_id, title="Чат 1", is_active=True)
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return sess


def _serialize_sessions(db: Session, user_id: int) -> List[Dict]:
    items = (
        db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.id.asc())
        )
        .scalars()
        .all()
    )
    return [{"id": s.id, "title": s.title, "is_active": s.is_active} for s in items]


# --------- list sessions ---------
@router.get("/{chat_id}")
def list_sessions(chat_id: int, db: Session = Depends(get_db)):
    user = _get_or_create_user(db, chat_id)
    items = _serialize_sessions(db, user.id)
    if not items:
        # гарантия хотя бы одного чата
        s = ChatSession(user_id=user.id, title="Чат 1", is_active=True)
        db.add(s)
        db.commit()
        items = _serialize_sessions(db, user.id)
    return {"items": items}


# --------- create session (с опциональным названием) ---------
@router.post("/{chat_id}/create")
def create_session(
    chat_id: int,
    payload: ChatCreateIn | None = None,
    db: Session = Depends(get_db),
):
    user = _get_or_create_user(db, chat_id)
    if payload and payload.title:
        title = payload.title.strip()[:100] or "Чат"
    else:
        last_num = (
            db.execute(
                select(func.count(ChatSession.id)).where(
                    ChatSession.user_id == user.id
                )
            ).scalar()
            or 0
        )
        title = f"Чат {last_num + 1}"

    s = ChatSession(user_id=user.id, title=title, is_active=False)
    db.add(s)
    db.commit()
    db.refresh(s)
    return {"id": s.id, "title": s.title, "is_active": s.is_active}


# --------- clear all (исправлено: удаляем и сообщения) ---------
@router.post("/{chat_id}/clear")
def clear_sessions(chat_id: int, db: Session = Depends(get_db)):
    """
    Безопасно удаляет все чаты пользователя вместе с сообщениями,
    затем создаёт новый пустой активный «Чат 1» и возвращает актуальный список.
    """
    user = _get_or_create_user(db, chat_id)

    sessions = db.query(ChatSession).filter(ChatSession.user_id == user.id).all()
    for s in sessions:
        # сначала чистим сообщения этого чата (bulk без загрузки в сессию)
        db.query(ChatMessage).filter(
            ChatMessage.session_id == s.id
        ).delete(synchronize_session=False)
        # затем удаляем саму сессию через ORM (на случай, если каскады где-то поменяются)
        db.delete(s)

    db.flush()
    # создать новый стартовый активный чат
    first = ChatSession(user_id=user.id, title="Чат 1", is_active=True)
    db.add(first)
    db.commit()

    return {"ok": True, "items": _serialize_sessions(db, user.id)}


# --------- activate session (фиксация .set -> .values уже есть) ---------
@router.post("/{chat_id}/{session_id}/activate")
def activate_session(
    chat_id: int, session_id: int, db: Session = Depends(get_db)
):
    user = _get_or_create_user(db, chat_id)

    # снять активность со всех чатов пользователя
    db.execute(
        update(ChatSession)
        .where(ChatSession.user_id == user.id, ChatSession.is_active.is_(True))
        .values(is_active=False)
    )

    # включить конкретный
    s = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == user.id, ChatSession.id == session_id)
        .first()
    )
    if not s:
        db.rollback()
        raise HTTPException(status_code=404, detail="session not found")

    s.is_active = True
    db.commit()
    db.refresh(s)

    # последнее сообщение активного
    last_msg = (
        db.execute(
            select(ChatMessage.content)
            .where(ChatMessage.session_id == s.id)
            .order_by(ChatMessage.id.desc())
            .limit(1)
        ).scalar_one_or_none()
    )

    return {"ok": True, "title": s.title, "last_message": last_msg}


# --------- rename single session ---------
@router.post("/{chat_id}/{session_id}/rename")
def rename_session(
    chat_id: int,
    session_id: int,
    payload: ChatRenameIn,
    db: Session = Depends(get_db),
):
    """
    Переименовывает конкретный чат пользователя.
    Возвращает обновлённый список чатов.
    """
    user = _get_or_create_user(db, chat_id)

    new_title = (payload.title or "").strip()[:100]
    if not new_title:
        raise HTTPException(status_code=400, detail="empty title")

    s = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == user.id, ChatSession.id == session_id)
        .first()
    )
    if not s:
        raise HTTPException(status_code=404, detail="session not found")

    s.title = new_title
    db.commit()
    db.refresh(s)

    items = _serialize_sessions(db, user.id)

    return {"ok": True, "id": s.id, "title": s.title, "items": items}


# --------- delete single session (с удалением сообщений) ---------
@router.post("/{chat_id}/{session_id}/delete")
def delete_session(chat_id: int, session_id: int, db: Session = Depends(get_db)):
    """
    Удаляет конкретный чат пользователя вместе с его сообщениями.
    Если удалён активный — делаем активным последний оставшийся.
    Если ничего не осталось — создаём новый «Чат 1» как активный.
    """
    user = _get_or_create_user(db, chat_id)

    s = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == user.id, ChatSession.id == session_id)
        .first()
    )
    if not s:
        raise HTTPException(status_code=404, detail="session not found")

    was_active = bool(s.is_active)

    # явная зачистка сообщений этого чата
    db.query(ChatMessage).filter(
        ChatMessage.session_id == s.id
    ).delete(synchronize_session=False)

    db.delete(s)
    db.commit()

    # оставшиеся сессии
    remaining = (
        db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user.id)
            .order_by(ChatSession.id.desc())
        )
        .scalars()
        .all()
    )

    if not remaining:
        ns = ChatSession(user_id=user.id, title="Чат 1", is_active=True)
        db.add(ns)
        db.commit()
        db.refresh(ns)
        items = _serialize_sessions(db, user.id)
        return {
            "ok": True,
            "items": items,
            "active_id": ns.id,
            "active_title": ns.title,
            "last_message": None,
        }

    if was_active:
        # делаем активным самый «свежий» оставшийся
        remaining[0].is_active = True
        db.commit()
        db.refresh(remaining[0])

    items = _serialize_sessions(db, user.id)

    # отдать превью последнего сообщения активного
    active = next((x for x in remaining if x.is_active), remaining[0])
    last_msg = (
        db.execute(
            select(ChatMessage.content)
            .where(ChatMessage.session_id == active.id)
            .order_by(ChatMessage.id.desc())
            .limit(1)
        ).scalar_one_or_none()
    )

    return {
        "ok": True,
        "items": items,
        "active_id": active.id,
        "active_title": active.title,
        "last_message": last_msg,
    }


def trim_context_by_chars(
    messages: list[dict],
    limit: int = MAX_CONTEXT_CHARS,
) -> list[dict]:
    """
    Обрезает контекст так, чтобы суммарная длина контента (кроме system)
    не превышала limit символов.

    Логика:
    - все system-сообщения сохраняем как есть;
    - по остальным (user/assistant/и т.п.) идём с конца и набираем хвост,
      пока не упрёмся в лимит;
    - возвращаем system + обрезанный хвост.
    """
    if not messages:
        return messages

    # 1. Забираем все system-сообщения отдельно
    system_messages = [m for m in messages if m.get("role") == "system"]

    # 2. Всё остальное — диалог (user / assistant / tool / etc.)
    dialog_messages = [m for m in messages if m.get("role") != "system"]

    total_chars = 0
    kept_reversed: list[dict] = []

    # 3. Идём с конца диалога, набираем хвост
    for m in reversed(dialog_messages):
        content = m.get("content", "")
        length = len(content or "")

        # если добавление этого сообщения превысит лимит — стоп
        if total_chars + length > limit and kept_reversed:
            break

        total_chars += length
        kept_reversed.append(m)

        # если это первое сообщение и оно само больше limit — всё равно забираем,
        # чтобы модель хоть что-то увидела
        if total_chars >= limit:
            break

    # 4. Переворачиваем обратно (чтобы шли по времени)
    trimmed_dialog = list(reversed(kept_reversed))

    # 5. Склеиваем system + диалог
    return system_messages + trimmed_dialog


# --------- add message + LLM ---------
@router.post("/{chat_id}/message")
def add_message(chat_id: int, payload: MessageIn, db: Session = Depends(get_db)):
    user = _get_or_create_user(db, chat_id)
    sess = _get_active_session(db, user.id)

    text = (payload.text or "").strip()
    if not text:
        return {"ok": False, "reply": "Сообщение пустое."}

    # сохраняем user-сообщение сразу
    db.add(ChatMessage(session_id=sess.id, role="user", content=text))
    db.commit()

    # загружаем историю
    hist = (
        db.execute(
            select(ChatMessage.role, ChatMessage.content)
            .where(ChatMessage.session_id == sess.id)
            .order_by(ChatMessage.id.asc())
        ).all()
    )

    history = [{"role": r, "content": c} for (r, c) in hist]

    # ограничиваем длину контекста
    history = trim_context_by_chars(history, MAX_CONTEXT_CHARS)

    # генерируем ответ
    provider = GeminiProvider()
    reply_payload = provider.chat_reply(history, text, return_meta=True)
    charged_usd = 0.0

    if isinstance(reply_payload, dict):
        reply = str(reply_payload.get("text") or "").strip() or "🤖 Ошибка нейросети."
        usage_tokens = reply_payload.get("usage_tokens")
        model_used = str(reply_payload.get("model_used") or "")
        provider_name = str(reply_payload.get("provider") or "")
        if usage_tokens and model_used:
            charged_usd = record_generation_cost(
                db,
                user,
                kind="chat_reply",
                provider=provider_name,
                model_name=model_used,
                usage_tokens=usage_tokens,
            )
    else:
        reply = str(reply_payload or "").strip() or "🤖 Ошибка нейросети."

    # сохраняем ответ
    db.add(ChatMessage(session_id=sess.id, role="assistant", content=reply))
    db.commit()

    return {"ok": True, "reply": reply, "cost_usd_charged": round(charged_usd, 6)}

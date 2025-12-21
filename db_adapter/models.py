from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Integer,
    String,
    DateTime,
    ForeignKey,
    Text,
    Boolean,
    BigInteger,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from db_adapter.database import Base


# -------------------- USERS & CREDITS --------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(50), default="free")
    balance_cents: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    premium: Mapped["PremiumCredits"] = relationship(
        "PremiumCredits",
        back_populates="user",
        uselist=False,
    )

    sessions: Mapped[list["ChatSession"]] = relationship(
        "ChatSession",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    
    subscription: Mapped["Subscription"] = relationship(
        "Subscription", 
        back_populates="user", 
        uselist=False
    )


class PremiumCredits(Base):
    __tablename__ = "premium_credits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    user: Mapped["User"] = relationship(
        "User",
        back_populates="premium",
    )

    # базовые лимиты по подписке
    msg_limit_base: Mapped[int] = mapped_column(Integer, default=0)
    img_limit_base: Mapped[int] = mapped_column(Integer, default=0)
    video_limit_base: Mapped[int] = mapped_column(Integer, default=0)

    # usage (фактическое потребление)
    total_queries: Mapped[int] = mapped_column(Integer, default=0)       # текст
    web_queries: Mapped[int] = mapped_column(Integer, default=0)         # картинки
    video_used: Mapped[int] = mapped_column(Integer, default=0)          # видео

    # докупленные лимиты
    web_queries_left: Mapped[int] = mapped_column(Integer, default=0)    # доп. текст
    image_credits: Mapped[int] = mapped_column(Integer, default=0)       # доп. изображения
    video_seconds_left: Mapped[int] = mapped_column(Integer, default=0)  # доп. видео


# -------------------- CHATS --------------------


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="sessions")
    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        index=True,
    )
    role: Mapped[str] = mapped_column(String(32))  # "user" | "assistant" | ...
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped["ChatSession"] = relationship("ChatSession", back_populates="messages")


# -------------------- VIDEO / FILES / SUBSCRIPTIONS / PAYMENTS --------------------


class VideoJob(Base):
    __tablename__ = "video_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(16))
    prompt: Mapped[str] = mapped_column(Text)
    aspect: Mapped[str] = mapped_column(String(10))
    duration: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    result_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    seconds_billed: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class File(Base):
    __tablename__ = "files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))  # voice|image|doc
    url: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )

    plan: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # "Light" | "Max" | "Ultra"
    status: Mapped[str] = mapped_column(String(32), default="active")       # "active" | "canceled"
    current_period_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)

    # legacy-поля
    stars_plan_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    renew_at: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    
    user: Mapped["User"] = relationship("User", back_populates="subscription")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    stars_payment_id: Mapped[str] = mapped_column(String(128), unique=True)
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# -------------------- CATALOG (EDITOR & SHOOTS) --------------------


class CatalogCategory(Base):
    __tablename__ = "catalog_categories"
    
    __table_args__ = (
        UniqueConstraint('slug', 'gender', name='uq_slug_gender'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    slug: Mapped[str] = mapped_column(String(64), index=True)  
    type: Mapped[str] = mapped_column(String(32))  # 'editor' | 'shoot'
    gender: Mapped[str] = mapped_column(String(16))  # 'm' | 'f' | 'all'
    title_ru: Mapped[str] = mapped_column(String(128))

    pages: Mapped[list["CatalogPage"]] = relationship(
        "CatalogPage",
        back_populates="category",
        order_by="CatalogPage.page_number",
        cascade="all, delete-orphan",
    )


class CatalogPage(Base):
    __tablename__ = "catalog_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("catalog_categories.id", ondelete="CASCADE")
    )
    page_number: Mapped[int] = mapped_column(Integer)  # 1, 2, 3...
    image_path: Mapped[str] = mapped_column(String(512))  # "assets/..."

    category: Mapped["CatalogCategory"] = relationship(
        "CatalogCategory", back_populates="pages"
    )
    items: Mapped[list["CatalogItem"]] = relationship(
        "CatalogItem",
        back_populates="page",
        order_by="CatalogItem.slot_number",
        cascade="all, delete-orphan",
    )


class CatalogItem(Base):
    __tablename__ = "catalog_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    page_id: Mapped[int] = mapped_column(
        ForeignKey("catalog_pages.id", ondelete="CASCADE")
    )

    slot_number: Mapped[int] = mapped_column(Integer)  # 1-9
    prompt: Mapped[str] = mapped_column(Text)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_premium: Mapped[bool] = mapped_column(Boolean, default=True)

    page: Mapped["CatalogPage"] = relationship("CatalogPage", back_populates="items")
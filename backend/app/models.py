from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    first_name: Mapped[str | None] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(255))
    language_code: Mapped[str | None] = mapped_column(String(16))
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")
    status: Mapped[str] = mapped_column(String(16), default="active")
    accepted_terms_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProviderCredential(Base):
    """Личный ключ API источника данных (Checko). Секрет хранится только зашифрованным."""

    __tablename__ = "provider_credentials"
    __table_args__ = (UniqueConstraint("owner_user_id", "provider_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider_code: Mapped[str] = mapped_column(String(32))
    encrypted_secret: Mapped[str] = mapped_column(Text)
    key_suffix: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16), default="untested")  # untested | ok | invalid
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(255))
    requests_today: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PortfolioItem(Base):
    """ИНН в личном портфеле пользователя."""

    __tablename__ = "portfolio_items"
    __table_args__ = (UniqueConstraint("owner_user_id", "inn"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    inn: Mapped[str] = mapped_column(String(12))
    subject_type: Mapped[str] = mapped_column(String(16))  # company | ip
    label: Mapped[str | None] = mapped_column(String(255))
    monitoring_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    fetch_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | ok | not_found | error
    fetch_error: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CompanyProfile(Base):
    """Нормализованная карточка + сырой ответ источника (для будущих снимков мониторинга)."""

    __tablename__ = "company_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    portfolio_item_id: Mapped[int] = mapped_column(ForeignKey("portfolio_items.id", ondelete="CASCADE"), unique=True)
    summary: Mapped[dict] = mapped_column(JSON)
    payload: Mapped[dict] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(32), default="checko")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

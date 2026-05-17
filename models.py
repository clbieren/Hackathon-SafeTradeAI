from __future__ import annotations
import uuid as _uuid
from typing import List, Dict, Tuple, Optional, Union, Any
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from sqlalchemy.dialects.postgresql import JSONB

_JSON_TYPE = JSON().with_variant(JSONB, "postgresql")

from app.database import Base


def utcnow() -> datetime:
    """Timezone-aware UTC zamanı döner (Python 3.11+ uyumlu)."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Kullanıcı Modeli (YENİ)
# ---------------------------------------------------------------------------

class User(Base):
    """
    Kullanıcı modeli — JWT tabanlı kimlik doğrulama.

    Alanlar:
        id              : UUID birincil anahtar (PostgreSQL gen_random_uuid).
        email           : Benzersiz e-posta adresi.
        hashed_password : bcrypt ile hashlenmiş şifre.
        full_name       : Kullanıcının tam adı.
        company_name    : Opsiyonel şirket adı.
        role            : 'admin' veya 'user' (varsayılan: 'user').
        is_active       : Hesap aktiflik durumu.
        created_at      : Hesap oluşturulma zamanı.
        updated_at      : Son güncelleme zamanı.
    """

    __tablename__ = "users"

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=_uuid.uuid4,
        nullable=False,
    )
    email: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=True
    )

    # İlişkiler
    companies: Mapped[List["Company"]] = relationship(
        "Company", back_populates="owner", lazy="noload"
    )
    reports: Mapped[List["Report"]] = relationship(
        "Report", back_populates="owner", lazy="noload"
    )
    alerts: Mapped[List["UserAlert"]] = relationship(
        "UserAlert", back_populates="user", lazy="noload", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} role={self.role!r}>"


# ---------------------------------------------------------------------------
# Şirket Modeli
# ---------------------------------------------------------------------------

class Company(Base):
    """
    Şirket modelı.

    Alanlar:
        id          : Otomatik artan birincil anahtar.
        name        : Şirket adı (zorunlu, en fazla 255 karakter).
        tax_number  : Vergi numarası (zorunlu, benzersiz, en fazla 50 karakter).
        owner_id    : Şirketi oluşturan kullanıcının UUID'si (nullable — eski kayıtlar).
        created_at  : Kaydın oluşturulma zamanı (UTC, otomatik).
    """

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    tax_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    owner_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    # İlişki: bir şirketin birden fazla raporu olabilir
    reports: Mapped[List["Report"]] = relationship(
        "Report",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="noload",
    )
    # İlişki: şirketi oluşturan kullanıcı
    owner: Mapped["User"] = relationship(
        "User", back_populates="companies", lazy="noload"
    )

    def __repr__(self) -> str:
        return f"<Company id={self.id} name={self.name!r} tax={self.tax_number!r}>"


class Report(Base):
    """
    Rapor modeli.

    Alanlar:
        id               : Otomatik artan birincil anahtar.
        company_id       : İlişkili şirketin FK'sı (zorunlu).
        owner_id         : Raporu oluşturan kullanıcının UUID'si (nullable).
        trust_score      : Güven skoru, ondalıklı (örn. 0.00 – 100.00).
        risk_summary     : Kısa risk özeti metni.
        market_data      : Piyasa verisi (JSON veya serbest metin olarak saklanır).
        official_records : Faz-1 yasal röntgen verisi (JSONB/JSON).
                           Anahtarlar: gib_status, mersis_data, kik_ban, tsg_records
        created_at       : Kaydın oluşturulma zamanı (UTC, otomatik).
    """

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    trust_score: Mapped[float] = mapped_column(
        Numeric(precision=5, scale=2),
        nullable=True,
    )
    risk_summary: Mapped[str] = mapped_column(Text, nullable=True)
    market_data: Mapped[str] = mapped_column(Text, nullable=True)
    # ---------------------------------------------------------------------------
    # Faz-1: Resmi Yasal Kayıtlar (GİB / MERSİS / KİK / TSG)
    # ---------------------------------------------------------------------------
    # PostgreSQL'de JSONB olarak saklanır (indekslenebilir, sıkıştırılmış).
    # SQLite geliştirme ortamında standart JSON tipine otomatik düşülür.
    official_records: Mapped[Dict[str, Any]] = mapped_column(
        _JSON_TYPE,
        nullable=True,
        comment=(
            "Faz-1 yasal röntgen verisi. "
            "Anahtarlar: gib_status, mersis_data, kik_ban, tsg_records"
        ),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    # İlişki: raporun sahibi olan şirket
    company: Mapped["Company"] = relationship(
        "Company",
        back_populates="reports",
        lazy="noload",
    )
    # İlişki: raporu oluşturan kullanıcı
    owner: Mapped["User"] = relationship(
        "User", back_populates="reports", lazy="noload"
    )

    def __repr__(self) -> str:
        return f"<Report id={self.id} company_id={self.company_id} score={self.trust_score}>"


# ---------------------------------------------------------------------------
# Kullanıcı Alert Modeli
# ---------------------------------------------------------------------------

class UserAlert(Base):
    """
    Kullanıcıların aylık otomatik pazar analizi e-posta alertleri.

    Alanlar:
        id            : Otomatik artan birincil anahtar.
        user_id       : Alerti oluşturan kullanıcının UUID'si (CASCADE DELETE).
        company_name  : Analiz edilecek şirket adı.
        full_address  : Şirketin tam adresi.
        is_active     : Alert aktiflik durumu.
        last_run_at   : Son çalışma zamanı (nullable).
        next_run_at   : Bir sonraki çalışma zamanı.
        created_at    : Kaydın oluşturulma zamanı.
    """

    __tablename__ = "user_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    full_address: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    # İlişki: alerte ait kullanıcı
    user: Mapped["User"] = relationship(
        "User", back_populates="alerts", lazy="noload"
    )

    def __repr__(self) -> str:
        return f"<UserAlert id={self.id} user_id={self.user_id} company={self.company_name!r} active={self.is_active}>"

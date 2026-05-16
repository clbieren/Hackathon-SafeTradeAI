import uuid
from typing import List, Dict, Tuple, Optional, Union, Any
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---------------------------------------------------------------------------
# User (Auth) Şemaları
# ---------------------------------------------------------------------------

class UserCreate(BaseModel):
    """Yeni kullanıcı kaydı için istek gövdesi."""
    email: str = Field(..., min_length=3, max_length=255, examples=["user@safetrade.com"])
    password: str = Field(..., min_length=8, max_length=128, examples=["StrongP@ss1"])
    full_name: str = Field(..., min_length=1, max_length=255, examples=["Kayra Alan"])
    company_name: Optional[str] = Field(None, max_length=255, examples=["SafeTrade Teknoloji"])


class UserLogin(BaseModel):
    """Kullanıcı girişi için istek gövdesi."""
    email: str = Field(..., examples=["user@safetrade.com"])
    password: str = Field(..., examples=["StrongP@ss1"])


class UserOut(BaseModel):
    """API yanıtında dönen kullanıcı nesnesi."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    company_name: Optional[str] = None
    role: str
    created_at: datetime


class Token(BaseModel):
    """JWT token yanıtı."""
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """JWT payload'dan çıkarılan veriler."""
    email: Optional[str] = None


# ---------------------------------------------------------------------------
# Company Şemaları
# ---------------------------------------------------------------------------

class CompanyBase(BaseModel):
    """Company için ortak alanlar."""
    name: str = Field(..., min_length=1, max_length=255, examples=["Acme Corp"])
    tax_number: str = Field(..., min_length=1, max_length=50, examples=["1234567890"])


class CompanyCreate(CompanyBase):
    """Yeni şirket oluştururken kullanılan istek gövdesi."""
    pass


class CompanyUpdate(BaseModel):
    """Şirket güncellemek için kısmi (partial) şema. Tüm alanlar opsiyoneldir."""
    name:Optional[ str ] = Field(None, min_length=1, max_length=255)
    tax_number:Optional[ str ] = Field(None, min_length=1, max_length=50)


class CompanyResponse(CompanyBase):
    """API yanıtında dönen tam şirket nesnesi."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


# ---------------------------------------------------------------------------
# Report Şemaları
# ---------------------------------------------------------------------------

class ReportBase(BaseModel):
    """Report için ortak alanlar."""
    company_id: int = Field(..., gt=0, examples=[1])
    trust_score:Optional[ float ] = Field(
        None, ge=0, le=100, examples=[87.50],
        description="0-100 arası güven skoru"
    )
    risk_summary:Optional[ str ] = Field(None, examples=["Düşük risk, stabil pazar"])
    market_data:Optional[ str ] = Field(None, examples=['{"revenue": 1500000}'])


class ReportCreate(ReportBase):
    """Yeni rapor oluştururken kullanılan istek gövdesi."""
    pass


class ReportUpdate(BaseModel):
    """Rapor güncellemek için kısmi (partial) şema. Tüm alanlar opsiyoneldir."""
    trust_score:Optional[ float ] = Field(None, ge=0, le=100)
    risk_summary:Optional[ str ] = None
    market_data:Optional[ str ] = None


class ReportResponse(ReportBase):
    """API yanıtında dönen tam rapor nesnesi."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


# ---------------------------------------------------------------------------
# Health Check Şeması
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    """Sistem sağlık durumu yanıtı."""
    status: str = Field(examples=["ok"])
    database: str = Field(examples=["ok", "error"])
    app_name: str
    app_version: str
    detail:Optional[ str ] = None


# ---------------------------------------------------------------------------
# Alert Şemaları
# ---------------------------------------------------------------------------

class AlertCreate(BaseModel):
    """Yeni alert oluştururken kullanılan istek gövdesi."""
    company_name: str = Field(..., min_length=1, max_length=255, examples=["SafeTrade Teknoloji A.Ş."])
    full_address: str = Field(..., min_length=5, examples=["Barbaros Mah. No:1 Ataşehir/İstanbul"])


class AlertResponse(BaseModel):
    """API yanıtında dönen alert nesnesi."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: uuid.UUID
    company_name: str
    full_address: str
    is_active: bool
    last_run_at: Optional[datetime] = None
    next_run_at: datetime
    created_at: datetime


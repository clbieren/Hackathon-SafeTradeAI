"""
routers/auth.py — Kimlik Doğrulama Endpoint'leri

Endpoint'ler:
    POST /auth/register  → Yeni kullanıcı kaydı
    POST /auth/login     → JWT token al (OAuth2PasswordRequestForm)
    GET  /auth/me        → Mevcut kullanıcı bilgisi (token gerekli)
    POST /auth/logout    → Client-side token silme bildirimi
"""

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    create_access_token,
    get_current_user,
    get_password_hash,
    verify_password,
)
from app.config import get_settings
from app.database import get_db
from app.models import User
from app.repository import create_user, get_user_by_email
from app.schemas import Token, UserCreate, UserOut

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/auth", tags=["Authentication"])


# ---------------------------------------------------------------------------
# POST /auth/register
# ---------------------------------------------------------------------------
@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Yeni kullanıcı kaydı oluşturur.

    - E-posta benzersiz olmalıdır.
    - Şifre en az 8 karakter olmalıdır.
    - Admin rolü doğrudan kayıt ile oluşturulamaz.
    """
    # E-posta zaten kayıtlı mı?
    existing = await get_user_by_email(db, user_data.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bu e-posta adresi zaten kayıtlı.",
        )

    # Şifreyi hashle ve kullanıcıyı oluştur
    hashed_pw = get_password_hash(user_data.password)
    user = await create_user(
        db=db,
        email=user_data.email,
        hashed_password=hashed_pw,
        full_name=user_data.full_name,
        company_name=user_data.company_name,
    )

    logger.info("Yeni kullanıcı kaydı: email=%s id=%s", user.email, user.id)
    return user


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------
@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """
    Kullanıcı girişi — JWT access token döner.

    OAuth2PasswordRequestForm kullanır:
    - username alanına e-posta girilir
    - password alanına şifre girilir
    """
    user = await get_user_by_email(db, form_data.username)
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-posta veya şifre hatalı.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu hesap devre dışı bırakılmış.",
        )

    access_token = create_access_token(
        data={"sub": user.email},
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )

    logger.info("Başarılı giriş: email=%s", user.email)
    return Token(access_token=access_token, token_type="bearer")


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------
@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    """Token sahibi kullanıcının bilgilerini döner."""
    return current_user


# ---------------------------------------------------------------------------
# POST /auth/logout
# ---------------------------------------------------------------------------
@router.post("/logout")
async def logout(current_user: User = Depends(get_current_user)):
    """
    Client-side logout bildirimi.

    JWT stateless olduğundan sunucu tarafında token iptal edilmez.
    Client tarafında localStorage'dan token silinmelidir.
    """
    return {"message": "Başarıyla çıkış yapıldı. Token'ı client tarafında silin."}

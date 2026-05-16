"""
auth.py — JWT Token Üretimi, Şifre Hashleme ve Kullanıcı Doğrulama

Bu modül, SafeTrade AI'ın kimlik doğrulama altyapısını sağlar:
- passlib (bcrypt) ile şifre hashleme ve doğrulama
- python-jose ile JWT token üretimi ve çözümlemesi
- FastAPI dependency olarak get_current_user
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import User
from app.schemas import TokenData

settings = get_settings()

# ---------------------------------------------------------------------------
# Şifre Hashleme (bcrypt)
# ---------------------------------------------------------------------------
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Düz metin şifreyi bcrypt hash ile karşılaştırır."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Şifreyi bcrypt ile hashler."""
    return pwd_context.hash(password)


# ---------------------------------------------------------------------------
# JWT Token İşlemleri
# ---------------------------------------------------------------------------
ALGORITHM = "HS256"

# OAuth2 şeması — Swagger UI'da "Authorize" butonu otomatik oluşturur
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    JWT access token üretir.

    Args:
        data: Token payload'ına gömülecek veriler (genellikle {"sub": email}).
        expires_delta: Token geçerlilik süresi. Verilmezse settings'ten okunur.

    Returns:
        Kodlanmış JWT string.
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.access_token_expire_minutes
        )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)
    return encoded_jwt


# ---------------------------------------------------------------------------
# FastAPI Dependency: Mevcut Kullanıcıyı Çek
# ---------------------------------------------------------------------------

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Bearer token'dan kullanıcıyı doğrular ve veritabanından çeker.

    Raises:
        HTTPException 401: Token geçersiz veya kullanıcı bulunamadı.
        HTTPException 403: Kullanıcı hesabı devre dışı.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Kimlik doğrulama başarısız. Lütfen tekrar giriş yapın.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
        token_data = TokenData(email=email)
    except JWTError:
        raise credentials_exception

    # Kullanıcıyı DB'den çek
    from app.repository import get_user_by_email  # döngüsel import önleme

    user = await get_user_by_email(db, email=token_data.email)
    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu hesap devre dışı bırakılmış.",
        )
    return user

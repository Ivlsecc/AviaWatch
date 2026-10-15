"""Вход в админку: один администратор, логин/пароль из .env, JWT в заголовке Authorization."""

from __future__ import annotations

import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from common.config import get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)
TOKEN_TTL = timedelta(days=7)
# Если секрет не задан — генерируем на время жизни процесса (после перезапуска войти заново)
_FALLBACK_SECRET = secrets.token_urlsafe(32)


def _secret() -> str:
    return get_settings().jwt_secret or _FALLBACK_SECRET


class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    token: str
    username: str


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn) -> TokenOut:
    s = get_settings()
    if not s.admin_password:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "ADMIN_PASSWORD не задан в .env — вход в админку выключен")
    ok_user = hmac.compare_digest(body.username, s.admin_username)
    ok_pass = hmac.compare_digest(body.password, s.admin_password)
    if not (ok_user and ok_pass):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")
    exp = datetime.now(timezone.utc) + TOKEN_TTL
    token = jwt.encode({"sub": body.username, "exp": exp}, _secret(), algorithm="HS256")
    return TokenOut(token=token, username=body.username)


async def require_admin(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Нужен вход")
    try:
        payload = jwt.decode(creds.credentials, _secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сессия истекла, войдите снова") from None
    return payload["sub"]


@router.get("/me")
async def me(user: str = Depends(require_admin)) -> dict:
    return {"username": user}

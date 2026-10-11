"""Autenticazione: utenti locali, sessioni con cookie, ruoli e gestione utenti.

- Password: hash scrypt (libreria standard) con salt casuale.
- Sessione: token casuale nel cookie HttpOnly/SameSite=Strict, nel DB solo lo SHA-256.
- CSRF: le richieste che modificano dati devono avere l'header X-KS-CSRF, che un sito
  esterno non puo' inviare senza preflight CORS (che non abilitiamo).
- Ruoli: viewer < operator < admin. Nelle API normali GET basta viewer, il resto operator.
"""

import base64
import hashlib
import hmac
import secrets
import threading
import time
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .app import get_or_404, get_session
from .models import Role, User, UserSession

COOKIE_NAME = "ks_session"
CSRF_HEADER = "X-KS-CSRF"
SESSION_IDLE = timedelta(hours=12)
MIN_PASSWORD_LENGTH = 8
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# --- password ----------------------------------------------------------------

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# Hash fittizio per non rivelare, dai tempi di risposta, se un utente esiste
_DUMMY_HASH = hash_password(secrets.token_hex(8))


def check_password_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"La password deve avere almeno {MIN_PASSWORD_LENGTH} caratteri")


# --- limite ai tentativi di login ---------------------------------------------

class LoginThrottle:
    """Dopo `max_failures` errori per utente o IP blocca per `lock_seconds`."""

    def __init__(self, max_failures: int = 5, lock_seconds: int = 60):
        self.max_failures = max_failures
        self.lock_seconds = lock_seconds
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> list[float]:
        return [t for t in self._failures.get(key, []) if now - t < self.lock_seconds]

    def retry_after(self, *keys: str) -> int:
        now = time.monotonic()
        with self._lock:
            waits = [
                int(self.lock_seconds - (now - recent[0])) + 1
                for key in keys
                if len(recent := self._recent(key, now)) >= self.max_failures
            ]
        return max(waits, default=0)

    def failure(self, *keys: str) -> None:
        now = time.monotonic()
        with self._lock:
            for key in keys:
                self._failures[key] = self._recent(key, now) + [now]

    def success(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._failures.pop(key, None)


# --- sessioni ----------------------------------------------------------------

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(s: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now()
    s.execute(delete(UserSession).where(UserSession.expires_at < now))  # pulizia sessioni scadute
    s.add(UserSession(token_hash=_token_hash(token), user_id=user.id, expires_at=now + SESSION_IDLE))
    user.last_login_at = now
    s.commit()
    return token


def user_from_token(s: Session, token: str | None) -> User | None:
    if not token:
        return None
    session = s.scalar(select(UserSession).where(UserSession.token_hash == _token_hash(token)))
    now = datetime.now()
    if session is None or session.expires_at < now or not session.user.active:
        return None
    # scadenza "scorrevole": rinnovata con l'uso, al massimo una volta al minuto
    if session.expires_at - now < SESSION_IDLE - timedelta(minutes=1):
        session.expires_at = now + SESSION_IDLE
        s.commit()
    return session.user


def _set_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=int(SESSION_IDLE.total_seconds()),
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        path="/",
    )


# --- dipendenze FastAPI ------------------------------------------------------

SessionDep = Annotated[Session, Depends(get_session)]


def current_user(request: Request, s: SessionDep) -> User:
    user = user_from_token(s, request.cookies.get(COOKIE_NAME))
    if user is None:
        raise HTTPException(401, "Accesso richiesto")
    if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
        raise HTTPException(403, "Richiesta non valida (header CSRF mancante)")
    request.state.user = user
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_role(role: Role):
    def dependency(user: CurrentUser) -> User:
        if Role(user.role).level < role.level:
            raise HTTPException(403, "Permessi insufficienti")
        return user

    return dependency


def api_access(request: Request, user: CurrentUser) -> User:
    """Regola delle API di dominio: lettura per tutti, modifiche da operatore in su."""
    needed = Role.VIEWER if request.method in SAFE_METHODS else Role.OPERATOR
    return require_role(needed)(user)


# --- schemi ------------------------------------------------------------------

class LoginIn(BaseModel):
    username: str
    password: str


class SetupIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    full_name: str = ""
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    full_name: str
    role: Role
    active: bool
    created_at: datetime
    last_login_at: datetime | None


class UserIn(BaseModel):
    username: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._@-]+$")
    full_name: str = ""
    role: Role = Role.VIEWER
    active: bool = True
    password: str | None = None  # obbligatoria in creazione, facoltativa in modifica


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str


# --- operazioni sugli utenti -------------------------------------------------

def count_users(s: Session) -> int:
    return s.scalar(select(func.count(User.id))) or 0


def create_user(s: Session, username: str, password: str, role: Role = Role.VIEWER, full_name: str = "") -> User:
    username = username.strip()
    if s.scalar(select(User).where(func.lower(User.username) == username.lower())):
        raise ValueError(f"L'utente '{username}' esiste gia'")
    check_password_strength(password)
    user = User(username=username, full_name=full_name, password_hash=hash_password(password), role=role)
    s.add(user)
    s.commit()
    return user


def set_password(s: Session, user: User, password: str) -> None:
    check_password_strength(password)
    user.password_hash = hash_password(password)
    s.execute(delete(UserSession).where(UserSession.user_id == user.id))  # chiude le sessioni aperte
    s.commit()


def _active_admins(s: Session) -> int:
    return s.scalar(select(func.count(User.id)).where(User.role == Role.ADMIN, User.active.is_(True))) or 0


def _validation(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


# --- endpoint: autenticazione ------------------------------------------------

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status")
def auth_status(request: Request, s: SessionDep):
    """Pubblico: dice se serve il primo setup e chi e' l'utente collegato (se c'e')."""
    user = user_from_token(s, request.cookies.get(COOKIE_NAME))
    return {
        "needs_setup": count_users(s) == 0,
        "user": UserOut.model_validate(user) if user else None,
    }


@router.post("/setup", response_model=UserOut, status_code=201)
def setup(data: SetupIn, request: Request, response: Response, s: SessionDep):
    """Crea il primo amministratore. Possibile solo finche' non esiste nessun utente."""
    if request.headers.get(CSRF_HEADER) != "1":
        raise HTTPException(403, "Richiesta non valida (header CSRF mancante)")
    if count_users(s) > 0:
        raise HTTPException(409, "Il setup e' gia' stato completato")
    user = _validation(create_user, s, data.username, data.password, Role.ADMIN, data.full_name)
    _set_cookie(request, response, create_session(s, user))
    return user


@router.post("/login", response_model=UserOut)
def login(data: LoginIn, request: Request, response: Response, s: SessionDep):
    if request.headers.get(CSRF_HEADER) != "1":
        raise HTTPException(403, "Richiesta non valida (header CSRF mancante)")
    throttle: LoginThrottle = request.app.state.login_throttle
    keys = (f"user:{data.username.strip().lower()}", f"ip:{request.client.host if request.client else '?'}")
    if wait := throttle.retry_after(*keys):
        raise HTTPException(429, f"Troppi tentativi falliti: riprova tra {wait} secondi")

    user = s.scalar(select(User).where(func.lower(User.username) == data.username.strip().lower()))
    valid = verify_password(data.password, user.password_hash if user else _DUMMY_HASH)
    if not (user and valid and user.active):
        throttle.failure(*keys)
        raise HTTPException(401, "Nome utente o password non corretti")
    throttle.success(*keys)
    _set_cookie(request, response, create_session(s, user))
    return user


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, s: SessionDep):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        s.execute(delete(UserSession).where(UserSession.token_hash == _token_hash(token)))
        s.commit()
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser):
    return user


@router.post("/password", status_code=204)
def change_password(data: PasswordChangeIn, request: Request, response: Response, user: CurrentUser, s: SessionDep):
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(422, "La password attuale non e' corretta")
    _validation(set_password, s, user, data.new_password)
    _set_cookie(request, response, create_session(s, user))  # resta collegato con una sessione nuova


# --- endpoint: gestione utenti (solo admin) ----------------------------------

users_router = APIRouter(
    prefix="/api/users", tags=["users"], dependencies=[Depends(require_role(Role.ADMIN))]
)


@users_router.get("", response_model=list[UserOut])
def list_users(s: SessionDep):
    return s.scalars(select(User).order_by(User.username)).all()


@users_router.post("", response_model=UserOut, status_code=201)
def add_user(data: UserIn, s: SessionDep):
    if not data.password:
        raise HTTPException(422, "La password e' obbligatoria")
    user = _validation(create_user, s, data.username, data.password, data.role, data.full_name)
    user.active = data.active
    s.commit()
    return user


@users_router.put("/{user_id}", response_model=UserOut)
def update_user(user_id: int, data: UserIn, s: SessionDep, me: CurrentUser):
    user = get_or_404(s, User, user_id)
    duplicate = s.scalar(select(User).where(func.lower(User.username) == data.username.lower(), User.id != user_id))
    if duplicate:
        raise HTTPException(422, f"L'utente '{data.username}' esiste gia'")
    losing_admin = user.role == Role.ADMIN and user.active and (data.role != Role.ADMIN or not data.active)
    if losing_admin and _active_admins(s) <= 1:
        raise HTTPException(422, "Deve restare almeno un amministratore attivo")
    if user.id == me.id and not data.active:
        raise HTTPException(422, "Non puoi disattivare il tuo utente")
    user.username, user.full_name, user.role, user.active = data.username, data.full_name, data.role, data.active
    if data.password:
        _validation(set_password, s, user, data.password)
    if not user.active:
        s.execute(delete(UserSession).where(UserSession.user_id == user.id))
    s.commit()
    return user


@users_router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int, s: SessionDep, me: CurrentUser):
    user = get_or_404(s, User, user_id)
    if user.id == me.id:
        raise HTTPException(422, "Non puoi eliminare il tuo utente")
    if user.role == Role.ADMIN and user.active and _active_admins(s) <= 1:
        raise HTTPException(422, "Deve restare almeno un amministratore attivo")
    s.delete(user)
    s.commit()

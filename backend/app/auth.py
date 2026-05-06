from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from .config import Settings
from .storage import utc_now

PBKDF2_ALGORITHM = "sha256"
PBKDF2_ITERATIONS = 210_000
TOKEN_TTL_SECONDS = 12 * 60 * 60


class AdminAccountRecord(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password_hash: str
    salt: str
    iterations: int = PBKDF2_ITERATIONS
    token_secret: str
    updated_at: str


class AuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class AdminSession:
    username: str
    token: str
    expires_at: int


class AdminAuthService:
    def __init__(self, account_path: Path):
        self.account_path = account_path
        self.account_path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_settings(cls, settings: Settings) -> AdminAuthService:
        service = cls(settings.data_root / "auth" / "admin_account.json")
        if (
            not service.is_configured
            and settings.admin_username
            and settings.admin_password
        ):
            service.write_account(settings.admin_username, settings.admin_password)
        return service

    @property
    def is_configured(self) -> bool:
        return self.account_path.is_file()

    def read_account(self) -> AdminAccountRecord:
        try:
            return AdminAccountRecord.model_validate_json(
                self.account_path.read_text(encoding="utf-8")
            )
        except FileNotFoundError as exc:
            raise AuthError("admin account is not configured") from exc
        except Exception as exc:
            raise AuthError("admin account file is invalid") from exc

    def write_account(
        self,
        username: str,
        password: str,
        *,
        token_secret: str | None = None,
    ) -> AdminAccountRecord:
        username = _validate_username(username)
        _validate_password(password)
        salt = secrets.token_bytes(16)
        record = AdminAccountRecord(
            username=username,
            password_hash=_hash_password(password, salt, PBKDF2_ITERATIONS),
            salt=_b64url(salt),
            iterations=PBKDF2_ITERATIONS,
            token_secret=token_secret or _b64url(secrets.token_bytes(32)),
            updated_at=utc_now(),
        )
        self._write_record(record)
        return record

    def update_account(
        self,
        *,
        current_password: str,
        username: str | None = None,
        new_password: str | None = None,
    ) -> AdminSession:
        current = self.read_account()
        if not self.verify_password(current_password):
            raise AuthError("current password is incorrect")
        next_username = _validate_username(username or current.username)
        next_password = new_password or None
        if next_password is not None:
            _validate_password(next_password)
        salt = secrets.token_bytes(16) if next_password else _b64decode(current.salt)
        password_hash = (
            _hash_password(next_password, salt, PBKDF2_ITERATIONS)
            if next_password
            else current.password_hash
        )
        record = AdminAccountRecord(
            username=next_username,
            password_hash=password_hash,
            salt=_b64url(salt),
            iterations=PBKDF2_ITERATIONS if next_password else current.iterations,
            token_secret=_b64url(secrets.token_bytes(32)),
            updated_at=utc_now(),
        )
        self._write_record(record)
        return self.issue_token(record.username)

    def verify_password(self, password: str) -> bool:
        record = self.read_account()
        expected = _hash_password(password, _b64decode(record.salt), record.iterations)
        return hmac.compare_digest(expected, record.password_hash)

    def issue_token(self, username: str) -> AdminSession:
        record = self.read_account()
        if username != record.username:
            raise AuthError("invalid admin username")
        expires_at = int(time.time()) + TOKEN_TTL_SECONDS
        payload = {
            "sub": record.username,
            "exp": expires_at,
            "nonce": secrets.token_urlsafe(12),
        }
        encoded_payload = _b64url(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        signature = _sign(encoded_payload, record.token_secret)
        return AdminSession(
            username=record.username,
            token=f"v1.{encoded_payload}.{signature}",
            expires_at=expires_at,
        )

    def verify_token(self, token: str) -> str:
        record = self.read_account()
        try:
            version, encoded_payload, signature = token.split(".", 2)
        except ValueError as exc:
            raise AuthError("invalid admin token") from exc
        if version != "v1":
            raise AuthError("invalid admin token")
        expected = _sign(encoded_payload, record.token_secret)
        if not hmac.compare_digest(signature, expected):
            raise AuthError("invalid admin token")
        try:
            payload = json.loads(_b64decode(encoded_payload).decode("utf-8"))
        except Exception as exc:
            raise AuthError("invalid admin token") from exc
        if payload.get("sub") != record.username:
            raise AuthError("invalid admin token")
        if int(payload.get("exp", 0)) < int(time.time()):
            raise AuthError("admin token expired")
        return record.username

    def _write_record(self, record: AdminAccountRecord) -> None:
        fd, tmp_name = tempfile.mkstemp(
            prefix="admin-account.", suffix=".tmp", dir=self.account_path.parent
        )
        try:
            with open(fd, "w", encoding="utf-8") as tmp:
                tmp.write(record.model_dump_json(indent=2))
                tmp.write("\n")
                tmp.flush()
                os.fchmod(tmp.fileno(), 0o600)
            Path(tmp_name).replace(self.account_path)
        finally:
            tmp_path = Path(tmp_name)
            if tmp_path.exists():
                tmp_path.unlink()


def _validate_username(username: str) -> str:
    username = username.strip()
    if not username:
        raise AuthError("admin username must not be empty")
    if any(char in username for char in ("\x00", "\n", "\r")):
        raise AuthError("admin username contains invalid characters")
    return username


def _validate_password(password: str) -> None:
    if len(password) < 8:
        raise AuthError("admin password must be at least 8 characters")
    if any(char in password for char in ("\x00", "\n", "\r")):
        raise AuthError("admin password contains invalid characters")


def _hash_password(password: str, salt: bytes, iterations: int) -> str:
    digest = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM, password.encode("utf-8"), salt, iterations
    )
    return _b64url(digest)


def _sign(encoded_payload: str, token_secret: str) -> str:
    digest = hmac.new(
        _b64decode(token_secret), encoded_payload.encode("ascii"), hashlib.sha256
    ).digest()
    return _b64url(digest)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))

"""Authentication helpers."""
from __future__ import annotations

import hashlib
from typing import Optional

import database


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def register_user(email: str, name: str, password: Optional[str]) -> int:
    password_hash = hash_password(password) if password else None
    return database.create_user(email=email, name=name, password_hash=password_hash)


def authenticate(email: str, password: str) -> Optional[dict]:
    user = database.get_user_by_email(email)
    if not user:
        return None
    stored_hash = user["password_hash"]
    if stored_hash and stored_hash != hash_password(password):
        return None
    return dict(user)

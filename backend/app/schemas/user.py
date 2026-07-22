# User request and response schemas.
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    password: str


class UserRegister(UserCreate):
    # Registration-only password policy; login keeps accepting legacy short
    # passwords via the shared UserCreate shape.
    password: str = Field(min_length=12)


class UserUpdate(BaseModel):
    is_active: bool | None = None
    role: Literal["admin", "user"] | None = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AuthResponse(BaseModel):
    user: UserResponse

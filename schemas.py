from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    account: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    username: Optional[str] = Field(default=None, max_length=64)
    display_name: Optional[str] = Field(default=None, max_length=64)
    phone: Optional[str] = Field(default=None, max_length=32)
    email: Optional[str] = Field(default=None, max_length=128)


class LoginRequest(BaseModel):
    account: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class UpdateProfileRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=64)
    phone: Optional[str] = Field(default=None, max_length=32)
    email: Optional[str] = Field(default=None, max_length=128)
    current_password: Optional[str] = Field(default=None, max_length=128)
    new_password: Optional[str] = Field(default=None, min_length=6, max_length=128)


class UserProfile(BaseModel):
    id: int
    account: str
    username: Optional[str] = None
    display_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    created_at: str
    updated_at: str


class AuthResponse(BaseModel):
    message: str
    user: UserProfile


class MessageResponse(BaseModel):
    message: str


class HistoryFileResult(BaseModel):
    filename: str
    result_label: str
    score: float
    is_bonafide: bool
    error: Optional[str] = None


class FileHistoryRecord(BaseModel):
    id: int
    history_id: int
    filename: str
    result_label: str
    score: float
    is_bonafide: bool
    error: Optional[str] = None
    created_at: str


class HistoryResponse(BaseModel):
    items: List[FileHistoryRecord]

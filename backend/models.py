"""Pydantic request/response models."""
from __future__ import annotations

from datetime import date, datetime
import re
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

Role = Literal["admin", "salesperson", "farmer"]
Locale = Literal["vi", "zh-TW"]
PondType = Literal["nursery", "growout", "treatment", "settling", "other"]
CycleStatus = Literal["planned", "active", "harvested", "aborted"]
CycleStage = Literal["nursery", "growout"]


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    email: EmailStr
    role: Role
    display_name: str
    locale: Locale = "vi"
    phone: Optional[str] = None
    is_active: bool = True


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    display_name: Optional[str] = None
    locale: Optional[Locale] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)


class MeUpdate(BaseModel):
    display_name: Optional[str] = None
    locale: Optional[Locale] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class AssignmentBody(BaseModel):
    salesperson_id: UUID
    farmer_id: UUID


class PondCreate(BaseModel):
    farmer_id: UUID
    code: str = Field(min_length=1, max_length=32)
    name: str
    pond_type: PondType = "growout"
    area_m2: Optional[float] = None
    depth_m: Optional[float] = None
    volume_m3: Optional[float] = None
    location_text: Optional[str] = None


class PondUpdate(BaseModel):
    name: Optional[str] = None
    pond_type: Optional[PondType] = None
    area_m2: Optional[float] = None
    depth_m: Optional[float] = None
    volume_m3: Optional[float] = None
    location_text: Optional[str] = None
    is_active: Optional[bool] = None
    farmer_id: Optional[UUID] = None


class CycleCreate(BaseModel):
    stage: CycleStage = "nursery"
    status: CycleStatus = "active"
    stocked_at: Optional[date] = None
    stocked_count: Optional[int] = None
    density_per_m2: Optional[float] = None
    sample_avg_weight_g: Optional[float] = None
    species: str = "whiteleg"
    notes: Optional[str] = None


class CycleUpdate(BaseModel):
    stage: Optional[CycleStage] = None
    status: Optional[CycleStatus] = None
    stocked_at: Optional[date] = None
    stocked_count: Optional[int] = None
    density_per_m2: Optional[float] = None
    sample_avg_weight_g: Optional[float] = None
    species: Optional[str] = None
    notes: Optional[str] = None
    harvested_at: Optional[date] = None


class DeviceCreate(BaseModel):
    serial: str = Field(min_length=12, max_length=12)
    pond_id: Optional[UUID] = None
    name: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("serial", mode="before")
    @classmethod
    def normalize_mac(cls, value):
        if not isinstance(value, str):
            raise ValueError("Device ID must be a MAC address")
        mac = value.strip()
        if not re.fullmatch(r"(?:[0-9a-fA-F]{12}|(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}|(?:[0-9a-fA-F]{2}-){5}[0-9a-fA-F]{2})", mac):
            raise ValueError("Enter a 12-digit MAC address, optionally separated by colons or hyphens")
        return mac.replace(":", "").replace("-", "").upper()


class DeviceUpdate(BaseModel):
    pond_id: Optional[UUID] = None
    name: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None
    unbind: bool = False


class LabTestCreate(BaseModel):
    sampled_at: datetime
    no2_ppm: Optional[float] = None
    nh3_ppm: Optional[float] = None
    alkalinity_ppm: Optional[float] = None
    ca_ppm: Optional[float] = None
    mg_ppm: Optional[float] = None
    k_ppm: Optional[float] = None
    notes: Optional[str] = None


class AlertRuleUpdate(BaseModel):
    min_value: Optional[float] = Field(default=None, allow_inf_nan=False)
    max_value: Optional[float] = Field(default=None, allow_inf_nan=False)
    severity: Optional[Literal["info", "warn", "critical"]] = None
    is_active: Optional[bool] = None

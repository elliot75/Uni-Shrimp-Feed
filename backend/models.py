"""Pydantic request/response models."""
from __future__ import annotations

from datetime import date, datetime
import re
from typing import Literal, Optional
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field, FiniteFloat, field_validator

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


class ProbeReadingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_serial: str = Field(min_length=12, max_length=12)
    recorded_at: AwareDatetime
    ph: Optional[FiniteFloat] = Field(default=None, ge=0, le=14)
    ph_mv: Optional[FiniteFloat] = None
    ph_temp_c: Optional[FiniteFloat] = None
    conductivity_us_cm: Optional[FiniteFloat] = Field(default=None, ge=0)
    salinity_ppt: Optional[FiniteFloat] = Field(default=None, ge=0)
    cond_temp_c: Optional[FiniteFloat] = None
    tds_mg_l: Optional[FiniteFloat] = Field(default=None, ge=0)
    do_mg_l: Optional[FiniteFloat] = Field(default=None, ge=0)
    do_sat_pct: Optional[FiniteFloat] = Field(default=None, ge=0)
    do_temp_c: Optional[FiniteFloat] = None
    raw: Optional[dict] = None

    @field_validator("device_serial", mode="before")
    @classmethod
    def normalize_mac(cls, value):
        return DeviceCreate.normalize_mac(value)


class ProbeReadingReceipt(BaseModel):
    id: int
    device_serial: str
    recorded_at: datetime
    temp_c: Optional[float]


class DeviceActivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_serial: str = Field(min_length=12, max_length=12)
    activation_code: str = Field(min_length=32, max_length=128)

    @field_validator("device_serial", mode="before")
    @classmethod
    def normalize_mac(cls, value):
        return DeviceCreate.normalize_mac(value)


class DeviceActivationCode(BaseModel):
    device_id: UUID
    device_serial: str
    activation_code: str
    expires_at: datetime


class DeviceKeyResponse(BaseModel):
    device_id: UUID
    device_serial: str
    api_key: str


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

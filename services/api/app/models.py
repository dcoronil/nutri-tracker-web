from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as date_type
from enum import StrEnum

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class NutritionBasis(StrEnum):
    per_100g = "per_100g"
    per_100ml = "per_100ml"
    per_serving = "per_serving"


class IntakeMethod(StrEnum):
    grams = "grams"
    percent_pack = "percent_pack"
    units = "units"


class Product(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    barcode: str | None = Field(default=None, unique=True, index=True, max_length=32)
    name: str = Field(max_length=256)
    brand: str | None = Field(default=None, max_length=128)
    nutrition_basis: NutritionBasis = Field(default=NutritionBasis.per_100g)
    serving_size_g: float | None = Field(default=None, ge=0)
    net_weight_g: float | None = Field(default=None, ge=0)

    kcal: float = Field(ge=0)
    protein_g: float = Field(ge=0)
    fat_g: float = Field(ge=0)
    sat_fat_g: float | None = Field(default=None, ge=0)
    carbs_g: float = Field(ge=0)
    sugars_g: float | None = Field(default=None, ge=0)
    fiber_g: float | None = Field(default=None, ge=0)
    salt_g: float | None = Field(default=None, ge=0)

    data_confidence: str = Field(default="manual", max_length=64)
    created_at: datetime = Field(default_factory=utcnow)


class Intake(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id", index=True)
    quantity_g: float | None = Field(default=None, ge=0)
    quantity_units: float | None = Field(default=None, ge=0)
    percent_pack: float | None = Field(default=None, ge=0, le=100)
    method: IntakeMethod = Field(default=IntakeMethod.grams)
    created_at: datetime = Field(default_factory=utcnow, index=True)

class DailyGoal(SQLModel, table=True):
    date: date_type = Field(primary_key=True)
    kcal_goal: float = Field(ge=0)
    protein_goal: float = Field(ge=0)
    fat_goal: float = Field(ge=0)
    carbs_goal: float = Field(ge=0)

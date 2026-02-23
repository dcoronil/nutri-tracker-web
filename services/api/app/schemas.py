from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models import IntakeMethod, NutritionBasis


class ProductRead(BaseModel):
    id: int
    barcode: str | None
    name: str
    brand: str | None
    nutrition_basis: NutritionBasis
    serving_size_g: float | None
    net_weight_g: float | None
    kcal: float
    protein_g: float
    fat_g: float
    sat_fat_g: float | None
    carbs_g: float
    sugars_g: float | None
    fiber_g: float | None
    salt_g: float | None
    data_confidence: str

    model_config = {"from_attributes": True}


class ProductLookupResponse(BaseModel):
    source: Literal["local", "openfoodfacts_imported", "openfoodfacts_incomplete", "not_found"]
    product: ProductRead | None = None
    missing_fields: list[str] = Field(default_factory=list)
    message: str | None = None


class NutritionExtract(BaseModel):
    kcal: float | None = None
    protein_g: float | None = None
    fat_g: float | None = None
    sat_fat_g: float | None = None
    carbs_g: float | None = None
    sugars_g: float | None = None
    fiber_g: float | None = None
    salt_g: float | None = None
    nutrition_basis: NutritionBasis | None = None
    serving_size_g: float | None = None


class LabelPhotoResponse(BaseModel):
    created: bool
    product: ProductRead | None = None
    extracted: NutritionExtract
    missing_fields: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)


class IntakeCreate(BaseModel):
    product_id: int
    method: IntakeMethod
    quantity_g: float | None = Field(default=None, gt=0)
    quantity_units: float | None = Field(default=None, gt=0)
    percent_pack: float | None = Field(default=None, gt=0, le=100)
    created_at: datetime | None = None

    @model_validator(mode="after")
    def validate_quantity(self) -> IntakeCreate:
        if self.method == IntakeMethod.grams and self.quantity_g is None:
            raise ValueError("quantity_g es obligatorio cuando method=grams")
        if self.method == IntakeMethod.units and self.quantity_units is None:
            raise ValueError("quantity_units es obligatorio cuando method=units")
        if self.method == IntakeMethod.percent_pack and self.percent_pack is None:
            raise ValueError("percent_pack es obligatorio cuando method=percent_pack")
        return self


class IntakeNutrients(BaseModel):
    kcal: float
    protein_g: float
    fat_g: float
    sat_fat_g: float
    carbs_g: float
    sugars_g: float
    fiber_g: float
    salt_g: float


class IntakeRead(BaseModel):
    id: int
    product_id: int
    method: IntakeMethod
    quantity_g: float | None
    quantity_units: float | None
    percent_pack: float | None
    created_at: datetime
    nutrients: IntakeNutrients

    model_config = {"from_attributes": True}


class DailyGoalUpsert(BaseModel):
    kcal_goal: float = Field(gt=0)
    protein_goal: float = Field(gt=0)
    fat_goal: float = Field(gt=0)
    carbs_goal: float = Field(gt=0)


class DaySummary(BaseModel):
    date: date
    goal: DailyGoalUpsert | None = None
    consumed: IntakeNutrients
    remaining: IntakeNutrients | None = None
    intakes: list[IntakeRead]

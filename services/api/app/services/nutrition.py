from __future__ import annotations

import math
import re
from io import BytesIO
from typing import Any

from fastapi import UploadFile
from PIL import Image

from app.config import get_settings
from app.models import NutritionBasis, Product

try:
    import pytesseract
except ImportError:  # pragma: no cover - optional runtime dependency behavior
    pytesseract = None

NUTRIENT_FIELDS = [
    "kcal",
    "protein_g",
    "fat_g",
    "sat_fat_g",
    "carbs_g",
    "sugars_g",
    "fiber_g",
    "salt_g",
]

CRITICAL_FIELDS = ["kcal", "protein_g", "fat_g", "carbs_g", "nutrition_basis"]

PATTERNS: dict[str, list[str]] = {
    "kcal": [r"(?:energ[ií]a|energy|kcal)[^\d]{0,20}(\d{1,4}(?:[\.,]\d{1,2})?)\s*(?:kcal)?"],
    "protein_g": [r"(?:prote[ií]nas?|protein)[^\d]{0,20}(\d{1,3}(?:[\.,]\d{1,2})?)\s*g"],
    "fat_g": [
        r"(?:grasas?\s+totales|fat(?!\s+saturada)|grasa(?!\s+saturada))"
        r"[^\d]{0,20}(\d{1,3}(?:[\.,]\d{1,2})?)\s*g"
    ],
    "sat_fat_g": [r"(?:grasas?\s+saturadas?|saturated\s+fat)[^\d]{0,20}(\d{1,3}(?:[\.,]\d{1,2})?)\s*g"],
    "carbs_g": [
        r"(?:hidratos\s+de\s+carbono|carbohidratos?|carbohydrates?|carbs)"
        r"[^\d]{0,20}(\d{1,3}(?:[\.,]\d{1,2})?)\s*g"
    ],
    "sugars_g": [r"(?:az[uú]cares?|sugars?)[^\d]{0,20}(\d{1,3}(?:[\.,]\d{1,2})?)\s*g"],
    "fiber_g": [r"(?:fibra|fiber)[^\d]{0,20}(\d{1,3}(?:[\.,]\d{1,2})?)\s*g"],
    "salt_g": [r"(?:sal|salt)[^\d]{0,20}(\d{1,3}(?:[\.,]\d{1,2})?)\s*g"],
}


class IntakeComputationError(ValueError):
    pass


def _to_float(raw: str | float | int | None) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    cleaned = raw.strip().replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _detect_basis(text: str) -> NutritionBasis | None:
    lowered = text.lower()
    if re.search(r"(?:por|per)\s*100\s*ml", lowered):
        return NutritionBasis.per_100ml
    if re.search(r"(?:por|per)\s*100\s*g", lowered):
        return NutritionBasis.per_100g
    if re.search(r"(?:por|per)\s*(?:serving|servicio|porci[oó]n|raci[oó]n)", lowered):
        return NutritionBasis.per_serving
    return None


def _extract_serving_size(text: str) -> float | None:
    lowered = text.lower()
    patterns = [
        r"(?:serving|porci[oó]n|raci[oó]n)\s*(?:size|de|:)??\s*(\d{1,4}(?:[\.,]\d{1,2})?)\s*g",
        r"(\d{1,4}(?:[\.,]\d{1,2})?)\s*g\s*(?:por|per)\s*(?:serving|porci[oó]n|raci[oó]n)",
    ]
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if not match:
            continue
        value = _to_float(match.group(1))
        if value is not None:
            return value
    return None


def extract_nutrition_from_text(text: str, basis_hint: NutritionBasis | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {field: None for field in NUTRIENT_FIELDS}
    lowered = text.lower()

    for field, patterns in PATTERNS.items():
        for pattern in patterns:
            match = re.search(pattern, lowered)
            if not match:
                continue
            value = _to_float(match.group(1))
            if value is None:
                continue
            result[field] = value
            break

    basis = basis_hint or _detect_basis(text)
    serving_size = _extract_serving_size(text)
    result["nutrition_basis"] = basis
    result["serving_size_g"] = serving_size
    return result


def missing_critical_fields(nutrition: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for key in CRITICAL_FIELDS:
        if nutrition.get(key) is None:
            missing.append(key)
    return missing


def coherence_questions(nutrition: dict[str, Any]) -> list[str]:
    questions: list[str] = []

    fat = nutrition.get("fat_g")
    sat_fat = nutrition.get("sat_fat_g")
    carbs = nutrition.get("carbs_g")
    sugars = nutrition.get("sugars_g")
    protein = nutrition.get("protein_g")
    kcal = nutrition.get("kcal")
    basis = nutrition.get("nutrition_basis")

    if fat is not None and sat_fat is not None and sat_fat > fat + 0.1:
        questions.append("La grasa saturada no puede superar la grasa total. ¿Puedes revisar ese valor?")

    if carbs is not None and sugars is not None and sugars > carbs + 0.1:
        questions.append("Los azúcares no pueden superar los carbohidratos totales. ¿Puedes confirmarlo?")

    if basis in {NutritionBasis.per_100g, NutritionBasis.per_100ml}:
        macro_total = sum(value for value in [fat, carbs, protein] if value is not None)
        if macro_total > 110:
            questions.append("La suma de grasa+carbohidratos+proteínas supera 110g por 100. ¿Hay un error de lectura?")

    if all(value is not None for value in [kcal, fat, carbs, protein]):
        estimated = 9 * fat + 4 * carbs + 4 * protein
        if estimated > 0:
            delta_ratio = abs(kcal - estimated) / estimated
            if delta_ratio > 0.35:
                questions.append(
                    "Las kcal no son coherentes con macros (desviación >35%). ¿Confirmas energía/macros de la etiqueta?"
                )

    return questions


async def ocr_text_from_images(photo_files: list[UploadFile]) -> str:
    if not photo_files or pytesseract is None:
        return ""

    settings = get_settings()
    chunks: list[str] = []
    for photo in photo_files:
        raw = await photo.read()
        if not raw:
            continue
        try:
            image = Image.open(BytesIO(raw)).convert("RGB")
            text = pytesseract.image_to_string(image, lang=settings.ocr_lang)
            if text:
                chunks.append(text)
        except Exception:
            # OCR failures are surfaced as follow-up questions instead of hard errors.
            continue

    return "\n".join(chunks).strip()


def nutrients_for_quantity(product: Product, quantity_g: float) -> dict[str, float]:
    if quantity_g <= 0:
        raise IntakeComputationError("quantity_g debe ser mayor que cero")

    if product.nutrition_basis in {NutritionBasis.per_100g, NutritionBasis.per_100ml}:
        factor = quantity_g / 100.0
    elif product.nutrition_basis == NutritionBasis.per_serving:
        if not product.serving_size_g:
            raise IntakeComputationError("El producto no tiene serving_size_g para calcular por porción")
        factor = quantity_g / product.serving_size_g
    else:
        raise IntakeComputationError("nutrition_basis inválido")

    def amount(value: float | None) -> float:
        return round((value or 0.0) * factor, 2)

    return {
        "kcal": amount(product.kcal),
        "protein_g": amount(product.protein_g),
        "fat_g": amount(product.fat_g),
        "sat_fat_g": amount(product.sat_fat_g),
        "carbs_g": amount(product.carbs_g),
        "sugars_g": amount(product.sugars_g),
        "fiber_g": amount(product.fiber_g),
        "salt_g": amount(product.salt_g),
    }


def quantity_from_method(
    *,
    product: Product,
    method: str,
    quantity_g: float | None,
    quantity_units: float | None,
    percent_pack: float | None,
) -> float:
    if method == "grams":
        if quantity_g is None:
            raise IntakeComputationError("quantity_g es requerido para method=grams")
        return quantity_g

    if method == "units":
        if quantity_units is None:
            raise IntakeComputationError("quantity_units es requerido para method=units")
        if not product.serving_size_g:
            raise IntakeComputationError("Producto sin serving_size_g para convertir unidades")
        return quantity_units * product.serving_size_g

    if method == "percent_pack":
        if percent_pack is None:
            raise IntakeComputationError("percent_pack es requerido para method=percent_pack")
        if not product.net_weight_g:
            raise IntakeComputationError("Producto sin net_weight_g para convertir porcentaje de paquete")
        return (percent_pack / 100.0) * product.net_weight_g

    raise IntakeComputationError(f"method inválido: {method}")


def zero_nutrients() -> dict[str, float]:
    return {field: 0.0 for field in NUTRIENT_FIELDS}


def sum_nutrients(acc: dict[str, float], current: dict[str, float]) -> dict[str, float]:
    return {key: round(acc.get(key, 0.0) + current.get(key, 0.0), 2) for key in NUTRIENT_FIELDS}


def remaining_from_goal(goal: dict[str, float], consumed: dict[str, float]) -> dict[str, float]:
    return {
        "kcal": round(goal["kcal"] - consumed["kcal"], 2),
        "protein_g": round(goal["protein_g"] - consumed["protein_g"], 2),
        "fat_g": round(goal["fat_g"] - consumed["fat_g"], 2),
        "sat_fat_g": 0.0,
        "carbs_g": round(goal["carbs_g"] - consumed["carbs_g"], 2),
        "sugars_g": 0.0,
        "fiber_g": 0.0,
        "salt_g": 0.0,
    }


def sanitize_numeric_values(data: dict[str, Any]) -> dict[str, Any]:
    sanitized = data.copy()
    for field in NUTRIENT_FIELDS + ["serving_size_g", "net_weight_g"]:
        value = sanitized.get(field)
        if value is None:
            continue
        sanitized[field] = max(_to_float(value) or 0.0, 0.0)

    # Enforce sensible ordering in case OCR swaps values.
    if (
        sanitized.get("sat_fat_g") is not None
        and sanitized.get("fat_g") is not None
        and sanitized["sat_fat_g"] > sanitized["fat_g"]
    ):
        sanitized["sat_fat_g"] = sanitized["fat_g"]

    if (
        sanitized.get("sugars_g") is not None
        and sanitized.get("carbs_g") is not None
        and sanitized["sugars_g"] > sanitized["carbs_g"]
    ):
        sanitized["sugars_g"] = sanitized["carbs_g"]

    if sanitized.get("kcal") is not None and math.isnan(float(sanitized["kcal"])):
        sanitized["kcal"] = None

    return sanitized

from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings
from app.models import NutritionBasis

CRITICAL_FIELDS = ["kcal", "protein_g", "fat_g", "carbs_g"]


class OpenFoodFactsClientError(RuntimeError):
    pass


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _basis_from_nutriments(nutriments: dict[str, Any]) -> NutritionBasis | None:
    if any(key.endswith("_100g") for key in nutriments):
        return NutritionBasis.per_100g
    if any(key.endswith("_100ml") for key in nutriments):
        return NutritionBasis.per_100ml
    if any(key.endswith("_serving") for key in nutriments):
        return NutritionBasis.per_serving
    return None


def _pick(nutriments: dict[str, Any], base_key: str, basis: NutritionBasis | None) -> float | None:
    keys: list[str] = []
    if basis == NutritionBasis.per_100g:
        keys = [f"{base_key}_100g"]
    elif basis == NutritionBasis.per_100ml:
        keys = [f"{base_key}_100ml"]
    elif basis == NutritionBasis.per_serving:
        keys = [f"{base_key}_serving"]

    keys.extend([base_key, f"{base_key}_value"])

    for key in keys:
        value = _to_float(nutriments.get(key))
        if value is not None:
            return value
    return None


def extract_product_from_openfoodfacts_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("status") != 1:
        return None

    product = payload.get("product") or {}
    nutriments = product.get("nutriments") or {}
    basis = _basis_from_nutriments(nutriments)

    extracted = {
        "barcode": product.get("code"),
        "name": product.get("product_name") or "Producto sin nombre",
        "brand": (product.get("brands") or "").split(",")[0].strip() or None,
        "image_url": product.get("image_front_url") or product.get("image_url"),
        "nutrition_basis": basis,
        "serving_size_g": _to_float(product.get("serving_quantity")),
        "net_weight_g": _to_float(product.get("product_quantity")),
        "kcal": _pick(nutriments, "energy-kcal", basis),
        "protein_g": _pick(nutriments, "proteins", basis),
        "fat_g": _pick(nutriments, "fat", basis),
        "sat_fat_g": _pick(nutriments, "saturated-fat", basis),
        "carbs_g": _pick(nutriments, "carbohydrates", basis),
        "sugars_g": _pick(nutriments, "sugars", basis),
        "fiber_g": _pick(nutriments, "fiber", basis),
        "salt_g": _pick(nutriments, "salt", basis),
    }

    return extracted


def missing_critical_fields(nutrition: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if nutrition.get("nutrition_basis") is None:
        missing.append("nutrition_basis")
    for key in CRITICAL_FIELDS:
        if nutrition.get(key) is None:
            missing.append(key)
    return missing


async def fetch_openfoodfacts_product(ean: str) -> dict[str, Any] | None:
    settings = get_settings()
    url = f"{settings.openfoodfacts_base_url}/product/{ean}.json"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise OpenFoodFactsClientError(f"OpenFoodFacts request failed: {exc}") from exc

    payload = response.json()
    return extract_product_from_openfoodfacts_payload(payload)

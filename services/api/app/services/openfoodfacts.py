from __future__ import annotations

import re
import unicodedata
from typing import Any

import httpx

from app.config import get_settings
from app.models import NutritionBasis

CRITICAL_FIELDS = ["kcal", "protein_g", "fat_g", "carbs_g"]
# Keep OFF fallback responsive; local DB is primary source.
OFF_TIMEOUT = httpx.Timeout(8.0, connect=2.8)
OFF_HEADERS = {
    "User-Agent": "nutri-tracker/0.1 (+https://github.com/nutri-tracker)",
}
OFF_FALLBACK_BASE_URLS = (
    "https://es.openfoodfacts.org/api/v2",
    "https://fr.openfoodfacts.org/api/v2",
    "https://world.openfoodfacts.org/api/v2",
)
SEARCH_FIELDS = ",".join(
    [
        "code",
        "product_name",
        "generic_name",
        "brands",
        "brands_tags",
        "countries",
        "countries_tags",
        "lang",
        "categories",
        "categories_tags",
        "image_front_url",
        "image_url",
        "serving_quantity",
        "product_quantity",
        "nutriments",
    ]
)


class OpenFoodFactsClientError(RuntimeError):
    pass


def _normalize_search_text(value: str) -> str:
    lowered = value.strip().lower()
    folded = unicodedata.normalize("NFKD", lowered)
    without_accents = "".join(char for char in folded if not unicodedata.combining(char))
    compact = re.sub(r"[^a-z0-9]+", " ", without_accents)
    return re.sub(r"\s+", " ", compact).strip()


def _brand_tag(value: str) -> str | None:
    normalized = _normalize_search_text(value)
    if not normalized:
        return None
    tag = normalized.replace(" ", "-")
    return tag or None


def _off_match_score(query: str, candidate: dict[str, Any]) -> float:
    q = _normalize_search_text(query)
    if not q:
        return 0.0

    name = _normalize_search_text(str(candidate.get("name") or ""))
    brand = _normalize_search_text(str(candidate.get("brand") or ""))
    lang = _normalize_search_text(str(candidate.get("lang") or ""))
    countries_tags_raw = candidate.get("countries_tags") or []
    if isinstance(countries_tags_raw, str):
        countries_tags = [_normalize_search_text(countries_tags_raw)]
    elif isinstance(countries_tags_raw, list):
        countries_tags = [_normalize_search_text(str(item)) for item in countries_tags_raw if item]
    else:
        countries_tags = []
    countries_text = _normalize_search_text(str(candidate.get("countries") or ""))
    score = 0.0

    if name == q:
        score += 900.0
    elif name.startswith(q):
        score += 520.0
    elif q in name:
        score += 260.0

    if brand == q:
        score += 700.0
    elif brand.startswith(q):
        score += 420.0
    elif q in brand:
        score += 240.0

    query_tokens = [token for token in q.split(" ") if token]
    if query_tokens:
        merged = f"{name} {brand}".strip()
        if merged and all(token in merged for token in query_tokens):
            score += 180.0
        for token in query_tokens:
            if token in name:
                score += 70.0
            if token in brand:
                score += 92.0

    if candidate.get("kcal") is not None:
        score += 8.0
    else:
        score -= 45.0

    # Country relevance for Spanish users.
    has_spain = any(
        tag in {"en:spain", "es:espana", "es:españa", "spain", "espana", "españa"} for tag in countries_tags
    ) or (
        "spain" in countries_text or "españa" in countries_text or "espana" in countries_text
    )
    eu_nearby_tags = {
        "en:france",
        "en:portugal",
        "en:italy",
        "en:germany",
        "en:belgium",
        "en:netherlands",
        "en:ireland",
        "en:austria",
        "en:poland",
        "en:sweden",
        "en:denmark",
    }
    has_nearby_eu = any(tag in eu_nearby_tags for tag in countries_tags)
    has_any_country = bool(countries_tags) or bool(countries_text)
    if has_spain:
        score += 260.0
    elif has_nearby_eu:
        score += 120.0
    elif has_any_country:
        score -= 70.0

    # Language relevance boost.
    if lang.startswith("es"):
        score += 80.0
    elif lang.startswith(("fr", "pt", "it")):
        score += 24.0
    elif lang:
        score -= 20.0

    # Penalize odd names and weak nutrition.
    alpha_ratio = (sum(1 for char in name if "a" <= char <= "z") / max(len(name), 1)) if name else 0.0
    if alpha_ratio < 0.55:
        score -= 55.0
    if not candidate.get("protein_g") and not candidate.get("fat_g") and not candidate.get("carbs_g"):
        score -= 30.0

    return score


def _candidate_base_urls(primary_base_url: str) -> list[str]:
    normalized_primary = primary_base_url.rstrip("/")
    candidates = [normalized_primary, *OFF_FALLBACK_BASE_URLS]
    deduped: list[str] = []
    for base_url in candidates:
        normalized = base_url.rstrip("/")
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


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


def _extract_product_entry(product: dict[str, Any]) -> dict[str, Any] | None:
    code = str(product.get("code") or "").strip()
    if not code:
        return None

    nutriments = product.get("nutriments") or {}
    basis = _basis_from_nutriments(nutriments)
    name = (
        str(product.get("product_name") or "").strip()
        or str(product.get("generic_name") or "").strip()
        or "Producto sin nombre"
    )

    return {
        "barcode": code,
        "name": name,
        "brand": (product.get("brands") or "").split(",")[0].strip() or None,
        "brands_tags": product.get("brands_tags") if isinstance(product.get("brands_tags"), list) else [],
        "countries": product.get("countries"),
        "countries_tags": product.get("countries_tags") if isinstance(product.get("countries_tags"), list) else [],
        "lang": product.get("lang"),
        "categories": product.get("categories"),
        "categories_tags": product.get("categories_tags") if isinstance(product.get("categories_tags"), list) else [],
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


def extract_product_from_openfoodfacts_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("status") != 1:
        return None

    product = payload.get("product") or {}
    return _extract_product_entry(product)


def extract_products_from_openfoodfacts_search_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    products = payload.get("products")
    if not isinstance(products, list):
        return []

    extracted: list[dict[str, Any]] = []
    seen_barcodes: set[str] = set()
    for raw in products:
        if not isinstance(raw, dict):
            continue
        candidate = _extract_product_entry(raw)
        if not candidate:
            continue
        barcode = str(candidate.get("barcode") or "").strip()
        if not barcode or barcode in seen_barcodes:
            continue
        seen_barcodes.add(barcode)
        extracted.append(candidate)
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
    errors: list[str] = []

    for base_url in _candidate_base_urls(settings.openfoodfacts_base_url):
        url = f"{base_url}/product/{ean}.json"
        try:
            async with httpx.AsyncClient(timeout=OFF_TIMEOUT, headers=OFF_HEADERS) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            errors.append(f"{base_url}: {exc.__class__.__name__}")
            continue

        payload = response.json()
        return extract_product_from_openfoodfacts_payload(payload)

    raise OpenFoodFactsClientError(f"OpenFoodFacts request failed on all mirrors: {' | '.join(errors)}")


async def search_openfoodfacts_products(query: str, *, limit: int = 20) -> list[dict[str, Any]]:
    settings = get_settings()
    bounded_limit = max(1, min(limit, 20))
    errors: list[str] = []
    candidate_urls = _candidate_base_urls(settings.openfoodfacts_base_url)[:2]

    for base_url in candidate_urls:
        try:
            async with httpx.AsyncClient(timeout=OFF_TIMEOUT, headers=OFF_HEADERS) as client:
                url = f"{base_url}/search"
                base_params = {
                    "page_size": max(10, min(24, bounded_limit * 2)),
                    "page": 1,
                    "fields": SEARCH_FIELDS,
                    "search_simple": 1,
                }
                candidates: list[dict[str, Any]] = []
                tag = _brand_tag(query)

                response = await client.get(
                    url,
                    params={
                        **base_params,
                        "search_terms": query,
                    },
                )
                response.raise_for_status()
                payload = response.json()
                candidates.extend(extract_products_from_openfoodfacts_search_payload(payload))

                # Optional brand query only when text search was sparse.
                if tag and " " not in query.strip() and len(candidates) < max(6, bounded_limit):
                    try:
                        brand_response = await client.get(
                            url,
                            params={
                                **base_params,
                                "brands_tags": tag,
                            },
                        )
                        brand_response.raise_for_status()
                        brand_payload = brand_response.json()
                        candidates.extend(extract_products_from_openfoodfacts_search_payload(brand_payload))
                    except httpx.HTTPError:
                        pass
        except httpx.HTTPError as exc:
            errors.append(f"{base_url}: {exc.__class__.__name__}")
            continue

        deduped: list[dict[str, Any]] = []
        seen_barcodes: set[str] = set()
        for candidate in candidates:
            barcode = str(candidate.get("barcode") or "").strip()
            if not barcode or barcode in seen_barcodes:
                continue
            seen_barcodes.add(barcode)
            deduped.append(candidate)

        deduped.sort(key=lambda item: _off_match_score(query, item), reverse=True)
        return deduped[:bounded_limit]

    raise OpenFoodFactsClientError(f"OpenFoodFacts search request failed on all mirrors: {' | '.join(errors)}")

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlmodel import Session, select

from app.database import get_session
from app.models import DailyGoal, Intake, NutritionBasis, Product
from app.schemas import (
    DailyGoalUpsert,
    DaySummary,
    IntakeCreate,
    IntakeRead,
    LabelPhotoResponse,
    NutritionExtract,
    ProductLookupResponse,
    ProductRead,
)
from app.services.nutrition import (
    IntakeComputationError,
    coherence_questions,
    extract_nutrition_from_text,
    missing_critical_fields,
    nutrients_for_quantity,
    ocr_text_from_images,
    quantity_from_method,
    remaining_from_goal,
    sanitize_numeric_values,
    sum_nutrients,
    zero_nutrients,
)
from app.services.openfoodfacts import (
    OpenFoodFactsClientError,
    fetch_openfoodfacts_product,
)
from app.services.openfoodfacts import (
    missing_critical_fields as off_missing_critical_fields,
)

router = APIRouter()

EAN_PATTERN = re.compile(r"^\d{8,14}$")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/products/by_barcode/{ean}", response_model=ProductLookupResponse)
async def product_by_barcode(
    ean: str,
    session: Annotated[Session, Depends(get_session)],
) -> ProductLookupResponse:
    if not EAN_PATTERN.match(ean):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="EAN/UPC inválido")

    local = session.exec(select(Product).where(Product.barcode == ean)).first()
    if local:
        return ProductLookupResponse(source="local", product=ProductRead.model_validate(local))

    try:
        off_product = await fetch_openfoodfacts_product(ean)
    except OpenFoodFactsClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    if off_product is None:
        return ProductLookupResponse(
            source="not_found",
            message="Producto no encontrado en base local ni en OpenFoodFacts",
        )

    missing = off_missing_critical_fields(off_product)
    if missing:
        return ProductLookupResponse(
            source="openfoodfacts_incomplete",
            missing_fields=missing,
            message="OpenFoodFacts no trae nutrición suficiente. Captura foto de etiqueta.",
        )

    product = Product(
        barcode=ean,
        name=off_product["name"],
        brand=off_product.get("brand"),
        nutrition_basis=off_product["nutrition_basis"],
        serving_size_g=off_product.get("serving_size_g"),
        net_weight_g=off_product.get("net_weight_g"),
        kcal=off_product["kcal"],
        protein_g=off_product["protein_g"],
        fat_g=off_product["fat_g"],
        sat_fat_g=off_product.get("sat_fat_g"),
        carbs_g=off_product["carbs_g"],
        sugars_g=off_product.get("sugars_g"),
        fiber_g=off_product.get("fiber_g"),
        salt_g=off_product.get("salt_g"),
        data_confidence="openfoodfacts",
    )
    session.add(product)
    session.commit()
    session.refresh(product)

    return ProductLookupResponse(
        source="openfoodfacts_imported",
        product=ProductRead.model_validate(product),
    )


@router.post("/products/from_label_photo", response_model=LabelPhotoResponse)
async def create_product_from_label_photo(
    session: Annotated[Session, Depends(get_session)],
    barcode: Annotated[str | None, Form()] = None,
    name: Annotated[str | None, Form()] = None,
    brand: Annotated[str | None, Form()] = None,
    nutrition_basis: Annotated[NutritionBasis | None, Form()] = None,
    serving_size_g: Annotated[float | None, Form()] = None,
    net_weight_g: Annotated[float | None, Form()] = None,
    label_text: Annotated[str | None, Form()] = None,
    photos: Annotated[list[UploadFile] | None, File()] = None,
) -> LabelPhotoResponse:
    photo_files = photos or []
    extracted_text = (label_text or "").strip()
    if not extracted_text and photo_files:
        extracted_text = await ocr_text_from_images(photo_files)

    extracted = extract_nutrition_from_text(extracted_text, basis_hint=nutrition_basis)
    extracted["serving_size_g"] = extracted.get("serving_size_g") or serving_size_g

    missing_fields = missing_critical_fields(extracted)
    questions = coherence_questions(extracted)

    if not extracted_text:
        questions.insert(
            0,
            "No pude extraer texto de la etiqueta. Sube una foto más nítida o pega el texto OCR.",
        )

    if not name:
        questions.append("Falta el nombre del producto.")

    if missing_fields:
        for field in missing_fields:
            questions.append(f"Falta {field}. ¿Puedes confirmarlo manualmente?")

    nutrition_payload = NutritionExtract.model_validate(extracted)

    if missing_fields or not name:
        return LabelPhotoResponse(
            created=False,
            extracted=nutrition_payload,
            missing_fields=missing_fields,
            questions=questions,
        )

    payload = sanitize_numeric_values({**extracted, "net_weight_g": net_weight_g})

    existing = None
    if barcode:
        existing = session.exec(select(Product).where(Product.barcode == barcode)).first()

    if existing:
        existing.name = name
        existing.brand = brand
        existing.nutrition_basis = payload["nutrition_basis"]
        existing.serving_size_g = payload.get("serving_size_g")
        existing.net_weight_g = payload.get("net_weight_g")
        existing.kcal = payload["kcal"]
        existing.protein_g = payload["protein_g"]
        existing.fat_g = payload["fat_g"]
        existing.sat_fat_g = payload.get("sat_fat_g")
        existing.carbs_g = payload["carbs_g"]
        existing.sugars_g = payload.get("sugars_g")
        existing.fiber_g = payload.get("fiber_g")
        existing.salt_g = payload.get("salt_g")
        existing.data_confidence = "label_photo"
        product = existing
    else:
        product = Product(
            barcode=barcode,
            name=name,
            brand=brand,
            nutrition_basis=payload["nutrition_basis"],
            serving_size_g=payload.get("serving_size_g"),
            net_weight_g=payload.get("net_weight_g"),
            kcal=payload["kcal"],
            protein_g=payload["protein_g"],
            fat_g=payload["fat_g"],
            sat_fat_g=payload.get("sat_fat_g"),
            carbs_g=payload["carbs_g"],
            sugars_g=payload.get("sugars_g"),
            fiber_g=payload.get("fiber_g"),
            salt_g=payload.get("salt_g"),
            data_confidence="label_photo",
        )
        session.add(product)

    session.commit()
    session.refresh(product)

    return LabelPhotoResponse(
        created=True,
        product=ProductRead.model_validate(product),
        extracted=nutrition_payload,
        missing_fields=[],
        questions=questions,
    )


@router.post("/intakes", response_model=IntakeRead)
def create_intake(
    payload: IntakeCreate,
    session: Annotated[Session, Depends(get_session)],
) -> IntakeRead:
    product = session.get(Product, payload.product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Producto no encontrado")

    try:
        resolved_quantity_g = quantity_from_method(
            product=product,
            method=payload.method.value,
            quantity_g=payload.quantity_g,
            quantity_units=payload.quantity_units,
            percent_pack=payload.percent_pack,
        )
    except IntakeComputationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    intake = Intake(
        product_id=payload.product_id,
        quantity_g=resolved_quantity_g,
        quantity_units=payload.quantity_units,
        percent_pack=payload.percent_pack,
        method=payload.method,
        created_at=payload.created_at or datetime.now(UTC),
    )
    session.add(intake)
    session.commit()
    session.refresh(intake)

    nutrients = nutrients_for_quantity(product, resolved_quantity_g)

    return IntakeRead(
        id=intake.id,
        product_id=intake.product_id,
        method=intake.method,
        quantity_g=intake.quantity_g,
        quantity_units=intake.quantity_units,
        percent_pack=intake.percent_pack,
        created_at=intake.created_at,
        nutrients=nutrients,
    )


@router.get("/days/{day}/summary", response_model=DaySummary)
def day_summary(
    day: date,
    session: Annotated[Session, Depends(get_session)],
) -> DaySummary:
    start_dt = datetime.combine(day, time.min).replace(tzinfo=UTC)
    end_dt = datetime.combine(day + timedelta(days=1), time.min).replace(tzinfo=UTC)

    statement = select(Intake).where(Intake.created_at >= start_dt).where(Intake.created_at < end_dt)
    intakes = session.exec(statement).all()

    consumed = zero_nutrients()
    intake_rows: list[IntakeRead] = []

    for intake in intakes:
        product = session.get(Product, intake.product_id)
        if not product or intake.quantity_g is None:
            continue
        nutrients = nutrients_for_quantity(product, intake.quantity_g)
        consumed = sum_nutrients(consumed, nutrients)
        intake_rows.append(
            IntakeRead(
                id=intake.id,
                product_id=intake.product_id,
                method=intake.method,
                quantity_g=intake.quantity_g,
                quantity_units=intake.quantity_units,
                percent_pack=intake.percent_pack,
                created_at=intake.created_at,
                nutrients=nutrients,
            )
        )

    goal = session.get(DailyGoal, day)
    goal_payload = None
    remaining = None

    if goal:
        goal_payload = DailyGoalUpsert(
            kcal_goal=goal.kcal_goal,
            protein_goal=goal.protein_goal,
            fat_goal=goal.fat_goal,
            carbs_goal=goal.carbs_goal,
        )
        remaining = remaining_from_goal(
            {
                "kcal": goal.kcal_goal,
                "protein_g": goal.protein_goal,
                "fat_g": goal.fat_goal,
                "carbs_g": goal.carbs_goal,
            },
            consumed,
        )

    return DaySummary(
        date=day,
        goal=goal_payload,
        consumed=consumed,
        remaining=remaining,
        intakes=intake_rows,
    )


@router.post("/goals/{day}", response_model=DailyGoalUpsert)
def upsert_daily_goal(
    day: date,
    payload: DailyGoalUpsert,
    session: Annotated[Session, Depends(get_session)],
) -> DailyGoalUpsert:
    existing = session.get(DailyGoal, day)
    if existing:
        existing.kcal_goal = payload.kcal_goal
        existing.protein_goal = payload.protein_goal
        existing.fat_goal = payload.fat_goal
        existing.carbs_goal = payload.carbs_goal
    else:
        existing = DailyGoal(
            date=day,
            kcal_goal=payload.kcal_goal,
            protein_goal=payload.protein_goal,
            fat_goal=payload.fat_goal,
            carbs_goal=payload.carbs_goal,
        )
        session.add(existing)

    session.commit()
    return payload

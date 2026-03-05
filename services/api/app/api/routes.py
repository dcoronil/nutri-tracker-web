from __future__ import annotations

import json
import logging
import math
import re
import unicodedata
from datetime import UTC, date, datetime, time, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile, status
from sqlalchemy import Float, and_, case, cast, func, literal, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, desc, select
from starlette.datastructures import Headers

from app.config import get_settings
from app.database import get_session
from app.models import (
    BodyMeasurementLog,
    BodyProgressPhoto,
    BodyWeightLog,
    DailyGoal,
    Intake,
    IntakeMethod,
    MealPhotoAnalysis,
    NutritionBasis,
    PendingRegistration,
    Product,
    UserAccount,
    UserFavoriteProduct,
    UserProductPreference,
    UserProfile,
    WaterIntakeLog,
)
from app.schemas import (
    AuthResponse,
    AuthUser,
    BodyMeasurementLogCreate,
    BodyMeasurementLogRead,
    BodyProgressPhotoCreate,
    BodyProgressPhotoRead,
    BodySummaryResponse,
    BodyTrendPoint,
    BodyWeightLogCreate,
    BodyWeightLogRead,
    CalendarDayEntry,
    CalendarMonthResponse,
    CommunityFoodCreate,
    CommunityFoodReportResponse,
    DailyGoalResponse,
    DailyGoalUpsert,
    DaySummary,
    FavoriteProductRead,
    FavoriteProductToggleResponse,
    FoodSearchItem,
    FoodSearchResponse,
    GoalFeedback,
    IntakeCreate,
    IntakeDeleteResponse,
    IntakeRead,
    LabelPhotoResponse,
    LoginRequest,
    MealEstimateQuestionsResponse,
    MealPhotoEstimateResponse,
    MeResponse,
    NutritionExtract,
    ProductCorrectionResponse,
    ProductDataQualityResponse,
    ProductLookupResponse,
    ProductPreference,
    ProductRead,
    ProfileAnalysisResponse,
    ProfileInput,
    ProfileRead,
    RegisterRequest,
    RegisterResponse,
    RepeatIntakesResponse,
    ResendCodeRequest,
    UserAIKeyDeleteResponse,
    UserAIKeyStatusResponse,
    UserAIKeyTestRequest,
    UserAIKeyTestResponse,
    UserAIKeyUpsertRequest,
    UsernameAvailabilityResponse,
    VerifyRequest,
    WaterLogCreate,
    WaterLogRead,
    WidgetTodaySummaryResponse,
)
from app.services.ai_keys import (
    AIKeyValidationError,
    decrypt_api_key,
    encrypt_api_key,
    mask_key_for_display,
    normalize_provider_or_default,
    test_provider_api_key,
    validate_api_key_shape,
)
from app.services.auth import (
    AuthTokenError,
    create_access_token,
    create_verification_code,
    hash_otp_code,
    hash_password,
    validate_email_format,
    verify_access_token,
    verify_otp_code,
    verify_password,
)
from app.services.body_metrics import (
    bmi,
    bmi_category,
    body_fat_category,
    body_fat_percent,
    coach_hints,
    goal_feedback,
    recommended_goals,
    rolling_weight_points,
    should_prompt_weight_log,
    suggested_kcal_adjustment,
    weekly_weight_change,
)
from app.services.email import EmailSendError, send_verification_email
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
    search_openfoodfacts_products,
)
from app.services.openfoodfacts import (
    missing_critical_fields as off_missing_critical_fields,
)
from app.services.rate_limit import client_key_from_ip, rate_limiter
from app.services.vision_ai import (
    VisionAIError,
    estimate_meal_with_ai,
    extract_label_nutrition_with_ai,
    generate_meal_questions_with_ai,
)

router = APIRouter()
logger = logging.getLogger(__name__)

EAN_PATTERN = re.compile(r"^\d{8,14}$")
MONTH_PATTERN = re.compile(r"^\d{4}-\d{2}$")
USERNAME_PATTERN = re.compile(r"^[a-z0-9._]{3,32}$")
OTP_MAX_ATTEMPTS = 5
MAX_MEAL_PHOTOS = 3


def _meal_analysis_storage_root() -> Path:
    storage_root = Path(get_settings().meal_analysis_storage_dir).expanduser()
    storage_root.mkdir(parents=True, exist_ok=True)
    return storage_root


def _guess_photo_extension(filename: str | None, content_type: str | None) -> str:
    lowered_name = (filename or "").lower()
    lowered_type = (content_type or "").lower()
    if lowered_name.endswith(".png") or "png" in lowered_type:
        return ".png"
    if lowered_name.endswith(".webp") or "webp" in lowered_type:
        return ".webp"
    return ".jpg"


def _safe_photo_content_type(content_type: str | None, extension: str) -> str:
    if content_type and content_type.startswith("image/"):
        return content_type
    if extension == ".png":
        return "image/png"
    if extension == ".webp":
        return "image/webp"
    return "image/jpeg"


def _parse_analysis_meta(raw_meta: str | None) -> list[dict[str, str]]:
    if not raw_meta:
        return []
    try:
        parsed = json.loads(raw_meta)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []

    normalized: list[dict[str, str]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "")).strip()
        if not path:
            continue
        normalized.append(
            {
                "path": path,
                "filename": str(item.get("filename") or Path(path).name),
                "content_type": str(item.get("content_type") or "image/jpeg"),
            }
        )
    return normalized


def _remove_meal_analysis_files(raw_meta: str | None) -> None:
    meta = _parse_analysis_meta(raw_meta)
    if not meta:
        return

    parent: Path | None = None
    for item in meta:
        path = Path(item["path"])
        try:
            if path.exists():
                path.unlink()
        except OSError:
            logger.warning("Could not delete cached analysis file: %s", path)
        if parent is None:
            parent = path.parent

    if parent is not None:
        try:
            if parent.exists():
                parent.rmdir()
        except OSError:
            # Ignore non-empty or already removed directories.
            pass


def _cleanup_expired_meal_analysis(session: Session, *, user_id: int | None = None) -> None:
    now = datetime.now(UTC)
    query = select(MealPhotoAnalysis).where(MealPhotoAnalysis.expires_at <= now)
    if user_id is not None:
        query = query.where(MealPhotoAnalysis.user_id == user_id)
    expired = session.exec(query).all()
    if not expired:
        return

    for analysis in expired:
        _remove_meal_analysis_files(analysis.image_meta_json)
        session.delete(analysis)
    session.commit()


async def _store_meal_analysis(
    *,
    session: Session,
    user_id: int,
    photo_files: list[UploadFile],
) -> MealPhotoAnalysis:
    analysis_id = uuid4().hex
    root = _meal_analysis_storage_root() / analysis_id
    root.mkdir(parents=True, exist_ok=True)

    metadata: list[dict[str, str]] = []
    for index, photo in enumerate(photo_files):
        raw = await photo.read()
        await photo.seek(0)
        if not raw:
            continue
        extension = _guess_photo_extension(photo.filename, photo.content_type)
        filename = f"photo_{index + 1}{extension}"
        filepath = root / filename
        filepath.write_bytes(raw)
        metadata.append(
            {
                "path": str(filepath),
                "filename": filename,
                "content_type": _safe_photo_content_type(photo.content_type, extension),
            }
        )

    if not metadata:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Adjunta al menos una foto.")

    expires_at = datetime.now(UTC) + timedelta(minutes=max(1, get_settings().meal_analysis_ttl_minutes))
    analysis = MealPhotoAnalysis(
        id=analysis_id,
        user_id=user_id,
        image_meta_json=json.dumps(metadata, ensure_ascii=True),
        expires_at=expires_at,
    )
    session.add(analysis)
    session.commit()
    session.refresh(analysis)
    return analysis


def _load_meal_analysis_files(
    *,
    session: Session,
    analysis_id: str,
    user_id: int,
) -> tuple[list[UploadFile], MealPhotoAnalysis]:
    analysis = session.get(MealPhotoAnalysis, analysis_id)
    if not analysis or analysis.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Análisis temporal no encontrado.")

    if _to_utc(analysis.expires_at) <= datetime.now(UTC):
        _remove_meal_analysis_files(analysis.image_meta_json)
        session.delete(analysis)
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="El análisis temporal expiró. Sube las fotos otra vez.",
        )

    uploads: list[UploadFile] = []
    for item in _parse_analysis_meta(analysis.image_meta_json):
        path = Path(item["path"])
        if not path.exists():
            continue
        file_handle = path.open("rb")
        headers = Headers({"content-type": item.get("content_type", "image/jpeg")})
        uploads.append(UploadFile(file=file_handle, filename=item.get("filename") or path.name, headers=headers))

    if not uploads:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="No se encontraron fotos para este análisis. Sube las fotos de nuevo.",
        )
    if len(uploads) > MAX_MEAL_PHOTOS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Máximo {MAX_MEAL_PHOTOS} fotos por estimación.",
        )
    return uploads, analysis


async def _close_upload_files(upload_files: list[UploadFile]) -> None:
    for upload in upload_files:
        try:
            await upload.close()
        except Exception:
            continue


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _age_from_birth_date(birth_date: date | None, *, today: date | None = None) -> int | None:
    if birth_date is None:
        return None
    current_day = today or datetime.now(UTC).date()
    years = current_day.year - birth_date.year
    if (current_day.month, current_day.day) < (birth_date.month, birth_date.day):
        years -= 1
    return max(years, 0)


def _rate_limit(request: Request, *, scope: str, limit: int, window_seconds: int, key_suffix: str = "") -> None:
    client_ip = request.headers.get("x-forwarded-for")
    if not client_ip and request.client:
        client_ip = request.client.host
    client_key = client_key_from_ip(client_ip)
    full_key = f"{client_key}:{key_suffix}" if key_suffix else client_key
    rate_limiter.check(scope=scope, key=full_key, limit=limit, window_seconds=window_seconds)


def _auth_user(user: UserAccount) -> AuthUser:
    return AuthUser(
        id=user.id,
        email=user.email,
        username=user.username,
        sex=user.sex,
        birth_date=user.birth_date,
        email_verified=user.email_verified,
        onboarding_completed=user.onboarding_completed,
    )


def _profile_to_read(profile: UserProfile, user: UserAccount | None = None) -> ProfileRead:
    effective_age = profile.age
    effective_sex = profile.sex
    if user is not None:
        effective_age = _age_from_birth_date(user.birth_date) if user.birth_date else profile.age
        effective_sex = user.sex

    bmi_value = profile.bmi if profile.bmi is not None else bmi(profile.weight_kg, profile.height_cm)
    bmi_label, bmi_color = bmi_category(bmi_value)

    fat_value = profile.body_fat_percent
    if fat_value is None:
        profile_for_fat = UserProfile.model_validate(profile.model_dump())
        profile_for_fat.sex = effective_sex
        fat_value = body_fat_percent(profile_for_fat)
    fat_label, fat_color = body_fat_category(fat_value, effective_sex)

    return ProfileRead(
        weight_kg=profile.weight_kg,
        height_cm=profile.height_cm,
        age=effective_age,
        sex=effective_sex,
        activity_level=profile.activity_level,
        goal_type=profile.goal_type,
        waist_cm=profile.waist_cm,
        neck_cm=profile.neck_cm,
        hip_cm=profile.hip_cm,
        chest_cm=profile.chest_cm,
        arm_cm=profile.arm_cm,
        thigh_cm=profile.thigh_cm,
        bmi=bmi_value,
        bmi_category=bmi_label,
        bmi_color=bmi_color,
        body_fat_percent=fat_value,
        body_fat_category=fat_label,
        body_fat_color=fat_color,
    )


def _load_profile(session: Session, user_id: int) -> UserProfile | None:
    return session.get(UserProfile, user_id)


def _load_profile_or_404(session: Session, user_id: int) -> UserProfile:
    profile = _load_profile(session, user_id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return profile


def _ai_key_status(user: UserAccount) -> UserAIKeyStatusResponse:
    configured = bool(user.ai_api_key_encrypted)
    provider = None
    key_hint = None

    if configured:
        try:
            provider = normalize_provider_or_default(user.ai_provider)
            key_hint = mask_key_for_display(decrypt_api_key(user.ai_api_key_encrypted or ""))
        except AIKeyValidationError:
            provider = normalize_provider_or_default(user.ai_provider)
            key_hint = None

    return UserAIKeyStatusResponse(
        configured=configured,
        provider=provider,
        key_hint=key_hint,
    )


def _user_ai_provider_and_key(
    user: UserAccount,
    *,
    required: bool,
) -> tuple[str, str] | None:
    if not user.ai_api_key_encrypted:
        if required:
            raise HTTPException(
                status_code=status.HTTP_428_PRECONDITION_REQUIRED,
                detail="Configura tu API key en Settings > IA para usar esta función.",
            )
        return None

    try:
        provider = normalize_provider_or_default(user.ai_provider)
        api_key = decrypt_api_key(user.ai_api_key_encrypted)
    except AIKeyValidationError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    if provider != "openai":
        if not required:
            return None
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Provider '{provider}' no implementado para visión todavía.",
        )

    return provider, api_key


async def _extract_label_payload(
    *,
    user: UserAccount,
    basis_hint: NutritionBasis | None,
    serving_size_g: float | None,
    net_weight_g: float | None,
    label_text: str | None,
    photos: list[UploadFile] | None,
) -> tuple[dict[str, object], list[str], list[str], Literal["ai_vision", "ocr_fallback"]]:
    photo_files = photos or []
    extracted_text = (label_text or "").strip()
    warnings: list[str] = []
    questions: list[str] = []
    analysis_method: Literal["ai_vision", "ocr_fallback"] = "ocr_fallback"
    extracted: dict[str, object] = {}

    ai_credentials = _user_ai_provider_and_key(user, required=False)
    if ai_credentials and (extracted_text or photo_files):
        _, api_key = ai_credentials
        try:
            ai_result = await extract_label_nutrition_with_ai(
                api_key=api_key,
                label_text=extracted_text,
                photo_files=photo_files,
                basis_hint=basis_hint,
            )
            extracted = dict(ai_result["nutrition"])  # type: ignore[arg-type]
            questions.extend(ai_result["questions"])  # type: ignore[arg-type]
            analysis_method = "ai_vision"
        except VisionAIError as exc:
            warnings.append(f"IA no disponible ({exc}). Se aplicó OCR clásico.")

    if analysis_method != "ai_vision":
        if user.ai_api_key_encrypted and not ai_credentials:
            warnings.append("Proveedor IA actual no soportado para visión; se aplicó OCR clásico.")
        if photo_files and not user.ai_api_key_encrypted:
            warnings.append("Sin API key configurada: se aplicó OCR clásico (menos preciso).")
        if not extracted_text and photo_files:
            extracted_text = await ocr_text_from_images(photo_files)
        extracted = extract_nutrition_from_text(extracted_text, basis_hint=basis_hint)

    extracted["serving_size_g"] = extracted.get("serving_size_g") or serving_size_g
    if net_weight_g is not None:
        extracted["net_weight_g"] = net_weight_g

    if not extracted_text and not photo_files:
        questions.append("No se recibió texto ni imagen de etiqueta.")

    questions.extend(coherence_questions(extracted))
    return extracted, questions, warnings, analysis_method


def _parse_meal_answers_json(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}

    if not isinstance(parsed, dict):
        return {}

    answers: dict[str, str] = {}
    for key, value in parsed.items():
        normalized_key = str(key).strip()
        normalized_value = str(value).strip()
        if normalized_key and normalized_value:
            answers[normalized_key] = normalized_value
    return answers


def _infer_portion_from_answers(answers: dict[str, str]) -> Literal["small", "medium", "large"] | None:
    joined = " ".join(answers.values()).lower()
    if "small" in joined or "peque" in joined:
        return "small"
    if "large" in joined or "grande" in joined:
        return "large"
    if "medium" in joined or "media" in joined or "mediana" in joined:
        return "medium"
    return None


def _infer_added_fats_from_answers(answers: dict[str, str]) -> bool | None:
    joined = " ".join(answers.values()).lower()
    if any(token in joined for token in {"no se", "no sé", "i don't know", "dont know", "unknown"}):
        return None
    if re.search(r"\b(yes|si|sí)\b", joined):
        return True
    if re.search(r"\bno\b", joined):
        return False
    return None


def _infer_quantity_note_from_answers(answers: dict[str, str]) -> str | None:
    quantity_parts = [
        value
        for key, value in answers.items()
        if any(token in key.lower() for token in {"qty", "quantity", "cantidad"})
    ]
    if not quantity_parts:
        quantity_parts = [value for value in answers.values() if re.search(r"\d", value)]
    joined = " | ".join(quantity_parts).strip()
    return joined or None


def _answers_to_context(answers: dict[str, str]) -> list[str]:
    return [f"{key}: {value}" for key, value in answers.items() if key and value]


def _resolve_meal_inputs(
    *,
    description: str | None,
    answers_json: str | None,
    portion_size: str | None,
    has_added_fats: bool | None,
    quantity_note: str | None,
    locale: Literal["es", "en"] = "es",
) -> tuple[str, Literal["small", "medium", "large"] | None, bool | None, str | None, list[str]]:
    answers = _parse_meal_answers_json(answers_json)
    normalized_portion: Literal["small", "medium", "large"] | None
    normalized_portion = (
        portion_size
        if portion_size in {"small", "medium", "large"}
        else _infer_portion_from_answers(answers)
    )
    normalized_added_fats = has_added_fats if has_added_fats is not None else _infer_added_fats_from_answers(answers)
    normalized_quantity_note = (quantity_note or "").strip() or _infer_quantity_note_from_answers(answers)
    answer_context = _answers_to_context(answers)

    resolved_description = (description or "").strip()
    if answer_context:
        answer_text = " | ".join(answer_context)
        resolved_description = f"{resolved_description}. {answer_text}" if resolved_description else answer_text

    if not resolved_description:
        resolved_description = "Estimated meal from photo" if locale == "en" else "Comida estimada por foto"

    return resolved_description, normalized_portion, normalized_added_fats, normalized_quantity_note, answer_context


def _normalize_locale(locale: str | None) -> Literal["es", "en"]:
    if locale and locale.strip().lower().startswith("en"):
        return "en"
    return "es"


def _apply_meal_preview_overrides(
    *,
    preview_nutrients: dict[str, float],
    override_kcal: float | None,
    override_protein_g: float | None,
    override_fat_g: float | None,
    override_carbs_g: float | None,
) -> dict[str, float]:
    output = dict(preview_nutrients)
    overrides = {
        "kcal": override_kcal,
        "protein_g": override_protein_g,
        "fat_g": override_fat_g,
        "carbs_g": override_carbs_g,
    }

    for key, value in overrides.items():
        if value is None:
            continue
        if not math.isfinite(value) or value < 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Valor inválido para {key}.",
            )
        output[key] = round(float(value), 2)

    return output


def get_current_user(
    session: Annotated[Session, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> UserAccount:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Authorization header")

    try:
        payload = verify_access_token(token)
    except AuthTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    user = session.get(UserAccount, payload["uid"])
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user


def get_verified_user(
    current_user: Annotated[UserAccount, Depends(get_current_user)],
) -> UserAccount:
    if not current_user.email_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Email is not verified")
    return current_user


def get_ready_user(
    current_user: Annotated[UserAccount, Depends(get_verified_user)],
) -> UserAccount:
    if not current_user.onboarding_completed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Onboarding not completed")
    return current_user


def _otp_response(email: str, username: str, message: str, code: str | None) -> RegisterResponse:
    settings = get_settings()
    debug_code = code if settings.expose_verification_code else None

    return RegisterResponse(
        user_id=0,
        email=email,
        username=username,
        email_verified=False,
        onboarding_completed=False,
        message=message,
        debug_verification_code=debug_code,
    )


def _normalize_username(raw: str) -> str:
    return raw.strip().lower()


def _validate_username(username: str) -> str:
    normalized = _normalize_username(username)
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nombre de usuario inválido. Usa 3-32 caracteres (a-z, 0-9, punto o guion bajo).",
        )
    return normalized


def _create_or_refresh_pending_registration(
    session: Session,
    *,
    email: str,
    username: str | None = None,
    password_hash: str | None = None,
    sex: Literal["male", "female", "other"] | None = None,
    birth_date: date | None = None,
) -> str:
    settings = get_settings()
    raw_code = create_verification_code()
    code_hash = hash_otp_code(raw_code)

    pending = session.exec(select(PendingRegistration).where(PendingRegistration.email == email)).first()
    if pending:
        if username:
            pending.username = username
        if password_hash:
            pending.password_hash = password_hash
        if sex:
            pending.sex = sex
        if birth_date:
            pending.birth_date = birth_date
        pending.code_hash = code_hash
        pending.expires_at = datetime.now(UTC) + timedelta(minutes=settings.verification_code_ttl_minutes)
        pending.attempts = 0
        pending.created_at = datetime.now(UTC)
        session.add(pending)
    else:
        if not password_hash:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending registration not found")
        if not username:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Username is required")
        pending = PendingRegistration(
            email=email,
            username=username,
            password_hash=password_hash,
            sex=sex or "other",
            birth_date=birth_date,
            code_hash=code_hash,
            expires_at=datetime.now(UTC) + timedelta(minutes=settings.verification_code_ttl_minutes),
            attempts=0,
        )
        session.add(pending)
    return raw_code


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/auth/register", response_model=RegisterResponse)
def register(
    payload: RegisterRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> RegisterResponse:
    _rate_limit(request, scope="auth_register", limit=8, window_seconds=60)
    email = payload.email.strip().lower()
    username = _validate_username(payload.username)
    age = _age_from_birth_date(payload.birth_date)
    if age is None or age < 13:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Debes tener al menos 13 años")
    if not validate_email_format(email):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid email")

    existing = session.exec(select(UserAccount).where(UserAccount.email == email)).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    existing_username = session.exec(select(UserAccount).where(UserAccount.username == username)).first()
    if existing_username:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already in use")

    pending_with_username = session.exec(
        select(PendingRegistration).where(PendingRegistration.username == username)
    ).first()
    if pending_with_username and pending_with_username.email != email:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already in use")

    try:
        password_hash = hash_password(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    raw_code = _create_or_refresh_pending_registration(
        session,
        email=email,
        username=username,
        password_hash=password_hash,
        sex=payload.sex,
        birth_date=payload.birth_date,
    )
    session.commit()

    settings = get_settings()
    message = "Account created. Verify your email with the code."
    try:
        sent = send_verification_email(email, raw_code)
    except EmailSendError as exc:
        logger.exception("SMTP send failed on register for %s", email)
        sent = False
        if settings.dev_email_mode:
            logger.info("DEV OTP fallback for %s: %s", email, raw_code)
        message = f"Cuenta creada, pero fallo enviando email de verificación (SMTP). Error: {exc}"

    if not sent:
        if not settings.smtp_host:
            message = "Cuenta creada. SMTP desactivado, usa el OTP de desarrollo."
        elif settings.dev_email_mode:
            message = "Cuenta creada. SMTP falló, usa OTP de desarrollo y revisa tu configuración SMTP."
        else:
            message = "Cuenta creada, pero no se pudo enviar el email de verificación. Revisa SMTP."

    return _otp_response(email, username, message, raw_code)


@router.get("/auth/check-username", response_model=UsernameAvailabilityResponse)
def check_username_availability(
    username: str,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> UsernameAvailabilityResponse:
    _rate_limit(request, scope="auth_username_check", limit=40, window_seconds=60)
    normalized = _normalize_username(username)

    if not normalized:
        return UsernameAvailabilityResponse(
            username="",
            available=False,
            reason="Escribe un nombre de usuario.",
        )

    if not USERNAME_PATTERN.fullmatch(normalized):
        return UsernameAvailabilityResponse(
            username=normalized,
            available=False,
            reason="Formato inválido. Usa 3-32 caracteres: letras minúsculas, números, punto o guion bajo.",
        )

    existing = session.exec(select(UserAccount).where(UserAccount.username == normalized)).first()
    if existing:
        return UsernameAvailabilityResponse(
            username=normalized,
            available=False,
            reason="Ese nombre de usuario ya está en uso.",
        )

    pending = session.exec(select(PendingRegistration).where(PendingRegistration.username == normalized)).first()
    if pending:
        return UsernameAvailabilityResponse(
            username=normalized,
            available=False,
            reason="Ese nombre de usuario está reservado por un registro pendiente.",
        )

    return UsernameAvailabilityResponse(username=normalized, available=True, reason=None)


@router.post("/auth/resend-code", response_model=RegisterResponse)
def resend_code(
    payload: ResendCodeRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> RegisterResponse:
    _rate_limit(request, scope="auth_resend", limit=8, window_seconds=60)
    email = payload.email.strip().lower()
    existing_user = session.exec(select(UserAccount).where(UserAccount.email == email)).first()
    if existing_user and existing_user.email_verified:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already verified")

    pending = session.exec(select(PendingRegistration).where(PendingRegistration.email == email)).first()
    if not pending:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending registration not found")

    raw_code = _create_or_refresh_pending_registration(session, email=email)
    session.commit()

    settings = get_settings()
    message = "A new verification code was generated."
    try:
        sent = send_verification_email(email, raw_code)
    except EmailSendError as exc:
        logger.exception("SMTP send failed on resend-code for %s", email)
        sent = False
        if settings.dev_email_mode:
            logger.info("DEV OTP fallback for %s: %s", email, raw_code)
        message = f"Código regenerado, pero fallo enviando email (SMTP). Error: {exc}"

    if not sent:
        if not settings.smtp_host:
            message = "SMTP desactivado, usa el OTP de desarrollo."
        elif settings.dev_email_mode:
            message = "SMTP falló, usa OTP de desarrollo y revisa tu configuración SMTP."
        else:
            message = "No se pudo enviar el código por email. Revisa SMTP."

    return _otp_response(email, pending.username, message, raw_code)


@router.post("/auth/verify", response_model=AuthResponse)
def verify_email(
    payload: VerifyRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> AuthResponse:
    _rate_limit(request, scope="auth_verify", limit=20, window_seconds=60)
    email = payload.email.strip().lower()
    pending = session.exec(select(PendingRegistration).where(PendingRegistration.email == email)).first()
    if not pending:
        existing_user = session.exec(select(UserAccount).where(UserAccount.email == email)).first()
        if existing_user and existing_user.email_verified:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already verified")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending registration not found")

    if pending.attempts >= OTP_MAX_ATTEMPTS:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many attempts")

    if _to_utc(pending.expires_at) < datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Verification code expired")

    if not verify_otp_code(payload.code, pending.code_hash):
        pending.attempts += 1
        session.add(pending)
        session.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification code")

    existing_user = session.exec(select(UserAccount).where(UserAccount.email == email)).first()
    if existing_user:
        session.delete(pending)
        session.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    if pending.birth_date is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Pending registration missing birth date",
        )

    user = UserAccount(
        email=email,
        username=pending.username,
        password_hash=pending.password_hash,
        sex=pending.sex,
        birth_date=pending.birth_date,
        email_verified=True,
        onboarding_completed=False,
    )
    session.add(user)
    session.flush()
    session.delete(pending)

    user.email_verified = True
    session.add(user)
    session.commit()

    token = create_access_token(user.id, user.email)
    profile = _load_profile(session, user.id)

    return AuthResponse(
        access_token=token,
        user=_auth_user(user),
        profile=_profile_to_read(profile, user) if profile else None,
    )


@router.post("/auth/login", response_model=AuthResponse)
def login(
    payload: LoginRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> AuthResponse:
    _rate_limit(request, scope="auth_login", limit=12, window_seconds=60)
    email = payload.email.strip().lower()
    user = session.exec(select(UserAccount).where(UserAccount.email == email)).first()
    if not user:
        pending = session.exec(select(PendingRegistration).where(PendingRegistration.email == email)).first()
        if pending:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Email pending verification. Complete code verification first.",
            )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not user.email_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Email is not verified")

    token = create_access_token(user.id, user.email)
    profile = _load_profile(session, user.id)

    return AuthResponse(
        access_token=token,
        user=_auth_user(user),
        profile=_profile_to_read(profile, user) if profile else None,
    )


@router.get("/me", response_model=MeResponse)
def me(
    current_user: Annotated[UserAccount, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
) -> MeResponse:
    profile = _load_profile(session, current_user.id)
    return MeResponse(
        user=_auth_user(current_user),
        profile=_profile_to_read(profile, current_user) if profile else None,
    )


@router.get("/user/ai-key/status", response_model=UserAIKeyStatusResponse)
def user_ai_key_status(
    current_user: Annotated[UserAccount, Depends(get_verified_user)],
) -> UserAIKeyStatusResponse:
    return _ai_key_status(current_user)


@router.post("/user/ai-key", response_model=UserAIKeyStatusResponse)
def upsert_user_ai_key(
    payload: UserAIKeyUpsertRequest,
    request: Request,
    current_user: Annotated[UserAccount, Depends(get_verified_user)],
    session: Annotated[Session, Depends(get_session)],
) -> UserAIKeyStatusResponse:
    _rate_limit(request, scope="ai_key_upsert", limit=15, window_seconds=60, key_suffix=str(current_user.id))
    try:
        provider = normalize_provider_or_default(payload.provider)
        validate_api_key_shape(provider, payload.api_key)
    except AIKeyValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    current_user.ai_provider = provider
    current_user.ai_api_key_encrypted = encrypt_api_key(payload.api_key.strip())
    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    return _ai_key_status(current_user)


@router.delete("/user/ai-key", response_model=UserAIKeyDeleteResponse)
def delete_user_ai_key(
    current_user: Annotated[UserAccount, Depends(get_verified_user)],
    session: Annotated[Session, Depends(get_session)],
) -> UserAIKeyDeleteResponse:
    current_user.ai_provider = None
    current_user.ai_api_key_encrypted = None
    session.add(current_user)
    session.commit()
    return UserAIKeyDeleteResponse(deleted=True)


@router.post("/user/ai-key/test", response_model=UserAIKeyTestResponse)
async def test_user_ai_key(
    payload: UserAIKeyTestRequest,
    request: Request,
    current_user: Annotated[UserAccount, Depends(get_verified_user)],
) -> UserAIKeyTestResponse:
    _rate_limit(request, scope="ai_key_test", limit=20, window_seconds=60, key_suffix=str(current_user.id))
    provider = normalize_provider_or_default(payload.provider or current_user.ai_provider)

    if payload.api_key and payload.api_key.strip():
        raw_key = payload.api_key.strip()
    elif current_user.ai_api_key_encrypted:
        try:
            raw_key = decrypt_api_key(current_user.ai_api_key_encrypted)
        except AIKeyValidationError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No API key configured")

    ok, message = await test_provider_api_key(provider, raw_key)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

    return UserAIKeyTestResponse(ok=True, provider=provider, message=message)


@router.post("/profile", response_model=ProfileRead)
def upsert_profile(
    payload: ProfileInput,
    current_user: Annotated[UserAccount, Depends(get_verified_user)],
    session: Annotated[Session, Depends(get_session)],
) -> ProfileRead:
    profile = _load_profile(session, current_user.id)
    derived_age = _age_from_birth_date(current_user.birth_date)

    if profile is None:
        profile = UserProfile(
            user_id=current_user.id,
            weight_kg=payload.weight_kg,
            height_cm=payload.height_cm,
            age=derived_age if derived_age is not None else payload.age,
            sex=current_user.sex,
            activity_level=payload.activity_level,
            goal_type=payload.goal_type,
            weekly_weight_goal_kg=payload.weekly_weight_goal_kg,
            waist_cm=payload.waist_cm,
            neck_cm=payload.neck_cm,
            hip_cm=payload.hip_cm,
            chest_cm=payload.chest_cm,
            arm_cm=payload.arm_cm,
            thigh_cm=payload.thigh_cm,
            updated_at=datetime.now(UTC),
        )
        session.add(profile)
    else:
        profile.weight_kg = payload.weight_kg
        if abs(profile.height_cm - payload.height_cm) > 1e-6:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Altura bloqueada: no se puede modificar tras crear la cuenta.",
            )
        profile.age = derived_age if derived_age is not None else profile.age
        profile.sex = current_user.sex
        profile.activity_level = payload.activity_level
        profile.goal_type = payload.goal_type
        profile.weekly_weight_goal_kg = payload.weekly_weight_goal_kg
        profile.waist_cm = payload.waist_cm
        profile.neck_cm = payload.neck_cm
        profile.hip_cm = payload.hip_cm
        profile.chest_cm = payload.chest_cm
        profile.arm_cm = payload.arm_cm
        profile.thigh_cm = payload.thigh_cm
        profile.updated_at = datetime.now(UTC)

    profile.bmi = bmi(profile.weight_kg, profile.height_cm)
    profile.body_fat_percent = body_fat_percent(profile)

    session.add(profile)
    session.commit()
    session.refresh(profile)
    return _profile_to_read(profile, current_user)


@router.get("/me/analysis", response_model=ProfileAnalysisResponse)
def me_analysis(
    current_user: Annotated[UserAccount, Depends(get_verified_user)],
    session: Annotated[Session, Depends(get_session)],
    day: date | None = None,
) -> ProfileAnalysisResponse:
    profile = _load_profile_or_404(session, current_user.id)
    recommended = recommended_goals(profile)
    weight_logs = session.exec(
        select(BodyWeightLog).where(BodyWeightLog.user_id == current_user.id).order_by(desc(BodyWeightLog.created_at))
    ).all()
    weekly_delta = weekly_weight_change(weight_logs)
    kcal_adjustment = suggested_kcal_adjustment(
        weekly_weight_delta=weekly_delta,
        goal_type=profile.goal_type,
    )

    target_day = day or datetime.now(UTC).date()
    goal = session.exec(
        select(DailyGoal).where(DailyGoal.user_id == current_user.id).where(DailyGoal.date == target_day)
    ).first()

    feedback = None
    if goal:
        feedback = GoalFeedback(
            **goal_feedback(
                profile,
                {
                    "kcal_goal": goal.kcal_goal,
                    "protein_goal": goal.protein_goal,
                    "fat_goal": goal.fat_goal,
                    "carbs_goal": goal.carbs_goal,
                },
                recommended,
            )
        )

    return ProfileAnalysisResponse(
        profile=_profile_to_read(profile, current_user),
        recommended_goal=DailyGoalUpsert(**recommended),
        goal_feedback_today=feedback,
        suggested_kcal_adjustment=kcal_adjustment,
        weekly_weight_goal_kg=profile.weekly_weight_goal_kg,
    )


def _preference_payload(pref: UserProductPreference | None) -> ProductPreference | None:
    if not pref:
        return None
    return ProductPreference(
        method=pref.method,
        quantity_g=pref.quantity_g,
        quantity_units=pref.quantity_units,
        percent_pack=pref.percent_pack,
    )


def _nutrition_extract_from_product(product: Product) -> NutritionExtract:
    return NutritionExtract(
        kcal=product.kcal,
        protein_g=product.protein_g,
        fat_g=product.fat_g,
        sat_fat_g=product.sat_fat_g,
        carbs_g=product.carbs_g,
        sugars_g=product.sugars_g,
        fiber_g=product.fiber_g,
        salt_g=product.salt_g,
        nutrition_basis=product.nutrition_basis,
        serving_size_g=product.serving_size_g,
    )


def _weight_log_to_read(record: BodyWeightLog) -> BodyWeightLogRead:
    return BodyWeightLogRead(
        id=record.id,
        weight_kg=record.weight_kg,
        note=record.note,
        created_at=record.created_at,
    )


def _measurement_log_to_read(record: BodyMeasurementLog) -> BodyMeasurementLogRead:
    return BodyMeasurementLogRead(
        id=record.id,
        waist_cm=record.waist_cm,
        neck_cm=record.neck_cm,
        hip_cm=record.hip_cm,
        chest_cm=record.chest_cm,
        arm_cm=record.arm_cm,
        thigh_cm=record.thigh_cm,
        created_at=record.created_at,
    )


def _water_log_to_read(record: WaterIntakeLog) -> WaterLogRead:
    return WaterLogRead(
        id=record.id,
        ml=record.ml,
        created_at=record.created_at,
    )


def _body_photo_to_read(record: BodyProgressPhoto) -> BodyProgressPhotoRead:
    return BodyProgressPhotoRead(
        id=record.id,
        image_url=record.image_url,
        note=record.note,
        is_private=record.is_private,
        created_at=record.created_at,
    )


@router.post("/body/weight-logs", response_model=BodyWeightLogRead)
def create_body_weight_log(
    payload: BodyWeightLogCreate,
    current_user: Annotated[UserAccount, Depends(get_verified_user)],
    session: Annotated[Session, Depends(get_session)],
) -> BodyWeightLogRead:
    created_at = payload.created_at or datetime.now(UTC)
    record = BodyWeightLog(
        user_id=current_user.id,
        weight_kg=payload.weight_kg,
        note=payload.note,
        created_at=created_at,
    )
    session.add(record)

    profile = _load_profile(session, current_user.id)
    if profile:
        profile.weight_kg = payload.weight_kg
        profile.age = _age_from_birth_date(current_user.birth_date) if current_user.birth_date else profile.age
        profile.sex = current_user.sex
        profile.bmi = bmi(profile.weight_kg, profile.height_cm)
        profile.body_fat_percent = body_fat_percent(profile)
        profile.updated_at = datetime.now(UTC)
        session.add(profile)

    session.commit()
    session.refresh(record)
    return _weight_log_to_read(record)


@router.get("/body/weight-logs", response_model=list[BodyWeightLogRead])
def list_body_weight_logs(
    current_user: Annotated[UserAccount, Depends(get_verified_user)],
    session: Annotated[Session, Depends(get_session)],
    limit: int = 120,
) -> list[BodyWeightLogRead]:
    bounded_limit = max(1, min(limit, 365))
    rows = session.exec(
        select(BodyWeightLog)
        .where(BodyWeightLog.user_id == current_user.id)
        .order_by(desc(BodyWeightLog.created_at))
        .limit(bounded_limit)
    ).all()
    return [_weight_log_to_read(row) for row in rows]


@router.post("/body/measurement-logs", response_model=BodyMeasurementLogRead)
def create_body_measurement_log(
    payload: BodyMeasurementLogCreate,
    current_user: Annotated[UserAccount, Depends(get_verified_user)],
    session: Annotated[Session, Depends(get_session)],
) -> BodyMeasurementLogRead:
    created_at = payload.created_at or datetime.now(UTC)
    record = BodyMeasurementLog(
        user_id=current_user.id,
        waist_cm=payload.waist_cm,
        neck_cm=payload.neck_cm,
        hip_cm=payload.hip_cm,
        chest_cm=payload.chest_cm,
        arm_cm=payload.arm_cm,
        thigh_cm=payload.thigh_cm,
        created_at=created_at,
    )
    session.add(record)

    profile = _load_profile(session, current_user.id)
    if profile:
        profile.age = _age_from_birth_date(current_user.birth_date) if current_user.birth_date else profile.age
        profile.sex = current_user.sex
        profile.waist_cm = payload.waist_cm
        profile.neck_cm = payload.neck_cm
        profile.hip_cm = payload.hip_cm
        profile.chest_cm = payload.chest_cm
        profile.arm_cm = payload.arm_cm
        profile.thigh_cm = payload.thigh_cm
        profile.body_fat_percent = body_fat_percent(profile)
        profile.updated_at = datetime.now(UTC)
        session.add(profile)

    session.commit()
    session.refresh(record)
    return _measurement_log_to_read(record)


@router.get("/body/measurement-logs", response_model=list[BodyMeasurementLogRead])
def list_body_measurement_logs(
    current_user: Annotated[UserAccount, Depends(get_verified_user)],
    session: Annotated[Session, Depends(get_session)],
    limit: int = 120,
) -> list[BodyMeasurementLogRead]:
    bounded_limit = max(1, min(limit, 365))
    rows = session.exec(
        select(BodyMeasurementLog)
        .where(BodyMeasurementLog.user_id == current_user.id)
        .order_by(desc(BodyMeasurementLog.created_at))
        .limit(bounded_limit)
    ).all()
    return [_measurement_log_to_read(row) for row in rows]


@router.post("/body/progress-photos", response_model=BodyProgressPhotoRead)
def create_body_progress_photo(
    payload: BodyProgressPhotoCreate,
    request: Request,
    current_user: Annotated[UserAccount, Depends(get_verified_user)],
    session: Annotated[Session, Depends(get_session)],
) -> BodyProgressPhotoRead:
    _rate_limit(request, scope="body_photo_create", limit=10, window_seconds=60, key_suffix=str(current_user.id))
    image_url = payload.image_url.strip()
    if not image_url:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="image_url is required")

    record = BodyProgressPhoto(
        user_id=current_user.id,
        image_url=image_url,
        note=(payload.note or "").strip() or None,
        is_private=payload.is_private,
        created_at=payload.created_at or datetime.now(UTC),
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return _body_photo_to_read(record)


@router.get("/body/progress-photos", response_model=list[BodyProgressPhotoRead])
def list_body_progress_photos(
    current_user: Annotated[UserAccount, Depends(get_verified_user)],
    session: Annotated[Session, Depends(get_session)],
    limit: int = 120,
) -> list[BodyProgressPhotoRead]:
    bounded_limit = max(1, min(limit, 365))
    rows = session.exec(
        select(BodyProgressPhoto)
        .where(BodyProgressPhoto.user_id == current_user.id)
        .order_by(desc(BodyProgressPhoto.created_at))
        .limit(bounded_limit)
    ).all()
    return [_body_photo_to_read(row) for row in rows]


@router.post("/water/logs", response_model=WaterLogRead)
def create_water_log(
    payload: WaterLogCreate,
    request: Request,
    current_user: Annotated[UserAccount, Depends(get_ready_user)],
    session: Annotated[Session, Depends(get_session)],
) -> WaterLogRead:
    _rate_limit(request, scope="water_create", limit=30, window_seconds=60, key_suffix=str(current_user.id))
    record = WaterIntakeLog(
        user_id=current_user.id,
        ml=payload.ml,
        created_at=payload.created_at or datetime.now(UTC),
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return _water_log_to_read(record)


@router.get("/water/logs", response_model=list[WaterLogRead])
def list_water_logs(
    current_user: Annotated[UserAccount, Depends(get_ready_user)],
    session: Annotated[Session, Depends(get_session)],
    day: date | None = None,
    limit: int = 240,
) -> list[WaterLogRead]:
    bounded_limit = max(1, min(limit, 1000))
    stmt = (
        select(WaterIntakeLog)
        .where(WaterIntakeLog.user_id == current_user.id)
        .order_by(desc(WaterIntakeLog.created_at))
    )
    if day:
        start_dt = datetime.combine(day, time.min).replace(tzinfo=UTC)
        end_dt = datetime.combine(day + timedelta(days=1), time.min).replace(tzinfo=UTC)
        stmt = stmt.where(WaterIntakeLog.created_at >= start_dt).where(WaterIntakeLog.created_at < end_dt)

    rows = session.exec(stmt.limit(bounded_limit)).all()
    return [_water_log_to_read(row) for row in rows]


@router.get("/body/summary", response_model=BodySummaryResponse)
def body_summary(
    current_user: Annotated[UserAccount, Depends(get_ready_user)],
    session: Annotated[Session, Depends(get_session)],
) -> BodySummaryResponse:
    profile = _load_profile(session, current_user.id)

    weight_logs = session.exec(
        select(BodyWeightLog)
        .where(BodyWeightLog.user_id == current_user.id)
        .order_by(desc(BodyWeightLog.created_at))
        .limit(400)
    ).all()

    latest_weight = weight_logs[0] if weight_logs else None
    weekly_change = weekly_weight_change(weight_logs, now=datetime.now(UTC))
    weight_points = rolling_weight_points(weight_logs, days=84)
    trend_points: list[BodyTrendPoint] = [
        BodyTrendPoint(date=date.fromisoformat(str(point["date"])), weight_kg=float(point["weight_kg"]))
        for point in weight_points
    ]

    bmi_value = None
    bmi_label = "unknown"
    body_fat_value = None
    body_fat_label = "unknown"

    if profile:
        if latest_weight:
            bmi_value = bmi(latest_weight.weight_kg, profile.height_cm)
        else:
            bmi_value = bmi(profile.weight_kg, profile.height_cm)
        bmi_label, _ = bmi_category(bmi_value)

        measurement = session.exec(
            select(BodyMeasurementLog)
            .where(BodyMeasurementLog.user_id == current_user.id)
            .order_by(desc(BodyMeasurementLog.created_at))
        ).first()

        body_fat_profile = UserProfile(
            user_id=profile.user_id,
            weight_kg=latest_weight.weight_kg if latest_weight else profile.weight_kg,
            height_cm=profile.height_cm,
            age=profile.age,
            sex=profile.sex,
            activity_level=profile.activity_level,
            goal_type=profile.goal_type,
            waist_cm=measurement.waist_cm if measurement else profile.waist_cm,
            neck_cm=measurement.neck_cm if measurement else profile.neck_cm,
            hip_cm=measurement.hip_cm if measurement else profile.hip_cm,
            chest_cm=measurement.chest_cm if measurement else profile.chest_cm,
            arm_cm=measurement.arm_cm if measurement else profile.arm_cm,
            thigh_cm=measurement.thigh_cm if measurement else profile.thigh_cm,
        )
        body_fat_value = body_fat_percent(body_fat_profile)
        body_fat_label, _ = body_fat_category(body_fat_value, body_fat_profile.sex)

    today = datetime.now(UTC).date()
    today_summary = _day_summary(day=today, current_user=current_user, session=session, include_intakes=False)
    has_intakes_today = bool(
        session.exec(
            select(func.count(Intake.id))
            .where(Intake.user_id == current_user.id)
            .where(Intake.created_at >= datetime.combine(today, time.min).replace(tzinfo=UTC))
            .where(Intake.created_at < datetime.combine(today + timedelta(days=1), time.min).replace(tzinfo=UTC))
        ).one()
    )
    hints = coach_hints(
        consumed_kcal=today_summary.consumed.kcal,
        kcal_goal=today_summary.goal.kcal_goal if today_summary.goal else None,
        consumed_protein_g=today_summary.consumed.protein_g,
        protein_goal=today_summary.goal.protein_goal if today_summary.goal else None,
        has_intakes_today=has_intakes_today,
        weekly_weight_delta=weekly_change,
        latest_weight_kg=latest_weight.weight_kg if latest_weight else profile.weight_kg if profile else None,
        goal_type=profile.goal_type if profile else None,
        weekly_weight_goal_kg=profile.weekly_weight_goal_kg if profile else None,
    )

    return BodySummaryResponse(
        latest_weight_kg=latest_weight.weight_kg if latest_weight else profile.weight_kg if profile else None,
        weekly_change_kg=weekly_change,
        bmi=bmi_value,
        bmi_category=bmi_label,
        body_fat_percent=body_fat_value,
        body_fat_category=body_fat_label,
        needs_weight_checkin=should_prompt_weight_log(latest_weight.created_at if latest_weight else None),
        trend_points=trend_points,
        hints=hints,
    )


def _apply_openfoodfacts_payload(product: Product, off_product: dict[str, object]) -> None:
    brand_value = off_product.get("brand")
    image_value = off_product.get("image_url")

    product.name = str(off_product["name"])
    product.brand = brand_value if isinstance(brand_value, str | type(None)) else None
    product.image_url = image_value if isinstance(image_value, str | type(None)) else None
    product.nutrition_basis = off_product["nutrition_basis"]  # type: ignore[assignment]
    product.serving_size_g = off_product.get("serving_size_g")  # type: ignore[assignment]
    product.net_weight_g = off_product.get("net_weight_g")  # type: ignore[assignment]
    product.kcal = off_product["kcal"]  # type: ignore[assignment]
    product.protein_g = off_product["protein_g"]  # type: ignore[assignment]
    product.fat_g = off_product["fat_g"]  # type: ignore[assignment]
    product.sat_fat_g = off_product.get("sat_fat_g")  # type: ignore[assignment]
    product.carbs_g = off_product["carbs_g"]  # type: ignore[assignment]
    product.sugars_g = off_product.get("sugars_g")  # type: ignore[assignment]
    product.fiber_g = off_product.get("fiber_g")  # type: ignore[assignment]
    product.salt_g = off_product.get("salt_g")  # type: ignore[assignment]
    product.source = "openfoodfacts"
    product.is_verified = False
    product.verified_at = None
    product.data_confidence = "openfoodfacts_imported"


def _product_data_quality(product: Product) -> ProductDataQualityResponse:
    if product.id is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Product id missing")

    if product.is_verified or product.source == "local_verified":
        return ProductDataQualityResponse(
            product_id=product.id,
            status="verified",
            label="Verificado",
            source=product.source,
            is_verified=product.is_verified,
            data_confidence=product.data_confidence,
            verified_at=product.verified_at,
            message="Valores verificados localmente con etiqueta o revisión manual.",
        )

    if product.source == "photo_estimate" or product.data_confidence.startswith("estimate"):
        return ProductDataQualityResponse(
            product_id=product.id,
            status="estimated",
            label="Estimado",
            source=product.source,
            is_verified=False,
            data_confidence=product.data_confidence,
            verified_at=product.verified_at,
            message="Estimación aproximada; revisar con etiqueta real cuando sea posible.",
        )

    if product.source == "community":
        return ProductDataQualityResponse(
            product_id=product.id,
            status="imported",
            label="Comunidad",
            source=product.source,
            is_verified=product.is_verified,
            data_confidence=product.data_confidence,
            verified_at=product.verified_at,
            message="Producto creado por la comunidad y compartido públicamente.",
        )

    return ProductDataQualityResponse(
        product_id=product.id,
        status="imported",
        label="Importado",
        source=product.source,
        is_verified=product.is_verified,
        data_confidence=product.data_confidence,
        verified_at=product.verified_at,
        message="Datos importados de fuente externa sin verificación local.",
    )


def _product_badge(product: Product) -> Literal["Verificado", "Comunidad", "Importado", "Estimado"]:
    if product.is_verified or product.source in {"local_verified", "community_verified"}:
        return "Verificado"
    if product.source == "community":
        return "Comunidad"
    if product.source == "photo_estimate" or product.data_confidence.startswith("estimate"):
        return "Estimado"
    return "Importado"


def _as_float_or_zero(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _as_float_or_none(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _normalize_search_text(value: str) -> str:
    lowered = value.strip().lower()
    folded = unicodedata.normalize("NFKD", lowered)
    without_accents = "".join(char for char in folded if not unicodedata.combining(char))
    compact = re.sub(r"[^a-z0-9]+", " ", without_accents)
    return re.sub(r"\s+", " ", compact).strip()


def _tokenize_search_text(value: str) -> list[str]:
    normalized = _normalize_search_text(value)
    if not normalized:
        return []
    stopwords = {"de", "del", "la", "el", "los", "las", "con", "sin", "para", "por", "al", "en", "y"}
    tokens = [token for token in normalized.split(" ") if token and token not in stopwords]
    deduped: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        deduped.append(token)
    return deduped


def _similarity_bonus(query: str, target: str, *, weight: float) -> float:
    if not query or not target:
        return 0.0
    ratio = SequenceMatcher(None, query, target).ratio()
    if ratio >= 0.92:
        return weight
    if ratio >= 0.85:
        return weight * 0.72
    if ratio >= 0.76:
        return weight * 0.44
    if ratio >= 0.68:
        return weight * 0.24
    return 0.0


def _minimum_text_score_for_query(query: str) -> float:
    normalized = _normalize_search_text(query)
    length = len(normalized)
    if length <= 2:
        return 9.0
    if length <= 4:
        return 18.0
    if length <= 7:
        return 30.0
    return 40.0


def _text_match_score(query: str, name: str, brand: str | None, barcode: str | None) -> float:
    q = _normalize_search_text(query)
    name_l = _normalize_search_text(name)
    brand_l = _normalize_search_text(brand or "")
    barcode_l = (barcode or "").strip()

    if not q:
        return 0.0

    if barcode_l and q == barcode_l:
        return 1200.0

    score = 0.0
    if name_l == q:
        score += 820.0
    elif name_l.startswith(q):
        score += 500.0
    elif q in name_l:
        score += 300.0

    if brand_l == q:
        score += 400.0
    elif brand_l.startswith(q):
        score += 230.0
    elif q in brand_l:
        score += 130.0

    score += _similarity_bonus(q, name_l, weight=240.0)
    score += _similarity_bonus(q, brand_l, weight=180.0)

    query_tokens = [token for token in q.split(" ") if len(token) >= 2]
    name_tokens = [token for token in name_l.split(" ") if len(token) >= 2]
    brand_tokens = [token for token in brand_l.split(" ") if len(token) >= 2]

    if query_tokens:
        combined = f"{name_l} {brand_l}".strip()
        if combined and all(token in combined for token in query_tokens):
            score += 80.0

    for token in query_tokens:
        if token in name_tokens:
            score += 85.0
            continue
        if token in brand_tokens:
            score += 72.0
            continue

        best_name_ratio = max(
            (SequenceMatcher(None, token, candidate).ratio() for candidate in name_tokens),
            default=0.0,
        )
        best_brand_ratio = max(
            (SequenceMatcher(None, token, candidate).ratio() for candidate in brand_tokens),
            default=0.0,
        )
        best_ratio = max(best_name_ratio, best_brand_ratio)
        if best_ratio >= 0.9:
            score += 56.0
        elif best_ratio >= 0.82:
            score += 38.0
        elif best_ratio >= 0.74:
            score += 24.0

    return score


def _source_priority_score(product: Product) -> float:
    if product.is_verified:
        return 290.0
    if product.source in {"community_verified", "local_verified"}:
        return 270.0
    if product.source == "community":
        return 190.0
    if product.source == "openfoodfacts":
        return 85.0
    return 120.0


def _name_legibility_penalty(name: str) -> float:
    normalized = name.strip()
    if not normalized:
        return -60.0
    alpha_count = sum(1 for ch in normalized if ch.isalpha())
    ratio = alpha_count / max(len(normalized), 1)
    penalty = 0.0
    if ratio < 0.55:
        penalty -= 65.0
    if len(normalized) < 4:
        penalty -= 20.0
    if normalized.count("_") >= 2:
        penalty -= 12.0
    return penalty


def _nutrition_quality_penalty(product: Product) -> float:
    penalty = 0.0
    if product.kcal <= 0:
        penalty -= 65.0
    if product.protein_g <= 0 and product.fat_g <= 0 and product.carbs_g <= 0:
        penalty -= 45.0
    return penalty


def _local_search_score(
    *,
    query: str,
    product: Product,
    is_favorite: bool,
    user_use_count: int,
    global_use_count: int,
    text_score: float | None = None,
) -> float:
    score = (
        text_score
        if text_score is not None
        else _text_match_score(query, product.name, product.brand, product.barcode)
    )
    score += _source_priority_score(product)
    score += _name_legibility_penalty(product.name)
    score += _nutrition_quality_penalty(product)
    if product.created_by_user_id is not None:
        score += 28.0
    if is_favorite:
        score += 220.0
    score += min(user_use_count, 30) * 15.0
    score += min(global_use_count, 100) * 2.4
    return score


def _remote_country_tags(candidate: dict[str, object]) -> set[str]:
    tags_raw = candidate.get("countries_tags")
    if isinstance(tags_raw, list):
        return {_normalize_search_text(str(item)) for item in tags_raw if item}
    if isinstance(tags_raw, str) and tags_raw.strip():
        return {_normalize_search_text(tags_raw)}
    return set()


def _remote_country_relevance_score(candidate: dict[str, object]) -> float:
    tags = _remote_country_tags(candidate)
    countries_text = _normalize_search_text(str(candidate.get("countries") or ""))
    spain_tags = {"en:spain", "es:espana", "es:españa", "spain", "espana", "españa"}
    if tags & spain_tags or "spain" in countries_text or "espana" in countries_text or "españa" in countries_text:
        return 260.0

    nearby_eu_tags = {
        "en:portugal",
        "en:france",
        "en:italy",
        "en:germany",
        "en:belgium",
        "en:netherlands",
        "en:ireland",
        "en:austria",
        "en:poland",
        "en:sweden",
        "en:denmark",
        "en:finland",
    }
    if tags & nearby_eu_tags:
        return 130.0

    if tags or countries_text:
        return -80.0
    return 0.0


def _remote_language_relevance_score(candidate: dict[str, object]) -> float:
    lang = _normalize_search_text(str(candidate.get("lang") or ""))
    if lang.startswith("es"):
        return 85.0
    if lang.startswith(("pt", "it", "fr")):
        return 26.0
    if lang:
        return -18.0
    return 0.0


def _remote_candidate_score(query: str, candidate: dict[str, object]) -> float:
    name = str(candidate.get("name") or "")
    brand = candidate.get("brand")
    barcode = candidate.get("barcode")
    score = _text_match_score(query, name, str(brand) if brand is not None else None, str(barcode) if barcode else None)
    score += _remote_country_relevance_score(candidate)
    score += _remote_language_relevance_score(candidate)
    score += _name_legibility_penalty(name)

    kcal = _as_float_or_none(candidate.get("kcal"))
    protein = _as_float_or_none(candidate.get("protein_g"))
    fat = _as_float_or_none(candidate.get("fat_g"))
    carbs = _as_float_or_none(candidate.get("carbs_g"))
    if kcal is None or kcal <= 0:
        score -= 45.0
    if all(value is None or value <= 0 for value in (protein, fat, carbs)):
        score -= 30.0
    return score


def _local_search_candidates_postgres(
    *,
    session: Session,
    current_user: UserAccount,
    query: str,
    bounded_limit: int,
) -> list[tuple[Product, float]]:
    normalized = _normalize_search_text(query)
    if not normalized:
        return []

    tokens = _tokenize_search_text(query)[:5]
    visibility = or_(
        Product.created_by_user_id == current_user.id,
        and_(Product.is_public.is_(True), Product.is_hidden.is_(False), Product.status == "approved"),
    )

    favorite_subq = (
        select(UserFavoriteProduct.product_id.label("fav_product_id"))
        .where(UserFavoriteProduct.user_id == current_user.id)
        .subquery()
    )
    user_use_subq = (
        select(
            Intake.product_id.label("user_product_id"),
            func.count(Intake.id).label("user_use_count"),
        )
        .where(Intake.user_id == current_user.id)
        .group_by(Intake.product_id)
        .subquery()
    )
    global_use_subq = (
        select(
            Intake.product_id.label("global_product_id"),
            func.count(Intake.id).label("global_use_count"),
        )
        .group_by(Intake.product_id)
        .subquery()
    )

    name_norm = func.lower(func.immutable_unaccent(func.coalesce(Product.name, "")))
    brand_norm = func.lower(func.immutable_unaccent(func.coalesce(Product.brand, "")))
    combined_norm = func.trim(func.concat_ws(" ", name_norm, brand_norm))
    ts_rank_expr = cast(
        func.ts_rank_cd(
            func.to_tsvector("simple", combined_norm),
            func.plainto_tsquery("simple", normalized),
        ),
        Float,
    )
    sim_combined = cast(func.similarity(combined_norm, normalized), Float)
    sim_name = cast(func.similarity(name_norm, normalized), Float)
    sim_brand = cast(func.similarity(brand_norm, normalized), Float)

    exact_name = case((name_norm == normalized, 1.0), else_=0.0)
    prefix_name = case((name_norm.like(f"{normalized}%"), 1.0), else_=0.0)
    contains_name = case((name_norm.like(f"%{normalized}%"), 1.0), else_=0.0)
    exact_brand = case((brand_norm == normalized, 1.0), else_=0.0)
    prefix_brand = case((brand_norm.like(f"{normalized}%"), 1.0), else_=0.0)
    contains_brand = case((brand_norm.like(f"%{normalized}%"), 1.0), else_=0.0)

    token_hits = literal(0.0)
    token_filters: list[object] = []
    for token in tokens:
        token_hits = token_hits + case((combined_norm.like(f"%{token}%"), 1.0), else_=0.0)
        token_filters.append(combined_norm.like(f"%{token}%"))

    source_score = case(
        (Product.is_verified.is_(True), 5.0),
        (Product.source.in_(["local_verified", "community_verified"]), 4.3),
        (Product.source == "community", 3.1),
        (Product.source == "openfoodfacts", 1.2),
        else_=2.0,
    )
    favorite_bonus = case((favorite_subq.c.fav_product_id.is_not(None), 2.2), else_=0.0)
    own_product_bonus = case((Product.created_by_user_id == current_user.id, 1.15), else_=0.0)
    user_use_bonus = func.least(cast(func.coalesce(user_use_subq.c.user_use_count, 0), Float), 30.0) * 0.16
    global_use_bonus = func.least(cast(func.coalesce(global_use_subq.c.global_use_count, 0), Float), 140.0) * 0.03
    poor_kcal_penalty = case((Product.kcal <= 0, -1.2), else_=0.0)
    poor_macros_penalty = case(
        (and_(Product.protein_g <= 0, Product.fat_g <= 0, Product.carbs_g <= 0), -1.4),
        else_=0.0,
    )

    score_expr = (
        exact_name * 15.0
        + prefix_name * 9.0
        + contains_name * 4.0
        + exact_brand * 9.0
        + prefix_brand * 6.0
        + contains_brand * 3.2
        + token_hits * 2.0
        + sim_combined * 7.5
        + sim_name * 6.3
        + sim_brand * 4.8
        + ts_rank_expr * 9.0
        + source_score
        + favorite_bonus
        + own_product_bonus
        + user_use_bonus
        + global_use_bonus
        + poor_kcal_penalty
        + poor_macros_penalty
    )

    pre_filters = [
        Product.barcode.ilike(f"%{query.strip()}%"),
        name_norm.like(f"%{normalized}%"),
        brand_norm.like(f"%{normalized}%"),
        sim_combined >= 0.20,
        sim_name >= 0.22,
        sim_brand >= 0.24,
    ]
    pre_filters.extend(token_filters)

    stmt = (
        select(Product, score_expr.label("search_score"))
        .select_from(Product)
        .outerjoin(favorite_subq, favorite_subq.c.fav_product_id == Product.id)
        .outerjoin(user_use_subq, user_use_subq.c.user_product_id == Product.id)
        .outerjoin(global_use_subq, global_use_subq.c.global_product_id == Product.id)
        .where(visibility)
        .where(or_(*pre_filters))
        .order_by(desc(score_expr), desc(Product.is_verified), desc(Product.created_at))
        .limit(max(60, bounded_limit * 4))
    )

    rows = session.exec(stmt).all()
    threshold = _minimum_text_score_for_query(query)
    ranked: list[tuple[Product, float]] = []
    for row in rows:
        product = row[0]
        base_score = float(row[1] or 0.0)
        final_score = base_score + _name_legibility_penalty(product.name) + _nutrition_quality_penalty(product)
        if final_score < threshold:
            continue
        ranked.append((product, final_score))

    ranked.sort(key=lambda entry: (entry[1], entry[0].is_verified, entry[0].created_at), reverse=True)
    return ranked[: max(40, bounded_limit * 3)]


def _local_search_candidates_fallback(
    *,
    session: Session,
    current_user: UserAccount,
    query: str,
    bounded_limit: int,
) -> list[tuple[Product, float]]:
    pattern = f"%{query}%"
    query_tokens = _tokenize_search_text(query)
    token_patterns = [f"%{token}%" for token in query_tokens[:4]]
    visibility = or_(
        Product.created_by_user_id == current_user.id,
        and_(Product.is_public.is_(True), Product.is_hidden.is_(False), Product.status == "approved"),
    )

    text_filters = [
        Product.name.ilike(pattern),
        Product.brand.ilike(pattern),
        Product.barcode.ilike(pattern),
    ]
    for token_pattern in token_patterns:
        text_filters.extend([Product.name.ilike(token_pattern), Product.brand.ilike(token_pattern)])

    candidate_rows = session.exec(
        select(Product)
        .where(visibility)
        .where(or_(*text_filters))
        .order_by(desc(Product.is_verified), desc(Product.created_at))
        .limit(max(180, bounded_limit * 8))
    ).all()

    # If strict LIKE candidates are sparse, pull a broader pool and let Python ranking
    # recover fuzzy matches (useful on sqlite/tests where pg_trgm isn't available).
    if len(candidate_rows) < max(24, bounded_limit * 2):
        fallback_rows = session.exec(
            select(Product)
            .where(visibility)
            .order_by(desc(Product.is_verified), desc(Product.created_at))
            .limit(max(240, bounded_limit * 12))
        ).all()
        seen_ids = {product.id for product in candidate_rows if product.id is not None}
        for fallback in fallback_rows:
            if fallback.id is None or fallback.id in seen_ids:
                continue
            candidate_rows.append(fallback)
            seen_ids.add(fallback.id)

    product_ids = [product.id for product in candidate_rows if product.id is not None]
    favorite_ids: set[int] = set()
    user_use_counts: dict[int, int] = {}
    global_use_counts: dict[int, int] = {}

    if product_ids:
        favorite_rows = session.exec(
            select(UserFavoriteProduct.product_id)
            .where(UserFavoriteProduct.user_id == current_user.id)
            .where(UserFavoriteProduct.product_id.in_(product_ids))
        ).all()
        favorite_ids = set(favorite_rows)

        user_intakes = session.exec(
            select(Intake.product_id)
            .where(Intake.user_id == current_user.id)
            .where(Intake.product_id.in_(product_ids))
        ).all()
        for product_id in user_intakes:
            user_use_counts[product_id] = user_use_counts.get(product_id, 0) + 1

        global_intakes = session.exec(select(Intake.product_id).where(Intake.product_id.in_(product_ids))).all()
        for product_id in global_intakes:
            global_use_counts[product_id] = global_use_counts.get(product_id, 0) + 1

    minimum_text_score = _minimum_text_score_for_query(query)
    ranked: list[tuple[Product, float]] = []
    for product in candidate_rows:
        text_score = _text_match_score(query, product.name, product.brand, product.barcode)
        if text_score < minimum_text_score:
            continue
        final_score = _local_search_score(
            query=query,
            product=product,
            is_favorite=(product.id or -1) in favorite_ids,
            user_use_count=user_use_counts.get(product.id or -1, 0),
            global_use_count=global_use_counts.get(product.id or -1, 0),
            text_score=text_score,
        )
        ranked.append((product, final_score))

    ranked.sort(key=lambda entry: (entry[1], entry[0].is_verified, entry[0].created_at), reverse=True)
    return ranked[: max(40, bounded_limit * 3)]


def _local_search_candidates(
    *,
    session: Session,
    current_user: UserAccount,
    query: str,
    bounded_limit: int,
) -> list[tuple[Product, float]]:
    bind = session.get_bind()
    dialect = bind.dialect.name if bind is not None else ""
    if dialect == "postgresql":
        try:
            return _local_search_candidates_postgres(
                session=session,
                current_user=current_user,
                query=query,
                bounded_limit=bounded_limit,
            )
        except SQLAlchemyError as exc:
            logger.warning("Postgres search ranking fallback for query '%s': %s", query, exc)
    return _local_search_candidates_fallback(
        session=session,
        current_user=current_user,
        query=query,
        bounded_limit=bounded_limit,
    )


def _off_search_preview_product(item: dict[str, object], synthetic_id: int) -> ProductRead:
    basis = item.get("nutrition_basis")
    if not isinstance(basis, NutritionBasis):
        basis = NutritionBasis.per_100g

    barcode = str(item.get("barcode") or "").strip()
    name = str(item.get("name") or "").strip() or "Producto OpenFoodFacts"
    brand_raw = item.get("brand")
    image_raw = item.get("image_url")

    return ProductRead(
        id=synthetic_id,
        barcode=barcode or None,
        created_by_user_id=None,
        is_public=True,
        report_count=0,
        name=name,
        brand=brand_raw if isinstance(brand_raw, str) else None,
        image_url=image_raw if isinstance(image_raw, str) else None,
        nutrition_basis=basis,
        serving_size_g=_as_float_or_none(item.get("serving_size_g")),
        net_weight_g=_as_float_or_none(item.get("net_weight_g")),
        kcal=_as_float_or_zero(item.get("kcal")),
        protein_g=_as_float_or_zero(item.get("protein_g")),
        fat_g=_as_float_or_zero(item.get("fat_g")),
        sat_fat_g=_as_float_or_none(item.get("sat_fat_g")),
        carbs_g=_as_float_or_zero(item.get("carbs_g")),
        sugars_g=_as_float_or_none(item.get("sugars_g")),
        fiber_g=_as_float_or_none(item.get("fiber_g")),
        salt_g=_as_float_or_none(item.get("salt_g")),
        source="openfoodfacts",
        is_verified=False,
        verified_at=None,
        status="approved",
        is_hidden=False,
        canonical_product_id=None,
        data_confidence="openfoodfacts_search_preview",
    )


@router.post("/foods/community", response_model=ProductRead)
def create_community_food(
    payload: CommunityFoodCreate,
    request: Request,
    current_user: Annotated[UserAccount, Depends(get_ready_user)],
    session: Annotated[Session, Depends(get_session)],
) -> ProductRead:
    _rate_limit(request, scope="community_create", limit=15, window_seconds=60, key_suffix=str(current_user.id))
    barcode = payload.barcode.strip() if payload.barcode else None
    if barcode and not EAN_PATTERN.match(barcode):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid EAN/UPC")

    if barcode:
        existing = session.exec(select(Product).where(Product.barcode == barcode)).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Barcode already exists")

    image_url = payload.image_url.strip() if payload.image_url and payload.image_url.strip() else None
    brand = payload.brand.strip() if payload.brand and payload.brand.strip() else None

    product = Product(
        barcode=barcode,
        created_by_user_id=current_user.id,
        is_public=True,
        report_count=0,
        name=payload.name.strip(),
        brand=brand,
        image_url=image_url,
        nutrition_basis=payload.nutrition_basis,
        serving_size_g=payload.serving_size_g,
        net_weight_g=payload.net_weight_g,
        kcal=payload.kcal,
        protein_g=payload.protein_g,
        fat_g=payload.fat_g,
        sat_fat_g=payload.sat_fat_g,
        carbs_g=payload.carbs_g,
        sugars_g=payload.sugars_g,
        fiber_g=payload.fiber_g,
        salt_g=payload.salt_g,
        source="community",
        is_verified=False,
        verified_at=None,
        status="approved",
        is_hidden=False,
        canonical_product_id=None,
        data_confidence="community_approved_auto",
    )
    session.add(product)
    session.commit()
    session.refresh(product)
    return ProductRead.model_validate(product)


@router.get("/foods/mine", response_model=list[ProductRead])
def list_my_community_foods(
    current_user: Annotated[UserAccount, Depends(get_ready_user)],
    session: Annotated[Session, Depends(get_session)],
    limit: int = 100,
) -> list[ProductRead]:
    bounded_limit = max(1, min(limit, 300))
    rows = session.exec(
        select(Product)
        .where(Product.created_by_user_id == current_user.id)
        .where(Product.is_hidden.is_(False))
        .order_by(desc(Product.created_at))
        .limit(bounded_limit)
    ).all()
    return [ProductRead.model_validate(row) for row in rows]


@router.get("/foods/search", response_model=FoodSearchResponse)
async def search_foods(
    q: str,
    current_user: Annotated[UserAccount, Depends(get_ready_user)],
    session: Annotated[Session, Depends(get_session)],
    limit: int = 20,
) -> FoodSearchResponse:
    query = q.strip()
    if len(query) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="q must have at least 2 characters",
        )

    bounded_limit = max(1, min(limit, 40))
    local_candidates = _local_search_candidates(
        session=session,
        current_user=current_user,
        query=query,
        bounded_limit=bounded_limit,
    )

    results: list[FoodSearchItem] = []
    seen_product_ids: set[int] = set()
    seen_barcodes: set[str] = {
        product.barcode for product, _score in local_candidates if product.barcode and product.barcode.strip()
    }

    for product, _score in local_candidates:
        if product.id is None or product.id in seen_product_ids:
            continue
        seen_product_ids.add(product.id)
        results.append(
            FoodSearchItem(
                product=ProductRead.model_validate(product),
                badge=_product_badge(product),
                origin="local",
            )
        )
        if len(results) >= bounded_limit:
            return FoodSearchResponse(query=query, results=results)

    is_barcode_query = EAN_PATTERN.match(query) is not None
    has_exact_local_barcode = any(product.barcode == query for product, _score in local_candidates)

    should_try_openfoodfacts_barcode = EAN_PATTERN.match(query) is not None and all(
        product.barcode != query for product, _score in local_candidates
    )
    if should_try_openfoodfacts_barcode and not has_exact_local_barcode and len(results) < bounded_limit:
        try:
            off_product = await fetch_openfoodfacts_product(query)
        except OpenFoodFactsClientError as exc:
            logger.warning("OpenFoodFacts barcode lookup failed for %s: %s", query, exc)
            off_product = None

        if off_product and not off_missing_critical_fields(off_product):
            existing = session.exec(select(Product).where(Product.barcode == query)).first()
            imported = existing
            if imported is None:
                imported = Product(
                    barcode=query,
                    name="",
                    brand=None,
                    image_url=None,
                    nutrition_basis=NutritionBasis.per_100g,
                    serving_size_g=None,
                    net_weight_g=None,
                    kcal=0,
                    protein_g=0,
                    fat_g=0,
                    sat_fat_g=None,
                    carbs_g=0,
                    sugars_g=None,
                    fiber_g=None,
                    salt_g=None,
                    data_confidence="manual",
                )
            _apply_openfoodfacts_payload(imported, off_product)
            session.add(imported)
            session.commit()
            session.refresh(imported)
            if imported.id is not None and imported.id not in seen_product_ids:
                seen_product_ids.add(imported.id)
                if imported.barcode:
                    seen_barcodes.add(imported.barcode)
                results.append(
                    FoodSearchItem(
                        product=ProductRead.model_validate(imported),
                        badge=_product_badge(imported),
                        origin="local",
                    )
                )

    minimum_text_score = _minimum_text_score_for_query(query)
    local_top_score = local_candidates[0][1] if local_candidates else 0.0
    strong_local_count = sum(1 for _product, score in local_candidates if score >= (minimum_text_score + 24.0))
    has_high_quality_local = bool(local_candidates) and local_top_score >= (minimum_text_score + 60.0)
    has_enough_strong_local = len(results) >= min(8, bounded_limit) and strong_local_count >= 5
    should_try_openfoodfacts_text = (
        not is_barcode_query
        and len(results) < bounded_limit
        and not has_enough_strong_local
        and (len(results) < min(4, bounded_limit) or strong_local_count < 3 or not has_high_quality_local)
        and local_top_score < (minimum_text_score + 78.0)
    )
    if should_try_openfoodfacts_text:
        try:
            off_candidates = await search_openfoodfacts_products(query, limit=min(20, max(8, bounded_limit + 4)))
        except OpenFoodFactsClientError as exc:
            logger.warning("OpenFoodFacts text search failed for '%s': %s", query, exc)
            off_candidates = []

        remote_scored = [
            (candidate, _remote_candidate_score(query, candidate))
            for candidate in off_candidates
        ]
        remote_scored.sort(key=lambda item: item[1], reverse=True)

        remote_slots = bounded_limit - len(results)
        if len(results) >= 4:
            remote_slots = min(remote_slots, 4)
        else:
            remote_slots = min(remote_slots, 8)

        minimum_remote_score = max(22.0, minimum_text_score * 0.62)
        synthetic_id = -1
        appended = 0
        for candidate, remote_score in remote_scored:
            if remote_score < minimum_remote_score:
                continue
            barcode = str(candidate.get("barcode") or "").strip()
            if not barcode or barcode in seen_barcodes:
                continue
            results.append(
                FoodSearchItem(
                    product=_off_search_preview_product(candidate, synthetic_id),
                    badge="Importado",
                    origin="openfoodfacts_remote",
                )
            )
            synthetic_id -= 1
            seen_barcodes.add(barcode)
            appended += 1
            if len(results) >= bounded_limit or appended >= remote_slots:
                break

    return FoodSearchResponse(query=query, results=results)


@router.post("/foods/{product_id}/report", response_model=CommunityFoodReportResponse)
def report_community_food(
    product_id: int,
    request: Request,
    current_user: Annotated[UserAccount, Depends(get_ready_user)],
    session: Annotated[Session, Depends(get_session)],
) -> CommunityFoodReportResponse:
    _rate_limit(request, scope="community_report", limit=20, window_seconds=60, key_suffix=str(current_user.id))
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    product.report_count = (product.report_count or 0) + 1
    if product.report_count >= 5:
        product.status = "flagged"
        product.is_hidden = True

    session.add(product)
    session.commit()
    session.refresh(product)
    return CommunityFoodReportResponse(
        product_id=product.id,
        report_count=product.report_count,
        status=product.status,
        is_hidden=product.is_hidden,
    )


@router.get("/products/by_barcode/{ean}", response_model=ProductLookupResponse)
async def product_by_barcode(
    ean: str,
    current_user: Annotated[UserAccount, Depends(get_ready_user)],
    session: Annotated[Session, Depends(get_session)],
) -> ProductLookupResponse:
    if not EAN_PATTERN.match(ean):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid EAN/UPC")

    local = session.exec(select(Product).where(Product.barcode == ean)).first()
    if local:
        if local.is_hidden and local.created_by_user_id != current_user.id:
            return ProductLookupResponse(source="not_found", message="Product not found")
        # Avoid mixing label/manual nutrition with external images.
        # Only sync OpenFoodFacts products with OpenFoodFacts data.
        if local.source == "openfoodfacts" and not local.is_verified:
            try:
                off_product = await fetch_openfoodfacts_product(ean)
            except OpenFoodFactsClientError:
                off_product = None

            if off_product and not off_missing_critical_fields(off_product):
                _apply_openfoodfacts_payload(local, off_product)
                session.add(local)
                session.commit()
                session.refresh(local)

        pref = session.exec(
            select(UserProductPreference)
            .where(UserProductPreference.user_id == current_user.id)
            .where(UserProductPreference.product_id == local.id)
        ).first()
        return ProductLookupResponse(
            source="local",
            product=ProductRead.model_validate(local),
            preferred_serving=_preference_payload(pref),
        )

    try:
        off_product = await fetch_openfoodfacts_product(ean)
    except OpenFoodFactsClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    if off_product is None:
        return ProductLookupResponse(source="not_found", message="Product not found")

    missing = off_missing_critical_fields(off_product)
    if missing:
        return ProductLookupResponse(
            source="openfoodfacts_incomplete",
            missing_fields=missing,
            message="Missing nutrition fields. Capture the label.",
        )

    existing_after_fetch = session.exec(select(Product).where(Product.barcode == ean)).first()
    if existing_after_fetch:
        if existing_after_fetch.is_hidden and existing_after_fetch.created_by_user_id != current_user.id:
            return ProductLookupResponse(source="not_found", message="Product not found")
        pref = session.exec(
            select(UserProductPreference)
            .where(UserProductPreference.user_id == current_user.id)
            .where(UserProductPreference.product_id == existing_after_fetch.id)
        ).first()
        return ProductLookupResponse(
            source="local",
            product=ProductRead.model_validate(existing_after_fetch),
            preferred_serving=_preference_payload(pref),
        )

    product = Product(
        barcode=ean,
        name="",
        brand=None,
        image_url=None,
        nutrition_basis=NutritionBasis.per_100g,
        serving_size_g=None,
        net_weight_g=None,
        kcal=0,
        protein_g=0,
        fat_g=0,
        sat_fat_g=None,
        carbs_g=0,
        sugars_g=None,
        fiber_g=None,
        salt_g=None,
        data_confidence="manual",
    )
    _apply_openfoodfacts_payload(product, off_product)
    session.add(product)
    try:
        session.commit()
        session.refresh(product)
    except SQLAlchemyError:
        session.rollback()
        existing = session.exec(select(Product).where(Product.barcode == ean)).first()
        if existing:
            pref = session.exec(
                select(UserProductPreference)
                .where(UserProductPreference.user_id == current_user.id)
                .where(UserProductPreference.product_id == existing.id)
            ).first()
            return ProductLookupResponse(
                source="local",
                product=ProductRead.model_validate(existing),
                preferred_serving=_preference_payload(pref),
            )
        raise

    return ProductLookupResponse(source="openfoodfacts_imported", product=ProductRead.model_validate(product))


@router.get("/products/{product_id}/data-quality", response_model=ProductDataQualityResponse)
def product_data_quality(
    product_id: int,
    current_user: Annotated[UserAccount, Depends(get_ready_user)],
    session: Annotated[Session, Depends(get_session)],
) -> ProductDataQualityResponse:
    del current_user
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return _product_data_quality(product)


@router.post("/products/from_label_photo", response_model=LabelPhotoResponse)
async def create_product_from_label_photo(
    current_user: Annotated[UserAccount, Depends(get_ready_user)],
    session: Annotated[Session, Depends(get_session)],
    barcode: Annotated[str | None, Form()] = None,
    name: Annotated[str | None, Form()] = None,
    brand: Annotated[str | None, Form()] = None,
    image_url: Annotated[str | None, Form()] = None,
    nutrition_basis: Annotated[NutritionBasis | None, Form()] = None,
    serving_size_g: Annotated[float | None, Form()] = None,
    net_weight_g: Annotated[float | None, Form()] = None,
    label_text: Annotated[str | None, Form()] = None,
    photos: Annotated[list[UploadFile] | None, File()] = None,
) -> LabelPhotoResponse:
    image_url_clean = image_url.strip() if image_url and image_url.strip() else None

    extracted, questions, warnings, analysis_method = await _extract_label_payload(
        user=current_user,
        basis_hint=nutrition_basis,
        serving_size_g=serving_size_g,
        net_weight_g=net_weight_g,
        label_text=label_text,
        photos=photos,
    )

    missing_fields = missing_critical_fields(extracted)
    extracted_text = (label_text or "").strip()
    if not extracted_text and not photos:
        questions.insert(0, "Could not extract text from label. Upload a clearer image or paste OCR text.")

    if not name:
        questions.append("Missing product name.")

    if missing_fields:
        for field in missing_fields:
            questions.append(f"Missing {field}. Please confirm manually.")

    nutrition_payload = NutritionExtract.model_validate(extracted)

    if missing_fields or not name:
        return LabelPhotoResponse(
            created=False,
            extracted=nutrition_payload,
            missing_fields=missing_fields,
            questions=questions,
            analysis_method=analysis_method,
            warnings=warnings,
        )

    payload = sanitize_numeric_values({**extracted, "net_weight_g": net_weight_g})

    existing = None
    if barcode:
        existing = session.exec(select(Product).where(Product.barcode == barcode)).first()

    if existing:
        existing.name = name
        existing.brand = brand
        if image_url is not None:
            existing.image_url = image_url_clean
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
        existing.source = "local_verified"
        existing.is_verified = True
        existing.verified_at = datetime.now(UTC)
        existing.data_confidence = "label_photo_verified"
        product = existing
    else:
        product = Product(
            barcode=barcode,
            name=name,
            brand=brand,
            image_url=image_url_clean,
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
            source="local_verified",
            is_verified=True,
            verified_at=datetime.now(UTC),
            data_confidence="label_photo_verified",
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
        analysis_method=analysis_method,
        warnings=warnings,
    )


def _apply_extracted_label_to_product(
    product: Product,
    payload: dict[str, object],
    *,
    name: str | None = None,
    brand: str | None = None,
) -> None:
    if name is not None and name.strip():
        product.name = name.strip()
    if brand is not None:
        brand_clean = brand.strip()
        product.brand = brand_clean or None

    product.nutrition_basis = payload["nutrition_basis"]  # type: ignore[assignment]
    product.serving_size_g = payload.get("serving_size_g")  # type: ignore[assignment]
    product.net_weight_g = payload.get("net_weight_g")  # type: ignore[assignment]
    product.kcal = payload["kcal"]  # type: ignore[assignment]
    product.protein_g = payload["protein_g"]  # type: ignore[assignment]
    product.fat_g = payload["fat_g"]  # type: ignore[assignment]
    product.sat_fat_g = payload.get("sat_fat_g")  # type: ignore[assignment]
    product.carbs_g = payload["carbs_g"]  # type: ignore[assignment]
    product.sugars_g = payload.get("sugars_g")  # type: ignore[assignment]
    product.fiber_g = payload.get("fiber_g")  # type: ignore[assignment]
    product.salt_g = payload.get("salt_g")  # type: ignore[assignment]
    product.source = "local_verified"
    product.is_verified = True
    product.verified_at = datetime.now(UTC)
    product.data_confidence = "label_photo_verified"


async def _correct_product_from_label_impl(
    *,
    product: Product,
    user: UserAccount,
    session: Session,
    confirm_update: bool,
    name: str | None,
    brand: str | None,
    nutrition_basis: NutritionBasis | None,
    serving_size_g: float | None,
    net_weight_g: float | None,
    label_text: str | None,
    photos: list[UploadFile] | None,
) -> ProductCorrectionResponse:
    extracted, questions, warnings, analysis_method = await _extract_label_payload(
        user=user,
        basis_hint=nutrition_basis,
        serving_size_g=serving_size_g,
        net_weight_g=net_weight_g if net_weight_g is not None else product.net_weight_g,
        label_text=label_text,
        photos=photos,
    )
    missing_fields = missing_critical_fields(extracted)
    if not (label_text or "").strip() and not photos:
        questions.insert(0, "No se pudo extraer texto de la etiqueta. Sube una imagen más nítida o pega el OCR.")

    detected_payload = NutritionExtract.model_validate(extracted)
    current_payload = _nutrition_extract_from_product(product)

    if not confirm_update:
        return ProductCorrectionResponse(
            product_id=product.id,
            updated=False,
            product=ProductRead.model_validate(product),
            current=current_payload,
            detected=detected_payload,
            missing_fields=missing_fields,
            questions=questions,
            message="Revisa comparación y reenvía con confirm_update=true para guardar.",
            analysis_method=analysis_method,
            warnings=warnings,
        )

    if missing_fields:
        return ProductCorrectionResponse(
            product_id=product.id,
            updated=False,
            product=ProductRead.model_validate(product),
            current=current_payload,
            detected=detected_payload,
            missing_fields=missing_fields,
            questions=questions,
            message="Faltan campos críticos; no se guardó la corrección.",
            analysis_method=analysis_method,
            warnings=warnings,
        )

    payload = sanitize_numeric_values(extracted)
    _apply_extracted_label_to_product(
        product,
        payload,
        name=name,
        brand=brand,
    )

    session.add(product)
    session.commit()
    session.refresh(product)

    return ProductCorrectionResponse(
        product_id=product.id,
        updated=True,
        product=ProductRead.model_validate(product),
        current=current_payload,
        detected=detected_payload,
        missing_fields=[],
        questions=questions,
        message="Producto actualizado y marcado como verificado localmente.",
        analysis_method=analysis_method,
        warnings=warnings,
    )


@router.post("/products/{product_id}/correct-from-label-photo", response_model=ProductCorrectionResponse)
async def correct_product_from_label_photo(
    product_id: int,
    current_user: Annotated[UserAccount, Depends(get_ready_user)],
    session: Annotated[Session, Depends(get_session)],
    confirm_update: Annotated[bool, Form()] = False,
    name: Annotated[str | None, Form()] = None,
    brand: Annotated[str | None, Form()] = None,
    nutrition_basis: Annotated[NutritionBasis | None, Form()] = None,
    serving_size_g: Annotated[float | None, Form()] = None,
    net_weight_g: Annotated[float | None, Form()] = None,
    label_text: Annotated[str | None, Form()] = None,
    photos: Annotated[list[UploadFile] | None, File()] = None,
) -> ProductCorrectionResponse:
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    return await _correct_product_from_label_impl(
        product=product,
        user=current_user,
        session=session,
        confirm_update=confirm_update,
        name=name,
        brand=brand,
        nutrition_basis=nutrition_basis,
        serving_size_g=serving_size_g,
        net_weight_g=net_weight_g,
        label_text=label_text,
        photos=photos,
    )


@router.post("/products/correct-by-barcode-from-label-photo", response_model=ProductCorrectionResponse)
async def correct_product_by_barcode_from_label_photo(
    current_user: Annotated[UserAccount, Depends(get_ready_user)],
    session: Annotated[Session, Depends(get_session)],
    barcode: Annotated[str, Form()],
    confirm_update: Annotated[bool, Form()] = False,
    name: Annotated[str | None, Form()] = None,
    brand: Annotated[str | None, Form()] = None,
    nutrition_basis: Annotated[NutritionBasis | None, Form()] = None,
    serving_size_g: Annotated[float | None, Form()] = None,
    net_weight_g: Annotated[float | None, Form()] = None,
    label_text: Annotated[str | None, Form()] = None,
    photos: Annotated[list[UploadFile] | None, File()] = None,
) -> ProductCorrectionResponse:
    code = barcode.strip()
    if not code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="barcode is required")

    product = session.exec(select(Product).where(Product.barcode == code)).first()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found for barcode")

    return await _correct_product_from_label_impl(
        product=product,
        user=current_user,
        session=session,
        confirm_update=confirm_update,
        name=name,
        brand=brand,
        nutrition_basis=nutrition_basis,
        serving_size_g=serving_size_g,
        net_weight_g=net_weight_g,
        label_text=label_text,
        photos=photos,
    )


@router.post("/meal-photo-estimate/questions", response_model=MealEstimateQuestionsResponse)
async def meal_photo_estimate_questions(
    request: Request,
    current_user: Annotated[UserAccount, Depends(get_ready_user)],
    session: Annotated[Session, Depends(get_session)],
    description: Annotated[str | None, Form()] = None,
    quantity_note: Annotated[str | None, Form()] = None,
    locale: Annotated[str | None, Form()] = None,
    photos: Annotated[list[UploadFile] | None, File()] = None,
) -> MealEstimateQuestionsResponse:
    _rate_limit(request, scope="meal_questions", limit=12, window_seconds=60, key_suffix=str(current_user.id))
    _cleanup_expired_meal_analysis(session, user_id=current_user.id)
    ai_credentials = _user_ai_provider_and_key(current_user, required=True)
    if not ai_credentials:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No AI credentials available",
        )
    _, api_key = ai_credentials
    photo_files = photos or []
    if not photo_files:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Adjunta al menos una foto.")
    if len(photo_files) > MAX_MEAL_PHOTOS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Máximo {MAX_MEAL_PHOTOS} fotos por estimación.",
        )

    try:
        result = await generate_meal_questions_with_ai(
            api_key=api_key,
            description=(description or "").strip(),
            quantity_note=(quantity_note or "").strip() or None,
            photo_files=photo_files,
            locale=_normalize_locale(locale),
        )
    except VisionAIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    analysis_id: str | None = None
    analysis_expires_at: datetime | None = None
    try:
        analysis = await _store_meal_analysis(session=session, user_id=current_user.id, photo_files=photo_files)
        analysis_id = analysis.id
        analysis_expires_at = analysis.expires_at
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to persist meal photo analysis cache")

    return MealEstimateQuestionsResponse(
        model_used=result["model_used"],  # type: ignore[arg-type]
        questions=result["questions"],  # type: ignore[arg-type]
        question_items=result.get("question_items", []),  # type: ignore[arg-type]
        assumptions=result["assumptions"],  # type: ignore[arg-type]
        detected_ingredients=result["detected_ingredients"],  # type: ignore[arg-type]
        analysis_id=analysis_id,
        analysis_expires_at=analysis_expires_at,
    )


@router.post("/meal-photo-estimate/calculate", response_model=MealPhotoEstimateResponse)
async def meal_photo_estimate_calculate(
    request: Request,
    current_user: Annotated[UserAccount, Depends(get_ready_user)],
    session: Annotated[Session, Depends(get_session)],
    description: Annotated[str | None, Form()] = None,
    locale: Annotated[str | None, Form()] = None,
    analysis_id: Annotated[str | None, Form()] = None,
    answers_json: Annotated[str | None, Form()] = None,
    portion_size: Annotated[str | None, Form()] = None,
    has_added_fats: Annotated[bool | None, Form()] = None,
    quantity_note: Annotated[str | None, Form()] = None,
    adjust_percent: Annotated[int, Form()] = 0,
    override_kcal: Annotated[float | None, Form()] = None,
    override_protein_g: Annotated[float | None, Form()] = None,
    override_fat_g: Annotated[float | None, Form()] = None,
    override_carbs_g: Annotated[float | None, Form()] = None,
    commit: Annotated[bool, Form()] = False,
    photos: Annotated[list[UploadFile] | None, File()] = None,
) -> MealPhotoEstimateResponse:
    _rate_limit(request, scope="meal_calculate", limit=18, window_seconds=60, key_suffix=str(current_user.id))
    return await intake_from_meal_photo_estimate(
        request=request,
        current_user=current_user,
        session=session,
        description=description,
        locale=locale,
        analysis_id=analysis_id,
        answers_json=answers_json,
        portion_size=portion_size,
        has_added_fats=has_added_fats,
        quantity_note=quantity_note,
        adjust_percent=adjust_percent,
        override_kcal=override_kcal,
        override_protein_g=override_protein_g,
        override_fat_g=override_fat_g,
        override_carbs_g=override_carbs_g,
        commit=commit,
        photos=photos,
    )


@router.post("/intakes/from-meal-photo-estimate", response_model=MealPhotoEstimateResponse)
async def intake_from_meal_photo_estimate(
    request: Request,
    current_user: Annotated[UserAccount, Depends(get_ready_user)],
    session: Annotated[Session, Depends(get_session)],
    description: Annotated[str | None, Form()] = None,
    locale: Annotated[str | None, Form()] = None,
    analysis_id: Annotated[str | None, Form()] = None,
    answers_json: Annotated[str | None, Form()] = None,
    portion_size: Annotated[str | None, Form()] = None,
    has_added_fats: Annotated[bool | None, Form()] = None,
    quantity_note: Annotated[str | None, Form()] = None,
    adjust_percent: Annotated[int, Form()] = 0,
    override_kcal: Annotated[float | None, Form()] = None,
    override_protein_g: Annotated[float | None, Form()] = None,
    override_fat_g: Annotated[float | None, Form()] = None,
    override_carbs_g: Annotated[float | None, Form()] = None,
    commit: Annotated[bool, Form()] = False,
    photos: Annotated[list[UploadFile] | None, File()] = None,
) -> MealPhotoEstimateResponse:
    _rate_limit(request, scope="meal_commit", limit=25, window_seconds=60, key_suffix=str(current_user.id))
    ai_credentials = _user_ai_provider_and_key(current_user, required=True)
    if not ai_credentials:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No AI credentials available",
        )
    _, api_key = ai_credentials

    using_cached_analysis = False
    cached_analysis: MealPhotoAnalysis | None = None
    if analysis_id and analysis_id.strip():
        photo_files, cached_analysis = _load_meal_analysis_files(
            session=session,
            analysis_id=analysis_id.strip(),
            user_id=current_user.id,
        )
        using_cached_analysis = True
    else:
        photo_files = photos or []
        if not photo_files:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Adjunta al menos una foto.")
        if len(photo_files) > MAX_MEAL_PHOTOS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Máximo {MAX_MEAL_PHOTOS} fotos por estimación.",
            )

    normalized_locale = _normalize_locale(locale)
    resolved_description, normalized_portion, resolved_added_fats, resolved_quantity_note, answer_context = (
        _resolve_meal_inputs(
            description=description,
            answers_json=answers_json,
            portion_size=portion_size,
            has_added_fats=has_added_fats,
            quantity_note=quantity_note,
            locale=normalized_locale,
        )
    )
    normalized_adjust = max(-30, min(30, adjust_percent))
    try:
        result = await estimate_meal_with_ai(
            api_key=api_key,
            description=resolved_description,
            portion_size=normalized_portion,  # type: ignore[arg-type]
            has_added_fats=resolved_added_fats,
            quantity_note=resolved_quantity_note,
            photo_files=photo_files,
            adjust_percent=normalized_adjust,
            answers=answer_context,
            locale=normalized_locale,
        )
    except VisionAIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    finally:
        if using_cached_analysis:
            await _close_upload_files(photo_files)

    nutrition = result["nutrition"]  # type: ignore[assignment]
    preview_nutrients = {
        "kcal": float(nutrition["kcal"]),
        "protein_g": float(nutrition["protein_g"]),
        "fat_g": float(nutrition["fat_g"]),
        "sat_fat_g": float(nutrition.get("sat_fat_g") or 0.0),
        "carbs_g": float(nutrition["carbs_g"]),
        "sugars_g": float(nutrition.get("sugars_g") or 0.0),
        "fiber_g": float(nutrition.get("fiber_g") or 0.0),
        "salt_g": float(nutrition.get("salt_g") or 0.0),
    }
    preview_nutrients = _apply_meal_preview_overrides(
        preview_nutrients=preview_nutrients,
        override_kcal=override_kcal,
        override_protein_g=override_protein_g,
        override_fat_g=override_fat_g,
        override_carbs_g=override_carbs_g,
    )

    response_base = {
        "saved": False,
        "model_used": result["model_used"],
        "confidence_level": result["confidence_level"],
        "analysis_method": result.get("analysis_method", "heuristic"),
        "assumptions": result["assumptions"],
        "questions": result["questions"],
        "question_items": result.get("question_items", []),
        "detected_ingredients": result["detected_ingredients"],
        "preview_nutrients": preview_nutrients,
        "intake": None,
    }
    if not commit:
        return MealPhotoEstimateResponse.model_validate(response_base)

    serving_size = {
        "small": 200.0,
        "medium": 280.0,
        "large": 360.0,
    }.get(normalized_portion or "medium", 280.0)
    if resolved_quantity_note:
        match = re.search(r"(\\d+(?:[\\.,]\\d+)?)", resolved_quantity_note)
        if match:
            try:
                qty_factor = float(match.group(1).replace(",", "."))
                serving_size = max(120.0, min(620.0, serving_size * max(0.5, min(qty_factor, 2.0))))
            except ValueError:
                pass

    product_name = (description or "").strip()
    if not product_name:
        product_name = "Estimated meal" if normalized_locale == "en" else "Comida estimada"

    product = Product(
        barcode=None,
        name=(f"Estimate: {product_name[:72]}" if normalized_locale == "en" else f"Estimación: {product_name[:72]}"),
        brand=None,
        image_url=None,
        nutrition_basis=NutritionBasis.per_serving,
        serving_size_g=serving_size,
        net_weight_g=serving_size,
        kcal=preview_nutrients["kcal"],
        protein_g=preview_nutrients["protein_g"],
        fat_g=preview_nutrients["fat_g"],
        sat_fat_g=preview_nutrients["sat_fat_g"],
        carbs_g=preview_nutrients["carbs_g"],
        sugars_g=preview_nutrients["sugars_g"],
        fiber_g=preview_nutrients["fiber_g"],
        salt_g=preview_nutrients["salt_g"],
        source="photo_estimate",
        is_verified=False,
        verified_at=None,
        data_confidence=f"estimate_{result['confidence_level']}",
    )
    session.add(product)
    session.flush()

    intake = Intake(
        user_id=current_user.id,
        product_id=product.id,
        quantity_g=serving_size,
        quantity_units=1,
        percent_pack=None,
        method=IntakeMethod.units,
        estimated=True,
        estimate_confidence=result["confidence_level"],  # type: ignore[arg-type]
        user_description=resolved_description,
        source_method="meal_photo",
        created_at=datetime.now(UTC),
    )
    session.add(intake)
    session.commit()
    session.refresh(product)
    session.refresh(intake)

    if cached_analysis is not None:
        _remove_meal_analysis_files(cached_analysis.image_meta_json)
        session.delete(cached_analysis)
        session.commit()

    nutrients = nutrients_for_quantity(product, serving_size)
    intake_payload = IntakeRead(
        id=intake.id,
        product_id=intake.product_id,
        product_name=product.name,
        method=intake.method,
        quantity_g=intake.quantity_g,
        quantity_units=intake.quantity_units,
        percent_pack=intake.percent_pack,
        created_at=intake.created_at,
        estimated=intake.estimated,
        estimate_confidence=intake.estimate_confidence,
        user_description=intake.user_description,
        source_method=intake.source_method,
        nutrients=nutrients,
    )

    response_base["saved"] = True
    response_base["intake"] = intake_payload
    return MealPhotoEstimateResponse.model_validate(response_base)


@router.get("/favorites/products", response_model=list[FavoriteProductRead])
def list_favorite_products(
    current_user: Annotated[UserAccount, Depends(get_ready_user)],
    session: Annotated[Session, Depends(get_session)],
    limit: int = 60,
) -> list[FavoriteProductRead]:
    bounded_limit = max(1, min(limit, 200))
    rows = session.exec(
        select(UserFavoriteProduct, Product)
        .join(Product, Product.id == UserFavoriteProduct.product_id)
        .where(UserFavoriteProduct.user_id == current_user.id)
        .where(Product.is_hidden.is_(False))
        .order_by(desc(UserFavoriteProduct.created_at))
        .limit(bounded_limit)
    ).all()
    return [
        FavoriteProductRead(product=ProductRead.model_validate(product), created_at=favorite.created_at)
        for favorite, product in rows
    ]


@router.post("/favorites/products/{product_id}", response_model=FavoriteProductToggleResponse)
def add_favorite_product(
    product_id: int,
    current_user: Annotated[UserAccount, Depends(get_ready_user)],
    session: Annotated[Session, Depends(get_session)],
) -> FavoriteProductToggleResponse:
    product = session.get(Product, product_id)
    if not product or product.is_hidden:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    existing = session.exec(
        select(UserFavoriteProduct)
        .where(UserFavoriteProduct.user_id == current_user.id)
        .where(UserFavoriteProduct.product_id == product_id)
    ).first()
    if not existing:
        session.add(UserFavoriteProduct(user_id=current_user.id, product_id=product_id, created_at=datetime.now(UTC)))
        session.commit()
    return FavoriteProductToggleResponse(favorited=True, product_id=product_id)


@router.delete("/favorites/products/{product_id}", response_model=FavoriteProductToggleResponse)
def remove_favorite_product(
    product_id: int,
    current_user: Annotated[UserAccount, Depends(get_ready_user)],
    session: Annotated[Session, Depends(get_session)],
) -> FavoriteProductToggleResponse:
    existing = session.exec(
        select(UserFavoriteProduct)
        .where(UserFavoriteProduct.user_id == current_user.id)
        .where(UserFavoriteProduct.product_id == product_id)
    ).first()
    if existing:
        session.delete(existing)
        session.commit()
    return FavoriteProductToggleResponse(favorited=False, product_id=product_id)


@router.post("/intakes/repeat-from-day/{from_day}", response_model=RepeatIntakesResponse)
def repeat_intakes_from_day(
    from_day: date,
    current_user: Annotated[UserAccount, Depends(get_ready_user)],
    session: Annotated[Session, Depends(get_session)],
    to_day: date | None = None,
) -> RepeatIntakesResponse:
    target_day = to_day or datetime.now(UTC).date()
    if from_day == target_day:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="from_day and to_day must be different",
        )

    source_start = datetime.combine(from_day, time.min).replace(tzinfo=UTC)
    source_end = datetime.combine(from_day + timedelta(days=1), time.min).replace(tzinfo=UTC)
    target_start = datetime.combine(target_day, time.min).replace(tzinfo=UTC)

    existing_target = session.exec(
        select(Intake)
        .where(Intake.user_id == current_user.id)
        .where(Intake.created_at >= target_start)
        .where(Intake.created_at < target_start + timedelta(days=1))
    ).all()
    if existing_target:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Target day already has intakes")

    source_intakes = session.exec(
        select(Intake)
        .where(Intake.user_id == current_user.id)
        .where(Intake.created_at >= source_start)
        .where(Intake.created_at < source_end)
        .order_by(Intake.created_at.asc())
    ).all()

    copied = 0
    for index, source in enumerate(source_intakes):
        session.add(
            Intake(
                user_id=current_user.id,
                product_id=source.product_id,
                quantity_g=source.quantity_g,
                quantity_units=source.quantity_units,
                percent_pack=source.percent_pack,
                method=source.method,
                estimated=source.estimated,
                estimate_confidence=source.estimate_confidence,
                user_description=source.user_description,
                source_method="repeat_day",
                created_at=target_start + timedelta(minutes=10 * index),
            )
        )
        copied += 1

    session.commit()
    return RepeatIntakesResponse(copied=copied, from_day=from_day, to_day=target_day)


@router.post("/intakes", response_model=IntakeRead)
def create_intake(
    payload: IntakeCreate,
    request: Request,
    current_user: Annotated[UserAccount, Depends(get_ready_user)],
    session: Annotated[Session, Depends(get_session)],
) -> IntakeRead:
    _rate_limit(request, scope="intake_create", limit=60, window_seconds=60, key_suffix=str(current_user.id))
    product = session.get(Product, payload.product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    try:
        resolved_quantity_g = quantity_from_method(
            product=product,
            method=payload.method.value,
            quantity_g=payload.quantity_g,
            quantity_units=payload.quantity_units,
            percent_pack=payload.percent_pack,
        )
    except IntakeComputationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    intake = Intake(
        user_id=current_user.id,
        product_id=payload.product_id,
        quantity_g=resolved_quantity_g,
        quantity_units=payload.quantity_units,
        percent_pack=payload.percent_pack,
        method=payload.method,
        created_at=payload.created_at or datetime.now(UTC),
    )
    session.add(intake)

    preference = session.exec(
        select(UserProductPreference)
        .where(UserProductPreference.user_id == current_user.id)
        .where(UserProductPreference.product_id == payload.product_id)
    ).first()
    if preference is None:
        preference = UserProductPreference(
            user_id=current_user.id,
            product_id=payload.product_id,
            method=payload.method,
            quantity_g=payload.quantity_g,
            quantity_units=payload.quantity_units,
            percent_pack=payload.percent_pack,
            updated_at=datetime.now(UTC),
        )
        session.add(preference)
    else:
        preference.method = payload.method
        preference.quantity_g = payload.quantity_g
        preference.quantity_units = payload.quantity_units
        preference.percent_pack = payload.percent_pack
        preference.updated_at = datetime.now(UTC)

    session.commit()
    session.refresh(intake)

    nutrients = nutrients_for_quantity(product, resolved_quantity_g)
    return IntakeRead(
        id=intake.id,
        product_id=intake.product_id,
        product_name=product.name,
        method=intake.method,
        quantity_g=intake.quantity_g,
        quantity_units=intake.quantity_units,
        percent_pack=intake.percent_pack,
        created_at=intake.created_at,
        estimated=intake.estimated,
        estimate_confidence=intake.estimate_confidence,
        user_description=intake.user_description,
        source_method=intake.source_method,
        nutrients=nutrients,
    )


@router.delete("/intakes/{intake_id}", response_model=IntakeDeleteResponse)
def delete_intake(
    intake_id: int,
    current_user: Annotated[UserAccount, Depends(get_ready_user)],
    session: Annotated[Session, Depends(get_session)],
) -> IntakeDeleteResponse:
    intake = session.get(Intake, intake_id)
    if intake is None or intake.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intake not found")

    session.delete(intake)
    session.commit()
    return IntakeDeleteResponse(deleted=True, intake_id=intake_id)


def _day_summary(
    day: date,
    current_user: Annotated[UserAccount, Depends(get_ready_user)],
    session: Annotated[Session, Depends(get_session)],
    include_intakes: bool = True,
) -> DaySummary:
    start_dt = datetime.combine(day, time.min).replace(tzinfo=UTC)
    end_dt = datetime.combine(day + timedelta(days=1), time.min).replace(tzinfo=UTC)

    intakes = session.exec(
        select(Intake)
        .where(Intake.user_id == current_user.id)
        .where(Intake.created_at >= start_dt)
        .where(Intake.created_at < end_dt)
        .order_by(desc(Intake.created_at))
    ).all()

    consumed = zero_nutrients()
    rows: list[IntakeRead] = []
    product_cache: dict[int, Product] = {}
    product_ids = {intake.product_id for intake in intakes}
    if product_ids:
        products = session.exec(select(Product).where(Product.id.in_(product_ids))).all()
        product_cache = {product.id: product for product in products if product.id is not None}

    for intake in intakes:
        product = product_cache.get(intake.product_id)

        if not product or intake.quantity_g is None:
            continue

        nutrients = nutrients_for_quantity(product, intake.quantity_g)
        consumed = sum_nutrients(consumed, nutrients)
        if include_intakes:
            rows.append(
                IntakeRead(
                    id=intake.id,
                    product_id=intake.product_id,
                    product_name=product.name,
                    method=intake.method,
                    quantity_g=intake.quantity_g,
                    quantity_units=intake.quantity_units,
                    percent_pack=intake.percent_pack,
                    created_at=intake.created_at,
                    estimated=intake.estimated,
                    estimate_confidence=intake.estimate_confidence,
                    user_description=intake.user_description,
                    source_method=intake.source_method,
                    nutrients=nutrients,
                )
            )

    goal = session.exec(
        select(DailyGoal).where(DailyGoal.user_id == current_user.id).where(DailyGoal.date == day)
    ).first()

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

    water_rows = session.exec(
        select(WaterIntakeLog.ml)
        .where(WaterIntakeLog.user_id == current_user.id)
        .where(WaterIntakeLog.created_at >= start_dt)
        .where(WaterIntakeLog.created_at < end_dt)
    ).all()
    water_ml = int(sum(water_rows))

    return DaySummary(
        date=day,
        goal=goal_payload,
        consumed=consumed,
        remaining=remaining,
        intakes=rows if include_intakes else [],
        water_ml=water_ml,
    )


@router.get("/days/{day}/summary", response_model=DaySummary)
def day_summary(
    day: date,
    current_user: Annotated[UserAccount, Depends(get_ready_user)],
    session: Annotated[Session, Depends(get_session)],
) -> DaySummary:
    return _day_summary(day=day, current_user=current_user, session=session)


@router.get("/days/{day}", response_model=DaySummary)
def day_summary_legacy(
    day: date,
    current_user: Annotated[UserAccount, Depends(get_ready_user)],
    session: Annotated[Session, Depends(get_session)],
) -> DaySummary:
    return _day_summary(day=day, current_user=current_user, session=session)


@router.get("/widget/summary/today", response_model=WidgetTodaySummaryResponse)
def widget_today_summary(
    current_user: Annotated[UserAccount, Depends(get_ready_user)],
    session: Annotated[Session, Depends(get_session)],
) -> WidgetTodaySummaryResponse:
    today = datetime.now(UTC).date()
    summary = _day_summary(day=today, current_user=current_user, session=session)

    latest_weight = session.exec(
        select(BodyWeightLog)
        .where(BodyWeightLog.user_id == current_user.id)
        .order_by(desc(BodyWeightLog.created_at))
    ).first()

    protein_goal = summary.goal.protein_goal if summary.goal else 0.0
    kcal_goal = summary.goal.kcal_goal if summary.goal else 0.0
    kcal_remaining = max(kcal_goal - summary.consumed.kcal, 0.0)

    return WidgetTodaySummaryResponse(
        date=today,
        kcal_remaining=round(kcal_remaining, 2),
        protein_consumed_g=round(summary.consumed.protein_g, 2),
        protein_goal_g=round(protein_goal, 2),
        water_ml=summary.water_ml,
        latest_weight_kg=latest_weight.weight_kg if latest_weight else None,
    )


@router.post("/goals/{day}", response_model=DailyGoalResponse)
def upsert_daily_goal(
    day: date,
    payload: DailyGoalUpsert,
    current_user: Annotated[UserAccount, Depends(get_verified_user)],
    session: Annotated[Session, Depends(get_session)],
) -> DailyGoalResponse:
    profile = _load_profile_or_404(session, current_user.id)

    existing = session.exec(
        select(DailyGoal).where(DailyGoal.user_id == current_user.id).where(DailyGoal.date == day)
    ).first()

    if existing:
        existing.kcal_goal = payload.kcal_goal
        existing.protein_goal = payload.protein_goal
        existing.fat_goal = payload.fat_goal
        existing.carbs_goal = payload.carbs_goal
    else:
        session.add(
            DailyGoal(
                user_id=current_user.id,
                date=day,
                kcal_goal=payload.kcal_goal,
                protein_goal=payload.protein_goal,
                fat_goal=payload.fat_goal,
                carbs_goal=payload.carbs_goal,
            )
        )

    if not current_user.onboarding_completed:
        current_user.onboarding_completed = True
        session.add(current_user)

    session.commit()

    recommended = recommended_goals(profile)
    feedback_payload = GoalFeedback(
        **goal_feedback(
            profile,
            payload.model_dump(),
            recommended,
        )
    )

    return DailyGoalResponse(
        kcal_goal=payload.kcal_goal,
        protein_goal=payload.protein_goal,
        fat_goal=payload.fat_goal,
        carbs_goal=payload.carbs_goal,
        feedback=feedback_payload,
    )


@router.get("/goals/{day}", response_model=DailyGoalResponse | None)
def get_daily_goal(
    day: date,
    current_user: Annotated[UserAccount, Depends(get_verified_user)],
    session: Annotated[Session, Depends(get_session)],
) -> DailyGoalResponse | None:
    profile = _load_profile_or_404(session, current_user.id)
    goal = session.exec(
        select(DailyGoal).where(DailyGoal.user_id == current_user.id).where(DailyGoal.date == day)
    ).first()
    if not goal:
        return None

    recommended = recommended_goals(profile)
    feedback_payload = GoalFeedback(
        **goal_feedback(
            profile,
            {
                "kcal_goal": goal.kcal_goal,
                "protein_goal": goal.protein_goal,
                "fat_goal": goal.fat_goal,
                "carbs_goal": goal.carbs_goal,
            },
            recommended,
        )
    )

    return DailyGoalResponse(
        kcal_goal=goal.kcal_goal,
        protein_goal=goal.protein_goal,
        fat_goal=goal.fat_goal,
        carbs_goal=goal.carbs_goal,
        feedback=feedback_payload,
    )


@router.get("/calendar/{year_month}", response_model=CalendarMonthResponse)
def month_calendar(
    year_month: str,
    current_user: Annotated[UserAccount, Depends(get_ready_user)],
    session: Annotated[Session, Depends(get_session)],
) -> CalendarMonthResponse:
    if not MONTH_PATTERN.match(year_month):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid format. Use YYYY-MM")

    year, month = map(int, year_month.split("-"))
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)

    start_dt = datetime.combine(start_date, time.min).replace(tzinfo=UTC)
    end_dt = datetime.combine(end_date, time.min).replace(tzinfo=UTC)

    intakes = session.exec(
        select(Intake)
        .where(Intake.user_id == current_user.id)
        .where(Intake.created_at >= start_dt)
        .where(Intake.created_at < end_dt)
    ).all()

    stats: dict[date, dict[str, float | int | None]] = {}

    def ensure_bucket(entry_day: date) -> dict[str, float | int | None]:
        return stats.setdefault(
            entry_day,
            {
                "count": 0,
                "kcal": 0.0,
                "protein_g": 0.0,
                "protein_goal_g": None,
                "weight_kg": None,
            },
        )

    product_ids = {intake.product_id for intake in intakes}
    products: dict[int, Product] = {}
    if product_ids:
        rows = session.exec(select(Product).where(Product.id.in_(product_ids))).all()
        products = {row.id: row for row in rows}

    for intake in intakes:
        day = _to_utc(intake.created_at).date()
        bucket = ensure_bucket(day)
        bucket["count"] += 1

        product = products.get(intake.product_id)

        if product and intake.quantity_g is not None:
            nutrients = nutrients_for_quantity(product, intake.quantity_g)
            bucket["kcal"] = round(bucket["kcal"] + nutrients["kcal"], 2)
            bucket["protein_g"] = round(float(bucket["protein_g"]) + nutrients["protein_g"], 2)

    goals = session.exec(
        select(DailyGoal)
        .where(DailyGoal.user_id == current_user.id)
        .where(DailyGoal.date >= start_date)
        .where(DailyGoal.date < end_date)
    ).all()
    for goal in goals:
        bucket = ensure_bucket(goal.date)
        bucket["protein_goal_g"] = float(goal.protein_goal)

    weights = session.exec(
        select(BodyWeightLog)
        .where(BodyWeightLog.user_id == current_user.id)
        .where(BodyWeightLog.created_at >= start_dt)
        .where(BodyWeightLog.created_at < end_dt)
        .order_by(desc(BodyWeightLog.created_at))
    ).all()
    for entry in weights:
        day = _to_utc(entry.created_at).date()
        bucket = ensure_bucket(day)
        if bucket["weight_kg"] is None:
            bucket["weight_kg"] = float(entry.weight_kg)

    days = [
        CalendarDayEntry(
            date=entry_day,
            intake_count=int(values["count"]),
            kcal=float(values["kcal"]),
            protein_g=float(values["protein_g"]),
            protein_goal_g=float(values["protein_goal_g"]) if values["protein_goal_g"] is not None else None,
            weight_kg=float(values["weight_kg"]) if values["weight_kg"] is not None else None,
        )
        for entry_day, values in sorted(stats.items(), key=lambda item: item[0])
    ]

    return CalendarMonthResponse(month=year_month, days=days)

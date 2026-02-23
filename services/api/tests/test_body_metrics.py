from app.models import Sex, UserProfile
from app.services.body_metrics import bmi, bmi_category, body_fat_percent


def test_bmi_calculation_and_category():
    result = bmi(80, 180)
    assert result == 24.69

    label, color = bmi_category(result)
    assert label == "normal"
    assert color


def test_body_fat_us_navy_male_example():
    profile = UserProfile(
        user_id=1,
        weight_kg=80,
        height_cm=180,
        sex=Sex.male,
        waist_cm=90,
        neck_cm=40,
    )

    result = body_fat_percent(profile)
    assert result is not None
    assert abs(result - 11.96) < 0.2


def test_body_fat_us_navy_female_example():
    profile = UserProfile(
        user_id=2,
        weight_kg=65,
        height_cm=165,
        sex=Sex.female,
        waist_cm=90,
        neck_cm=33,
        hip_cm=102,
    )

    result = body_fat_percent(profile)
    assert result is not None
    assert abs(result - 13.69) < 0.2


def test_body_fat_requires_measurements():
    profile = UserProfile(
        user_id=3,
        weight_kg=77,
        height_cm=179,
        sex=Sex.male,
    )

    assert body_fat_percent(profile) is None

from datetime import date
from uuid import uuid4


def test_auth_state_transitions_and_onboarding_completion(client):
    email = f"new-{uuid4().hex[:8]}@example.com"

    register_response = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "supersecret123",
        },
    )
    assert register_response.status_code == 200
    register_body = register_response.json()

    assert register_body["email_verified"] is False
    assert register_body["onboarding_completed"] is False
    assert register_body["debug_verification_code"] is not None

    login_response = client.post(
        "/auth/login",
        json={"email": email, "password": "supersecret123"},
    )
    assert login_response.status_code == 200
    login_body = login_response.json()
    assert login_body["user"]["email_verified"] is False
    assert login_body["user"]["onboarding_completed"] is False

    token = login_body["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me_before_verify = client.get("/me", headers=headers)
    assert me_before_verify.status_code == 200
    assert me_before_verify.json()["user"]["email_verified"] is False

    verify_response = client.post(
        "/auth/verify",
        json={"email": email, "code": register_body["debug_verification_code"]},
    )
    assert verify_response.status_code == 200
    verify_body = verify_response.json()
    assert verify_body["user"]["email_verified"] is True
    assert verify_body["user"]["onboarding_completed"] is False

    verified_headers = {"Authorization": f"Bearer {verify_body['access_token']}"}

    profile_response = client.post(
        "/profile",
        headers=verified_headers,
        json={
            "weight_kg": 82,
            "height_cm": 180,
            "age": 31,
            "sex": "male",
            "activity_level": "moderate",
            "goal_type": "lose",
            "waist_cm": 90,
            "neck_cm": 39,
        },
    )
    assert profile_response.status_code == 200
    profile = profile_response.json()
    assert profile["bmi"] > 0
    assert profile["bmi_category"] in {"underweight", "normal", "overweight", "obesity"}

    analysis_response = client.get(f"/me/analysis?day={date.today().isoformat()}", headers=verified_headers)
    assert analysis_response.status_code == 200
    assert analysis_response.json()["recommended_goal"]["kcal_goal"] > 0

    goal_response = client.post(
        f"/goals/{date.today().isoformat()}",
        headers=verified_headers,
        json={
            "kcal_goal": 2100,
            "protein_goal": 150,
            "fat_goal": 68,
            "carbs_goal": 220,
        },
    )
    assert goal_response.status_code == 200

    me_after_goal = client.get("/me", headers=verified_headers)
    assert me_after_goal.status_code == 200
    assert me_after_goal.json()["user"]["onboarding_completed"] is True

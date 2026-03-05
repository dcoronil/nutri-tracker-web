from app.models import NutritionBasis


def _register_ready_user(client, *, email: str, password: str = "supersecret123") -> tuple[dict[str, str], int]:
    local_part = email.split("@")[0].lower().replace("-", "_").replace("+", "_").replace(".", "_")
    username = f"user_{local_part[:20]}"
    register = client.post(
        "/auth/register",
        json={
            "username": username,
            "email": email,
            "password": password,
            "sex": "male",
            "birth_date": "1993-08-17",
        },
    )
    assert register.status_code == 200
    code = register.json()["debug_verification_code"]

    verify = client.post("/auth/verify", json={"email": email, "code": code})
    assert verify.status_code == 200
    token = verify.json()["access_token"]
    user_id = verify.json()["user"]["id"]
    headers = {"Authorization": f"Bearer {token}"}

    profile = client.post(
        "/profile",
        headers=headers,
        json={
            "weight_kg": 70,
            "height_cm": 175,
            "age": 30,
            "sex": "male",
            "activity_level": "moderate",
            "goal_type": "maintain",
        },
    )
    assert profile.status_code == 200

    goals = client.post(
        "/goals/2026-02-26",
        headers=headers,
        json={
            "kcal_goal": 2200,
            "protein_goal": 140,
            "fat_goal": 70,
            "carbs_goal": 230,
        },
    )
    assert goals.status_code == 200

    return headers, user_id


def test_create_community_food_and_search(client, auth_headers):
    create = client.post(
        "/foods/community",
        json={
            "name": "Pan integral casero",
            "brand": "Comunidad",
            "barcode": "1234567890123",
            "nutrition_basis": "per_100g",
            "kcal": 260,
            "protein_g": 9.8,
            "fat_g": 3.4,
            "carbs_g": 46.0,
            "fiber_g": 6.3,
            "salt_g": 0.8,
        },
        headers=auth_headers,
    )
    assert create.status_code == 200
    body = create.json()
    assert body["source"] == "community"
    assert body["created_by_user_id"] is not None
    assert body["is_public"] is True

    search = client.get("/foods/search?q=pan", headers=auth_headers)
    assert search.status_code == 200
    payload = search.json()
    assert payload["query"] == "pan"
    assert any(item["product"]["id"] == body["id"] and item["badge"] == "Comunidad" for item in payload["results"])


def test_create_community_food_barcode_conflict(client, auth_headers):
    base_payload = {
        "name": "Yogur 0%",
        "brand": "Comunidad",
        "barcode": "7611111111111",
        "nutrition_basis": "per_100g",
        "kcal": 58,
        "protein_g": 10.0,
        "fat_g": 0.1,
        "carbs_g": 3.2,
    }

    first = client.post("/foods/community", json=base_payload, headers=auth_headers)
    assert first.status_code == 200

    second = client.post("/foods/community", json=base_payload, headers=auth_headers)
    assert second.status_code == 409


def test_search_foods_imports_openfoodfacts_for_barcode(monkeypatch, client, auth_headers):
    async def _mock_fetch(_ean: str):
        return {
            "barcode": "76199999",
            "name": "Barra OFF",
            "brand": "OFF",
            "image_url": "https://example.com/off.jpg",
            "nutrition_basis": NutritionBasis.per_100g,
            "serving_size_g": 30,
            "net_weight_g": 90,
            "kcal": 410,
            "protein_g": 8,
            "fat_g": 14,
            "sat_fat_g": 5,
            "carbs_g": 62,
            "sugars_g": 27,
            "fiber_g": 2,
            "salt_g": 0.4,
        }

    monkeypatch.setattr("app.api.routes.fetch_openfoodfacts_product", _mock_fetch)

    search = client.get("/foods/search?q=76199999", headers=auth_headers)
    assert search.status_code == 200
    payload = search.json()
    assert payload["results"]
    first = payload["results"][0]
    assert first["product"]["barcode"] == "76199999"
    assert first["badge"] == "Importado"
    assert first["origin"] == "local"


def test_search_foods_uses_openfoodfacts_text_search(monkeypatch, client, auth_headers):
    async def _fail_fetch(_ean: str):
        raise AssertionError("Barcode endpoint should not be used for text queries")

    async def _mock_search(query: str, *, limit: int = 20):
        assert query == "danone"
        assert limit >= 20
        return [
            {
                "barcode": "8410000000001",
                "name": "Danone Natural",
                "brand": "Danone",
                "image_url": "https://example.com/danone.jpg",
                "nutrition_basis": NutritionBasis.per_100g,
                "kcal": 64,
                "protein_g": 4.3,
                "fat_g": 2.8,
                "carbs_g": 5.1,
            }
        ]

    monkeypatch.setattr("app.api.routes.fetch_openfoodfacts_product", _fail_fetch)
    monkeypatch.setattr("app.api.routes.search_openfoodfacts_products", _mock_search)

    response = client.get("/foods/search?q=danone", headers=auth_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["results"]
    first = payload["results"][0]
    assert first["product"]["name"] == "Danone Natural"
    assert first["product"]["brand"] == "Danone"
    assert first["product"]["image_url"] == "https://example.com/danone.jpg"
    assert first["badge"] == "Importado"
    assert first["origin"] == "openfoodfacts_remote"


def test_search_foods_fuzzy_typo_matches_local_product(client, auth_headers):
    create = client.post(
        "/foods/community",
        json={
            "name": "Danone Natural Proteico",
            "brand": "Danone",
            "nutrition_basis": "per_100g",
            "kcal": 66,
            "protein_g": 5.1,
            "fat_g": 2.9,
            "carbs_g": 4.6,
        },
        headers=auth_headers,
    )
    assert create.status_code == 200

    response = client.get("/foods/search?q=danonne", headers=auth_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["results"]
    assert any(item["product"]["name"] == "Danone Natural Proteico" for item in payload["results"])


def test_search_foods_returns_public_community_from_other_user(client, auth_headers):
    other_headers, other_user_id = _register_ready_user(client, email="other-user@example.com")
    created = client.post(
        "/foods/community",
        json={
            "name": "Yogur Griego Comunidad",
            "brand": "Marca Vecina",
            "nutrition_basis": "per_100g",
            "kcal": 95,
            "protein_g": 9.0,
            "fat_g": 4.0,
            "carbs_g": 5.0,
        },
        headers=other_headers,
    )
    assert created.status_code == 200

    search = client.get("/foods/search?q=griego", headers=auth_headers)
    assert search.status_code == 200
    payload = search.json()
    assert payload["results"]
    assert any(
        item["product"]["name"] == "Yogur Griego Comunidad" and item["product"]["created_by_user_id"] == other_user_id
        for item in payload["results"]
    )


def test_search_foods_skips_remote_when_local_results_are_strong(monkeypatch, client, auth_headers):
    for index in range(6):
        response = client.post(
            "/foods/community",
            json={
                "name": f"Danone Natural {index}",
                "brand": "Danone",
                "nutrition_basis": "per_100g",
                "kcal": 62 + index,
                "protein_g": 4.0 + (index * 0.1),
                "fat_g": 2.0 + (index * 0.1),
                "carbs_g": 4.9,
            },
            headers=auth_headers,
        )
        assert response.status_code == 200

    async def _unexpected_remote(*_args, **_kwargs):
        raise AssertionError("Remote text search should not run when local results are already strong")

    monkeypatch.setattr("app.api.routes.search_openfoodfacts_products", _unexpected_remote)

    search = client.get("/foods/search?q=danone", headers=auth_headers)
    assert search.status_code == 200
    rows = search.json()["results"]
    assert rows
    assert all(item["origin"] == "local" for item in rows[:6])


def test_search_foods_remote_results_prioritize_spain(monkeypatch, client, auth_headers):
    async def _mock_search(query: str, *, limit: int = 20):
        assert query == "danone"
        assert limit >= 16
        return [
            {
                "barcode": "4000000000001",
                "name": "Danone Nature FR",
                "brand": "Danone",
                "image_url": "https://example.com/fr.jpg",
                "nutrition_basis": NutritionBasis.per_100g,
                "kcal": 66,
                "protein_g": 4.1,
                "fat_g": 2.8,
                "carbs_g": 5.0,
                "lang": "fr",
                "countries_tags": ["en:france"],
                "countries": "France",
            },
            {
                "barcode": "8410000000002",
                "name": "Danone Natural ES",
                "brand": "Danone",
                "image_url": "https://example.com/es.jpg",
                "nutrition_basis": NutritionBasis.per_100g,
                "kcal": 64,
                "protein_g": 4.3,
                "fat_g": 2.7,
                "carbs_g": 5.1,
                "lang": "es",
                "countries_tags": ["en:spain"],
                "countries": "Spain",
            },
        ]

    monkeypatch.setattr("app.api.routes.search_openfoodfacts_products", _mock_search)

    search = client.get("/foods/search?q=danone", headers=auth_headers)
    assert search.status_code == 200
    rows = search.json()["results"]
    assert rows
    assert rows[0]["origin"] == "openfoodfacts_remote"
    assert rows[0]["product"]["barcode"] == "8410000000002"

from datetime import date, timedelta


def _recipe_payload(title: str = "Bowl de avena") -> dict:
    return {
        "title": title,
        "meal_type": "breakfast",
        "servings": 2,
        "prep_time_min": 10,
        "ingredients": [
            {"name": "Avena", "quantity": 80, "unit": "g"},
            {"name": "Leche", "quantity": 300, "unit": "ml"},
            {"name": "Platano", "quantity": 1, "unit": "ud"},
        ],
        "steps": ["Mezcla todo", "Sirve en un bowl"],
        "tags": ["quick"],
        "nutrition_kcal": 460,
        "nutrition_protein_g": 28,
        "nutrition_carbs_g": 56,
        "nutrition_fat_g": 12,
    }


def test_weekly_meal_plan_and_shopping_list(client, auth_headers):
    recipe_response = client.post("/recipes", json=_recipe_payload(), headers=auth_headers)
    assert recipe_response.status_code == 200
    recipe = recipe_response.json()

    product_response = client.post(
        "/foods/community",
        json={
            "name": "Skyr natural",
            "brand": "Lidl",
            "nutrition_basis": "per_serving",
            "serving_size_g": 1,
            "kcal": 97,
            "protein_g": 17,
            "fat_g": 0.2,
            "carbs_g": 6,
        },
        headers=auth_headers,
    )
    assert product_response.status_code == 200
    product = product_response.json()

    monday = date.today() - timedelta(days=date.today().weekday())

    first_entry = client.post(
        "/meal-plan/entries",
        json={
            "planned_date": monday.isoformat(),
            "meal_type": "breakfast",
            "recipe_id": recipe["id"],
            "servings": 3,
            "note": "Pre entreno",
        },
        headers=auth_headers,
    )
    assert first_entry.status_code == 200
    created_recipe_entry = first_entry.json()
    assert created_recipe_entry["source_type"] == "recipe"
    assert created_recipe_entry["title"] == "Bowl de avena"
    assert created_recipe_entry["recipe"]["id"] == recipe["id"]

    second_entry = client.post(
        "/meal-plan/entries",
        json={
            "planned_date": (monday + timedelta(days=1)).isoformat(),
            "meal_type": "snack",
            "product_id": product["id"],
            "servings": 2,
        },
        headers=auth_headers,
    )
    assert second_entry.status_code == 200
    created_product_entry = second_entry.json()
    assert created_product_entry["source_type"] == "product"
    assert created_product_entry["product"]["id"] == product["id"]

    week_response = client.get(f"/meal-plan/week/{monday.isoformat()}", headers=auth_headers)
    assert week_response.status_code == 200
    week = week_response.json()
    assert week["week_start"] == monday.isoformat()
    assert len(week["days"]) == 7
    assert len(week["days"][0]["entries"]) == 1
    assert len(week["days"][1]["entries"]) == 1

    shopping_response = client.get(f"/meal-plan/week/{monday.isoformat()}/shopping-list", headers=auth_headers)
    assert shopping_response.status_code == 200
    shopping = shopping_response.json()
    assert shopping["planned_entry_count"] == 2
    by_name = {item["name"]: item for item in shopping["items"]}
    assert by_name["Avena"]["quantity"] == 120.0
    assert by_name["Leche"]["quantity"] == 450.0
    assert by_name["Platano"]["quantity"] == 1.5
    assert by_name["Skyr natural"]["quantity"] == 2.0
    assert by_name["Skyr natural"]["unit"] == "ud"

    delete_response = client.delete(f"/meal-plan/entries/{created_product_entry['id']}", headers=auth_headers)
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True


def test_meal_plan_upsert_replaces_same_slot(client, auth_headers):
    recipe_response = client.post("/recipes", json=_recipe_payload("Crema de arroz"), headers=auth_headers)
    assert recipe_response.status_code == 200
    recipe = recipe_response.json()

    monday = date.today() - timedelta(days=date.today().weekday())

    first_save = client.post(
        "/meal-plan/entries",
        json={
            "planned_date": monday.isoformat(),
            "meal_type": "breakfast",
            "recipe_id": recipe["id"],
            "servings": 1,
        },
        headers=auth_headers,
    )
    assert first_save.status_code == 200
    first_id = first_save.json()["id"]

    second_save = client.post(
        "/meal-plan/entries",
        json={
            "planned_date": monday.isoformat(),
            "meal_type": "breakfast",
            "recipe_id": recipe["id"],
            "servings": 2,
            "note": "Duplicado controlado",
        },
        headers=auth_headers,
    )
    assert second_save.status_code == 200
    updated = second_save.json()
    assert updated["id"] == first_id
    assert updated["servings"] == 2
    assert updated["note"] == "Duplicado controlado"

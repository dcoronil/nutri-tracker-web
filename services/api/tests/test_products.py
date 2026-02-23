from app.models import NutritionBasis


def test_lookup_local_product(client):
    payload = {
        "barcode": "12345678",
        "name": "Yogur griego",
        "brand": "Marca X",
        "nutrition_basis": NutritionBasis.per_100g.value,
        "label_text": "Por 100 g Energía 120 kcal Proteínas 8 g Grasas 4 g Carbohidratos 10 g",
    }

    create_response = client.post("/products/from_label_photo", data=payload)
    assert create_response.status_code == 200
    assert create_response.json()["created"] is True

    lookup = client.get("/products/by_barcode/12345678")
    assert lookup.status_code == 200
    body = lookup.json()
    assert body["source"] == "local"
    assert body["product"]["name"] == "Yogur griego"


def test_lookup_openfoodfacts_import(monkeypatch, client):
    async def _mock_fetch(_ean: str):
        return {
            "barcode": "76111111",
            "name": "Barrita",
            "brand": "Demo",
            "nutrition_basis": NutritionBasis.per_100g,
            "serving_size_g": 30,
            "net_weight_g": 90,
            "kcal": 420,
            "protein_g": 10,
            "fat_g": 15,
            "sat_fat_g": 4,
            "carbs_g": 60,
            "sugars_g": 20,
            "fiber_g": 3,
            "salt_g": 0.3,
        }

    monkeypatch.setattr("app.api.routes.fetch_openfoodfacts_product", _mock_fetch)

    response = client.get("/products/by_barcode/76111111")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "openfoodfacts_imported"
    assert body["product"]["barcode"] == "76111111"


def test_label_photo_missing_fields(client):
    payload = {
        "name": "Producto incompleto",
        "label_text": "Por 100 g Energía 180 kcal Proteínas 5 g",
    }

    response = client.post("/products/from_label_photo", data=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["created"] is False
    assert "fat_g" in body["missing_fields"]
    assert "carbs_g" in body["missing_fields"]

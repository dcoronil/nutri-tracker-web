from app.models import NutritionBasis


def test_lookup_local_product(client, auth_headers):
    payload = {
        "barcode": "12345678",
        "name": "Yogur griego",
        "brand": "Marca X",
        "nutrition_basis": NutritionBasis.per_100g.value,
        "label_text": "Por 100 g Energía 120 kcal Proteínas 8 g Grasas 4 g Carbohidratos 10 g",
    }

    create_response = client.post("/products/from_label_photo", data=payload, headers=auth_headers)
    assert create_response.status_code == 200
    assert create_response.json()["created"] is True

    lookup = client.get("/products/by_barcode/12345678", headers=auth_headers)
    assert lookup.status_code == 200
    body = lookup.json()
    assert body["source"] == "local"
    assert body["product"]["name"] == "Yogur griego"


def test_lookup_openfoodfacts_import(monkeypatch, client, auth_headers):
    async def _mock_fetch(_ean: str):
        return {
            "barcode": "76111111",
            "name": "Barrita",
            "brand": "Demo",
            "image_url": "https://images.openfoodfacts.org/images/products/761/111/11/front_es.3.400.jpg",
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

    response = client.get("/products/by_barcode/76111111", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "openfoodfacts_imported"
    assert body["product"]["barcode"] == "76111111"
    assert body["product"]["image_url"] is not None


def test_label_photo_missing_fields(client, auth_headers):
    payload = {
        "name": "Producto incompleto",
        "label_text": "Por 100 g Energía 180 kcal Proteínas 5 g",
    }

    response = client.post("/products/from_label_photo", data=payload, headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["created"] is False
    assert "fat_g" in body["missing_fields"]
    assert "carbs_g" in body["missing_fields"]


def test_local_manual_product_does_not_mix_with_openfoodfacts_image(monkeypatch, client, auth_headers):
    payload = {
        "barcode": "99001122",
        "name": "Producto manual",
        "brand": "Casa",
        "nutrition_basis": NutritionBasis.per_100g.value,
        "label_text": "Por 100 g Energía 250 kcal Proteínas 11 g Grasas 9 g Carbohidratos 30 g",
    }
    create_response = client.post("/products/from_label_photo", data=payload, headers=auth_headers)
    assert create_response.status_code == 200
    assert create_response.json()["created"] is True

    async def _fail_if_called(_ean: str):
        raise AssertionError("OpenFoodFacts should not be called for label/manual product")

    monkeypatch.setattr("app.api.routes.fetch_openfoodfacts_product", _fail_if_called)

    lookup = client.get("/products/by_barcode/99001122", headers=auth_headers)
    assert lookup.status_code == 200
    body = lookup.json()
    assert body["source"] == "local"
    assert body["product"]["name"] == "Producto manual"
    assert body["product"]["image_url"] is None

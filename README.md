# Nutri Tracker MVP

MVP funcional para tracking nutricional personal con flujo completo:

- Escaneo EAN/UPC (mobile)
- Búsqueda local en Postgres + fallback OpenFoodFacts
- Importación automática si hay nutrición suficiente
- Captura de etiqueta (foto + OCR opcional + preguntas de validación)
- Registro de intakes
- Dashboard diario con objetivos y restante

## Estructura

```text
/apps/mobile   # React Native Expo
/services/api  # FastAPI + SQLModel + Alembic + pytest
/infra         # docker-compose para Postgres
```

## Requisitos

- Docker + Docker Compose
- Python 3.11+
- Node 20+
- npm 10+

## 1) Variables de entorno

Copia el ejemplo raíz:

```bash
cp .env.example .env
```

Opcionalmente, usa los ejemplos por servicio:

- `services/api/.env.example`
- `apps/mobile/.env.example`

## 2) Levantar Postgres

```bash
cd infra
docker compose up -d
```

## 3) Backend (FastAPI)

```bash
cd services/api
python3 -m pip install --break-system-packages -e '.[dev]'
export $(grep -v '^#' ../../.env | xargs)
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Endpoints disponibles:

- `GET /health`
- `GET /products/by_barcode/{ean}`
- `POST /products/from_label_photo`
- `POST /intakes`
- `GET /days/{yyyy-mm-dd}/summary`
- `POST /goals/{yyyy-mm-dd}`

## 4) Mobile (Expo)

```bash
cd apps/mobile
npm install
cp .env.example .env
npm run start
```

Si corres Expo en emulador Android, normalmente conviene usar `EXPO_PUBLIC_API_BASE_URL=http://10.0.2.2:8000`.

## 5) Tests y lint backend

```bash
cd services/api
python3 -m pytest -q
python3 -m ruff check .
```

## Notas del flujo de etiqueta

- `POST /products/from_label_photo` acepta `multipart/form-data` con:
  - `barcode`, `name`, `brand`
  - `label_text` (OCR manual/opcional)
  - `photos` (lista de imágenes)
- Si faltan campos críticos (`kcal`, `protein_g`, `fat_g`, `carbs_g`, `nutrition_basis`), la API devuelve `questions` para completar desde el cliente.
- OCR con `pytesseract` es opcional y depende de tener instalado el binario `tesseract` en el sistema.

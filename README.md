# NutriTracker — Aplicación de nutrición y documentación de calidad de datos

Este repositorio contiene el proyecto **NutriTracker**, una aplicación orientada al seguimiento nutricional personal, junto con la documentación del trabajo de **Gestión de la Calidad de Datos** realizado con **OpenMetadata**.

La aplicación permite registrar usuarios, perfiles físicos, alimentos, ingestas, objetivos diarios y evolución corporal. Sobre esta base se ha realizado un análisis de calidad del dato, documentando las principales entidades, el glosario de negocio y las reglas de calidad configuradas en OpenMetadata.

---

## Estructura del repositorio

```text
apps/mobile
services/api
infra
docs
```

- `apps/mobile`: aplicación móvil desarrollada con Expo React Native.
- `services/api`: backend desarrollado con FastAPI, SQLModel, Alembic y pytest.
- `infra`: configuración de PostgreSQL mediante Docker Compose.
- `docs`: documentación del trabajo de calidad de datos con OpenMetadata.

---

## Documentación del trabajo de OpenMetadata

Dentro de la carpeta `docs` se incluye la documentación asociada a la práctica:

```text
docs/
├── manual-openmetadata.md
└── informe-final.pdf
```

### Documentos incluidos

- `manual-openmetadata.md`: manual de usuario de OpenMetadata aplicado a NutriTracker. Explica cómo acceder a la herramienta, consultar entidades, revisar el glosario y gestionar reglas de calidad.
- `informe-final.pdf`: informe técnico final del trabajo, con las secciones realizadas por los tres miembros del grupo.

---

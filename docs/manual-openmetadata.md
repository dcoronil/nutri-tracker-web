# Manual de Usuario — OpenMetadata

## Índice

1. Acceso a OpenMetadata
2. Navegación por la interfaz
3. Ver las entidades modeladas (tablas)
4. Ver el glosario de términos
5. Ver y gestionar las reglas de calidad
6. Cómo ejecutar los tests de calidad
7. Cómo añadir un nuevo término al glosario
8. Cómo añadir una nueva regla de calidad

---

## 1. Acceso a OpenMetadata

OpenMetadata es la plataforma de gobernanza del dato utilizada en este proyecto para documentar las entidades, el glosario y las reglas de calidad de NutriTracker.

**URL de acceso:**

http://localhost:8585

**Credenciales:**

- usuario: rsantervastorres@al.uloyola.es
- contraseña: "contactar con ese usuario para conocer la contraseña"

OpenMetadata debe estar arrancado mediante Docker antes de acceder. Si la página no carga, ejecuta docker compose up -d en el directorio de instalación.

---

## 2. Navegación por la interfaz

Una vez dentro, la barra lateral izquierda es el punto de entrada a todas las funciones. La interfaz está en español:

| Sección en la interfaz | Para qué sirve |
|---|---|
| 🏠 Inicio | Panel principal con actividad reciente y activos destacados |
| 🔍 Explorar | Buscar y navegar todas las tablas registradas de la BD |
| 🔗 Linaje | Ver las relaciones y flujo de datos entre tablas |
| 👁️ Observabilidad | Acceder a los Tests de calidad (Casos de Prueba y Suites de Pruebas) |
| 📊 Perspectivas | Dashboards y métricas de cobertura de calidad |
| 🌐 Dominios | Organización de activos por dominio de negocio |
| 🏛️ Gobernar | Glosario de términos, clasificaciones y políticas |
| ⚙️ Configuraciones | Servicios de BD, usuarios, roles y conexiones |

💡 Importante: En esta instalación, las reglas de calidad se encuentran en Observabilidad, no en una pestaña dentro de las tablas. La URL directa es: http://localhost:8585/data-quality/test-cases

---

## 3. Ver las entidades modeladas (tablas)

### Cómo acceder

1. Clic en Explorar en la barra lateral izquierda.
2. En el panel que se abre, selecciona la categoría Tables.
3. Verás el listado de todas las tablas descubiertas de la base de datos PostgreSQL de NutriTracker.

### Tablas registradas en NutriTracker

| Tabla | Descripción |
|---|---|
| user_account | Identidad y credenciales de los usuarios registrados |
| user_profile | Métricas físicas del usuario (peso, altura, IMC) |
| product | Catálogo maestro de alimentos con sus macronutrientes |
| intake | Registros de consumo de alimentos por usuario y fecha |
| daily_goal | Objetivos calóricos y nutricionales diarios por usuario |
| meal_plan_entry | Entradas del plan dietético estructurado |
| body_weight_log | Histórico de peso corporal del usuario |

### Cómo ver el detalle de una tabla

Clic sobre el nombre de la tabla (por ejemplo, intake).

Se abre la vista de detalle con las siguientes pestañas:

- Schema → columnas, tipos de dato, descripciones y tags PII
- Activity → historial de cambios
- Sample Data → muestra de datos reales (si la ingesta lo permite)
- Lineage → relaciones con otras tablas

### Campos sensibles (PII) marcados

Los siguientes campos están etiquetados con PII.Sensitive en OpenMetadata:

| Tabla | Campo | Motivo |
|---|---|---|
| user_account | email | Dato identificativo personal |
| user_account | password_hash | Credencial de seguridad |
| user_profile | weight_kg | Dato de salud |
| user_profile | height_cm | Dato de salud |
| user_profile | body_fat_percent | Dato de salud sensible |


---

## 4. Ver el glosario de términos

### Cómo acceder

1. En la barra lateral izquierda, clic en Gobernar.
2. Selecciona Glosario .
3. Verás el glosario "Glosario Aplicacion Nutricion" con todos los términos definidos.

### Términos definidos

| Término | Definición |
|---|---|
| Alimento validado | Producto cuyo contenido nutricional ha sido contrastado y marcado como fiable (product.is_verified = true) |
| Dieta activa | Configuración dietética vigente para un usuario en un periodo activo (tabla daily_goal donde date = fecha actual) |
| IMC | Índice de Masa Corporal calculado a partir de peso y altura (user_profile.bmi) |
| Ingesta registrada | Entrada que documenta el consumo de un alimento por un usuario en una fecha y hora determinadas (tabla intake) |
| Macronutriente | Nutriente principal expresado en gramos: product.protein_g, product.carbs_g, product.fat_g |
| Objetivo calórico | Número de kilocalorías diarias recomendadas a un usuario según su perfil (daily_goal.kcal_goal) |
| Plan dietético | Conjunto estructurado de recomendaciones alimentarias asociadas a un objetivo (tabla meal_plan_entry) |
| Sesión de usuario | Periodo operativo en el que el usuario interactúa con el sistema (tabla user_account, metadatos de acceso) |
| Usuario activo | Usuario con al menos una ingesta en los últimos 30 días y cuenta no bloqueada (user_account.is_active + actividad en intake) |
| Valor nutricional | Conjunto de calorías y macronutrientes por cada 100g de un alimento (tabla product: kcal, protein_g, etc.) |

### Cómo ver el detalle de un término

Dentro del glosario, clic sobre el nombre del término.

Se abre la vista con su definición completa, sinónimos (si los hay) y la vinculación con los campos del diccionario de datos.

---

## 5. Ver y gestionar las reglas de calidad

### Cómo acceder a los Tests de calidad

**Ruta de acceso:**

Menú lateral izquierdo → Observabilidad → (se despliega) → aparece la sección de Tests

O directamente por URL:

http://localhost:8585/data-quality/test-cases

Una vez dentro verás dos pestañas:

- Casos de Prueba → listado de todos los Test Cases individuales con su estado
- Suites de Pruebas → agrupaciones de Test Cases por conjunto

### Dashboard de calidad

En la parte superior de Observabilidad aparece un resumen visual:

| Métrica | Valor actual |
|---|---|
| Total de Pruebas | 6 |
| Success | 🟢 todos en verde |
| Activos de Datos Saludables | 3 tablas cubiertas |
| Cobertura de activos de datos | ~12.5% (se incrementa al añadir más tests) |

### Casos de Prueba configurados en NutriTracker

| Estado | Nombre del Test Case | Tabla | Columna | Última ejecución |
|---|---|---|---|---|
| ✅ Éxito | quantity_g_column_values_to_be_not_null_bhd_s | public.intake | quantity_g | 30 abril 2026 |
| ✅ Éxito | kcal_column_values_to_be_between_q_s_50 | public.product | kcal | 30 abril 2026 |
| ✅ Éxito | email_column_values_to_match_regex_c_kil | public.user_account | email | 30 abril 2026 |
| ✅ Éxito | email_column_values_to_be_unique_gu_9_y | public.user_account | email | 30 abril 2026 |
| ✅ Éxito | created_at_no_fecha_futura | public.intake | created_at | 30 abril 2026 |
| ✅ Éxito | email_no_nulo | public.user_account | email | 30 abril 2026 |

Estos 6 Test Cases cubren las 5 dimensiones de calidad requeridas por la normativa:

| Dimensión | Test Case que la cubre |
|---|---|
| Completitud | quantity_g_column_values_to_be_not_null · email_no_nulo |
| Validez (formato) | email_column_values_to_match_regex |
| Validez (rango) | kcal_column_values_to_be_between |
| Unicidad | email_column_values_to_be_unique |
| Actualidad | created_at_no_fecha_futura |

---

## 6. Cómo ejecutar los tests de calidad

1. Ve a Observabilidad en el menú lateral izquierdo.
2. Verás directamente el listado de Casos de Prueba con su estado actual.
3. Para ejecutar un test individual: clic en los tres puntos ⋮ a la derecha del Test Case → "Ejecutar".
4. Para ejecutar todos: ve a la pestaña Suites de Pruebas, abre el suite y busca el botón "Ejecutar todos".
5. El resultado aparece en la columna Estado:

| Estado | Significado |
|---|---|
| 🟢 Éxito | el dato cumple la regla |
| 🔴 Fallido | hay registros que violan la regla |
| ⚪ Sin ejecución | el test no se ha ejecutado todavía |

---

## 7. Cómo añadir un nuevo término al glosario

1. Ve a Gobernar → Glosario en el menú lateral izquierdo.
2. Abre el glosario "Glosario Aplicacion Nutricion".
3. Clic en el botón "Añadir término" (esquina superior derecha).
4. Rellena los campos:

- Nombre: nombre del término (ej: Porción estándar)
- Descripción: definición precisa y sin ambigüedad
- Sinónimos: sinónimos si los hay (opcional)
- Términos relacionados: otros términos del glosario relacionados (opcional)

5. Clic en "Guardar".
6. Para vincular el término a una columna: ve a Explorar → abre la tabla → selecciona la columna → en el panel de Etiquetas, añade el término del glosario.

---

## 8. Cómo añadir una nueva regla de calidad

1. Ve a Observabilidad en el menú lateral izquierdo.
2. Clic en el botón azul "Añadir Caso de Prueba" (esquina superior derecha).
3. Rellena los campos:

- Tabla: selecciona la tabla (ej: nutritracker-db.nutri_tracker.public.product)
- Columna: selecciona la columna (ej: kcal)
- Tipo de prueba: selecciona el tipo de validación:

| Tipo de prueba | Cuándo usarlo |
|---|---|
| columnValuesToNotBeNull | El campo no puede estar vacío |
| columnValuesToBeUnique | No puede haber duplicados |
| columnValuesToBeBetween | El valor debe estar entre un mínimo y un máximo |
| columnValuesToMatchRegex | El valor debe cumplir un patrón (ej: formato email) |
| tableRowCountToBeBetween | La tabla debe tener un número de filas en un rango |

- Nombre: nombre descriptivo (ej: kcal_no_negativa)
- Descripción: explicación de la regla
- Parámetros según el tipo (Min/Max para Between, Regex para MatchRegex)

4. Clic en "Guardar".
5. El Test Case quedará en el listado de Casos de Prueba y podrás ejecutarlo con los tres puntos ⋮ → "Ejecutar".

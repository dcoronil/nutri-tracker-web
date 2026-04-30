# Manual de Usuario — OpenMetadata

Este manual explica de forma sencilla cómo acceder y moverse por OpenMetadata dentro del trabajo de calidad de datos aplicado a NutriTracker. También recoge dónde se pueden consultar las tablas modeladas, el glosario y las reglas de calidad configuradas.

## Índice

1. Acceso a OpenMetadata  
2. Navegación por la interfaz  
3. Ver las entidades modeladas  
4. Ver el glosario de términos  
5. Ver y gestionar las reglas de calidad  
6. Cómo ejecutar los tests de calidad  
7. Cómo añadir un nuevo término al glosario  
8. Cómo añadir una nueva regla de calidad  

---

## 1. Acceso a OpenMetadata

OpenMetadata es la herramienta utilizada en este proyecto para documentar y controlar los datos principales de NutriTracker. En ella se han registrado las entidades de la base de datos, el glosario de términos y las reglas de calidad del dato.

La instancia se ejecuta en local y se accede desde el navegador mediante la siguiente dirección:

```text
http://localhost:8585
```

Por seguridad, las credenciales no se incluyen directamente en este documento. Para acceder a la instancia, se debe contactar con el responsable del entorno de OpenMetadata.

Antes de entrar, OpenMetadata debe estar levantado mediante Docker. Si la página no carga, se puede arrancar desde el directorio de instalación con:

```text
docker compose up -d
```

---

## 2. Navegación por la interfaz

Una vez dentro de OpenMetadata, la mayor parte del trabajo se realiza desde la barra lateral izquierda. Desde ahí se puede acceder a las tablas, al glosario, al linaje y a las reglas de calidad.

| Sección en la interfaz | Para qué sirve |
|---|---|
| Inicio | Muestra el panel principal con actividad reciente y activos destacados. |
| Explorar | Permite buscar y consultar las tablas registradas de la base de datos. |
| Linaje | Muestra las relaciones y el flujo de datos entre tablas. |
| Observabilidad | Permite consultar los tests de calidad y sus resultados. |
| Perspectivas | Muestra métricas y paneles relacionados con la cobertura de calidad. |
| Dominios | Organiza los activos de datos por áreas o dominios de negocio. |
| Gobernar | Contiene el glosario, clasificaciones y políticas. |
| Configuraciones | Permite gestionar servicios, usuarios, roles y conexiones. |

En esta instalación, las reglas de calidad se consultan desde **Observabilidad**, no directamente desde la pestaña de cada tabla. La ruta directa es:

```text
http://localhost:8585/data-quality/test-cases
```

---

## 3. Ver las entidades modeladas

Las entidades modeladas son las tablas principales de NutriTracker que han sido registradas en OpenMetadata. Estas tablas representan la información más importante de la aplicación: usuarios, perfiles físicos, alimentos, ingestas y objetivos nutricionales.

### Cómo acceder

1. Clic en **Explorar** en la barra lateral izquierda.
2. Seleccionar la categoría **Tables**.
3. Se mostrará el listado de tablas descubiertas desde la base de datos PostgreSQL de NutriTracker.

### Tablas registradas en NutriTracker

| Tabla | Descripción |
|---|---|
| `user_account` | Guarda la identidad y credenciales de los usuarios registrados. |
| `user_profile` | Almacena métricas físicas del usuario, como peso, altura o IMC. |
| `product` | Contiene el catálogo de alimentos con sus calorías y macronutrientes. |
| `intake` | Registra los alimentos consumidos por cada usuario y la fecha de consumo. |
| `daily_goal` | Guarda los objetivos calóricos y nutricionales diarios de cada usuario. |
| `meal_plan_entry` | Contiene entradas del plan dietético estructurado. |
| `body_weight_log` | Guarda el histórico de peso corporal del usuario. |

### Cómo ver el detalle de una tabla

Para consultar una tabla concreta, por ejemplo `intake`, se hace clic sobre su nombre en el listado de tablas.

Dentro de la vista de detalle se pueden consultar varias pestañas:

| Pestaña | Contenido |
|---|---|
| Schema | Columnas, tipos de datos, descripciones y etiquetas. |
| Activity | Historial de cambios realizados sobre la entidad. |
| Sample Data | Muestra de datos reales, si la configuración lo permite. |
| Lineage | Relaciones de la tabla con otros activos de datos. |

### Campos sensibles marcados

Algunos campos contienen información personal o relacionada con la salud del usuario. Por ello, se han marcado como sensibles dentro de OpenMetadata.

| Tabla | Campo | Motivo |
|---|---|---|
| `user_account` | `email` | Dato identificativo personal. |
| `user_account` | `password_hash` | Credencial sensible de seguridad. |
| `user_profile` | `weight_kg` | Dato relacionado con la salud del usuario. |
| `user_profile` | `height_cm` | Dato relacionado con la salud del usuario. |
| `user_profile` | `body_fat_percent` | Dato corporal sensible. |

**Captura recomendada:** vista de la tabla `user_account` o `user_profile` con las columnas y etiquetas sensibles visibles.

---

## 4. Ver el glosario de términos

El glosario sirve para definir de forma común los conceptos principales del dominio de NutriTracker. De esta forma, tanto la parte técnica como la parte funcional entienden los términos de la misma manera.

### Cómo acceder

1. En la barra lateral izquierda, hacer clic en **Gobernar**.
2. Seleccionar **Glosario**.
3. Abrir el glosario llamado **Glosario NutriTracker**.

### Términos definidos

| Término | Definición |
|---|---|
| Alimento validado | Producto cuyo contenido nutricional ha sido revisado y marcado como fiable. |
| Dieta activa | Configuración dietética vigente para un usuario en una fecha concreta. |
| IMC | Índice de Masa Corporal calculado a partir del peso y la altura del usuario. |
| Ingesta registrada | Registro que indica qué alimento ha consumido un usuario y en qué momento. |
| Macronutriente | Nutriente principal expresado en gramos, como proteínas, carbohidratos o grasas. |
| Objetivo calórico | Número de kilocalorías diarias recomendadas para un usuario. |
| Plan dietético | Conjunto de recomendaciones alimentarias organizadas para un usuario. |
| Sesión de usuario | Periodo en el que el usuario interactúa con la aplicación. |
| Usuario activo | Usuario que ha tenido actividad reciente en la aplicación y cuya cuenta no está bloqueada. |
| Valor nutricional | Conjunto de calorías y macronutrientes asociados a un alimento. |

### Cómo ver el detalle de un término

Dentro del glosario, se puede hacer clic sobre cualquier término para ver su definición completa y su relación con las tablas o campos correspondientes.

**Capturas recomendadas:**

- Listado del glosario con los términos visibles.
- Vista interior de un término, por ejemplo `Usuario activo` o `Valor nutricional`.

---

## 5. Ver y gestionar las reglas de calidad

Las reglas de calidad permiten comprobar si los datos cumplen ciertas condiciones mínimas. En NutriTracker son importantes porque la aplicación depende de datos correctos para calcular calorías, macronutrientes, objetivos diarios y evolución del usuario.

### Cómo acceder a los tests de calidad

Se puede acceder desde:

```text
Menú lateral izquierdo → Observabilidad → Casos de Prueba
```

También se puede entrar directamente desde:

```text
http://localhost:8585/data-quality/test-cases
```

Dentro de esta sección aparecen principalmente dos apartados:

| Apartado | Descripción |
|---|---|
| Casos de Prueba | Lista de tests individuales configurados. |
| Suites de Pruebas | Agrupaciones de varios tests de calidad. |

### Resumen de calidad

En la parte superior de Observabilidad aparece un resumen con el estado general de los tests.

| Métrica | Valor |
|---|---|
| Total de pruebas configuradas | 6 |
| Estado general | Tests ejecutados correctamente |
| Tablas cubiertas | `user_account`, `product`, `intake` |
| Cobertura de activos de datos | Aproximadamente 12,5% |

### Casos de prueba configurados

| Estado | Test Case | Tabla | Columna | Última ejecución |
|---|---|---|---|---|
| Éxito | `quantity_g_column_values_to_be_not_null` | `public.intake` | `quantity_g` | 28 abril 2026 |
| Éxito | `kcal_column_values_to_be_between` | `public.product` | `kcal` | 28 abril 2026 |
| Éxito | `email_column_values_to_match_regex` | `public.user_account` | `email` | 28 abril 2026 |
| Éxito | `email_column_values_to_be_unique` | `public.user_account` | `email` | 28 abril 2026 |
| Éxito | `created_at_no_fecha_futura` | `public.intake` | `created_at` | 28 abril 2026 |
| Éxito | `email_no_nulo` | `public.user_account` | `email` | 28 abril 2026 |

Estos tests cubren las principales dimensiones de calidad trabajadas en el informe.

| Dimensión | Test que la cubre |
|---|---|
| Completitud | `quantity_g_column_values_to_be_not_null`, `email_no_nulo` |
| Validez de formato | `email_column_values_to_match_regex` |
| Validez de rango | `kcal_column_values_to_be_between` |
| Unicidad | `email_column_values_to_be_unique` |
| Actualidad | `created_at_no_fecha_futura` |

**Captura recomendada:** vista de Observabilidad con los casos de prueba configurados y en estado correcto.

---

## 6. Cómo ejecutar los tests de calidad

Para ejecutar los tests de calidad:

1. Ir a **Observabilidad** en el menú lateral izquierdo.
2. Entrar en el listado de **Casos de Prueba**.
3. Para ejecutar un test concreto, hacer clic en los tres puntos situados a la derecha del test.
4. Seleccionar la opción **Ejecutar**.
5. Para ejecutar un conjunto completo, entrar en **Suites de Pruebas** y ejecutar la suite correspondiente.

El resultado de cada test aparece en la columna de estado.

| Estado | Significado |
|---|---|
| Éxito | El dato cumple la regla definida. |
| Fallido | Hay registros que no cumplen la regla. |
| Sin ejecución | El test todavía no se ha ejecutado. |

---

## 7. Cómo añadir un nuevo término al glosario

Para añadir un nuevo término:

1. Ir a **Gobernar → Glosario**.
2. Abrir el glosario **Glosario NutriTracker**.
3. Hacer clic en **Añadir término**.
4. Rellenar los campos principales:
   - **Nombre:** nombre del término, por ejemplo `Porción estándar`.
   - **Descripción:** explicación clara del término.
   - **Sinónimos:** opcional.
   - **Términos relacionados:** opcional.
5. Hacer clic en **Guardar**.

Para vincular el término a una columna:

1. Ir a **Explorar**.
2. Abrir la tabla correspondiente.
3. Seleccionar la columna relacionada.
4. Añadir el término desde el panel de etiquetas o glosario.

---

## 8. Cómo añadir una nueva regla de calidad

Para añadir una nueva regla de calidad:

1. Ir a **Observabilidad** en el menú lateral izquierdo.
2. Hacer clic en **Añadir Caso de Prueba**.
3. Seleccionar la tabla correspondiente.
4. Seleccionar la columna sobre la que se quiere aplicar la regla.
5. Elegir el tipo de prueba.
6. Rellenar el nombre, descripción y parámetros necesarios.
7. Guardar el Test Case.

### Tipos de pruebas más usadas

| Tipo de prueba | Cuándo usarla |
|---|---|
| `columnValuesToNotBeNull` | Cuando un campo no puede estar vacío. |
| `columnValuesToBeUnique` | Cuando no puede haber valores duplicados. |
| `columnValuesToBeBetween` | Cuando un valor debe estar dentro de un rango. |
| `columnValuesToMatchRegex` | Cuando un campo debe cumplir un formato concreto, como un email. |
| `tableRowCountToBeBetween` | Cuando una tabla debe tener un número de filas dentro de un rango esperado. |

Ejemplo de regla:

| Campo | Valor |
|---|---|
| Tabla | `nutritracker-db.nutri_tracker.public.product` |
| Columna | `kcal` |
| Tipo de prueba | `columnValuesToBeBetween` |
| Nombre | `kcal_rango_valido` |
| Descripción | Comprueba que las calorías de un producto estén dentro de un rango razonable. |

Una vez guardado, el Test Case aparecerá en el listado de casos de prueba y se podrá ejecutar desde los tres puntos de opciones.
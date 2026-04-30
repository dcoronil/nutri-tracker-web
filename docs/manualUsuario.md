Manual de Usuario — OpenMetadata

Índice

Acceso a OpenMetadata
Navegación por la interfaz
Ver las entidades modeladas (tablas)
Ver el glosario de términos
Ver y gestionar las reglas de calidad
Cómo ejecutar los tests de calidad
Cómo añadir un nuevo término al glosario
Cómo añadir una nueva regla de calidad


1. Acceso a OpenMetadata
OpenMetadata es la plataforma de gobernanza del dato utilizada en este proyecto para documentar las entidades, el glosario y las reglas de calidad de NutriTracker.
URL de acceso:
http://localhost:8585
Credenciales:
usuario: rsantervastorres@al.uloyola.es
contraseña: "contactar con ese usuario para conocer la contraseña"

OpenMetadata debe estar arrancado mediante Docker antes de acceder. Si la página no carga, ejecuta docker compose up -d en el directorio de instalación.


2. Navegación por la interfaz
Una vez dentro, la barra lateral izquierda es el punto de entrada a todas las funciones. La interfaz está en español:
Sección en la interfazPara qué sirve🏠 InicioPanel principal con actividad reciente y activos destacados🔍 ExplorarBuscar y navegar todas las tablas registradas de la BD🔗 LinajeVer las relaciones y flujo de datos entre tablas👁️ ObservabilidadAcceder a los Tests de calidad (Casos de Prueba y Suites de Pruebas)📊 PerspectivasDashboards y métricas de cobertura de calidad🌐 DominiosOrganización de activos por dominio de negocio🏛️ GobernarGlosario de términos, clasificaciones y políticas⚙️ ConfiguracionesServicios de BD, usuarios, roles y conexiones

💡 Importante: En esta instalación, las reglas de calidad se encuentran en Observabilidad, no en una pestaña dentro de las tablas. La URL directa es: http://localhost:8585/data-quality/test-cases


3. Ver las entidades modeladas (tablas)
Cómo acceder

Clic en Explorar en la barra lateral izquierda.
En el panel que se abre, selecciona la categoría Tables.
Verás el listado de todas las tablas descubiertas de la base de datos PostgreSQL de NutriTracker.

Tablas registradas en NutriTracker
TablaDescripciónuser_accountIdentidad y credenciales de los usuarios registradosuser_profileMétricas físicas del usuario (peso, altura, IMC)productCatálogo maestro de alimentos con sus macronutrientesintakeRegistros de consumo de alimentos por usuario y fechadaily_goalObjetivos calóricos y nutricionales diarios por usuariomeal_plan_entryEntradas del plan dietético estructuradobody_weight_logHistórico de peso corporal del usuario
Cómo ver el detalle de una tabla

Clic sobre el nombre de la tabla (por ejemplo, intake).
Se abre la vista de detalle con las siguientes pestañas:

Schema → columnas, tipos de dato, descripciones y tags PII
Activity → historial de cambios
Sample Data → muestra de datos reales (si la ingesta lo permite)
Lineage → relaciones con otras tablas



Campos sensibles (PII) marcados
Los siguientes campos están etiquetados con PII.Sensitive en OpenMetadata:
TablaCampoMotivouser_accountemailDato identificativo personaluser_accountpassword_hashCredencial de seguridaduser_profileweight_kgDato de saluduser_profileheight_cmDato de saluduser_profilebody_fat_percentDato de salud sensible

📸 [Insertar captura: vista de la tabla user_account con las columnas y los tags PII visibles]


4. Ver el glosario de términos
Cómo acceder

En la barra lateral izquierda, clic en Gobernar.
Selecciona Glosario (o Glossary).
Verás el glosario "Glosario NutriTracker" con todos los términos definidos.

Términos definidos
TérminoDefiniciónAlimento validadoProducto cuyo contenido nutricional ha sido contrastado y marcado como fiable (product.is_verified = true)Dieta activaConfiguración dietética vigente para un usuario en un periodo activo (tabla daily_goal donde date = fecha actual)IMCÍndice de Masa Corporal calculado a partir de peso y altura (user_profile.bmi)Ingesta registradaEntrada que documenta el consumo de un alimento por un usuario en una fecha y hora determinadas (tabla intake)MacronutrienteNutriente principal expresado en gramos: product.protein_g, product.carbs_g, product.fat_gObjetivo calóricoNúmero de kilocalorías diarias recomendadas a un usuario según su perfil (daily_goal.kcal_goal)Plan dietéticoConjunto estructurado de recomendaciones alimentarias asociadas a un objetivo (tabla meal_plan_entry)Sesión de usuarioPeriodo operativo en el que el usuario interactúa con el sistema (tabla user_account, metadatos de acceso)Usuario activoUsuario con al menos una ingesta en los últimos 30 días y cuenta no bloqueada (user_account.is_active + actividad en intake)Valor nutricionalConjunto de calorías y macronutrientes por cada 100g de un alimento (tabla product: kcal, protein_g, etc.)
Cómo ver el detalle de un término

Dentro del glosario, clic sobre el nombre del término.
Se abre la vista con su definición completa, sinónimos (si los hay) y la vinculación con los campos del diccionario de datos.


📸 [Insertar captura: listado del glosario con los 10 términos visibles]


📸 [Insertar captura: vista interior de un término, por ejemplo "Usuario activo"]


5. Ver y gestionar las reglas de calidad
Cómo acceder a los Tests de calidad
Ruta de acceso:
Menú lateral izquierdo → Observabilidad → (se despliega) → aparece la sección de Tests
O directamente por URL:
http://localhost:8585/data-quality/test-cases
Una vez dentro verás dos pestañas:

Casos de Prueba → listado de todos los Test Cases individuales con su estado
Suites de Pruebas → agrupaciones de Test Cases por conjunto

Dashboard de calidad
En la parte superior de Observabilidad aparece un resumen visual:
MétricaValor actualTotal de Pruebas6 (tras añadir los 2 pendientes)Success🟢 todos en verdeActivos de Datos Saludables3 tablas cubiertasCobertura de activos de datos~12.5% (se incrementa al añadir más tests)
Casos de Prueba configurados en NutriTracker
EstadoNombre del Test CaseTablaColumnaÚltima ejecución✅ Éxitoquantity_g_column_values_to_be_not_null_bhd_spublic.intakequantity_g28 abril 2026✅ Éxitokcal_column_values_to_be_between_q_s_50public.productkcal28 abril 2026✅ Éxitoemail_column_values_to_match_regex_c_kilpublic.user_accountemail28 abril 2026✅ Éxitoemail_column_values_to_be_unique_gu_9_ypublic.user_accountemail28 abril 2026✅ Éxitocreated_at_no_fecha_futurapublic.intakecreated_at28 abril 2026✅ Éxitoemail_no_nulopublic.user_accountemail28 abril 2026
Estos 6 Test Cases cubren las 5 dimensiones de calidad requeridas por la normativa:
DimensiónTest Case que la cubreCompletitudquantity_g_column_values_to_be_not_null · email_no_nuloValidez (formato)email_column_values_to_match_regexValidez (rango)kcal_column_values_to_be_betweenUnicidademail_column_values_to_be_uniqueActualidadcreated_at_no_fecha_futura

📸 [Insertar captura: 07_quality_test_cases.png — vista de Observabilidad con los 6 Casos de Prueba en estado Éxito, tal como aparece en localhost:8585/data-quality/test-cases]


6. Cómo ejecutar los tests de calidad

Ve a Observabilidad en el menú lateral izquierdo.
Verás directamente el listado de Casos de Prueba con su estado actual.
Para ejecutar un test individual: clic en los tres puntos ⋮ a la derecha del Test Case → "Ejecutar".
Para ejecutar todos: ve a la pestaña Suites de Pruebas, abre el suite y busca el botón "Ejecutar todos".
El resultado aparece en la columna Estado:

🟢 Éxito → el dato cumple la regla
🔴 Fallido → hay registros que violan la regla
⚪ Sin ejecución → el test no se ha ejecutado todavía




7. Cómo añadir un nuevo término al glosario

Ve a Gobernar → Glosario en el menú lateral izquierdo.
Abre el glosario "Glosario NutriTracker".
Clic en el botón "Añadir término" (esquina superior derecha).
Rellena los campos:

Nombre: nombre del término (ej: Porción estándar)
Descripción: definición precisa y sin ambigüedad
Sinónimos: sinónimos si los hay (opcional)
Términos relacionados: otros términos del glosario relacionados (opcional)


Clic en "Guardar".
Para vincular el término a una columna: ve a Explorar → abre la tabla → selecciona la columna → en el panel de Etiquetas, añade el término del glosario.


8. Cómo añadir una nueva regla de calidad

Ve a Observabilidad en el menú lateral izquierdo.
Clic en el botón azul "Añadir Caso de Prueba" (esquina superior derecha).
Rellena los campos:

Tabla: selecciona la tabla (ej: nutritracker-db.nutri_tracker.public.product)
Columna: selecciona la columna (ej: kcal)
Tipo de prueba: selecciona el tipo de validación:



Tipo de pruebaCuándo usarlocolumnValuesToNotBeNullEl campo no puede estar vacíocolumnValuesToBeUniqueNo puede haber duplicadoscolumnValuesToBeBetweenEl valor debe estar entre un mínimo y un máximocolumnValuesToMatchRegexEl valor debe cumplir un patrón (ej: formato email)tableRowCountToBeBetweenLa tabla debe tener un número de filas en un rango

Nombre: nombre descriptivo (ej: kcal_no_negativa)
Descripción: explicación de la regla
Parámetros según el tipo (Min/Max para Between, Regex para MatchRegex)


Clic en "Guardar".
El Test Case quedará en el listado de Casos de Prueba y podrás ejecutarlo con los tres puntos ⋮ → "Ejecutar".
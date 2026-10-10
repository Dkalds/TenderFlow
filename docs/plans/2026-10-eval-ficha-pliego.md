# Evaluación de la ficha del pliego: saber si un cambio la mejora o la empeora

**Estado:** diseño aprobado por el propietario el 2026-10-11; especificación
pendiente de su revisión. Sin código escrito.
**Alcance:** medir la extracción de la ficha del pliego
(`services/rag/fact_sheet.py`) contra pliegos reales con etiquetas humanas.
Fuera de alcance: las respuestas del asistente, el clasificador, la búsqueda de
`/ask` y cualquier pantalla (§10).
**Ítem del backlog que implementa:** «[P2] Golden set de extracción de fichas:
la calidad de la ficha no se mide». Desbloquea «[P2] Unificar la selección de
páginas de la ficha con el retrieval pgvector».

## 1. Por qué

- La búsqueda de `/ask` tiene eval con ratchet en CI
  (`tests/eval/test_eval_rag.py`), las respuestas del asistente tienen una
  revisión manual (`make eval-llm`) y el clasificador tiene su golden set. **La
  ficha no tiene nada.**
- `tender-facts-v6` (2026-09-28) cambió el selector de páginas, el presupuesto
  de contexto y el tope de salida comparando cuatro pliegos a mano y sin
  etiquetas. Esa comparación cuenta hechos; no dice cuántos son ciertos.
- El fallo de la v5 fueron las **omisiones** (fichas con 0 hechos). La
  validación de citas que ya existe solo detecta lo contrario: un hecho cuyo
  texto no está en el pliego. Lo que la ficha calla no lo detecta nadie.
- Unificar el selector de páginas con el retrieval lleva desde el 2026-09-01
  esperando a que esto exista.

## 2. Qué se mide y con qué honestidad

Diez pliegos reales, etiquetados de dos maneras (decisión del propietario,
2026-10-11):

| Tipo de caso | Cuántos | Cómo se etiqueta | Qué permite afirmar |
|---|---|---|---|
| **Completo** | 3 | Se revisa lo extraído **y** se lee el pliego entero para añadir lo omitido | Precisión y cobertura estrictas |
| **Parcial** | 7 | Solo se revisa lo que la app extrajo | Aciertos y errores confirmados; lo demás queda «sin juzgar» |

La regla que gobierna todo lo demás es la de ADR-014 aplicada a una etiqueta:
**un hecho que nadie revisó no es un error, es un desconocido.** En un caso
parcial, un hecho nuevo que no casa con nada etiquetado se cuenta como «sin
juzgar» y se ofrece a revisión; solo en un caso completo cuenta como falso
positivo.

Se desvía del ítem del backlog en un punto: aquel pedía ~10 pliegos etiquetados
a mano desde cero. Con tres completos la cobertura se mide sobre menos pliegos,
a cambio de que el conjunto llegue a existir.

## 3. Los casos de referencia

Una carpeta por pliego en `tests/fixtures/fichas/<caso>/`:

- `paginas.jsonl` — **todas** las páginas con texto del expediente, una por
  línea: `documento_id`, `page_number`, `tipo`, `filename`, `texto`,
  `start_offset`, `end_offset`, `ocr`. Todas y no solo las seleccionadas,
  porque el selector es parte de lo que se evalúa. **Sin `uri`**: las de PLACSP
  llevan un token.
- `golden.json` — metadatos del caso (`licitacion_id`, `completo`, fecha de
  captura, `extraction_version` y modelo de la propuesta) y los hechos por
  familia, con la forma de `TenderFactSheet` más un campo `veredicto` por hecho:

  | `veredicto` | Significado | Cuenta como |
  |---|---|---|
  | `correcto` | El hecho extraído es cierto | positivo |
  | `corregido` | Estaba en el sitio correcto con un valor mal; el golden guarda el valor bueno y conserva el original en `valor_extraido` | positivo (y el original, negativo) |
  | `añadido` | Lo omitió la app; lo aportó quien leyó el pliego | positivo |
  | `incorrecto` | El hecho extraído es falso o no es de esa familia | negativo conocido |
  | `null` | Sin revisar | no cuenta |

  Un caso con algún `null` no entra en la evaluación: se avisa y se salta.
- `minimos.json` (uno, en la raíz de `fichas/`) — los mínimos de §6, con fecha,
  modelo y versión de la medición de base.

Los pliegos son documentos públicos. Tamaño esperado: unos pocos MB en total;
la captura avisa si un caso pasa de 1 MB y la decisión se revisa si el conjunto
supera los 10 MB.

*Corregido al implementar (2026-10-11):* la carpeta es `tests/fixtures/fichas/`
y no `tests/eval/fixtures/fichas/`, como decía el diseño. `tests/fixtures/` ya
está excluida de codespell y de detect-secrets en `.pre-commit-config.yaml`; en
la otra, el texto real de un pliego haría fallar el corrector en cada commit
(ya marcó como errata una palabra española en un docstring de este mismo trabajo). Y el límite de 1 MB por
caso no es solo un aviso: `check-added-large-files` rechaza un fichero mayor.

### Cómo se eligen los diez

Elegir solo fichas que salieron bien mediría el mejor caso. La selección cubre,
como mínimo: las tres fuentes con pliegos (PLACSP, PSCP, TED) si las hay, un
expediente multi-lote, uno con fórmula de precio, uno con páginas de OCR, uno
corto y uno largo, y **dos cuya ficha actual sea pobre o `failed`**. De los
tres completos, uno es de estos últimos.

## 4. Componentes

1. **Núcleo sin base de datos.** De `extract_fact_sheet` se separa
   `extraer_hechos(pages, *, model)`, que va de páginas a hechos validados
   (selector, llamada al LLM, `_parse_facts`, `_validate_fact_evidence`) y
   devuelve los hechos, los dos recuentos de descartes y las páginas
   seleccionadas. `extract_fact_sheet` pasa a llamarlo y sigue siendo quien
   persiste. Sin cambio de comportamiento y **sin bump de
   `EXTRACTION_VERSION`**. Es lo que garantiza que la evaluación mide el
   prompt, el selector y la validación de producción y no una copia.
2. **Emparejamiento y métricas** — `services/rag/ficha_eval.py`. Puro: sin BD,
   sin LLM, sin red. Recibe hechos extraídos y un golden, devuelve el resultado
   por familia (§5 y §6).
3. **Captura** — `scripts/capturar_ficha_golden.py`.
   - `--listar`: candidatos con fuente, nº de páginas, estado y nº de hechos de
     la ficha, para elegir con los criterios de §3.
   - `<licitacion_id> --caso <nombre> [--completo]`: escribe `paginas.jsonl` y
     un `golden.json` con la ficha vigente como propuesta y todo en `null`.
   - Solo lectura (`connect_read`). El SQL nuevo del listado vive en
     `db/repositories/tender_fact_sheets.py` (invariante 10).
   - Lo ejecuta el propietario: necesita la base de producción.
4. **Revisión** — `scripts/revisar_ficha_golden.py`, con el patrón de
   `scripts/revisar_golden_candidates.py`: un hecho cada vez con su familia,
   sus campos, la cita y la página; una tecla por veredicto; guarda tras cada
   respuesta y se puede retomar.
   - Corregir un valor pide solo el campo clave de la familia.
   - En los casos completos, un modo «añadir» pide familia, documento, página,
     cita y campo clave, y **rechaza la cita si no está literalmente en esa
     página** (misma función que producción, `_validated_evidence`).
   - `--estado` dice cuántos casos hay, cuántos completos y qué falta.
5. **Evaluación con el modelo real** — `scripts/eval_ficha.py` y
   `make eval-ficha`. Una llamada de extracción por caso. Arranca sin base de
   datos, como `eval_rag_generation.py`. Opciones: `--model`, `--caso`,
   `--check` (devuelve 1 por debajo de los mínimos), `--salida` (JSON del
   resultado, no versionado) y `--pendientes` (escribe los «sin juzgar» en
   `pendientes.json`, junto al golden del caso; la revisión los lee de ahí y
   solo al recibir veredicto pasan al golden, que nunca contiene un `null`
   una vez etiquetado).
6. **Comprobación del selector, en CI** — `tests/eval/test_eval_ficha_selector.py`
   (§7).

## 5. Cuándo un hecho extraído «es» uno del golden

Dos condiciones, y emparejamiento uno a uno (cada hecho del golden casa como
mucho con uno extraído; los empates se resuelven por solape de cita):

- **Ancla.** Comparten documento y sus citas normalizadas (`_normalize_quote`)
  tienen una subcadena común de al menos 20 caracteres
  (`_MIN_FRAGMENTO_CHARS`). Para las familias con clave vale también citar la
  misma página o una contigua.
- **Clave**, según la familia:

| Familias | Clave |
|---|---|
| `award_criteria` | `weight_pct` si ambos lo traen; si no, nombre |
| `economic_solvency`, `guarantees`, `penalties` | `amount_eur` si ambos lo traen |
| `lots` | `lot_number` normalizado; si falta, `amount_eur` |
| `price_formula` | `formula_type` (y `max_points` si ambos lo traen) |
| `rate_cards` | `role` y `max_rate_eur_hour` |
| `budget_breakdown` | `category` y `amount_eur` |
| `critical_deadlines` | `date_value` si ambos lo traen; si no, nombre |
| `team_requirements` | `role` (y `minimum_years` si ambos lo traen) |
| `certifications`, `technologies`, `service_levels`, `required_documents` | nombre normalizado |
| `technical_solvency`, `subcontracting`, `extensions` | sin clave: basta el ancla por cita |

Los números se comparan con tolerancia relativa de 0,5 %; los nombres, sin
mayúsculas, tildes ni signos, por solape de palabras.

**Ancla sin clave es su propia categoría: `valor_distinto`.** El extractor
encontró el sitio y leyó mal el dato —un peso del 40 % donde el pliego dice
60 %, con una cita real debajo—. Es el error más caro del producto, porque la
validación de citas lo deja pasar; se cuenta como error y se informa aparte.

Un hecho extraído que casa con un negativo conocido (`incorrecto`, o el
`valor_extraido` de un `corregido`) es un **error confirmado**.

## 6. Métricas y mínimos

Por familia y en total:

- **Casos completos:** precisión (positivos casados / extraídos) y cobertura
  (positivos casados / positivos del golden).
- **Casos parciales:** `confirmados`, `errores_confirmados`, `sin_juzgar` y
  **conservados** (positivos del golden que la nueva extracción sigue
  encontrando): la señal de regresión sobre lo que ya se sabía cierto.
- **En todos:** `valor_distinto`, descartes por esquema y por cita, y casos
  cuya extracción falló o volvió vacía.

Una familia con menos de 10 positivos en el conjunto se imprime con su N y la
leyenda «sin datos suficientes»: tres pliegos no sostienen un porcentaje por
familia.

**Mínimos (`minimos.json`), solo sobre totales:** precisión y cobertura de los
casos completos, conservados de los parciales, y cobertura del selector (§7).
El LLM no es determinista: la base se mide con tres ejecuciones y el mínimo es
la peor de las tres menos dos puntos. Solo suben, y se suben en el mismo cambio
que mejora la cifra. La cobertura del selector es determinista y su mínimo es
el valor exacto.

`make eval-ficha` **no entra en CI**: lo prohíbe el RFC de dependencia del LLM
(«no se mete un eval de generación LLM en el gate de CI»). Es el control que se
ejecuta, y cuyo resultado se pega en el PR, antes de tocar el prompt, el
modelo, el selector o la validación de citas.

## 7. Tests

Sin BD, sin LLM y sin red; quedan `unit` por el auto-marcado y corren en
`make check`:

- `tests/eval/test_eval_ficha_selector.py`
  - **Cobertura del selector:** de cada positivo del golden, ¿alguna de sus
    páginas citadas entra en `_select_pages(paginas)`? Total con ratchet al
    mínimo de `minimos.json`; por familia, publicado en el resumen del job como
    hace `test_eval_rag.py`.
  - **Integridad de los casos:** cada `golden.json` valida contra el esquema, y
    la cita de cada positivo está literalmente en su página. Un caso que se
    pudre falla aquí, no en silencio.
- `tests/test_ficha_eval.py` — el emparejador con hechos mínimos escritos a
  mano: clave igual y página contigua, `valor_distinto`, uno a uno con dos
  criterios del mismo peso, negativo conocido, caso parcial frente a completo.
  Prueba el código del emparejador, no la calidad del modelo.
- `tests/test_tender_fact_sheet.py` y
  `tests/test_fact_sheet_extract_async_route.py`, que ya existen: deben seguir
  en verde tras separar el núcleo, sin tocar sus aserciones.

## 8. Trabajo del propietario

1. `capturar_ficha_golden.py --listar` y elegir los diez con los criterios de §3.
2. Capturar los diez (tres con `--completo`).
3. Revisar los diez con `revisar_ficha_golden.py`.
4. Leer a fondo los tres completos y añadir lo omitido.
5. Tres ejecuciones de `make eval-ficha` para fijar la base.

Los pasos 1 a 4 no necesitan que el resto esté terminado más que los
componentes 3 y 4; por eso van primero en el plan de implementación.

## 9. Decisiones

| | Decisión | Estado |
|---|---|---|
| D1 | Etiquetado mixto: 10 revisados, 3 de ellos completos | Tomada (propietario, 2026-10-11) |
| D2 | Comparación determinista por ancla y clave; sin LLM juez | Tomada (propietario, 2026-10-11) |
| D3 | Mínimos solo sobre totales; por familia se informa | Propuesta en esta especificación |
| D4 | Versionar el texto completo de los pliegos en el repositorio | **A confirmar.** Son públicos, pero traen nombres de firmantes y de responsables del contrato tal como los publica la Plataforma |
| D5 | Qué diez pliegos | Del propietario, tras `--listar` |

Dato que falta: cuántas fichas v6 con hechos suficientes hay en producción. La
consulta desde la sesión de diseño fue denegada por el clasificador de
permisos; `--listar` lo responde.

## 10. Fuera de alcance

- Evaluar las respuestas del asistente, el resumen IA o el clasificador.
- Un LLM como juez.
- Ejecutarlo de forma programada (exige tocar un workflow: OK aparte).
- Una pantalla de revisión o de resultados.
- La unificación del selector con pgvector: es su propio ítem, y este trabajo
  le da la red.
- Ampliar más allá de diez casos. El formato lo admite; se decide con la
  primera medición delante.

## 11. Criterios de aceptación

- Diez casos en `tests/fixtures/fichas/`, tres con `completo: true`,
  ninguno con veredictos en `null`.
- `make eval-ficha` imprime las métricas de §6 por familia y en total, y
  `--check` devuelve 1 por debajo de `minimos.json`.
- `minimos.json` contiene la base medida con tres ejecuciones, con fecha,
  modelo y `EXTRACTION_VERSION`.
- `tests/eval/test_eval_ficha_selector.py` y `tests/test_ficha_eval.py` en
  verde dentro de `make check`.
- `extract_fact_sheet` persiste lo mismo que antes: sus tests no cambian.
- El ítem del backlog se mueve a _Cerrados_ y el de la unificación del selector
  deja de citar este como bloqueo.

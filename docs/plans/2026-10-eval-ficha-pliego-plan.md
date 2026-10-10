# Evaluación de la ficha del pliego — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** poder medir, contra diez pliegos reales con etiquetas humanas, si un
cambio en la extracción de la ficha la mejora o la empeora.

**Architecture:** los casos viven como ficheros en `tests/eval/fixtures/fichas/`.
Un módulo puro empareja lo extraído con el golden y calcula métricas; tres
scripts lo rodean (capturar, revisar, evaluar con el LLM real). De
`extract_fact_sheet` se separa un núcleo sin base de datos para que el eval
ejecute el camino de producción y no una copia.

**Tech Stack:** Python 3.13, Pydantic v2, pytest. Sin dependencias nuevas.

**Spec:** [2026-10-eval-ficha-pliego.md](2026-10-eval-ficha-pliego.md). Léela
antes de empezar: este plan fija nombres y firmas, no repite sus razones.

## Global Constraints

- **Typing strict** en `services/` y `db/`: sin `# type: ignore` ni `Any` sin
  comentario que lo justifique (AGENTS.md §3.1). `scripts/` y `tests/` están
  fuera de mypy.
- **Todo el SQL en `db/`** (invariante 10). Los scripts llaman a repositorios.
- **Capas** (`make check-layers`): `services/` importa de `db`, `llm`, `shared`;
  nunca de `scraper`, `scheduler` ni `api`.
- **Sin marcadores manuales de categoría.** Un test con `tmp_db` queda
  `integration` solo; el resto, `unit`, y un `unit` no toca red ni BD.
- **Sin bump de `EXTRACTION_VERSION`** (`tender-facts-v6`).
- **El eval con LLM no entra en CI** ni en ningún workflow.
- **`paginas.jsonl` nunca lleva `uri`.**
- Constantes de la spec, tal cual: subcadena común mínima **20** caracteres
  (`_MIN_FRAGMENTO_CHARS`); página contigua **±1**; tolerancia numérica relativa
  **0,5 %**; familia con menos de **10** positivos = «sin datos suficientes»;
  base = **3** ejecuciones, mínimo = la peor **menos 0,02**; aviso si un caso
  pasa de **1 MB**.
- Commits convencionales en español, cabecera ≤ 93 caracteres, sin
  `--no-verify`.
- **Entorno de esta máquina:** no hay Postgres. Los tests con `tmp_db` (los
  de la tarea 3 y los ya existentes de `tests/test_tender_fact_sheet.py`) **no
  se pueden ejecutar en local**: se dice así al terminar y los corre CI.
  `pytest` no está en el PATH: usar el Python del `.venv` de la raíz principal
  con `ENV=dev PYTHONPATH="$PWD"`.
- Post-flight de AGENTS.md §5 al terminar: `make lint`, `make typecheck`,
  `make test-unit`, `make check-layers`.

## Review Focus

Lo que la spec implica y ningún test de las tareas cubriría si no se añade
(cada línea tiene su test en la tarea indicada):

1. **Recapturar un caso ya revisado** borraría horas de etiquetado: la captura
   se niega si `golden.json` existe, salvo `--forzar` (tarea 3).
2. **La extracción falla o vuelve vacía** en un caso: el eval sigue con los
   demás, lo cuenta como fallido y sus positivos como omitidos (tareas 6 y 7).
3. **`--check` sin población** (ningún caso completo, o `minimos.json`
   ausente) debe fallar, no pasar por división entre cero (tareas 6 y 7).
4. **El modelo repite el mismo hecho dos veces:** solo uno puede ser acierto
   (tarea 5).
5. **Revisión interrumpida** con Ctrl-C o EOF a media respuesta: el golden
   queda en JSON válido y se retoma donde iba (tarea 4).

---

## Estructura de ficheros

| Fichero | Responsabilidad |
|---|---|
| `services/rag/ficha_golden.py` (nuevo) | Modelos del golden, lectura y escritura de casos, campos clave por familia |
| `services/rag/ficha_eval.py` (nuevo) | Emparejamiento, métricas, mínimos, cobertura del selector. Puro |
| `services/rag/fact_sheet.py` | Se añade `extraer_hechos`; `extract_fact_sheet` lo usa |
| `db/repositories/tender_fact_sheets.py` | Se añade `list_candidatas_golden` |
| `scripts/capturar_ficha_golden.py` (nuevo) | Producción → carpeta del caso |
| `scripts/revisar_ficha_golden.py` (nuevo) | Veredictos, corrección, añadir, estado |
| `scripts/eval_ficha.py` (nuevo) | Ejecuta el LLM sobre los casos e informa |
| `Makefile` | Objetivo `eval-ficha` |
| `tests/eval/test_eval_ficha_selector.py` (nuevo) | Integridad de los casos y ratchet del selector, en CI |

---

### Task 1: Modelos y ficheros del golden

**Files:**
- Create: `services/rag/ficha_golden.py`
- Test: `tests/test_ficha_golden.py`

**Interfaces — Produces:**

```python
Veredicto = Literal["correcto", "corregido", "añadido", "incorrecto"]
VEREDICTOS_POSITIVOS: frozenset[str]  # correcto, corregido, añadido
FAMILIAS: tuple[str, ...]             # tuple(TenderFactSheet.model_fields)
CAMPOS_PAGINA = ("documento_id", "page_number", "tipo", "filename",
                 "texto", "start_offset", "end_offset", "ocr")
CAMPOS_CLAVE: dict[str, tuple[str, ...]]

class HechoGolden(BaseModel):         # extra="forbid"
    veredicto: Veredicto | None
    hecho: dict[str, Any]             # forma del modelo de su familia
    valor_extraido: dict[str, Any] | None = None  # solo en `corregido`

class CasoGolden(BaseModel):          # extra="forbid"
    licitacion_id: str
    completo: bool
    capturado_el: date
    extraction_version: str | None
    model: str | None
    status_origen: str | None
    hechos: dict[str, list[HechoGolden]]

@dataclass(frozen=True)
class Caso:
    nombre: str
    golden: CasoGolden
    paginas: list[dict[str, Any]]

def modelo_de(familia: str) -> type[FactItem]
def positivos(golden: CasoGolden) -> dict[str, list[FactItem]]
def negativos(golden: CasoGolden) -> dict[str, list[FactItem]]
def sin_revisar(golden: CasoGolden) -> int
def propuesta_desde_ficha(licitacion_id: str, ficha: dict[str, Any] | None,
                          *, completo: bool, hoy: date) -> CasoGolden
def listar_casos(raiz: Path) -> list[Path]   # subcarpetas con golden.json, ordenadas
def leer_caso(carpeta: Path) -> Caso
def escribir_golden(carpeta: Path, golden: CasoGolden) -> None   # atómico: .tmp + replace
def escribir_paginas(carpeta: Path, paginas: list[dict[str, Any]]) -> int  # bytes escritos
```

`CAMPOS_CLAVE`, copiado de la spec §5 (el orden importa en la tarea 5):

| Familia | Campos |
|---|---|
| `award_criteria` | `weight_pct`, `name` |
| `economic_solvency`, `guarantees`, `penalties` | `amount_eur` |
| `lots` | `lot_number`, `amount_eur` |
| `price_formula` | `formula_type`, `max_points` |
| `rate_cards` | `role`, `max_rate_eur_hour` |
| `budget_breakdown` | `category`, `amount_eur` |
| `critical_deadlines` | `date_value`, `name` |
| `team_requirements` | `role`, `minimum_years` |
| `certifications`, `technologies`, `service_levels`, `required_documents` | `name` |
| `technical_solvency`, `subcontracting`, `extensions` | (ninguno) |

Reglas que la firma no determina:
- `CasoGolden` valida cada `hecho` contra `modelo_de(familia)` y rechaza una
  familia que no esté en `FAMILIAS`.
- `negativos` devuelve los `incorrecto` **y**, por cada `corregido`, el hecho
  con `valor_extraido` superpuesto (el valor original, que era el erróneo).
- `propuesta_desde_ficha` con `ficha=None` o sin `facts` devuelve un caso sin
  hechos; `status_origen`, `extraction_version` y `model` salen de la fila.
- `escribir_paginas` descarta las páginas con `texto` vacío y cualquier clave
  fuera de `CAMPOS_PAGINA`. Todo se escribe en UTF-8 con `ensure_ascii=False`.

- [ ] **Step 1: tests que fallan** en `tests/test_ficha_golden.py`

```python
def test_campos_clave_cubre_todas_las_familias_y_sus_campos_existen():
    assert set(CAMPOS_CLAVE) == set(TenderFactSheet.model_fields)
    for familia, campos in CAMPOS_CLAVE.items():
        assert set(campos) <= set(modelo_de(familia).model_fields)

def test_un_hecho_que_no_encaja_en_su_familia_se_rechaza():
    # award_criteria sin `name` -> ValidationError al construir CasoGolden

def test_una_familia_desconocida_se_rechaza(): ...

def test_positivos_negativos_y_sin_revisar():
    # correcto, corregido(hecho.weight_pct=60, valor_extraido={"weight_pct": 40}),
    # añadido, incorrecto y uno con veredicto None, todos en award_criteria
    assert len(positivos(g)["award_criteria"]) == 3
    assert [n.weight_pct for n in negativos(g)["award_criteria"]] == [<el incorrecto>, 40]
    assert sin_revisar(g) == 1

def test_escribir_paginas_omite_uri_y_paginas_vacias(tmp_path): ...
def test_golden_se_relee_igual_y_no_deja_temporal(tmp_path): ...
def test_propuesta_desde_ficha_deja_todo_sin_veredicto(): ...
def test_propuesta_de_una_ficha_fallida_no_tiene_hechos(): ...
```

- [ ] **Step 2:** ejecutar `python -m pytest tests/test_ficha_golden.py -q` → falla por import.
- [ ] **Step 3:** implementar `services/rag/ficha_golden.py`. `modelo_de` saca
  el tipo con `get_args(TenderFactSheet.model_fields[familia].annotation)`,
  como hace `_parse_facts`.
- [ ] **Step 4:** el mismo comando → verde. `python -m mypy services/rag/ficha_golden.py` → sin errores.
- [ ] **Step 5:** commit `feat(eval): modelos y ficheros del golden de la ficha del pliego`.

---

### Task 2: Núcleo de extracción sin base de datos

**Files:**
- Modify: `services/rag/fact_sheet.py` (función `extract_fact_sheet`, hoy en 667-760)
- Test: `tests/test_ficha_extraer_hechos.py`

**Interfaces — Produces:**

```python
@dataclass(frozen=True)
class ExtraccionHechos:
    facts: TenderFactSheet
    invalidos: int        # descartes de `_parse_facts`
    inverificables: int   # descartes de `_validate_fact_evidence`
    seleccionadas: list[dict[str, Any]]

def extraer_hechos(pages: list[dict[str, Any]], *, licitacion_id: str,
                   model: str = DEFAULT_MODEL) -> ExtraccionHechos
```

Reglas:
- `extraer_hechos` selecciona con `_select_pages`, lanza el mismo
  `ValueError("No hay texto por página disponible para extraer la ficha")` si
  no hay nada, llama al LLM con los mismos argumentos que hoy y valida las
  citas contra **todas** las páginas, no solo las seleccionadas.
- `extract_fact_sheet` **conserva la comprobación de páginas fuera del `try`**:
  hoy ese `ValueError` no persiste una fila `failed`, y debe seguir sin
  hacerlo. El resto de su cuerpo (log `fact_sheet_items_rejected`, `status`,
  `upsert`, relectura) no cambia.
- `stream_llm_response` se sigue referenciando desde este módulo: los tests
  existentes lo parchean como `services.rag.fact_sheet.stream_llm_response`.

- [ ] **Step 1: tests que fallan**

```python
def test_extraer_hechos_no_toca_los_repositorios():
    # patch de DocumentosRepository y TenderFactSheetsRepository con
    # side_effect=AssertionError; patch de stream_llm_response con un payload
    # de un criterio cuya cita está en la página
    r = extraer_hechos(paginas, licitacion_id="X", model="m")
    assert len(r.facts.award_criteria) == 1
    assert (r.invalidos, r.inverificables) == (0, 0)
    assert r.seleccionadas == paginas

def test_extraer_hechos_cuenta_los_dos_tipos_de_descarte():
    # un criterio sin `name` y otro con una cita que no está en la página
    assert (r.invalidos, r.inverificables) == (1, 1)

def test_extraer_hechos_sin_texto_lanza_value_error(): ...
def test_respuesta_vacia_del_modelo_lanza_value_error(): ...
```

- [ ] **Step 2:** `python -m pytest tests/test_ficha_extraer_hechos.py -q` → falla por import.
- [ ] **Step 3:** implementar. Un privado común recibe `pages` y `selected`;
  `extraer_hechos` y `extract_fact_sheet` lo llaman.
- [ ] **Step 4:** el mismo comando → verde; `python -m mypy services/rag/fact_sheet.py`.
- [ ] **Step 5:** `tests/test_tender_fact_sheet.py` y
  `tests/test_fact_sheet_extract_async_route.py` **no se tocan**. Necesitan
  Postgres: anotar «no ejecutados en local» y comprobarlos en CI.
- [ ] **Step 6:** commit `refactor(pliegos): la extracción de hechos de la ficha se puede llamar sin base de datos`.

---

### Task 3: Candidatos y captura

**Files:**
- Modify: `db/repositories/tender_fact_sheets.py`
- Create: `scripts/capturar_ficha_golden.py`
- Test: `tests/test_tender_fact_sheets_candidatas.py` (con `tmp_db`), `tests/test_capturar_ficha_golden.py`

**Interfaces:**
- Consumes: `propuesta_desde_ficha`, `escribir_golden`, `escribir_paginas`
  (tarea 1); `DocumentosRepository.list_pages_by_licitacion`,
  `TenderFactSheetsRepository.get`.
- Produces:

```python
# db/repositories/tender_fact_sheets.py
def list_candidatas_golden(self, *, limit: int = 200) -> list[dict[str, Any]]
# claves: licitacion_id, fuente, documentos, paginas, paginas_ocr,
#         status, extraction_version, field_count, lotes, formulas

# scripts/capturar_ficha_golden.py
RAIZ_POR_DEFECTO = <repo>/tests/eval/fixtures/fichas
class CasoYaExiste(Exception): ...
def capturar(licitacion_id: str, carpeta: Path, *, completo: bool, forzar: bool,
             documentos: Any, fichas: Any, hoy: date) -> int   # bytes de paginas.jsonl
def main(argv: list[str] | None = None) -> int
```

Reglas:
- La consulta usa `connect_read`, solo lista licitaciones con alguna página de
  texto no vacío, hace `LEFT JOIN` con `tender_fact_sheets` (una licitación sin
  ficha sale con `status` nulo) y ordena por `fuente`, `field_count`,
  `licitacion_id`. `data_json` es `text`: `lotes` y `formulas` salen de
  `jsonb_array_length(COALESCE(data_json::jsonb -> 'lots', '[]'::jsonb))` y lo
  mismo con `'price_formula'`.
- CLI: `--listar`; o `<licitacion_id> --caso <nombre> [--completo] [--forzar]`;
  `--raiz` para tests. Imprime un aviso si `paginas.jsonl` supera 1 MB.
- `capturar` lanza `CasoYaExiste` si `carpeta/golden.json` existe y no hay
  `forzar`; `main` lo traduce a un mensaje y código 1.

- [ ] **Step 1: tests que fallan**

```python
# tests/test_tender_fact_sheets_candidatas.py
def test_lista_solo_licitaciones_con_paginas_y_cuenta_lotes(tmp_db):
    # sembrar como `_seed_pages` de tests/test_tender_fact_sheet.py; una con
    # ficha de dos lotes, otra con páginas y sin ficha, otra sin páginas
    filas = {f["licitacion_id"]: f for f in repo.list_candidatas_golden()}
    assert filas["A"]["lotes"] == 2 and filas["A"]["formulas"] == 0
    assert filas["B"]["status"] is None
    assert "C" not in filas

# tests/test_capturar_ficha_golden.py  (repositorios falsos, sin BD)
def test_captura_escribe_paginas_sin_uri_y_golden_sin_veredictos(tmp_path): ...
def test_no_pisa_un_caso_que_ya_existe(tmp_path):
    with pytest.raises(CasoYaExiste): capturar(..., forzar=False)
    # y el golden.json sigue intacto, byte a byte
def test_con_forzar_si_lo_reescribe(tmp_path): ...
def test_main_devuelve_1_y_no_lanza_si_el_caso_existe(tmp_path, capsys): ...
```

- [ ] **Step 2:** `python -m pytest tests/test_capturar_ficha_golden.py -q` → falla por import.
- [ ] **Step 3:** implementar el método del repositorio y el script.
- [ ] **Step 4:** el mismo comando → verde. El test con `tmp_db` no se ejecuta
  en local: anotarlo.
- [ ] **Step 5:** commit `feat(eval): captura de pliegos reales como casos del golden de la ficha`.

---

### Task 4: Revisión

**Files:**
- Create: `scripts/revisar_ficha_golden.py`
- Test: `tests/test_revisar_ficha_golden.py`

**Interfaces:**
- Consumes: `leer_caso`, `escribir_golden`, `CAMPOS_CLAVE`, `modelo_de`,
  `sin_revisar`, `listar_casos` (tarea 1); `_validated_evidence` de
  `services.rag.fact_sheet`.
- Produces:

```python
Lector = Callable[[str], str]   # misma firma que input()
def revisar(carpeta: Path, *, leer: Lector = input) -> int   # veredictos escritos
def anadir(carpeta: Path, *, leer: Lector = input) -> int    # hechos añadidos
def estado(raiz: Path) -> bool   # ≥ 10 casos, ≥ 3 completos y 0 sin revisar
def main(argv: list[str] | None = None) -> int
```

Reglas (patrón de `scripts/revisar_golden_candidates.py`):
- Teclas: `c` correcto · `i` incorrecto · `v` corregir valor · `s` saltar ·
  `?` ver la página entera de la cita · `q` guardar y salir. **Se guarda tras
  cada veredicto.** `EOFError` y `KeyboardInterrupt` equivalen a `q`.
- `v` pregunta uno a uno los campos de `CAMPOS_CLAVE[familia]`; una respuesta
  vacía conserva el valor. El hecho resultante se valida con
  `modelo_de(familia)`; si no valida, se vuelve a preguntar. Guarda
  `veredicto="corregido"` y en `valor_extraido` solo los campos que cambiaron.
  En una familia sin campos clave, `v` no existe.
- Antes de los hechos del golden se revisan los de `pendientes.json` (lista de
  `{"familia", "hecho"}` que escribe la tarea 7): al recibir veredicto pasan al
  golden; el fichero se borra al quedar vacío.
- `anadir` solo funciona si `golden.completo`. Pide familia, `documento_id`,
  `page_number`, cita, campos clave y descripción (por defecto, la cita). La
  cita se comprueba con `_validated_evidence` contra las páginas del caso; si
  no está literalmente, se dice y se vuelve a pedir. `confidence=1.0`,
  `veredicto="añadido"`.
- CLI: `<caso>`, `--anadir`, `--estado`, `--raiz`.

- [ ] **Step 1: tests que fallan** (el `leer` es un iterador de respuestas)

```python
def test_guarda_cada_veredicto_y_retoma_donde_iba(tmp_path):
    assert revisar(caso, leer=respuestas("c", "i", "q")) == 2
    assert revisar(caso, leer=respuestas("c")) == 1     # solo quedaba uno

def test_corregir_guarda_el_valor_bueno_y_el_original(tmp_path):
    # criterio con weight_pct=40; respuestas "v", "60", ""
    assert h.veredicto == "corregido"
    assert h.hecho["weight_pct"] == 60 and h.valor_extraido == {"weight_pct": 40}

def test_un_valor_que_no_valida_se_vuelve_a_pedir(tmp_path): ...   # "v", "abc", "60", ""

def test_eof_a_media_revision_deja_un_golden_valido(tmp_path):
    # `leer` lanza EOFError en la segunda pregunta
    assert revisar(caso, leer=...) == 1
    leer_caso(caso)   # no lanza

def test_anadir_rechaza_una_cita_que_no_esta_en_la_pagina(tmp_path): ...
def test_anadir_se_niega_en_un_caso_parcial(tmp_path): ...
def test_los_pendientes_pasan_al_golden_y_el_fichero_desaparece(tmp_path): ...
def test_estado_es_falso_con_nueve_casos(tmp_path): ...
```

- [ ] **Step 2:** `python -m pytest tests/test_revisar_ficha_golden.py -q` → falla por import.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** el mismo comando → verde.
- [ ] **Step 5:** commit `feat(eval): revisión a teclado de los casos del golden de la ficha`.

**Tras esta tarea el propietario ya puede empezar los pasos 1 a 4 de la spec §8**
mientras se hacen las tareas 5 a 8.

---

### Task 5: Emparejamiento

**Files:**
- Create: `services/rag/ficha_eval.py`
- Test: `tests/test_ficha_eval.py`

**Interfaces:**
- Consumes: `CAMPOS_CLAVE` (tarea 1); `_normalize_quote`, `_MIN_FRAGMENTO_CHARS`
  de `services.rag.fact_sheet`.
- Produces:

```python
Comparacion = Literal["igual", "distinta", "sin_comparar"]
Resultado = Literal["acierto", "valor_distinto", "error_confirmado",
                    "sin_juzgar", "falso_positivo"]

@dataclass(frozen=True)
class Emparejado:
    extraido: FactItem
    golden: FactItem | None
    resultado: Resultado

@dataclass(frozen=True)
class EmparejamientoFamilia:
    familia: str
    pares: list[Emparejado]     # uno por hecho extraído, en su orden
    omitidos: list[FactItem]    # positivos sin acierto

def comparar_clave(familia: str, a: FactItem, b: FactItem) -> Comparacion
def emparejar(familia: str, extraidos: Sequence[FactItem],
              positivos: Sequence[FactItem], negativos: Sequence[FactItem],
              *, completo: bool) -> EmparejamientoFamilia
```

`comparar_clave`:
- Números: `math.isclose(a, b, rel_tol=0.005)`. Fechas y literales
  (`formula_type`, `category`): igualdad. Texto (`name`, `role`): sin
  mayúsculas, tildes ni signos, partido en palabras; iguales si un conjunto de
  palabras contiene al otro o su Jaccard es ≥ 0,5. `lot_number`: lo mismo
  quitando la palabra «lote», e igualdad exacta de lo que queda.
- Un campo solo se compara si **ambos** lados lo traen.
- Familias de dos campos, según la spec §5:
  - **alternativa** (`award_criteria`, `lots`, `critical_deadlines`): decide el
    primer campo si es comparable; si no, el segundo.
  - **conjunta** (`price_formula`, `rate_cards`, `budget_breakdown`,
    `team_requirements`): el primero debe ser comparable e igual; el segundo
    solo cuenta si es comparable.
- Nada comparable, o familia sin campos → `sin_comparar`.

`emparejar` (el algoritmo no sale de la firma):
1. Para cada par (extraído, golden): `solape` = mayor subcadena común entre sus
   citas normalizadas del mismo documento (`difflib.SequenceMatcher(...,
   autojunk=False).find_longest_match`); `ancla_cita` = solape ≥ 20;
   `ancla_pagina` = mismo documento y páginas a distancia ≤ 1.
2. Un par **casa** si `ancla_cita` y la clave no es `distinta`, o si
   `ancla_pagina` y la clave es `igual`. La página sola nunca basta cuando la
   clave es `sin_comparar`.
3. Tres pasadas uno a uno, cada una sobre lo que dejó libre la anterior,
   asignando por mayor solape y, a igualdad, por orden de aparición:
   positivos que casan → `acierto`; negativos que casan → `error_confirmado`;
   positivos libres con `ancla_cita` y clave `distinta` → `valor_distinto`
   (ese positivo queda consumido, pero **sigue en `omitidos`**).
4. Lo que queda: `falso_positivo` si `completo`, `sin_juzgar` si no.

- [ ] **Step 1: tests que fallan**

```python
@pytest.mark.parametrize(("familia", "a", "b", "esperado"), [
    ("award_criteria", {"weight_pct": 60}, {"weight_pct": 60.2}, "igual"),
    ("award_criteria", {"weight_pct": 60}, {"weight_pct": 61}, "distinta"),
    ("award_criteria", {"name": "Precio"}, {"name": "Oferta económica (precio)"}, "igual"),
    ("certifications", {"name": "ISO 27001"}, {"name": "ISO/IEC 27001:2022"}, "igual"),
    ("certifications", {"name": "ISO 9001"}, {"name": "ISO 27001"}, "distinta"),
    ("lots", {"lot_number": "Lote 1"}, {"lot_number": "1"}, "igual"),
    ("price_formula", {"formula_type": "otra"}, {"formula_type": "proporcional_inversa"}, "distinta"),
    ("economic_solvency", {"amount_eur": None}, {"amount_eur": 5000.0}, "sin_comparar"),
    ("technical_solvency", {}, {}, "sin_comparar"),
])
def test_comparar_clave(familia, a, b, esperado): ...

def test_misma_clave_en_pagina_contigua_es_acierto_sin_solape_de_cita(): ...
def test_cita_solapada_con_otro_peso_es_valor_distinto_y_el_positivo_queda_omitido(): ...
def test_dos_criterios_del_mismo_peso_en_la_misma_pagina_casan_cada_uno_con_el_suyo(): ...
def test_un_hecho_repetido_solo_acierta_una_vez():
    # completo=True  -> resultados == ["acierto", "falso_positivo"]
    # completo=False -> resultados == ["acierto", "sin_juzgar"]
def test_un_negativo_conocido_es_error_confirmado(): ...
def test_repetir_el_valor_original_de_un_corregido_es_error_confirmado_no_valor_distinto(): ...
def test_familia_sin_clave_no_casa_solo_por_la_pagina(): ...
def test_importe_ausente_no_casa_solo_por_la_pagina(): ...
def test_una_cita_abreviada_con_elipsis_casa_con_la_completa(): ...
```

- [ ] **Step 2:** `python -m pytest tests/test_ficha_eval.py -q` → falla por import.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** el mismo comando → verde; `python -m mypy services/rag/ficha_eval.py`.
- [ ] **Step 5:** commit `feat(eval): emparejamiento determinista entre la ficha extraída y el golden`.

---

### Task 6: Métricas, mínimos y cobertura del selector

**Files:**
- Modify: `services/rag/ficha_eval.py`
- Test: `tests/test_ficha_eval.py`

**Interfaces:**
- Consumes: `emparejar` (tarea 5); `Caso`, `positivos`, `negativos`, `FAMILIAS`
  (tarea 1); `ExtraccionHechos` (tarea 2).
- Produces:

```python
MIN_POSITIVOS_POR_FAMILIA = 10
CLAVES_DE_MINIMOS = ("precision_completos", "cobertura_completos",
                     "conservados_parciales", "selector_cobertura")

@dataclass(frozen=True)
class MetricasFamilia:
    extraidos: int = 0
    positivos: int = 0
    aciertos: int = 0
    valor_distinto: int = 0
    errores_confirmados: int = 0
    sin_juzgar: int = 0
    falsos_positivos: int = 0
    def __add__(self, otra: MetricasFamilia) -> MetricasFamilia
    @property
    def precision(self) -> float | None    # aciertos / extraidos
    @property
    def cobertura(self) -> float | None    # aciertos / positivos

@dataclass(frozen=True)
class ResultadoCaso:
    nombre: str
    completo: bool
    por_familia: dict[str, MetricasFamilia]
    invalidos: int
    inverificables: int
    fallo: str | None
    pendientes: list[tuple[str, FactItem]]   # los `sin_juzgar`, con su familia

@dataclass(frozen=True)
class Informe:
    completos: dict[str, MetricasFamilia]
    parciales: dict[str, MetricasFamilia]
    n_completos: int
    n_parciales: int
    casos_fallidos: int
    invalidos: int                     # suma de los casos
    inverificables: int                # suma de los casos
    totales: dict[str, float | None]   # las tres primeras CLAVES_DE_MINIMOS

def medir_caso(caso: Caso, extraccion: ExtraccionHechos | None,
               *, fallo: str | None = None) -> ResultadoCaso
def agregar(resultados: Sequence[ResultadoCaso]) -> Informe
def comprobar_minimos(totales: Mapping[str, float | None],
                      minimos: Mapping[str, float]) -> list[str]   # faltas; vacío = cumple
def cobertura_selector(caso: Caso, seleccionadas: Sequence[Mapping[str, Any]]
                       ) -> dict[str, tuple[int, int]]   # familia -> (cubiertos, positivos)
def minimos_desde(ejecuciones: Sequence[Mapping[str, float | None]],
                  selector: float) -> dict[str, float]
```

Reglas:
- `precision` y `cobertura` son `None` con denominador 0.
- `medir_caso(caso, None, fallo=...)`: 0 extraídos y todos los positivos sin
  acierto. Sus positivos **sí** entran en los denominadores.
- `conservados_parciales` = aciertos / positivos sobre los casos parciales.
- `comprobar_minimos`: una clave con mínimo y valor `None` es una falta («sin
  población»); una clave de `minimos` que no esté en `totales` también.
- `cobertura_selector`: un positivo está cubierto si alguna de sus citas cae
  en una página seleccionada.
- `minimos_desde`: por clave, el menor valor de las ejecuciones menos 0,02,
  nunca por debajo de 0, truncado a tres decimales; lanza `ValueError` si
  alguna ejecución trae `None`. `selector_cobertura` entra tal cual.

- [ ] **Step 1: tests que fallan**

```python
def test_caso_completo_precision_y_cobertura():
    # 4 extraídos: 2 aciertos, 1 valor_distinto, 1 falso positivo; 3 positivos
    assert (t.precision, t.cobertura) == (0.5, pytest.approx(2 / 3))

def test_en_un_caso_parcial_lo_no_revisado_no_es_error_y_sale_en_pendientes(): ...

def test_una_extraccion_fallida_cuenta_sus_positivos_como_omitidos():
    r = medir_caso(caso, None, fallo="respuesta vacía")
    assert agregar([r]).casos_fallidos == 1
    assert agregar([r]).totales["cobertura_completos"] == 0.0

def test_sin_casos_completos_los_totales_son_none(): ...

def test_comprobar_minimos():
    assert comprobar_minimos({"precision_completos": 0.8}, {"precision_completos": 0.7}) == []
    assert len(comprobar_minimos({"precision_completos": 0.6}, {"precision_completos": 0.7})) == 1
    assert len(comprobar_minimos({"precision_completos": None}, {"precision_completos": 0.7})) == 1

def test_cobertura_selector_cuenta_el_positivo_si_su_pagina_entro(): ...

def test_minimos_desde_toma_la_peor_ejecucion_menos_dos_puntos():
    e = [{"precision_completos": 0.80, ...}, {"precision_completos": 0.74, ...}, ...]
    assert minimos_desde(e, selector=0.9)["precision_completos"] == 0.72
    assert minimos_desde(e, selector=0.9)["selector_cobertura"] == 0.9
```

- [ ] **Step 2:** `python -m pytest tests/test_ficha_eval.py -q` → los nuevos fallan.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** el mismo comando → verde; mypy del módulo.
- [ ] **Step 5:** commit `feat(eval): métricas por familia, mínimos y cobertura del selector de la ficha`.

---

### Task 7: Evaluación con el modelo real

**Files:**
- Create: `scripts/eval_ficha.py`
- Modify: `Makefile` (junto a `eval-llm`, línea 130)
- Test: `tests/test_unit_eval_ficha.py`

**Interfaces:**
- Consumes: tareas 1, 2 y 6.
- Produces:

```python
Extractor = Callable[..., ExtraccionHechos]   # la firma de `extraer_hechos`
def evaluar(raiz: Path, *, model: str, solo: str | None = None,
            extraer: Extractor = extraer_hechos
            ) -> tuple[Informe, list[ResultadoCaso], dict[str, tuple[int, int]]]
            # el tercero: cobertura del selector sumada por familia
def formatear(informe: Informe, selector: Mapping[str, tuple[int, int]]) -> str
def main(argv: list[str] | None = None) -> int
```

Reglas:
- `main` deja el proceso sin base de datos **antes de importar nada que
  conecte**, igual que `_sin_bd()` en `scripts/eval_rag_generation.py`.
- Un caso con `sin_revisar(golden) > 0` se salta con un aviso por stderr.
- Si `extraer` lanza, el caso se mide con `fallo=str(exc)` y se sigue.
- `formatear`: una tabla para completos y otra para parciales, por familia y
  total. Una familia con menos de `MIN_POSITIVOS_POR_FAMILIA` positivos
  muestra su N y «sin datos suficientes» en vez de porcentajes.
- Opciones: `--model` (por defecto `DEFAULT_MODEL`), `--caso`, `--raiz`,
  `--salida <json>`, `--pendientes`, `--check`, `--fijar-minimos`.
  - `--pendientes`: escribe `pendientes.json` en cada caso parcial con hechos
    `sin_juzgar` (lista de `{"familia", "hecho"}`).
  - `--check`: código 1 si falta `minimos.json` o `comprobar_minimos`
    devuelve faltas, imprimiéndolas. Antes de comprobar, `main` añade a
    `informe.totales` la clave `selector_cobertura` (cubiertos / positivos
    sumando todas las familias): `comprobar_minimos` trata como falta una
    clave de `minimos` que no reciba.
  - `--fijar-minimos`: tres ejecuciones, `minimos_desde`, y escribe
    `minimos.json` con `medido_el`, `model`, `extraction_version`,
    `ejecuciones: 3` y `minimos`. **Se niega (código 1) a escribir un mínimo
    más bajo que el que ya existe**, diciendo cuál.
  - Código 2 si no hay ningún caso evaluable.
- Makefile:
  `eval-ficha:  ## Eval de la ficha del pliego con el LLM real (sin BD, fuera de CI; requiere la API key del LLM)`
  → `python scripts/eval_ficha.py`

- [ ] **Step 1: tests que fallan** (el `extraer` es un doble; nunca hay LLM)

```python
def test_no_abre_conexiones_aunque_el_entorno_apunte_a_produccion(monkeypatch, tmp_path):
    # mismo patrón que tests/test_unit_eval_rag_generation.py

def test_un_caso_con_veredictos_pendientes_se_salta_y_se_avisa(tmp_path, capsys): ...

def test_si_la_extraccion_de_un_caso_lanza_los_demas_se_evaluan(tmp_path):
    informe, resultados, _ = evaluar(raiz, model="m", extraer=falla_en("caso-b"))
    assert informe.casos_fallidos == 1 and len(resultados) == 2

def test_check_devuelve_1_por_debajo_del_minimo(tmp_path): ...
def test_check_devuelve_1_si_no_hay_minimos_json(tmp_path): ...
def test_sin_casos_evaluables_devuelve_2(tmp_path): ...
def test_formatear_dice_sin_datos_suficientes_con_menos_de_diez_positivos(): ...
def test_pendientes_escribe_los_sin_juzgar_de_un_caso_parcial(tmp_path): ...
def test_fijar_minimos_no_baja_un_minimo_existente(tmp_path): ...
```

- [ ] **Step 2:** `python -m pytest tests/test_unit_eval_ficha.py -q` → falla por import.
- [ ] **Step 3:** implementar el script y el objetivo del Makefile.
- [ ] **Step 4:** el mismo comando → verde. `python scripts/eval_ficha.py`
  sin casos → código 2 y un mensaje que remite a la spec §8.
- [ ] **Step 5:** commit `feat(eval): make eval-ficha mide la ficha del pliego contra el golden`.

---

### Task 8: Integridad de los casos y ratchet del selector, en CI

**Files:**
- Create: `tests/eval/test_eval_ficha_selector.py`

**Interfaces — Consumes:** `listar_casos`, `leer_caso`, `positivos`,
`sin_revisar` (tarea 1); `cobertura_selector` (tarea 6); `_select_pages`,
`_validated_evidence` de `services.rag.fact_sheet`.

Reglas:
- Raíz: `tests/eval/fixtures/fichas`. **Sin casos y sin `minimos.json`**: los
  dos tests de datos hacen `pytest.skip` con el motivo «aún no hay casos
  capturados (docs/plans/2026-10-eval-ficha-pliego.md §8)». **Con
  `minimos.json` y sin casos: fallan.** Un control que se salta en silencio
  cuando ya debería morder no cuenta como verde.
- `test_integridad_de_los_casos`: cada caso carga, no tiene veredictos en
  `null`, y la cita de cada positivo está literalmente en su página
  (`_validated_evidence` sobre una **copia** de la cita: la función la muta).
- `test_cobertura_del_selector`: total de cubiertos / positivos ≥
  `minimos["selector_cobertura"]`; la tabla por familia se publica con el
  mismo mecanismo que `_publicar` de `tests/eval/test_eval_rag.py`
  (`GITHUB_STEP_SUMMARY`).
- La política de saltar o fallar vive en una función con la raíz como
  parámetro, para poder probarla con `tmp_path`.

- [ ] **Step 1: tests que fallan**

```python
def test_sin_casos_ni_minimos_se_salta(tmp_path):
    with pytest.raises(pytest.skip.Exception): _casos_o_skip(tmp_path)

def test_con_minimos_y_sin_casos_falla(tmp_path):
    (tmp_path / "minimos.json").write_text("{}", encoding="utf-8")
    with pytest.raises(pytest.fail.Exception): _casos_o_skip(tmp_path)

def test_integridad_de_los_casos(): ...
def test_cobertura_del_selector(): ...
```

- [ ] **Step 2:** `python -m pytest tests/eval/test_eval_ficha_selector.py -q -rs`
  → los dos primeros fallan por import.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** el mismo comando → 2 verdes y 2 saltados con el motivo escrito.
- [ ] **Step 5:** `make lint`, `make typecheck`, `make test-unit`,
  `make check-layers`. Anotar lo que no se pudo ejecutar y por qué.
- [ ] **Step 6:** commit `test(eval): integridad de los casos de la ficha y ratchet de su selector de páginas`.

---

## Después del código: lo que solo puede hacer el propietario

No son tareas de un agente (spec §8). En este orden:

1. `python scripts/capturar_ficha_golden.py --listar` y elegir diez con los
   criterios de la spec §3 (dos de ficha pobre o fallida; uno de ellos entre
   los tres completos).
2. Capturar los diez, tres con `--completo`.
3. `python scripts/revisar_ficha_golden.py <caso>` en los diez;
   `--anadir` en los tres completos tras leer el pliego entero.
4. `python scripts/revisar_ficha_golden.py --estado` → cumple.
5. `python scripts/eval_ficha.py --fijar-minimos` y commit de los casos y de
   `minimos.json`. Desde ese commit, los dos tests de datos de la tarea 8
   dejan de saltarse.

Y entonces, en el mismo cambio (AGENTS.md §5, post-flight 4): mover el ítem
«Golden set de extracción de fichas» a _Cerrados_, quitar del ítem «Unificar la
selección de páginas…» la frase que lo da por bloqueado, y poner la spec en
«implementada».

**D4 de la spec sigue sin respuesta explícita** (versionar el texto completo de
los pliegos). El plan asume que sí; si la respuesta es no, cambia solo
`RAIZ_POR_DEFECTO` y la raíz de la tarea 8, y los dos tests de datos pasan a
depender de una ruta fuera del repositorio.

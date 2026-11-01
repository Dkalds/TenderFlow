# Puntuaciones del acta de adjudicación — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** en una oportunidad adjudicada, enseñar la nota de cada licitador por
criterio según el acta de la mesa, la diferencia de la organización frente al
ganador y un motivo de pérdida propuesto.

**Architecture:** el parser CODICE guarda las actas de PLACSP como
`documentos.tipo='acta'`, que el pipeline de pliegos ignora. Tras cada pasada,
un job de la cola (`puntuaciones_acta`) descarga las actas de los expedientes
con oportunidad, extrae la tabla de puntuaciones con una llamada al LLM, la
valida cita a cita y la guarda en filas. La ficha de la oportunidad la lee en
`PursuitAdjudicacionDetectada.puntuaciones`. La fila propia se confirma con el
`PATCH` de siempre, que la anota en el ledger.

**Tech Stack:** Python 3.12, FastAPI, psycopg/Postgres, Alembic, Pydantic v2,
lxml, pytest; Next.js + React + vitest en `web/`.

**Spec:** [docs/superpowers/specs/2026-11-01-puntuaciones-acta-design.md](../specs/2026-11-01-puntuaciones-acta-design.md)

## Global Constraints

- Plan 2026-10, D50: ni endpoint, ni espacio, ni pantalla nuevos. `api/superficie_congelada.txt` y la lista `NUEVAS` no cambian.
- Typing strict en todo `.py` de producción. Ni `Any` ni `# type: ignore` sin comentario inline. Ningún override nuevo en `pyproject.toml` (AGENTS.md §3.1).
- Todo el SQL vive en `db/` (§3.10). `services/` llama a `db.*` y nunca al revés. Los imports van hacia abajo (`make check-layers`).
- Las rutas nacen tipadas con DTOs Pydantic v2 en `shared/dto/pursuits.py` (§3.5). Nada de `dict[str, Any]` en el contrato.
- Escrituras idempotentes (§3.2): la de `acta_puntuaciones` borra y vuelve a insertar el expediente en una transacción.
- Migraciones append-only (§3.3). **Antes de crear la revisión hace falta el OK explícito del usuario** (AGENTS.md §6).
- Sin cita verificable no hay dato (ADR-014). La cita la valida `services.rag.fact_sheet._validated_evidence`; esa lógica no se copia.
- LLM sin fallback de proveedor (la fila guarda `model`), con `model=settings.PLIEGO_FACTS_MODEL` y un tope de tiempo propio.
- Versión de extracción: `EXTRACTION_VERSION = "acta-puntuaciones-v1"`.
- Tipo de job: `TIPO_PUNTUACIONES_ACTA = "puntuaciones_acta"`, deduplicado por `licitacion_id`.
- Evento del ledger: `FILA_ACTA_EVENT_TYPE = "fila_acta_confirmada"`, con payload `{"lote_numero": str | None, "licitador_normalizado": str}`.
- Textos de la interfaz, literales del spec §6.5:
  - pendiente: «Leyendo el acta de la mesa»
  - sin acta: «PLACSP no publicó acta de mesa para este expediente»
  - sin tabla: «El acta no trae puntuaciones por licitador»
  - error: «No se pudo leer el acta; se reintenta en la próxima pasada»
  - botones: «Esta es mi empresa» y «¿Es esta tu empresa?»
- Tests: la categoría (`unit`/`integration`) la infiere `tests/conftest.py` por el nombre y por los fixtures de BD. Sin markers manuales. Postgres no está en este equipo: los `integration` corren en CI o con `bash scripts/dev/wsl_run.sh`, y si no se ejecutan se dice.
- Prefijá `ENV=dev` y `PYTHONPATH="$PWD"` a todo comando Python en este worktree. El intérprete es el `.venv` del checkout principal.
- Cada commit termina con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Sin push ni PR sin pedirlo.

## Desviaciones del spec (decididas al leer el código)

- **§4.1. El encolado no vive dentro de `notify_detected_awards`.** Ese aviso solo recorre oportunidades *abiertas* (`open_with_award_rows`), y el post-mortem sirve sobre todo a las ya cerradas como perdidas. Por eso hay una función propia, `services.puntuaciones_acta.encolar_pendientes`, que `scheduler/pipeline_runs.py` llama justo después del aviso.
- **§4.2.5. `_validated_evidence` se importa de `services.rag.fact_sheet`, no se mueve.** Hay cuatro importadores y un precedente igual (`services/rag/ficha_eval.py`), y la regla del spec era no copiarla.
- **§4.2.4. La fila que devuelve el modelo lleva `documento_id`.** Con hasta tres actas por expediente, la página sola no identifica la cita.
- **§6.1. `DiferenciaCriterio` lleva `documento_id` y `pagina`.** Es lo que necesita «cada cifra enlaza a su página del acta» (§6.5).
- **§6.4. La preselección del motivo va en la tarjeta de adjudicación.** Hoy esa tarjeta cierra como perdida sin `outcome_reason_code` y la API responde 422: es un defecto existente, y Task 8 lo arregla al añadir el selector. `DialogoCierre` no cambia, porque su decisión de no preseleccionar está documentada y no tiene la evidencia del acta.

## Review Focus

1. **Oportunidad de un solo lote frente a un acta de varios.** Con `pursuits.lote_numero` informado y presente en el acta, la ficha enseña solo ese lote. Si no está en el acta, enseña todos. Test: Task 7, `test_puntuaciones_filtra_el_lote_de_la_oportunidad`.
2. **UTE que incluye a la organización.** Una fila «UTE MI EMPRESA - OTRA» no es la fila propia: el casamiento es exacto tras `normalize_company`. Test: Task 5, `test_fila_propia_no_casa_una_ute_que_la_contiene`.
3. **Rótulos de lote distintos** («Lote 1», «LOTE Nº 1», «1») frente a `lotes.numero = "1"`. Todos casan tras `normalizar_lote`. Test: Task 5, `test_normalizar_lote`.
4. **Cifras con coma decimal** que el modelo devuelve como texto («18,50», «65»). Se convierten a `float`; una cifra ilegible es `None` y no tumba la fila. Test: Task 5, `test_respuesta_acepta_coma_decimal`.
5. **Fila confirmada que desaparece al reextraer**, porque el acta o la versión cambian y su `licitador_normalizado` ya no está. La lectura vuelve a la propuesta, con `fila_propia_confirmada=False`. Test: Task 7, `test_confirmacion_huerfana_vuelve_a_la_propuesta`.

---

### Task 1: El parser guarda las actas de `GeneralDocument`

**Files:**
- Modify: `scraper/codice_parser.py` (`_DOC_REF_TAGS` ~246, `parse_document_references` ~253)
- Modify: `db/upsert.py:370` (comentario de `DocumentoReferencia.tipo`: añadir `acta`)
- Modify: `tests/fixtures/placsp/golden.jsonl` (regenerado)
- Test: `tests/test_codice_parser.py` (clase nueva `TestActasGeneralDocument` junto a `TestParseDocumentReferences`)

**Interfaces:**
- Produces: `DocumentoReferencia(tipo="acta", uri, filename, source_hash)`. `parse_document_references(entry)` mantiene su firma.

- [ ] **Step 1: Escribir los tests que fallan**

  Un builder local `_make_entry_con_general_documents(docs: list[tuple[str, str, str | None]])`, donde cada tupla es `(type_code, filename, uri)`. Genera los nodos `cac-place-ext:GeneralDocument/GeneralDocumentDocumentReference` con la misma forma que el fixture 19 (líneas 343–378): `cbc:ID`, `cbc:DocumentTypeCode` y `cac:Attachment/cac:ExternalReference/{cbc:URI,cbc:FileName}`.

  ```python
  def test_codigo_12_entra_como_acta(self):
      refs = parse_document_references(self._get_entry(_make_entry_con_general_documents(
          [("12", "Acta del órgano de asistencia", "https://contrataciondelestado.es/a12")])))
      assert [(r.tipo, r.uri, r.filename) for r in refs] == [
          ("acta", "https://contrataciondelestado.es/a12", "Acta del órgano de asistencia")]

  @pytest.mark.parametrize("nombre", ["Informe de valoración", "Informe criterios automaticos",
                                      "Adjudicación definitiva 0027", "Propuesta de adjudicación"])
  def test_zzz_con_nombre_de_valoracion_entra(self, nombre): ...  # un ref tipo "acta"

  @pytest.mark.parametrize("codigo,nombre", [("9", "Memoria justificativa"),
      ("11", "Aprobación del expediente"), ("14", "Informe ofertas anormales"),
      ("ZZZ", "Anuncio de licitación")])
  def test_otros_general_documents_se_ignoran(self, codigo, nombre): ...  # refs == []

  def test_general_document_sin_uri_se_descarta(self): ...  # ("12", "Acta", None) -> []

  def test_fixture_19_trae_sus_dos_actas(self):
      # Parsear tests/fixtures/placsp/19_multilote_adjudicado_real.xml con
      # `_parse_fixture` de tests/test_codice_parser_golden.py (importarlo).
      actas = [d for d in parsed["documentos"] if d["tipo"] == "acta"]
      assert len(actas) == 2
      assert all(d["filename"] == "Acta del órgano de asistencia" for d in actas)
  ```

- [ ] **Step 2: Ejecutarlos y ver que fallan**

  Run: `ENV=dev PYTHONPATH="$PWD" python -m pytest tests/test_codice_parser.py -k "Actas" -q`
  Expected: FAIL (no sale ningún `acta`).

- [ ] **Step 3: Implementar en `scraper/codice_parser.py`**

  Tras el bucle de `_DOC_REF_TAGS`, un segundo recorrido sobre `f"{cfs}/cacext:GeneralDocument/cacext:GeneralDocumentDocumentReference"`. Es acta si `cbc:DocumentTypeCode == "12"`, o si es `"ZZZ"` y `fold_text(nombre)` casa con `_NOMBRE_ACTA_RE = re.compile(r"valoraci|criterios autom|adjudicaci|propuesta")`. `fold_text` viene de `services.normalization`. Comprobar con `make check-layers` que `scraper` puede importarlo; si no, la regex se aplica sobre `nombre.casefold()` con las variantes sin tilde. La extracción de URI, nombre y hash se saca a un helper `_referencia(node, tipo) -> DocumentoReferencia | None`, que usan los dos recorridos para no duplicarla. Ampliar el docstring con un párrafo sobre `GeneralDocument`.

- [ ] **Step 4: Ejecutar y ver que pasan**

  Run: `ENV=dev PYTHONPATH="$PWD" python -m pytest tests/test_codice_parser.py -q`
  Expected: PASS.

- [ ] **Step 5: Regenerar el golden y revisar el diff**

  Run: `ENV=dev PYTHONPATH="$PWD" python -m tests.test_codice_parser_golden --update`, luego `git diff --stat tests/fixtures/placsp/golden.jsonl` y `git diff tests/fixtures/placsp/golden.jsonl`.
  Expected: solo aparecen entradas nuevas `{"tipo": "acta", ...}` en `documentos`, y solo en los fixtures que tienen `GeneralDocument` con código 12 o ZZZ de valoración. Cualquier otro cambio es un efecto no previsto: parar y revisarlo.

- [ ] **Step 6: Pasar el golden**

  Run: `ENV=dev PYTHONPATH="$PWD" python -m pytest tests/test_codice_parser_golden.py -q`
  Expected: PASS.

- [ ] **Step 7: Commit**

  ```bash
  git add scraper/codice_parser.py db/upsert.py tests/test_codice_parser.py tests/fixtures/placsp/golden.jsonl
  git commit -m "feat(parser): las actas de la mesa de PLACSP entran como documentos tipo acta"
  ```

  Ojo: hasta Task 2 el CHECK de la BD rechaza `tipo='acta'`. Task 1 y Task 2 se mergean juntas, nunca Task 1 sola en producción.

---

### Task 2: Migración v169 y catálogo del MCP

**Files:**
- Create: `db/alembic/versions/v169_actas_puntuaciones.py`, o el número siguiente al head de `master`, que hay que comprobar antes de crearla porque hay PR abiertos.
- Modify: `mcp_server/catalogo.py` (dos entradas en el bloque `_DOC`)
- Modify: `scripts/setup_pg_role_mcp.sql` (regenerado)
- Test: `tests/test_migracion_v169_actas.py` (integration, `tmp_db`)

**Interfaces:**
- Produces: CHECK `documentos.tipo IN ('legal','technical','additional','acta')`, más las tablas `acta_extracciones` y `acta_puntuaciones` exactamente como el spec §5.

- [ ] **Step 0: Pedir el OK del usuario para tocar `db/alembic/`** (AGENTS.md §6). Sin él, parar aquí.

- [ ] **Step 1: Escribir el test que falla**

  ```python
  def test_documentos_admite_tipo_acta(tmp_db): ...   # INSERT tipo='acta' no lanza
  def test_documentos_sigue_rechazando_tipos_desconocidos(tmp_db): ...  # tipo='otro' -> CheckViolation
  def test_acta_puntuaciones_unicidad_con_lote_y_criterio_nulos(tmp_db):
      # dos filas (lic, NULL lote, "ACME", NULL criterio) -> UniqueViolation
  def test_acta_extracciones_status_cerrado(tmp_db): ...  # status='raro' -> CheckViolation
  def test_borrar_documento_borra_sus_puntuaciones(tmp_db): ...  # FK documento_id ON DELETE CASCADE
  ```

- [ ] **Step 2: Escribir la revisión**

  `revision = "v169_actas_puntuaciones"`, `down_revision` el head real. Solo Postgres, con el mismo guard que las revisiones vecinas.

  `upgrade()`:
  1. Busca el nombre del CHECK de `tipo` en `pg_constraint` (`conrelid = 'documentos'::regclass AND contype = 'c' AND pg_get_constraintdef(oid) LIKE '%tipo%'`), lo borra y crea `ck_documentos_tipo`. El nombre se busca porque v56 lo declaró inline.
  2. Crea `acta_extracciones`:
     - `licitacion_id text PK REFERENCES licitaciones(id_externo) ON DELETE CASCADE`
     - `status` con CHECK
     - `updated_at timestamptz NOT NULL DEFAULT now()`
  3. Crea `acta_puntuaciones`:
     - `id bigint identity PK`
     - `licitacion_id` con FK a `licitaciones(id_externo)` y `ON DELETE CASCADE`
     - `documento_id integer NOT NULL REFERENCES documentos(id) ON DELETE CASCADE`
     - `excluida boolean NOT NULL DEFAULT false`
     - índice único `uq_acta_puntuaciones_fila` sobre `(licitacion_id, COALESCE(lote_numero,''), licitador_normalizado, COALESCE(criterio,''))`

  `downgrade()` hace lo contrario. El docstring sigue el formato «Qué falla hoy / Qué hace» de v168.

- [ ] **Step 3: Añadir las tablas al catálogo y regenerar los grants**

  En `mcp_server/catalogo.py`, junto a `tender_fact_sheets`:
  - `("acta_extracciones", _V, _DOC, "Estado de la lectura del acta de la mesa de cada expediente con oportunidad.")`
  - `("acta_puntuaciones", _V, _DOC, "Puntos por licitador, criterio y lote leídos del acta de la mesa, con su cita.")`

  Run: `ENV=dev PYTHONPATH="$PWD" python scripts/gen_mcp_grants.py`

- [ ] **Step 4: Verificar**

  Run: `ENV=dev PYTHONPATH="$PWD" python -m pytest tests/test_mcp_catalogo.py -q`
  Expected: PASS.

  Run: `bash scripts/dev/wsl_run.sh python -m pytest tests/test_migracion_v169_actas.py tests/test_mcp_catalogo_integration.py -q`
  Expected: PASS. Si WSL no está disponible, anotarlo como no ejecutado.

- [ ] **Step 5: Commit**

  ```bash
  git add db/alembic/versions/v169_actas_puntuaciones.py mcp_server/catalogo.py scripts/setup_pg_role_mcp.sql tests/test_migracion_v169_actas.py
  git commit -m "feat(db): v169 — documentos tipo acta y tablas de puntuaciones del acta"
  ```

---

### Task 3: El pipeline de pliegos no ve las actas

**Files:**
- Modify: `db/repositories/documentos.py`
- Modify: `db/repositories/tecnologia_pliego.py:348` (`list_licitaciones_pending_signal`)
- Modify: `services/rag/fact_sheet.py:612-681` (`ensure_documents_ready`)
- Test: `tests/test_documentos_actas_fuera.py` (integration, `tmp_db`); `tests/test_unit_fact_sheet_ondemand_tipos.py` (unit, con el repositorio y `fetch_and_extract` parcheados)

**Interfaces:**
- Produces, en `db/repositories/documentos.py`:
  - `TIPO_ACTA: Final = "acta"`
  - `TIPOS_PLIEGO: Final[frozenset[str]] = frozenset({"legal", "technical", "additional"})`
  - `DocumentosRepository.list_pages_by_licitacion(licitacion_id: str, *, tipos: frozenset[str] = TIPOS_PLIEGO) -> list[dict[str, Any]]`
- Produces, en `services/rag/fact_sheet.py`: `ensure_documents_ready(licitacion_id: str, *, tipos: frozenset[str] = TIPOS_PLIEGO, max_documentos: int = _ONDEMAND_MAX_DOCUMENTS) -> dict[str, int]`

- [ ] **Step 1: Escribir los tests que fallan**

  ```python
  # integration: siembra una licitación con un pliego 'legal' y un 'acta', ambos pending
  def test_list_pendientes_no_elige_actas(tmp_db): ...           # solo sale el legal
  def test_list_extracted_without_chunks_ignora_actas(tmp_db): ...  # acta extracted -> no sale
  def test_list_pages_by_licitacion_por_defecto_sin_actas(tmp_db): ...
  def test_list_pages_by_licitacion_con_tipos_acta(tmp_db): ...  # tipos={"acta"} -> solo las del acta
  def test_list_textos_by_licitacion_ignora_actas(tmp_db): ...
  def test_formato_counts_no_cuenta_actas_pendientes(tmp_db): ...  # 'pendientes' excluye el acta
  def test_status_counts_separa_las_actas(tmp_db): ...  # pending == 1 (el legal), actas == 1
  def test_pending_signal_ignora_licitaciones_con_solo_actas(tmp_db): ...
  # unit:
  def test_ensure_documents_ready_por_defecto_no_descarga_actas(): ...
  def test_ensure_documents_ready_con_tipos_acta_respeta_el_tope(): ...  # 5 actas, max_documentos=3 -> 3 intentos
  ```

- [ ] **Step 2: Ejecutar el unit y ver que falla**

  Run: `ENV=dev PYTHONPATH="$PWD" python -m pytest tests/test_unit_fact_sheet_ondemand_tipos.py -q`
  Expected: FAIL.

- [ ] **Step 3: Implementar**

  - Añadir `AND d.tipo <> 'acta'` (o el equivalente sin alias) a:
    - `list_pendientes`
    - `list_extracted_without_chunks`
    - `list_textos_by_licitacion`
    - `list_chunks_by_licitacion`
    - la columna `pendientes` de `formato_counts`
    - la consulta de `tecnologia_pliego.list_licitaciones_pending_signal`
  - `list_pages_by_licitacion` filtra con `AND d.tipo = ANY(%s)`, pasando `list(tipos)`.
  - `status_counts` cuenta por estado solo los pliegos (`WHERE tipo <> 'acta'`) y añade la clave `"actas"` con el total de actas. Si no, el `pending` del informe del cron crecería sin parar con actas que, por diseño, nunca descarga.
  - `list_by_licitacion` **no** cambia: la ficha puede enseñar el acta como documento.
  - `ensure_documents_ready` filtra `rows` por `tipos` antes de calcular `pending`, `any_extracted` y `candidates`, y usa `candidates[:max_documentos]`.
  - En cada filtro, una línea de comentario que remite al spec §3.3.

- [ ] **Step 4: Verificar**

  Run: `ENV=dev PYTHONPATH="$PWD" python -m pytest tests/test_unit_fact_sheet_ondemand_tipos.py tests -m unit -q -k "documentos or fact_sheet or pliego"`
  Expected: PASS.

  Run: `bash scripts/dev/wsl_run.sh python -m pytest tests/test_documentos_actas_fuera.py -q`
  Expected: PASS, o anotarlo como no ejecutado.

- [ ] **Step 5: Commit**

  ```bash
  git add db/repositories/documentos.py db/repositories/tecnologia_pliego.py services/rag/fact_sheet.py tests/test_documentos_actas_fuera.py tests/test_unit_fact_sheet_ondemand_tipos.py
  git commit -m "feat(documentos): las actas quedan fuera del pipeline de pliegos y de la ficha"
  ```

---

### Task 4: Repositorio de puntuaciones y eventos de fila confirmada

**Files:**
- Create: `db/repositories/puntuaciones_acta.py`
- Modify: `db/repositories/pursuits.py` (junto al bloque del kit, ~1157)
- Test: `tests/test_puntuaciones_acta_repo.py` (integration, `tmp_db`)

**Interfaces:**
- Produces, en `db/repositories/puntuaciones_acta.py` (TypedDicts con `total=True`):

  ```python
  ActaStatus = Literal["ok", "sin_tabla", "sin_acta", "error"]

  class ActaExtraccionRow(TypedDict):
      licitacion_id: str; status: ActaStatus; extraction_version: str; model: str | None
      documentos_leidos: int; error_detail: str | None; extracted_at: datetime | None

  class PuntuacionNueva(TypedDict):          # lo que escribe el job
      lote_numero: str | None; licitador_nombre: str; licitador_normalizado: str
      criterio: str | None; puntos: float | None; puntos_max: float | None
      es_precio: bool | None; excluida: bool; documento_id: int; pagina: int; cita: str

  class PuntuacionRow(PuntuacionNueva):      # lo que lee la ficha
      id: int

  class ExpedienteActaPendiente(TypedDict):
      licitacion_id: str; tiene_acta: bool

  class AdjudicatarioLote(TypedDict):
      lote_numero: str | None; nombre: str | None; nif: str | None

  class PuntuacionesActaRepository:
      def get_extraccion(self, licitacion_id: str) -> ActaExtraccionRow | None
      def tiene_actas(self, licitacion_id: str) -> bool
      def list_puntuaciones(self, licitacion_id: str) -> list[PuntuacionRow]
      def guardar(self, licitacion_id: str, *, status: ActaStatus, extraction_version: str,
                  model: str | None, documentos_leidos: int, error_detail: str | None,
                  filas: Sequence[PuntuacionNueva]) -> None
      def expedientes_pendientes(self, *, extraction_version: str, limit: int = 200
                                 ) -> list[ExpedienteActaPendiente]
      def adjudicatarios_por_lote(self, licitacion_id: str) -> list[AdjudicatarioLote]
      def nombres_de_organizacion(self, organization_id: int) -> list[str]
  ```

- Produces, en `PursuitRepository`:
  - `FILA_ACTA_EVENT_TYPE = "fila_acta_confirmada"`
  - `fila_acta_events(self, organization_id: int, pursuit_id: int) -> list[FilaActaEventRow]`, con `FilaActaEventRow` = `{actor_user_id: int, payload_json: str, created_at: str}`, el mismo shape que `KitEventRow`
  - `append_fila_acta_event(self, *, organization_id: int, pursuit_id: int, actor_user_id: int, payload: Mapping[str, object]) -> None`

  Las dos copian el patrón de `kit_events` y `append_kit_event`.

- [ ] **Step 1: Escribir los tests que fallan**

  ```python
  def test_guardar_reemplaza_el_expediente_entero(tmp_db): ...  # guardar 3 filas, luego 1 -> list_puntuaciones len 1
  def test_guardar_dos_veces_igual_no_duplica(tmp_db): ...
  def test_guardar_sin_filas_deja_la_extraccion_y_borra_las_puntuaciones(tmp_db): ...  # status sin_tabla
  def test_expedientes_pendientes_solo_con_oportunidad_y_adjudicacion(tmp_db): ...
      # A: pursuit + adjudicación + acta -> sale con tiene_acta=True
      # B: pursuit + adjudicación, sin acta -> sale con tiene_acta=False
      # C: adjudicación + acta, sin pursuit -> no sale
      # D: pursuit + acta, sin adjudicación -> no sale
  def test_expedientes_pendientes_excluye_la_version_vigente_salvo_error(tmp_db): ...
      # ok@v1 -> no sale; ok@v0 -> sale; error@v1 -> sale; sin_acta@v1 sin actas -> no sale;
      # sin_acta@v1 con un acta llegada después -> sale
  def test_expedientes_pendientes_un_expediente_con_dos_pursuits_sale_una_vez(tmp_db): ...
  def test_adjudicatarios_por_lote_trae_el_numero_del_lote(tmp_db): ...  # join lotes por a.lote_id
  def test_nombres_de_organizacion(tmp_db): ...
      # NIF declarado + adjudicación con ese NIF -> su nombre; empresa_id -> empresas.nombre
      # + empresa_aliases.alias_normalizado; y organizations.name
  def test_fila_acta_events_en_orden(tmp_db): ...  # PursuitRepository
  ```

- [ ] **Step 2: Implementar `db/repositories/puntuaciones_acta.py`**

  Mismo estilo que `db/repositories/condiciones_oficiales.py`: `connect`, `connect_read`, `rows_to_dicts`, `typed_rows`.

  - `guardar`: una sola transacción. `INSERT ... ON CONFLICT (licitacion_id) DO UPDATE` sobre `acta_extracciones` (`extracted_at = now()` solo si `status = 'ok'` o `'sin_tabla'`), luego `DELETE FROM acta_puntuaciones WHERE licitacion_id = %s` y un `executemany` de las filas.
  - `expedientes_pendientes`: `SELECT DISTINCT` sobre `pursuits` con `EXISTS` adjudicaciones, `LEFT JOIN acta_extracciones`. Sale cuando no hay fila, o cuando `extraction_version <> %s`, o cuando `status = 'error'`, o cuando `status = 'sin_acta'` y ya existe un `documentos.tipo = 'acta'`.
    - `tiene_acta` es `EXISTS (documentos tipo='acta')`.
    - Las filas `error` se reencolan en cada pasada. A la escala de hoy (16 oportunidades) es barato. Dejarlo marcado con `# shortcut: reencola 'error' en cada pasada, sin tope; poner un tope por updated_at si las oportunidades pasan del centenar`.
  - `nombres_de_organizacion`: la unión de cuatro fuentes:
    - `adjudicaciones.nombre` de los NIF de `organization_nifs`
    - `empresas.nombre` de `organization_nifs.empresa_id`; mirar en `OrganizationNifRepository.empresa_ids` de dónde sale el `empresa_id`
    - `empresa_aliases.alias_normalizado` de esos `empresa_id`
    - el nombre de la organización (`organizations.name`)

    Devuelve los nombres crudos. Normaliza el servicio.

- [ ] **Step 3: Añadir los eventos a `db/repositories/pursuits.py`**

- [ ] **Step 4: Verificar**

  Run: `bash scripts/dev/wsl_run.sh python -m pytest tests/test_puntuaciones_acta_repo.py -q`
  Expected: PASS, o anotarlo como no ejecutado.

  Run: `ENV=dev PYTHONPATH="$PWD" python -m mypy db/repositories/puntuaciones_acta.py db/repositories/pursuits.py`
  Expected: sin errores.

- [ ] **Step 5: Commit**

  ```bash
  git add db/repositories/puntuaciones_acta.py db/repositories/pursuits.py tests/test_puntuaciones_acta_repo.py
  git commit -m "feat(db): repositorio de puntuaciones del acta y evento de fila confirmada"
  ```

---

### Task 5: Reglas puras (sin BD ni red)

**Files:**
- Create: `services/puntuaciones_acta_reglas.py`
- Create: `tests/fixtures/actas/astillero_1611_2026.json` (páginas reales del acta)
- Test: `tests/test_unit_puntuaciones_acta_reglas.py`

**Interfaces:**
- Consumes: `services.normalization.normalize_company`, `fold_text`; `shared.dto.pursuits.PursuitOutcomeReasonCode`; `services.rag.fact_sheet._validated_evidence`, con el mismo precedente de import privado que `services/rag/ficha_eval.py`; `shared.tender_facts.EvidenceRef`.
- Produces:

  ```python
  class CriterioActa(BaseModel):   # extra="ignore"; puntos/maximo con BeforeValidator coma->punto, ilegible->None
      nombre: str; puntos: float | None = None; maximo: float | None = None
  class FilaActa(BaseModel):
      licitador: str; criterios: list[CriterioActa] = []; total: float | None = None
      excluida: bool = False; cita: str; pagina: int; documento_id: int
  class LoteActa(BaseModel):
      lote: str | None = None; filas: list[FilaActa] = []
  class RespuestaActa(BaseModel):
      lotes: list[LoteActa] = []

  def normalizar_lote(raw: str | None) -> str | None
  def es_precio_de(nombre: str, criterios_pliego: Sequence[Mapping[str, object]],
                   lote_numero: str | None) -> bool | None
  def seleccionar_paginas(paginas: Sequence[Mapping[str, Any]],
                          nombres_criterio: Sequence[str]) -> list[dict[str, Any]]
  def filas_validadas(respuesta: RespuestaActa, paginas: Sequence[Mapping[str, Any]],
                      criterios_pliego: Sequence[Mapping[str, object]]) -> list[PuntuacionNueva]
  def fila_ganadora(filas: Sequence[FilaCalculo], adjudicatarios_normalizados: set[str]
                    ) -> tuple[int | None, bool]          # (índice, es_mayor_puntuacion)
  def fila_propia(filas: Sequence[FilaCalculo], nombres_org_normalizados: set[str]) -> int | None
  def diferencia(propia: FilaCalculo, ganadora: FilaCalculo) -> list[DiferenciaCalculo]
  def motivo_sugerido(propia: FilaCalculo, ganadora: FilaCalculo, *, propia_es_ganadora: bool
                      ) -> PursuitOutcomeReasonCode | None
  ```

  `FilaCalculo` y `DiferenciaCalculo` son dataclasses `frozen` de este módulo:
  - `FilaCalculo(licitador, licitador_normalizado, total, excluida, criterios: tuple[CriterioCalculo, ...])`
  - `CriterioCalculo(nombre, puntos, maximo, es_precio, documento_id, pagina, cita)`
  - `DiferenciaCalculo(criterio: str | None, diferencia: float, maximo: float | None, es_precio: bool | None)`, donde `criterio=None` es el total

  Task 7 las convierte a DTO.

- [ ] **Step 1: Generar el fixture del acta real** (una vez, con red)

  Descargar con `curl -sSL -o "$TMPDIR/acta.pdf"` la URI del primer documento de código 12 del fixture 19 (línea 361). Extraer las páginas con `scraper.document_fetcher._extract_pdf_pages(content)`. Guardar en `tests/fixtures/actas/astillero_1611_2026.json` una lista `[{"documento_id": 1, "page_number": n, "texto": ...}]`. Debe incluir al menos la página con la tabla «EMPRESA | Informe técnico (sobre 30) | … | TOTAL» y una sin tabla.

  Añadir un `README.md` de dos líneas en `tests/fixtures/actas/` con el origen y la fecha. Si la URI ya no responde, buscar otra acta de código 12 con `buscar_licitaciones` y anotar cuál se usó.

- [ ] **Step 2: Escribir los tests que fallan**

  ```python
  @pytest.mark.parametrize("raw,esperado", [("Lote 1", "1"), ("LOTE Nº 1", "1"), ("lote n.º 2", "2"),
                                            ("1", "1"), (None, None), ("", None), ("Único", None)])
  def test_normalizar_lote(raw, esperado): ...

  def test_respuesta_acepta_coma_decimal():
      r = RespuestaActa.model_validate({"lotes": [{"lote": "1", "filas": [{"licitador": "A",
          "criterios": [{"nombre": "Precio", "puntos": "18,50", "maximo": "65"}], "total": "n/d",
          "cita": "x", "pagina": 1, "documento_id": 1}]}]})
      c = r.lotes[0].filas[0].criterios[0]
      assert (c.puntos, c.maximo, r.lotes[0].filas[0].total) == (18.5, 65.0, None)

  def test_es_precio_por_criterio_del_pliego(): ...   # descripcion casa por fold_text -> su es_precio
  def test_es_precio_por_nombre(): ...               # "Oferta económica (sobre 65 puntos)" -> True; "Informe técnico" -> False
  def test_es_precio_desconocido(): ...              # "Mejoras" sin pliego -> None

  def test_seleccionar_paginas_del_acta_real():      # fixture: la página de la tabla sale; la que no tiene señales, no
  def test_filas_validadas_descarta_cita_inventada(): # fila con cita que no está en el texto -> fuera
  def test_filas_validadas_acta_real():              # respuesta escrita a mano con las filas reales del fixture
      # -> una PuntuacionNueva por criterio más una de total (criterio=None), licitador_normalizado
      #    = normalize_company(licitador), es_precio resuelto, excluidas con excluida=True

  def test_fila_ganadora_por_nombre_adjudicatario(): ...      # (i, False)
  def test_fila_ganadora_por_mayor_total_sin_excluidas(): ... # adjudicatario no casa -> (mayor total no excluida, True)
  def test_fila_ganadora_sin_totales(): ...                   # (None, False)
  def test_fila_propia_exacta(): ...
  def test_fila_propia_ambigua(): ...                          # dos filas casan -> None
  def test_fila_propia_ninguna(): ...
  def test_fila_propia_no_casa_una_ute_que_la_contiene(): ...  # "UTE MI EMPRESA - OTRA" frente a {"MI EMPRESA"} -> None

  def test_diferencia_por_criterio_y_total(): ...   # propia 40/65 precio, 28/30 técnica; ganadora 58.5/65, 30/30
      # -> [("Precio", -18.5, 65, True), ("Técnica", -2, 30, False), (None, -20.5, None, None)]
  def test_motivo_precio(): ...                     # caso anterior -> "precio"
  def test_motivo_tecnica(): ...                    # pierde 10 en técnica y 3 en precio -> "tecnica"
  def test_motivo_empate_de_perdidas_es_tecnica(): ...  # 5 y 5 -> "tecnica"
  def test_motivo_sin_perdidas(): ...               # gana en todo pero no es la adjudicataria -> None
  def test_motivo_sin_es_precio(): ...              # todos los es_precio None -> None
  def test_motivo_propia_ganadora(): ...            # -> None
  def test_motivo_propia_excluida(): ...            # -> None
  ```

- [ ] **Step 3: Ejecutarlos y ver que fallan**

  Run: `ENV=dev PYTHONPATH="$PWD" python -m pytest tests/test_unit_puntuaciones_acta_reglas.py -q`
  Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 4: Implementar `services/puntuaciones_acta_reglas.py`**

  Decisiones que ni las firmas ni los tests fijan:
  - **`es_precio_de`:** casa el criterio del acta con el del pliego cuando el `fold_text` de uno contiene al del otro, en el mismo `lote_numero` o a nivel de expediente. La regex de nombre es `r"oferta econ|precio|baja"` sobre `fold_text`.
  - **`seleccionar_paginas`:**
    - Puntúa cada página con +2 por «puntuaci», +1 por «total», +2 por `r"sobre \d+(?:[.,]\d+)? puntos"`, y +1 por cada nombre de criterio (fold, ≥ 6 caracteres) presente.
    - Se queda con las de puntuación > 1, en orden de documento y página, hasta `_MAX_PAGINAS = 12` y `_MAX_CHARS = 40_000`.
  - **`filas_validadas`:** construye un `EvidenceRef(documento_id, page_number=pagina, quote=cita[:600])` y llama a `_validated_evidence(ref, page_index)`, con `page_index = {(documento_id, page_number): página}`. Si devuelve `None`, la fila se tira. Si corrige la página, se usa la corregida.
  - **`motivo_sugerido`:** sigue literalmente el spec §6.4.

- [ ] **Step 5: Ejecutar y ver que pasan**

  Run: `ENV=dev PYTHONPATH="$PWD" python -m pytest tests/test_unit_puntuaciones_acta_reglas.py -q`
  Expected: PASS.

  Run: `ENV=dev PYTHONPATH="$PWD" python -m mypy services/puntuaciones_acta_reglas.py`
  Expected: limpio.

- [ ] **Step 6: Commit**

  ```bash
  git add services/puntuaciones_acta_reglas.py tests/test_unit_puntuaciones_acta_reglas.py tests/fixtures/actas/
  git commit -m "feat(actas): reglas de lote, precio, fila ganadora, fila propia y motivo propuesto"
  ```

---

### Task 6: Job de extracción y encolado tras cada pasada

**Files:**
- Create: `services/puntuaciones_acta.py`
- Modify: `services/rag/fact_sheet.py:817` (`_llamar_modelo` gana `stop: threading.Event | None = None`, que pasa a `stream_llm_response`)
- Modify: `services/jobs.py` (constante, entrada en `TIPOS_A_DEMANDA`, `__all__`)
- Modify: `scheduler/worker.py` (`ejecutar_puntuaciones_acta`)
- Modify: `scheduler/pipeline_runs.py:595` (un bloque `try` más tras `notify_detected_awards`, con `_contar_error("puntuaciones_acta")`)
- Test: `tests/test_unit_puntuaciones_acta_job.py` (repositorios, `ensure_documents_ready`, `_llamar_modelo` y `enqueue` parcheados)

**Interfaces:**
- Consumes: Task 3 (`ensure_documents_ready(..., tipos=frozenset({TIPO_ACTA}), max_documentos=3)` y `list_pages_by_licitacion(..., tipos=frozenset({TIPO_ACTA}))`), Task 4 (`PuntuacionesActaRepository`), Task 5 (`RespuestaActa`, `seleccionar_paginas`, `filas_validadas`), `llm.json_utils.extract_json_object`, `db.repositories.condiciones_oficiales.CondicionesOficialesRepository().get(lic)["criterios"]`.
- Produces:

  ```python
  EXTRACTION_VERSION: Final = "acta-puntuaciones-v1"
  _MAX_ACTAS: Final = 3
  _TOPE_LLM_SEGUNDOS: Final = 300

  def encolar_pendientes(*, limit: int = 200) -> int          # jobs encolados + filas sin_acta escritas
  def extraer_puntuaciones(licitacion_id: str, *, model: str) -> ActaStatus
  ```

  `TIPOS_A_DEMANDA[TIPO_PUNTUACIONES_ACTA] = TipoJob(nombre=..., handler="scheduler.worker:ejecutar_puntuaciones_acta", clave_dedupe="licitacion_id", descripcion="Lee las puntuaciones por licitador del acta de la mesa.")`

- [ ] **Step 1: Escribir los tests que fallan**

  ```python
  def test_encolar_escribe_sin_acta_sin_job(): ...       # pendiente con tiene_acta=False -> guardar(status="sin_acta"), enqueue no llamado
  def test_encolar_encola_con_acta(): ...                 # tiene_acta=True -> enqueue(TIPO_PUNTUACIONES_ACTA,
                                                          #   {"licitacion_id": ..., "model": settings.PLIEGO_FACTS_MODEL}, organization_id=None)
  def test_extraer_ok_guarda_filas_con_cita(): ...        # LLM stub devuelve JSON del fixture -> status "ok", filas > 0
  def test_extraer_sin_filas_validas_es_sin_tabla(): ...  # citas inventadas -> "sin_tabla", sin excepción
  def test_extraer_sin_paginas_con_señales_no_llama_al_llm(): ...  # -> "sin_tabla", error_detail menciona las señales
  def test_extraer_acta_escaneada_es_sin_tabla(): ...     # ensure devuelve sin_texto=1 y no hay páginas -> "sin_tabla"
  def test_extraer_descarga_fallida_lanza_y_deja_error(): ...  # sin páginas ni sin_texto -> guardar(status="error") y RuntimeError
  def test_extraer_llm_vacio_lanza_y_deja_error(): ...    # _llamar_modelo lanza ValueError -> status "error" guardado, re-lanza
  def test_extraer_tope_de_tiempo(): ...                  # stop se activa -> TimeoutError, status "error"
  def test_worker_lanza_si_queda_en_error(): ...          # ejecutar_puntuaciones_acta propaga, para que la cola reintente
  ```

- [ ] **Step 2: Ejecutarlos y ver que fallan**

  Run: `ENV=dev PYTHONPATH="$PWD" python -m pytest tests/test_unit_puntuaciones_acta_job.py -q`
  Expected: FAIL.

- [ ] **Step 3: Implementar**

  `extraer_puntuaciones`:
  1. Descarga: `ensure_documents_ready(..., tipos={TIPO_ACTA}, max_documentos=_MAX_ACTAS)`.
  2. Páginas: lee las del acta. Sin páginas hay dos casos:
     - si hubo `sin_texto`, `sin_tabla` con `error_detail="El acta no tiene texto extraíble (escaneada); falta OCR"`;
     - si no, `error` y `RuntimeError`.
  3. Selección: `seleccionar_paginas`. Si no queda ninguna, `sin_tabla` sin llamada al LLM.
  4. LLM: `_llamar_modelo(_PREGUNTA_ACTA, seleccionadas, licitacion_id=..., model=..., keywords=("puntuación", "total"), max_tokens=4000, stop=stop)`, con `threading.Timer(_TOPE_LLM_SEGUNDOS, stop.set)`. Si al volver `stop.is_set()`, `TimeoutError`.
  5. Validación: `RespuestaActa.model_validate(extract_json_object(raw))`, luego `filas_validadas`.
  6. Escritura: `guardar` con `documentos_leidos = número de documento_id distintos en las páginas`.

  Cualquier excepción tras empezar se captura una vez: `guardar(status="error", error_detail=str(exc)[:500], filas=[])`, y se re-lanza.

  `_PREGUNTA_ACTA` (constante del módulo) pide:
  - un único objeto JSON con la forma de `RespuestaActa`;
  - una fila por licitador y lote, incluidas las excluidas con `excluida: true`;
  - `cita` copiada literal de la página, de hasta 300 caracteres, con el nombre del licitador y su total;
  - `pagina` y `documento_id` de esa página;
  - las cifras tal como se leen;
  - `{"lotes": []}` si no hay tabla de puntuaciones por licitador.

  `ejecutar_puntuaciones_acta(job)` llama a `extraer_puntuaciones(str(job.payload["licitacion_id"]), model=str(job.payload["model"]))` y devuelve `{"licitacion_id": ..., "status": ...}`. Mismo patrón que `ejecutar_ficha_pliego`.

- [ ] **Step 4: Verificar**

  Run: `ENV=dev PYTHONPATH="$PWD" python -m pytest tests/test_unit_puntuaciones_acta_job.py tests -m unit -q -k "jobs or worker or pipeline_runs or fact_sheet"`
  Expected: PASS.

  Run: `ENV=dev PYTHONPATH="$PWD" python scripts/check_layers.py`
  Expected: sin violaciones nuevas.

- [ ] **Step 5: Commit**

  ```bash
  git add services/puntuaciones_acta.py services/rag/fact_sheet.py services/jobs.py scheduler/worker.py scheduler/pipeline_runs.py tests/test_unit_puntuaciones_acta_job.py
  git commit -m "feat(actas): job que lee las puntuaciones del acta y su encolado tras cada pasada"
  ```

---

### Task 7: DTOs, lectura en la ficha y confirmación de la fila propia

**Files:**
- Modify: `shared/dto/pursuits.py` (modelos nuevos; campo en `PursuitAdjudicacionDetectada` y en `PursuitUpdate`); re-exportar desde `shared/dto/__init__.py`
- Modify: `services/puntuaciones_acta.py` (lectura)
- Modify: `services/pursuits.py` (`_adjudicacion_detectada` ~266, `update_pursuit` ~451)
- Test: `tests/test_unit_puntuaciones_acta_lectura.py` (unit, repositorios parcheados); `tests/test_pursuits_fila_acta.py` (integration, `client` y `api_db`)

**Interfaces:**
- Produces, en `shared/dto/pursuits.py` (todos con `extra="forbid"`):

  ```python
  PuntuacionesEstado = Literal["pendiente", "ok", "sin_tabla", "sin_acta", "error"]
  class CriterioPuntuado(BaseModel): nombre: str; puntos: float | None; maximo: float | None
      es_precio: bool | None; documento_id: int; pagina: int; cita: str
  class FilaPuntuacion(BaseModel): licitador: str; licitador_normalizado: str
      total: float | None; excluida: bool; criterios: list[CriterioPuntuado]
  class DiferenciaCriterio(BaseModel): criterio: str | None; diferencia: float
      maximo: float | None; es_precio: bool | None; documento_id: int | None; pagina: int | None
  class PuntuacionesLote(BaseModel): lote_numero: str | None; filas: list[FilaPuntuacion]
      fila_ganadora: int | None; ganadora_es_mayor_puntuacion: bool
      fila_propia: int | None; fila_propia_confirmada: bool
      diferencia: list[DiferenciaCriterio]; motivo_sugerido: PursuitOutcomeReasonCode | None
  class PuntuacionesActa(BaseModel): estado: PuntuacionesEstado; lotes: list[PuntuacionesLote]
  class FilaActaRef(BaseModel): lote_numero: str | None = None
      licitador_normalizado: str = Field(min_length=1, max_length=300)
  # PursuitAdjudicacionDetectada.puntuaciones: PuntuacionesActa | None = None
  # PursuitUpdate.fila_acta: FilaActaRef | None = None
  ```

  `DiferenciaCriterio.documento_id`/`pagina` vienen de la cita de la fila ganadora: el enlace de la interfaz va a esa página.

- Produces, en `services/puntuaciones_acta.py`:
  - `puntuaciones_de_pursuit(*, licitacion_id: str, organization_id: int, pursuit_id: int, lote_pursuit: str | None) -> PuntuacionesActa | None`
  - `validar_fila_acta(licitacion_id: str, ref: FilaActaRef) -> bool`

- [ ] **Step 1: Escribir los tests que fallan**

  ```python
  # unit
  def test_sin_actas_ni_extraccion_es_none(): ...
  def test_con_actas_sin_extraccion_es_pendiente(): ...        # estado "pendiente", lotes []
  @pytest.mark.parametrize("status", ["sin_acta", "sin_tabla", "error"])
  def test_estados_sin_filas(status): ...                       # estado == status, lotes []
  def test_ok_agrupa_por_lote_ordena_excluidas_al_final(): ...
  def test_propuesta_sin_confirmar(): ...                       # fila_propia=i, fila_propia_confirmada=False, motivo calculado
  def test_confirmacion_gana_a_la_propuesta(): ...              # último evento del lote manda
  def test_confirmacion_huerfana_vuelve_a_la_propuesta(): ...   # Review Focus 5
  def test_puntuaciones_filtra_el_lote_de_la_oportunidad(): ... # Review Focus 1: lote_pursuit "2" presente -> solo lote 2; "9" ausente -> todos
  def test_ganadora_casa_por_lote(): ...                        # adjudicatario del lote 1 no es ganadora del lote 2
  def test_sin_propia_no_hay_diferencia_ni_motivo(): ...
  # integration
  def test_patch_fila_acta_anota_el_ledger_y_se_lee_confirmada(client, api_db): ...
  def test_patch_fila_acta_inexistente_es_422(client, api_db): ...
  def test_patch_solo_fila_acta_no_sube_la_version(client, api_db): ...
  ```

- [ ] **Step 2: Ejecutar el unit y ver que falla**

  Run: `ENV=dev PYTHONPATH="$PWD" python -m pytest tests/test_unit_puntuaciones_acta_lectura.py -q`
  Expected: FAIL.

- [ ] **Step 3: Implementar**

  - **`puntuaciones_de_pursuit`:**
    - Lee extracción, filas, adjudicatarios por lote, nombres de la organización y eventos `fila_acta_confirmada`.
    - Agrupa las filas en `FilaCalculo` por `(lote_numero, licitador_normalizado)`: la fila `criterio=None` es el total.
    - El lote del acta casa con el de la adjudicación con `normalizar_lote` en los dos lados.
    - Aplica las reglas de Task 5 y construye el DTO.
  - **En `services/pursuits.py`:**
    - `_adjudicacion_detectada` añade `puntuaciones=_puntuaciones(row, organization_id)`. Ese helper es fail-open, como `_resultado_sugerido`: loguea y devuelve `None`.
    - `update_pursuit` hace `requested.pop("fila_acta", None)` antes de `_normalize_and_validate_update`. Si `validar_fila_acta` es `False`, lanza `PursuitValidationError("Esa fila no está en el acta leída de este expediente.")`, que ya se mapea a 422. Tras validar escribe `append_fila_acta_event`. Si `changes` queda vacío, no llama a `_repo.update` y devuelve `_detalle(current, ...)`.

- [ ] **Step 4: Verificar**

  Run: `ENV=dev PYTHONPATH="$PWD" python -m pytest tests/test_unit_puntuaciones_acta_lectura.py tests -m unit -q -k "pursuit"`
  Expected: PASS.

  Run: `ENV=dev PYTHONPATH="$PWD" python scripts/check_openapi_contract.py`
  Expected: PASS.

  Run: `bash scripts/dev/wsl_run.sh python -m pytest tests/test_pursuits_fila_acta.py -q`
  Expected: PASS, o anotarlo como no ejecutado.

- [ ] **Step 5: Commit**

  ```bash
  git add shared/dto/pursuits.py shared/dto/__init__.py services/puntuaciones_acta.py services/pursuits.py tests/test_unit_puntuaciones_acta_lectura.py tests/test_pursuits_fila_acta.py
  git commit -m "feat(oportunidades): la adjudicación trae las puntuaciones del acta y la fila propia se confirma por PATCH"
  ```

---

### Task 8: Interfaz en la tarjeta de adjudicación

**Files:**
- Modify: `web/src/generated/api.d.ts` (regenerado con `python scripts/export_openapi.py`)
- Modify: `web/src/components/pursuits/adjudicacion-detectada.tsx`
- Create: `web/src/components/pursuits/puntuaciones-acta.tsx` (la tabla por lote y la diferencia, para que la tarjeta no crezca)
- Modify: `web/src/components/pursuits/pursuit-presenters.tsx` (recibe `MOTIVOS_PERDIDA`, que se mueve desde `dialogo-cierre.tsx`; `dialogo-cierre.tsx` lo importa de aquí)
- Test: `web/src/components/pursuits/__tests__/adjudicacion-detectada.test.tsx`

**Interfaces:**
- Consumes: el tipo `Pursuit["adjudicacion"]["puntuaciones"]` del cliente generado; `useUpdatePursuit`.
- Produces: `PuntuacionesActa({ pursuit, puntuaciones, onConfirmarFila })` y `MOTIVOS_PERDIDA` exportado.

**Defecto de hoy que esta tarea arregla:** «Cerrar como perdida» y «Confirmar como perdida» mandan `outcome: "lost"` sin `outcome_reason_code`, y la API responde 422 (`services/pursuits.py:991`). Desde esta tarjeta hoy no se puede cerrar una pérdida. La tarea añade el selector de motivo, que es donde va la preselección del spec §6.4.

- [ ] **Step 0: Leer `PRODUCT.md` y `DESIGN.md`** y cargar el skill `impeccable`, que da el acabado: superficies de `console/panel`, tipografía `text-tf-*`, foco visible.

- [ ] **Step 1: Regenerar el cliente**

  Run: `ENV=dev PYTHONPATH="$PWD" python scripts/export_openapi.py` y luego `git diff --stat web/src/generated/api.d.ts`.
  Expected: aparecen `PuntuacionesActa`, `FilaActaRef` y `fila_acta`.

- [ ] **Step 2: Escribir los tests que fallan** (en `describe("puntuaciones del acta")`)

  ```tsx
  it("pinta una tabla por lote con caption, cabeceras «sobre N» y el total")
  it("marca con texto la fila ganadora y la propia")          // «Ganadora», «Tu empresa» (o «Mayor puntuación»)
  it("pinta la diferencia «Precio −18,5 de 65 · Técnica −2 de 30 · Total −20,5»")
  it("cada cifra de la diferencia enlaza a su página del acta")
  it("«Esta es mi empresa» manda el PATCH con fila_acta")      // mutateAsync con { fila_acta: { lote_numero, licitador_normalizado } }
  it("con propuesta sin confirmar pregunta «¿Es esta tu empresa?»")
  it.each([["pendiente", "Leyendo el acta de la mesa"], ["sin_acta", "PLACSP no publicó acta de mesa para este expediente"],
           ["sin_tabla", "El acta no trae puntuaciones por licitador"],
           ["error", "No se pudo leer el acta; se reintenta en la próxima pasada"]])("estado %s", ...)
  it("cerrar como perdida manda outcome_reason_code")          // sin propuesta: el selector obliga a elegir
  it("cerrar como perdida preselecciona el motivo sugerido")   // motivo_sugerido "precio" -> seleccionado y enviado
  it("sin puntuaciones la tarjeta sigue como antes")           // puntuaciones: null
  ```

  Los dos tests actuales de «perdida» se actualizan para elegir motivo antes de cerrar.

- [ ] **Step 3: Ejecutarlos y ver que fallan**

  Run: `cd web && npx vitest run src/components/pursuits/__tests__/adjudicacion-detectada.test.tsx`
  Expected: FAIL. Antes hace falta `npm ci` en `web/`.

- [ ] **Step 4: Implementar**

  - La tabla va dentro de un `div` con `overflow-x-auto`: la tabla hace scroll en su contenedor y la página no.
  - El número se formatea con `Intl.NumberFormat("es-ES")` y el signo menos tipográfico (`−`).
  - El enlace de página es `/oportunidades/{id}` con el mismo visor de documentos que usa la ficha para las citas. Buscarlo en `tender-fact-sheet.tsx` y reutilizar su componente o helper de enlace a cita, sin crear uno nuevo.
  - El selector de motivo usa `MOTIVOS_PERDIDA` y solo aparece al elegir «perdida». Su valor inicial es `motivo_sugerido` del lote de la fila propia; si no lo hay, vacío, y con selector vacío el botón queda deshabilitado.

- [ ] **Step 5: Verificar**

  Run: `cd web && npx vitest run src/components/pursuits src/app/\(dashboard\)/oportunidades`
  Expected: PASS.

  Run: `make web-lint` y `make web-typecheck`, o sus `npm run` equivalentes en Windows (ver memoria «Entorno Windows sin make»).
  Expected: limpio.

  Run: `ENV=dev PYTHONPATH="$PWD" python scripts/check_openapi_contract.py && ENV=dev PYTHONPATH="$PWD" python scripts/check_contract_fixtures.py` (lo que ejecuta `make check-api-contract`)
  Expected: PASS. Si `check_contract_fixtures` pide actualizar un fixture de oportunidad del frontend con `puntuaciones: null`, se actualiza en este commit.

- [ ] **Step 6: Commit**

  ```bash
  git add web/src/generated/api.d.ts web/src/components/pursuits/ "web/src/app/(dashboard)/oportunidades/_components/dialogo-cierre.tsx"
  git commit -m "feat(web): puntuaciones del acta y motivo propuesto en la tarjeta de adjudicación"
  ```

---

### Task 9: Escenario CU-05, documentación y gates

**Files:**
- Modify: `tests/test_escenario_oportunidad.py` (test nuevo)
- Modify: `docs/casos-de-uso.md` (viñeta en CU-05 y tabla regenerada)
- Modify: `docs/database-schema.md` (regenerado), `docs/STATUS.md` (regenerado)
- Modify: `docs/IMPROVEMENT_BACKLOG.md` (entrada)
- Modify: `docs/superpowers/specs/2026-11-01-puntuaciones-acta-design.md` (cabecera: estado «implementado» y enlace a este plan)

- [ ] **Step 1: Escribir el escenario**

  `test_cu05_perdida_con_puntuaciones_del_acta(client, api_db)`:
  1. `sembrar_licitacion`, una adjudicación a «Ganadora SL» y un documento `tipo='acta'` con dos páginas en `documento_pages`.
  2. Abrir la oportunidad y llevarla a `submitted`.
  3. Llamar a `services.puntuaciones_acta.extraer_puntuaciones`, parcheando `ensure_documents_ready` (no descarga) y `services.rag.fact_sheet._llamar_modelo` con un stub que devuelve el JSON. Las citas son texto de esas páginas.
  4. `GET /pursuits/{id}` trae `adjudicacion.puntuaciones.estado == "ok"` y `fila_propia is None`.
  5. `PATCH` con `fila_acta`; el `GET` trae `fila_propia_confirmada is True` y `motivo_sugerido == "precio"`.
  6. `PATCH status="lost", outcome_reason_code="precio"` → 200.

- [ ] **Step 2: Documentación**

  - CU-05 gana una viñeta: «Si la mesa publicó acta con puntuaciones, ve su nota frente a la del ganador criterio a criterio y el cierre como perdida llega con el motivo propuesto».
  - Run: `ENV=dev PYTHONPATH="$PWD" python scripts/check_casos_uso.py --write` (lo que ejecuta `make casos-uso`) y después `python scripts/check_casos_uso.py`.
  - Entrada en `docs/IMPROVEMENT_BACKLOG.md` con lo hecho y lo que queda: ampliar más allá de oportunidades, backfill de las cerradas, PSCP/TED, OCR de actas escaneadas, perfil de competidor con `acta_puntuaciones`, y el tope de reencolado de `error`.

- [ ] **Step 3: Gates**

  Run:
  - `ENV=dev PYTHONPATH="$PWD" python scripts/check_layers.py`
  - `python scripts/check_api_surface.py`
  - `PYTHONUTF8=1 python scripts/check_agent_docs.py`
  - `ruff check . && ruff format --check .`
  - `ENV=dev python -m mypy .`, o el target de `make typecheck`
  - `ENV=dev PYTHONPATH="$PWD" python -m pytest -m "unit and not slow" -q`

  Expected: todo verde. `check_api_surface` no debe pedir ninguna entrada en `NUEVAS`.

  Run: `bash scripts/dev/wsl_run.sh make check`, `bash scripts/dev/wsl_run.sh make schema-doc` y `bash scripts/dev/wsl_run.sh make status`.
  Expected: verde, con los dos documentos regenerados. Sin WSL, anotar `make check` (parte integration), `schema-doc` y `status` como no ejecutados, para que CI los cubra antes del merge.

- [ ] **Step 4: Commit**

  ```bash
  git add tests/test_escenario_oportunidad.py docs/
  git commit -m "docs(actas): CU-05 con el post-mortem del acta, esquema, estado y backlog"
  ```

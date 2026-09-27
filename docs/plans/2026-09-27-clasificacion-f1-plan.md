# Fase F1 de la clasificación en tres niveles: plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** dejar lista la recogida de etiquetas independientes de las reglas:

- taxonomía con las familias nuevas;
- LLM que dice si un contrato es TI;
- feedback humano con un solo significado;
- cola de revisión por desacuerdo en `/ops`;
- golden set real exportable;
- informe de acuerdo LLM↔humanos.

**Architecture:** no hay migraciones (spec §6).

- La salida «¿es TI?» del LLM se guarda como fila marcador en
  `licitacion_tecnologia_pliego`, con `method='llm_es_ti'`, score 0 y la
  confianza en `evidence_json`.
- El feedback humano nuevo va a `ml_feedback` con `source='revision_ti'`, y ahí
  `relevante` = es TI.
- La cola por desacuerdo es una consulta en `db/`, que la ruta
  `GET /feedback/queue?strategy=desacuerdo` sirve a la vista de etiquetado.
- El golden y el informe de acuerdo son módulos puros más dos scripts.

**Tech Stack:** Python 3.13 (FastAPI, psycopg 3, pydantic v2, mypy strict), Postgres, Next.js + React Query + vitest.

**Spec:** [2026-09-27-clasificacion-tres-niveles.md](2026-09-27-clasificacion-tres-niveles.md). Decisiones D1 y D2 aprobadas por el propietario el 2026-09-27 tal como están en su §7.

## Global Constraints

- **Migraciones:** «Hasta F5 no hay migraciones.» No se toca `db/alembic/`.
- **D1, frontera de TI.**
  - Dentro: software (licencias, SaaS, desarrollo, mantenimiento de
    aplicaciones), servicios TI (soporte, CAU, outsourcing, consultoría TI),
    infraestructura (cloud, hosting, CPD, redes de datos, virtualización,
    servidores, almacenamiento, backup), ciberseguridad, datos/BI/IA,
    administración electrónica, sanidad digital, GIS y hardware de puesto.
  - Fuera: formación sobre herramientas (salvo dentro de una implantación),
    suscripciones a contenidos (revistas, bases de datos bibliográficas o
    clínicas), telefonía de voz, publicidad y eventos, y obra civil o
    climatización del CPD.
  - Los contratos menores ya adjudicados siguen siendo TI.
- **D2, familias.**
  - Nuevas: `RRHH_NOMINA`, `GESTION_DOCUMENTAL` y `PUESTO_TRABAJO`.
  - Las redes de datos van dentro de `CLOUD_INFRA`, cuya etiqueta legible pasa
    a ser «Infraestructura, cloud y redes».
- **Etiquetas del LLM:** «solo entrenan si su acuerdo con los humanos en el
  golden es ≥ 0,90 en `es_ti` y ≥ 0,80 de F1 por familia».
- **Filas sin etiqueta:** «Una fila sin etiqueta **no** es un negativo.»
- **Golden:** `tests/fixtures/golden_ti.jsonl`, con fuente, fecha,
  `etiquetado_por` y reparto temporal fijo (holdout = el 50 % más reciente).
- **Feedback:** `ml_feedback.relevante` pasa a significar `es_ti`, y solo eso.
- **Invariantes de AGENTS.md §3:**
  - Tipado estricto en producción: sin `Any` ni `# type: ignore` sin comentario
    que lo justifique.
  - Todo el SQL nuevo vive en `db/`.
  - Nada de markers manuales de categoría en tests.
  - Pre-commit sin `--no-verify`.
  - Una ruta nueva o un campo nuevo de respuesta nace tipado.
- **Contrato API:** si cambia, se regeneran `api/openapi.json`
  (`scripts/export_openapi.py`) y `web/src/generated/api.d.ts`
  (`npm run codegen:file`). El job `codegen-drift` de CI falla si no. Los
  docstrings de las rutas son parte del contrato.
- **Comandos en esta máquina** (Windows, Git Bash, desde la raíz del worktree):
  ```bash
  PY="/c/Users/Daniel Kalitovics/Desktop/Proyectos/licitaciones-sap/.venv/Scripts/python.exe"
  ENV=dev PYTHONPATH="$PWD" "$PY" -m pytest <tests> -q -p no:cacheprovider
  "$PY" -m ruff check <ficheros> && "$PY" -m ruff format --check <ficheros>
  ENV=dev "$PY" -m mypy <ficheros de producción>
  ```
  - No hay Postgres local: los tests con `tmp_db`/`api_db` se escriben y se
    reportan como **no ejecutados**.
  - Rojo de base conocido: 5 fallos en `test_document_fetcher_formatos.py` y
    `test_s2_step_tiers.py::test_ml_tecnologias_reporta_skipped_con_el_flag_apagado`;
    mypy da 5 errores en `config/secrets.py` y `services/rate_limit_redis.py`.
- **Commits:**
  - Mensaje en castellano con estilo conventional (`feat(…)`, `fix(…)`).
  - Si lleva caracteres no ASCII, se escribe en un fichero del scratchpad y se
    usa `git commit -F <fichero>`.
  - Termina con una línea en blanco y
    `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  - No se añade `graphify-out/`.
- **Web en el worktree:** no hay `web/node_modules`. Se instala con
  `cd web && npm ci --prefer-offline --no-audit --no-fund` (~1 min). El script
  `npm run build` no funciona en Windows; basta con typecheck, eslint y vitest.

## Review Focus

- Un título cuya única keyword se movió de familia («sistema de nóminas») tiene
  que salir `RRHH_NOMINA` y **no** `ERP`. Test en Tarea 1.
- Los enlaces guardados a la analítica con la etiqueta antigua «Cloud e
  infraestructura» siguen resolviendo a `CLOUD_INFRA`. Test en Tarea 1.
- Si el LLM responde `es_ti: false` pero también lista familias, las familias
  **no** se guardan. Test en Tarea 2.
- Una respuesta del LLM sin campo `es_ti` sigue siendo válida: se guardan sus
  familias y no se escribe fila de es_ti. Test en Tarea 2.
- Una fila heredada de `ml_feedback` (`source='human'`, `relevante=0`, sin
  tecnología) no entrena como negativo de todas las familias: su significado
  («no es SAP») no era «no es TI». Test en Tarea 3.
- La cola por desacuerdo nunca devuelve una licitación ya revisada con
  `revision_ti`, aunque tenga filas heredadas. Test en Tarea 4.

---

### Tarea 1: Taxonomía D2: familias nuevas y redes en `CLOUD_INFRA`

**Files:**
- Modify: `config/keywords.py`: listas de `TECHNOLOGY_KEYWORDS`, `TECH_CATEGORIAS`, `TECH_LABEL_TIPO`, `TECH_DEFINICIONES`.
- Modify: `services/analytics/tecnologias.py`: `_codes_for_label`.
- Modify: `web/src/app/(publico)/_content/landing.ts:146`, el texto «Cloud e infraestructura».
- Modify: `docs/taxonomia-tecnologica.md`: filas de las familias nuevas y sección «Frontera de TI» con el texto de D1.
- Test: `tests/test_taxonomia_tecnologica.py`.

**Interfaces:**
- Produces:
  - `TECH_LABELS` con 25 labels: los 13 fabricantes (primero, en su orden) + `ERP, CRM, CLOUD_INFRA, CIBERSEGURIDAD, DATOS_IA, DESARROLLO, GIS, SANIDAD_DIGITAL, ADMIN_ELECTRONICA, RRHH_NOMINA, GESTION_DOCUMENTAL, PUESTO_TRABAJO`.
  - `TECH_LABEL_TIPO[x] == "categoria"` para las tres nuevas.
  - `services.analytics.tecnologias._ETIQUETAS_ANTERIORES: dict[str, str]`.

- [ ] **Step 1: Tests que fallan**

En `tests/test_taxonomia_tecnologica.py`:

1. Añade `"RRHH_NOMINA", "GESTION_DOCUMENTAL", "PUESTO_TRABAJO"` al `frozenset`
   `CATEGORIAS`.
2. Renombra `test_los_labels_son_los_trece_fabricantes_y_las_nueve_categorias`
   a `..._y_las_doce_categorias`.
3. En la parametrización de `test_la_definicion_cubre_lo_que_cubren_sus_keywords`:
   - sustituye `("ERP", "nóminas")` por `("RRHH_NOMINA", "nóminas")`;
   - añade:
     ```python
     ("GESTION_DOCUMENTAL", "gestor documental"),
     ("PUESTO_TRABAJO", "microinformática"),
     ("CLOUD_INFRA", "cableado estructurado"),
     ```
4. Añade al final del módulo:

```python
# ── 6. Familias nuevas (D2, 2026-09-27) ─────────────────────────────────────

FAMILIAS_NUEVAS = frozenset({"RRHH_NOMINA", "GESTION_DOCUMENTAL", "PUESTO_TRABAJO"})

TITULOS_FAMILIAS_NUEVAS: list[tuple[str, set[str]]] = [
    ("Implantación de un nuevo sistema de nóminas para el Ayuntamiento", {"RRHH_NOMINA"}),
    ("Subministrament del programari de nòmines i portal de l'empleat", {"RRHH_NOMINA"}),
    ("Mantenimiento del gestor documental corporativo", {"GESTION_DOCUMENTAL"}),
    ("Subscripció al programari de gestió documental Alfresco", {"GESTION_DOCUMENTAL"}),
    ("Suministro de ordenadores portátiles para el personal", {"PUESTO_TRABAJO"}),
    ("Servicio de centro de atención a usuarios y soporte microinformático", {"PUESTO_TRABAJO"}),
    ("Suministro de electrónica de red y cableado estructurado", {"CLOUD_INFRA"}),
]


class TestFamiliasNuevas:
    @pytest.mark.parametrize(("titulo", "esperadas"), TITULOS_FAMILIAS_NUEVAS)
    def test_detecta_la_familia(self, titulo: str, esperadas: set[str]) -> None:
        assert esperadas <= _detectadas(titulo), titulo

    def test_las_nominas_ya_no_son_erp(self) -> None:
        """La keyword se mudó de familia: si siguiera en las dos, el test de
        duplicados lo diría; si siguiera solo en ERP, esto."""
        assert "ERP" not in _detectadas("Implantación de un nuevo sistema de nóminas")

    def test_el_gestor_documental_ya_no_es_admin_electronica(self) -> None:
        assert "ADMIN_ELECTRONICA" not in _detectadas("Mantenimiento del gestor documental")

    @pytest.mark.parametrize(
        "texto",
        [
            "Valoración de puestos de trabajo del personal municipal",
            "Curso de formación en ofimática para empleados",
            "Servicio de custodia y gestión documental de archivos en papel",
        ],
    )
    def test_no_disparan_donde_la_palabra_significa_otra_cosa(self, texto: str) -> None:
        assert not (_detectadas(texto) & FAMILIAS_NUEVAS), texto

    def test_la_etiqueta_antigua_de_cloud_sigue_resolviendo(self) -> None:
        """Los enlaces guardados a la analítica llevan el texto de la etiqueta."""
        from services.analytics.tecnologias import _codes_for_label

        assert "CLOUD_INFRA" in _codes_for_label("Cloud e infraestructura")
        assert "CLOUD_INFRA" in _codes_for_label("Infraestructura, cloud y redes")
```

- [ ] **Step 2: Verificar que fallan**

Run:
```bash
ENV=dev PYTHONPATH="$PWD" "$PY" -m pytest tests/test_taxonomia_tecnologica.py -q -p no:cacheprovider
```
Expected: FAIL. Los labels nuevos no existen (`KeyError`/`AssertionError`), y `_codes_for_label("Cloud e infraestructura")` devuelve la etiqueta tal cual.

- [ ] **Step 3: Implementación**

En `config/keywords.py`:

1. **Quitar** de la lista de `"ERP"` estas 10 keywords, que pasan a `RRHH_NOMINA`:
   `"sistema de nóminas"`, `"software de nóminas"`,
   `"sistema de gestión de recursos humanos"`,
   `"sistema de información de recursos humanos"`, `"sistema de nòmines"`,
   `"programari de nòmines"`, `"sistema de gestió de recursos humans"`,
   `"nominen sistema"`, `"nominen softwarea"`,
   `"sistema de xestión de recursos humanos"`.
2. **Quitar** de la lista de `"ADMIN_ELECTRONICA"` estas 5, que pasan a
   `GESTION_DOCUMENTAL`: `"gestor documental"`,
   `"sistema de gestión documental"`, `"sistema de gestió documental"`,
   `"xestor documental"`, `"sistema de xestión documental"`. El archivo
   electrónico y los expedientes se quedan en `ADMIN_ELECTRONICA`.
3. **Añadir** a la lista de `"CLOUD_INFRA"`:
   ```python
   # Redes de datos (D2, 2026-09-27): CLOUD_INFRA es «infraestructura, cloud y
   # redes». Solo sintagmas: «red» a secas casa con saneamiento y agua.
   "electrónica de red", "electrònica de xarxa", "cableado estructurado",
   "cablejat estructurat", "cableado estruturado", "red de área local",
   "xarxa d'àrea local", "sd-wan", "red corporativa", "xarxa corporativa",
   "rede corporativa", "red wifi", "xarxa wifi", "rede wifi",
   ```
4. **Añadir** al final de `TECHNOLOGY_KEYWORDS`, detrás de
   `"ADMIN_ELECTRONICA"` (el orden decide `TECH_LABELS`):
   ```python
   # ── Familias de D2 (plan de clasificación en tres niveles, 2026-09-27) ──
   "RRHH_NOMINA": [
       # Movidas desde ERP: una nómina no es un ERP, y quien las busca no
       # quiere que se le mezclen con la gestión económico-financiera.
       "sistema de nóminas", "software de nóminas",
       "sistema de gestión de recursos humanos",
       "sistema de información de recursos humanos",
       "sistema de nòmines", "programari de nòmines",
       "sistema de gestió de recursos humans",
       "nominen sistema", "nominen softwarea",
       "sistema de xestión de recursos humanos",
       # Nuevas: siempre sobre el software, nunca sobre el servicio (la
       # «gestión de nóminas» externalizada es una gestoría, no TI).
       "aplicación de nóminas", "aplicació de nòmines",
       "portal del empleado", "portal de l'empleat", "portal do empregado",
       "software de recursos humanos", "programari de recursos humans",
       "giza baliabideen kudeaketa",
   ],
   "GESTION_DOCUMENTAL": [
       # Movidas desde ADMIN_ELECTRONICA.
       "gestor documental", "sistema de gestión documental",
       "sistema de gestió documental", "xestor documental",
       "sistema de xestión documental",
       # Nuevas. «gestión documental» a secas no: es también la custodia de
       # archivos en papel.
       "software de gestión documental", "programari de gestió documental",
       "plataforma de gestión documental", "plataforma de gestió documental",
       "gestión de contenidos empresariales", "alfresco", "nuxeo",
       "dokumentu-kudeaketa",
   ],
   "PUESTO_TRABAJO": [
       # Hardware y soporte del usuario. Ni «puesto de trabajo» (es también el
       # puesto de la plantilla) ni «ofimática» a secas (casa con cursos, que
       # D1 deja fuera de TI).
       "ordenadores personales", "ordenadores de sobremesa",
       "ordenadores portátiles", "equipos informáticos", "material informático",
       "microinformática", "soporte microinformático",
       "centro de atención a usuarios", "soporte a usuarios",
       "service desk", "help desk",
       "licencias de ofimática", "paquete ofimático", "suite ofimática",
       "ordinadors personals", "ordinadors portàtils", "equips informàtics",
       "material informàtic", "microinformàtica",
       "centre d'atenció a l'usuari", "llicències d'ofimàtica",
       "ordenadores persoais",
       "ordenagailu eramangarriak", "ekipamendu informatikoa",
   ],
   ```
   Formatea las listas con una keyword por línea, como el resto del fichero
   (`ruff format` lo hace).
5. `TECH_CATEGORIAS`:
   - cambia `"CLOUD_INFRA": "Cloud e infraestructura"` por
     `"CLOUD_INFRA": "Infraestructura, cloud y redes"`;
   - añade:
     ```python
     "RRHH_NOMINA": "RRHH y nómina",
     "GESTION_DOCUMENTAL": "Gestión documental",
     "PUESTO_TRABAJO": "Puesto de trabajo y soporte",
     ```
6. `TECH_LABEL_TIPO`: las tres nuevas como `"categoria"`.
7. `TECH_DEFINICIONES`: sustituye tres definiciones y añade tres.
   ```python
   "ERP": (
       "Sistema de gestión integrado sin fabricante nombrado: gestión "
       "económico-financiera, contabilidad presupuestaria o gestión tributaria."
   ),
   "CLOUD_INFRA": (
       "Nube (IaaS, PaaS, SaaS), contenedores, virtualización, CPD, hosting, "
       "almacenamiento, copias de seguridad, servidores y redes de datos "
       "(electrónica de red, cableado estructurado, wifi)."
   ),
   "ADMIN_ELECTRONICA": (
       "Administración electrónica: sede, registro y firma electrónicos, "
       "tramitación, gestor de expedientes, archivo electrónico, "
       "interoperabilidad, notificaciones, factura electrónica."
   ),
   "RRHH_NOMINA": (
       "Software de recursos humanos y nómina sin fabricante nombrado: sistema o "
       "aplicación de nóminas, gestión de recursos humanos, portal del empleado."
   ),
   "GESTION_DOCUMENTAL": (
       "Gestión documental y de contenidos sin fabricante nombrado: gestor "
       "documental, sistema o plataforma de gestión documental, ECM, Alfresco o Nuxeo."
   ),
   "PUESTO_TRABAJO": (
       "Puesto de trabajo del usuario: ordenadores de sobremesa y portátiles, "
       "equipos y material informático, microinformática, centro de atención a "
       "usuarios (CAU), service desk, ofimática."
   ),
   ```

En `services/analytics/tecnologias.py`:

```python
#: Etiquetas legibles que ya no existen y a qué código apuntaban. Los enlaces a
#: la analítica llevan la etiqueta, no el código: renombrar una (D2, 2026-09-27)
#: no puede dejar vacíos los guardados.
_ETIQUETAS_ANTERIORES: dict[str, str] = {"Cloud e infraestructura": "CLOUD_INFRA"}


def _codes_for_label(tecnologia: str) -> list[str]:
    # (docstring actual, más una frase sobre las etiquetas anteriores)
    tecnologia = _ETIQUETAS_ANTERIORES.get(tecnologia, tecnologia)
    codes = [code for code, label in TECHNOLOGY_LABELS.items() if label == tecnologia]
    if tecnologia not in codes:
        codes.append(tecnologia)
    return codes
```

En `web/src/app/(publico)/_content/landing.ts:146`: `"Cloud e infraestructura"` pasa a `"Infraestructura, cloud y redes"`. Busca en `web/src` tests que citen el texto antiguo y actualízalos.

En `docs/taxonomia-tecnologica.md`:
- añade las tres familias a la tabla de categorías;
- añade una sección «Frontera de TI (D1)» con el texto de D1 de las Global Constraints;
- anota que las keywords de nóminas salen de ERP y las del gestor documental salen de ADMIN_ELECTRONICA, y que eso cambia la familia de las filas que se reingieran.

- [ ] **Step 4: Verificar que pasan**

Run:
```bash
ENV=dev PYTHONPATH="$PWD" "$PY" -m pytest tests/test_taxonomia_tecnologica.py tests/test_keywords_matcher.py tests/test_tech_classifier_etiquetas.py tests/test_llm_tech_labeling.py tests/test_connectors_pscp.py -q -p no:cacheprovider -m unit
```
Expected: PASS. Si `test_sin_duplicados_entre_labels_salvo_los_intencionales` falla, una keyword quedó en dos labels: quítala de la antigua.

- [ ] **Step 5: Commit**

```bash
git add config/keywords.py services/analytics/tecnologias.py "web/src/app/(publico)/_content/landing.ts" docs/taxonomia-tecnologica.md tests/test_taxonomia_tecnologica.py
git commit -F <mensaje>   # feat(taxonomia): familias RRHH_NOMINA, GESTION_DOCUMENTAL y PUESTO_TRABAJO, y redes en CLOUD_INFRA
```

---

### Tarea 2: El LLM dice si el contrato es TI (prompt v3)

**Files:**
- Modify: `services/llm_tech_labeling.py`
- Modify: `scheduler/jobs/llm_tech_labeling.py`
- Modify: `db/repositories/tecnologia_pliego.py`: constantes de sentinel y `SENTINELS`.
- Modify: `llm/prompts.py:246-258`: `_SYSTEM_CLASIFICACION` deja de excluir «la ofimática genérica», que ahora es parte de `PUESTO_TRABAJO`.
- Test: `tests/test_llm_tech_labeling.py`

**Interfaces:**
- Consumes: `TECH_DEFINICIONES` y `TECH_LABELS` de la Tarea 1.
- Produces:
  - `services.llm_tech_labeling.PROMPT_VERSION = "v3"`.
  - `db.repositories.tecnologia_pliego.METHOD_ES_TI = "llm_es_ti"`, re-exportado por `services.llm_tech_labeling`. Vive en `db/` porque la cola de la Tarea 4, también en `db/`, lo necesita y `db/` no importa de `services/`.
  - `Clasificacion`, que añade los campos `es_ti: bool | None = None`, `confianza_es_ti: float | None = None` y `otros_fabricantes: tuple[str, ...] = ()`.
  - `db.repositories.tecnologia_pliego.ES_TI_SENTINEL = "__es_ti__"`, `NO_ES_TI_SENTINEL = "__no_es_ti__"`, y `SENTINELS` que las incluye.
  - La fila de es_ti se escribe con `upsert_signals(id, method=METHOD_ES_TI, signal_version=<la misma>, scores={<sentinel>: TechSignal(score=0.0, evidence=[{"es_ti": bool, "confianza": float | None, "otros_fabricantes": [str, ...]}])})`.

- [ ] **Step 1: Tests que fallan**

Añade a `tests/test_llm_tech_labeling.py` (usa `_TEXTO` y `_parse`, que ya existen):

```python
class TestEsTi:
    def test_es_ti_con_familias(self):
        raw = json.dumps(
            {
                "es_ti": True,
                "confianza_es_ti": 0.9,
                "tecnologias": [
                    {"tecnologia": "ERP", "confidence": 0.8, "evidencia": "mantenimiento evolutivo del ERP"}
                ],
                "otros_fabricantes": [],
            }
        )
        resultado = _parse(raw)
        assert resultado.es_ti is True
        assert resultado.confianza_es_ti == 0.9
        assert set(resultado.scores) == {"ERP"}

    def test_si_no_es_ti_se_descartan_las_familias(self):
        """Una familia en un contrato que no es TI es una contradicción del
        modelo: gana el «no es TI», que es la pregunta de nivel 1."""
        raw = json.dumps(
            {
                "es_ti": False,
                "confianza_es_ti": 0.8,
                "tecnologias": [
                    {"tecnologia": "ERP", "confidence": 0.7, "evidencia": "mantenimiento evolutivo del ERP"}
                ],
            }
        )
        resultado = _parse(raw)
        assert resultado.es_ti is False
        assert resultado.scores == {}

    def test_sin_es_ti_la_respuesta_sigue_valiendo(self):
        raw = '{"tecnologias": [{"tecnologia": "SAP", "confidence": 0.9, "evidencia": "S/4HANA"}]}'
        resultado = _parse(raw)
        assert resultado.es_ti is None
        assert set(resultado.scores) == {"SAP"}

    def test_otros_fabricantes_se_limpian(self):
        raw = json.dumps(
            {"es_ti": True, "tecnologias": [], "otros_fabricantes": [" Qlik ", "qlik", "", "Z" * 90]}
        )
        assert _parse(raw).otros_fabricantes == ("Qlik", "Z" * 60)

    def test_la_version_del_prompt_es_v3(self):
        assert signal_version("m").startswith("llm-meta-v3/")
```

Y en `TestSinEvidenciaEnElJob` (mismo `_run_with`):

```python
    def test_escribe_la_fila_de_es_ti_con_su_confianza(self, monkeypatch):
        from db.repositories.tecnologia_pliego import NO_ES_TI_SENTINEL, TechSignal
        from services.llm_tech_labeling import METHOD_ES_TI

        raw = '{"es_ti": false, "confianza_es_ti": 0.85, "tecnologias": []}'
        counts, repo, _feedback = self._run_with(raw, monkeypatch)

        version = signal_version(settings.LLM_TECH_LABELING_MODEL)
        repo.upsert_signals.assert_any_call(
            "EXP-E1",
            method=METHOD_ES_TI,
            signal_version=version,
            scores={
                NO_ES_TI_SENTINEL: TechSignal(
                    score=0.0,
                    evidence=[{"es_ti": False, "confianza": 0.85, "otros_fabricantes": []}],
                )
            },
        )
        assert counts["es_ti_no"] == 1

    def test_sin_es_ti_no_escribe_fila_de_es_ti(self, monkeypatch):
        from services.llm_tech_labeling import METHOD_ES_TI

        raw = '{"tecnologias": []}'
        counts, repo, _feedback = self._run_with(raw, monkeypatch)

        metodos = [c.kwargs["method"] for c in repo.upsert_signals.call_args_list]
        assert METHOD_ES_TI not in metodos
        assert counts["es_ti_sin_respuesta"] == 1
```

- [ ] **Step 2: Verificar que fallan**

Run: `ENV=dev PYTHONPATH="$PWD" "$PY" -m pytest tests/test_llm_tech_labeling.py -q -p no:cacheprovider -m unit -k "EsTi or es_ti or v3"`
Expected: FAIL (`AttributeError: 'Clasificacion' object has no attribute 'es_ti'`, `ImportError: METHOD_ES_TI`).

- [ ] **Step 3: Implementación**

1. `db/repositories/tecnologia_pliego.py`, junto a `SIN_EVIDENCIA_SENTINEL`:
   ```python
   # Marcadores del nivel 1 («¿es TI?», plan de clasificación en tres niveles).
   # Viven en su propio ``method`` (``llm_es_ti``) para que ni el merge ni la
   # resolución de etiquetas de familia los vean; con score 0 nunca pasan el
   # umbral del merge. La confianza viaja en ``evidence_json``.
   METHOD_ES_TI = "llm_es_ti"
   ES_TI_SENTINEL = "__es_ti__"
   NO_ES_TI_SENTINEL = "__no_es_ti__"
   ```
   Y `SENTINELS` pasa a ser `(NO_SIGNAL_SENTINEL, SIN_EVIDENCIA_SENTINEL, ES_TI_SENTINEL, NO_ES_TI_SENTINEL)`.

2. `services/llm_tech_labeling.py`:
   - `PROMPT_VERSION = "v3"`, con un comentario v3 junto al de v2: «pregunta de nivel 1 (`es_ti`) con la frontera de D1 y fabricantes fuera del vocabulario».
   - `from db.repositories.tecnologia_pliego import METHOD_ES_TI` (re-exportado: el job y los tests lo importan de aquí).
   - `_LlmTechResponse` añade:
     ```python
     es_ti: bool | None = None
     confianza_es_ti: float | None = Field(default=None, ge=0.0, le=1.0)
     otros_fabricantes: list[str] = []
     ```
   - `Clasificacion` añade `es_ti: bool | None = None`, `confianza_es_ti: float | None = None` y `otros_fabricantes: tuple[str, ...] = ()`, con su línea en el docstring.
   - Constantes `_MAX_OTROS_FABRICANTES = 5` y `_MAX_LARGO_FABRICANTE = 60`, y la función:
     ```python
     def _limpiar_fabricantes(nombres: list[str]) -> tuple[str, ...]:
         """Recorta, quita vacíos y repetidos (sin distinguir mayúsculas)."""
         vistos: dict[str, str] = {}
         for nombre in nombres:
             limpio = nombre.strip()[:_MAX_LARGO_FABRICANTE]
             if limpio and limpio.casefold() not in vistos:
                 vistos[limpio.casefold()] = limpio
         return tuple(vistos.values())[:_MAX_OTROS_FABRICANTES]
     ```
   - `parse_labels`: tras validar,
     ```python
     if parsed.es_ti is False:
         # Nivel 1 manda: un «no es TI» con familias es una contradicción del
         # modelo, y la familia de algo que no es TI no existe.
         return Clasificacion(
             scores={},
             es_ti=False,
             confianza_es_ti=parsed.confianza_es_ti,
             otros_fabricantes=_limpiar_fabricantes(parsed.otros_fabricantes),
         )
     ```
     El resto sigue igual y el `return` final añade `es_ti=parsed.es_ti`, `confianza_es_ti=parsed.confianza_es_ti` y `otros_fabricantes=_limpiar_fabricantes(parsed.otros_fabricantes)`.
   - `_QUESTION_TEMPLATE` (no puede pasar de `MAX_INTERNAL_QUESTION_LEN`) empieza por la pregunta de nivel 1 y cambia el formato de salida:
     ```
     Primero decide si el contrato es de TI (es_ti).
     - Es TI: software (licencias, suscripciones, desarrollo o mantenimiento de aplicaciones), servicios TI (soporte, CAU, outsourcing, consultoría TI), infraestructura (cloud, hosting, CPD, redes de datos, virtualización, servidores, almacenamiento, copias de seguridad), ciberseguridad, datos, BI e IA, administración electrónica, sanidad digital, GIS y hardware del puesto de trabajo. Un contrato menor ya adjudicado también puede serlo.
     - No es TI: la formación sobre herramientas (salvo dentro de una implantación), las suscripciones a contenidos (revistas, bases de datos bibliográficas o clínicas), la telefonía de voz, la publicidad y los eventos, la obra civil o la climatización (aunque sean de un CPD), ni nada que no adquiera lo anterior aunque su CPV sea de informática.
     Después, solo si es TI, clasifícalo con un vocabulario cerrado. …(las definiciones y las reglas actuales)…
     Formato de salida (JSON, sin Markdown):
     {{"es_ti": true, "confianza_es_ti": 0.0-1.0, "tecnologias": [{{"tecnologia": "<ETIQUETA>", "confidence": 0.0-1.0, "evidencia": "<cita literal del anuncio>"}}], "otros_fabricantes": ["<fabricante que el anuncio nombra y no está en la lista>"]}}
     Si no es TI: {{"es_ti": false, "confianza_es_ti": 0.0-1.0, "tecnologias": [], "otros_fabricantes": []}}.
     ```
   - `llm/prompts.py`: en `_SYSTEM_CLASIFICACION`, «no cuentan las menciones incidentales ni la ofimática genérica» pasa a «no cuentan las menciones incidentales».

3. `scheduler/jobs/llm_tech_labeling.py`:
   - `counts` añade `"es_ti_si": 0`, `"es_ti_no": 0` y `"es_ti_sin_respuesta": 0`.
   - Dentro del `try`, tras `repo.upsert_signals(...)` de familias:
     ```python
     if clasificacion.es_ti is not None:
         marcador = ES_TI_SENTINEL if clasificacion.es_ti else NO_ES_TI_SENTINEL
         repo.upsert_signals(
             licitacion_id,
             method=METHOD_ES_TI,
             signal_version=version,
             scores={
                 marcador: TechSignal(
                     score=0.0,
                     evidence=[
                         {
                             "es_ti": clasificacion.es_ti,
                             "confianza": clasificacion.confianza_es_ti,
                             "otros_fabricantes": list(clasificacion.otros_fabricantes),
                         }
                     ],
                 )
             },
         )
     ```
   - Tras el `try`: `counts["es_ti_si" if clasificacion.es_ti else "es_ti_no" if clasificacion.es_ti is False else "es_ti_sin_respuesta"] += 1`. Escríbelo como `if/elif/else` legible.
   - `_write_feedback` recibe `dict[str, Clasificacion]` en vez de `dict[str, dict[str, TechSignal]]` (y `run` guarda `clasificadas[licitacion_id] = clasificacion`).
     - `relevante=clasificacion.es_ti`.
     - Si `es_ti is None`, no escribe fila y la cuenta como `feedback_omitido`: `relevante` significa «es TI» (spec §3.3).
     - La principal y las secundarias salen de `clasificacion.scores` como ahora.
     - Actualiza su docstring y el comentario de `FEEDBACK_SOURCE`.
   - Actualiza los tests de `_write_feedback` que construían `dict[str, TechSignal]`.

- [ ] **Step 4: Verificar que pasan**

Run: `ENV=dev PYTHONPATH="$PWD" "$PY" -m pytest tests/test_llm_tech_labeling.py tests/test_taxonomia_tecnologica.py tests/test_tech_signal.py -q -p no:cacheprovider -m unit`
Expected: PASS. Revisa que `test_fits_client_validation_limits` sigue pasando: la pregunta tiene que caber en el tope.

- [ ] **Step 5: Commit**

`feat(llm): el etiquetado dice si el contrato es TI (llm-meta-v3) con la frontera de D1`

---

### Tarea 3: Un solo significado para el feedback humano

**Files:**
- Modify: `db/repositories/feedback.py`: constantes.
- Modify: `api/routes/feedback.py:submit_feedback`: escribe `source=FUENTE_REVISION_TI`. El docstring no cambia (contrato).
- Modify: `db/repositories/ml_dataset.py`:
  - `feedback_humano_sap` pasa a llamarse `feedback_humano_es_ti`, con `DISTINCT ON` y `revision_ti`;
  - el `EXISTS` de `filas_entrenamiento_tecnologia` usa `FUENTES_HUMANAS`.
- Modify: `scraper/ml_training.py`: su llamador.
- Modify: `db/repositories/licitaciones.py:etiquetas_tecnologia_no_circulares`: lee `FUENTES_HUMANAS`, y las filas heredadas sin tecnología no se pronuncian.
- Modify: `db/model_registry.py:186-198`, que cuenta `FUENTES_HUMANAS`.
- Modify: `scheduler/concept_drift.py:424` y `scheduler/drift_report.py:426`, que leen `revision_ti`.
- Test: `tests/test_unit_rutas_feedback_etiquetas.py`, `tests/test_etiquetas_humanas.py` (nuevo) y `tests/test_etiquetas_no_circulares.py` (integración).

**Interfaces:**
- Produces:
  - `db.repositories.feedback.FUENTE_REVISION_TI = "revision_ti"` y `FUENTES_HUMANAS: tuple[str, ...] = ("human", FUENTE_REVISION_TI)`.
  - `db.repositories.ml_dataset.feedback_humano_es_ti() -> list[dict[str, Any]]`, con claves `expediente` y `relevante`.
  - `db.repositories.licitaciones.etiqueta_humana(source: str, relevante: int | None, tecnologia: str | None, secundarias: str | None) -> str | None`, función pura de módulo.

- [ ] **Step 1: Tests que fallan**

En `tests/test_unit_rutas_feedback_etiquetas.py`:

```python
def test_la_revision_se_guarda_como_revision_ti(
    sesion_admin: TestClient, escrituras: list[dict[str, Any]]
) -> None:
    """Desde el plan de tres niveles, `relevante` significa «es TI». Las filas
    viejas (`human`) significaban «es SAP» y no se mezclan con las nuevas."""
    sesion_admin.post(RUTA, json=_CUERPO)
    assert escrituras[0]["source"] == "revision_ti"
```

Nuevo `tests/test_etiquetas_humanas.py`:

```python
"""Qué etiqueta de familia sale de una fila de `ml_feedback` (2026-09-27).

`relevante` significó «es SAP» hasta el plan de tres niveles y significa «es
TI» desde `revision_ti`. Una fila vieja con `relevante=0` y sin tecnología no
dice que no haya familia: dice que no era SAP. Tratarla como negativo de todas
las familias entrenaba 45 negativos falsos.
"""

from __future__ import annotations

import pytest

from db.repositories.licitaciones import etiqueta_humana


@pytest.mark.parametrize(
    ("source", "relevante", "tecnologia", "secundarias", "esperada"),
    [
        ("revision_ti", 1, "ERP", '["SAP"]', "ERP,SAP"),
        ("revision_ti", 1, None, None, ""),  # TI sin familia: negativo de todas
        ("revision_ti", 0, None, None, ""),  # no es TI: negativo de todas
        ("human", 1, "SAP", None, "SAP"),  # heredada con tecnología: vale
        ("human", 0, None, None, None),  # heredada sin tecnología: no se pronuncia
        ("human", 0, "ORACLE", None, "ORACLE"),
    ],
)
def test_etiqueta_humana(source, relevante, tecnologia, secundarias, esperada) -> None:
    assert etiqueta_humana(source, relevante, tecnologia, secundarias) == esperada
```

En `tests/test_etiquetas_no_circulares.py` (integración: se escribe y no se ejecuta en local), añade un test que siembre una fila `human` con `relevante=0` sin tecnología y otra `revision_ti` con `relevante=1` y `tecnologia='ERP'`. Comprueba que `etiquetas_tecnologia_no_circulares()` no da `tecnologia_humana` a la primera y da `"ERP"` a la segunda. Usa las mismas fixtures y helpers de siembra del módulo.

- [ ] **Step 2: Verificar que fallan**

Run: `ENV=dev PYTHONPATH="$PWD" "$PY" -m pytest tests/test_unit_rutas_feedback_etiquetas.py tests/test_etiquetas_humanas.py -q -p no:cacheprovider`
Expected: FAIL (`'human' != 'revision_ti'`, `ImportError: etiqueta_humana`).

- [ ] **Step 3: Implementación**

1. `db/repositories/feedback.py`, en cabecera de módulo:
   ```python
   #: Etiqueta de la revisión humana desde el plan de clasificación en tres
   #: niveles (2026-09-27): `relevante` = «es TI». Las filas `human` anteriores
   #: significaban «es SAP» y se conservan como histórico.
   FUENTE_REVISION_TI = "revision_ti"
   #: Las dos fuentes de etiqueta humana de familia (tecnologia/secundarias).
   FUENTES_HUMANAS: tuple[str, ...] = ("human", FUENTE_REVISION_TI)
   ```
2. `api/routes/feedback.py:submit_feedback`: `_repo.insert(..., source=FUENTE_REVISION_TI)`.
3. `db/repositories/licitaciones.py`:
   - función de módulo (no en la clase):
     ```python
     def etiqueta_humana(
         source: str, relevante: int | None, tecnologia: str | None, secundarias: str | None
     ) -> str | None:
         """CSV de familias de una fila humana, o ``None`` si no se pronuncia.

         ``""`` es un negativo de verdad. Una fila heredada (``human``) con
         ``relevante=0`` y sin tecnología no lo es: `relevante` significaba
         «es SAP», no «es TI».
         """
         etiquetas: list[str] = []
         if tecnologia:
             etiquetas.append(tecnologia.strip().upper())
         if secundarias:
             try:
                 extra = json.loads(secundarias)
             except (TypeError, ValueError):
                 extra = []
             if isinstance(extra, list):
                 etiquetas.extend(str(t).strip().upper() for t in extra if t)
         if not etiquetas and source != FUENTE_REVISION_TI and not relevante:
             return None
         return ",".join(dict.fromkeys(e for e in etiquetas if e))
     ```
   - En `etiquetas_tecnologia_no_circulares`, la consulta humana pasa a:
     ```sql
     SELECT DISTINCT ON (expediente) expediente, source, relevante, tecnologia, tecnologias_secundarias
     FROM ml_feedback WHERE source = ANY(%s)
     ORDER BY expediente, created_at DESC, id DESC
     ```
     con `(list(FUENTES_HUMANAS),)`. Por fila, `etiqueta = etiqueta_humana(...)`; si es `None` no se escribe `tecnologia_humana`. Actualiza el docstring.
4. `db/repositories/ml_dataset.py`:
   ```python
   def feedback_humano_es_ti() -> list[dict[str, Any]]:
       """Revisión humana de «¿es TI?», la más reciente por expediente.

       Solo ``revision_ti``: las filas ``human`` anteriores al plan de tres
       niveles significaban «es SAP», y el binario aprende «es TI».
       """
       with connect_read() as c:
           return rows_to_dicts(
               c.execute(
                   "SELECT DISTINCT ON (expediente) expediente, relevante FROM ml_feedback "
                   "WHERE source = %s ORDER BY expediente, created_at DESC, id DESC",
                   (FUENTE_REVISION_TI,),
               )
           )
   ```
   Renombra el llamador en `scraper/ml_training.py`. En `filas_entrenamiento_tecnologia`, `f.source = 'human'` pasa a `f.source = ANY(%s)` con `list(FUENTES_HUMANAS)` como parámetro, junto al que ya lleva.
5. `db/model_registry.py:186-198`: `source = 'human'` pasa a `source = ANY(%s)` con `FUENTES_HUMANAS`.
6. `scheduler/concept_drift.py:424` y `scheduler/drift_report.py:426`: `'human'` pasa a `%s` con `FUENTE_REVISION_TI`, porque ambos comparan `relevante` con la predicción del binario (es TI). Es SQL legado dentro del ratchet TID251: se edita en su sitio, sin añadir consultas nuevas fuera de `db/`.
7. Docstrings que citan `source = 'human'` (`scraper/tech_classifier.py:34`, `services/reportes_dato.py:12`, `scheduler/jobs/llm_tech_labeling.py`): una línea sobre `revision_ti`.

- [ ] **Step 4: Verificar que pasan**

Run: `ENV=dev PYTHONPATH="$PWD" "$PY" -m pytest tests/ -q -p no:cacheprovider -m unit -k "feedback or etiquet or ml_training or drift or model_registry"`
Expected: PASS. Busca con `grep -rn "feedback_humano_sap"` que no quede ningún uso.

- [ ] **Step 5: Commit**

`fix(feedback): relevante significa «es TI» desde revision_ti y el histórico sin tecnología deja de entrenar negativos`

---

### Tarea 4: Cola de revisión por desacuerdo en `/ops`

**Files:**
- Create: `db/repositories/revision_ti.py`
- Modify: `api/routes/feedback.py`: estrategia `desacuerdo`, `QueueLlmBlock` y los campos `motivo`/`llm` de `FeedbackQueueItem`.
- Modify: `web/src/app/(dashboard)/ops/_hooks/use-active-learning.ts`
- Modify: `web/src/app/(dashboard)/ops/_components/active-learning/labeling-queue.tsx`
- Modify: `web/src/app/(dashboard)/ops/_components/active-learning/queue-item-card.tsx`
- Regenerate: `web/src/generated/api.d.ts`
- Test:
  - `tests/test_revision_ti_desacuerdo.py` (integración);
  - `tests/test_unit_rutas_feedback_cola_desacuerdo.py` (unit);
  - `web/src/app/(dashboard)/ops/_components/active-learning/__tests__/queue-item-card.test.tsx` (vitest).

**Interfaces:**
- Consumes:
  - `ES_TI_SENTINEL`, `NO_ES_TI_SENTINEL`, `SENTINELS` y `METHOD_ES_TI` (Tarea 2);
  - `FUENTE_REVISION_TI` (Tarea 3);
  - `settings.PLIEGO_TECH_MIN_SCORE`.
- Produces:
  - `db.repositories.revision_ti.MOTIVOS: tuple[str, ...] = ("llm_no_reglas_si", "llm_si_reglas_no", "llm_no_cpv_si", "familias_distintas", "modelo_dudoso")`, en orden de prioridad.
  - `db.repositories.revision_ti.candidatos_desacuerdo(limit: int) -> list[dict[str, Any]]`. Claves: las de `get_unlabelled_candidates` más `ml_proba`, `motivo`, `llm_es_ti: bool | None`, `llm_confianza_es_ti: float | None` y `llm_familias: list[str]`.
  - API: `QueueLlmBlock(es_ti: bool | None, confianza_es_ti: float | None, familias: list[str])`; `FeedbackQueueItem.motivo: str | None = None` y `FeedbackQueueItem.llm: QueueLlmBlock | None = None`.
  - Web:
    - `Strategy = "desacuerdo" | "uncertainty" | "random"`, con `"desacuerdo"` por defecto;
    - `QueueItem.motivo?: string | null` y `QueueItem.llm?: { es_ti: boolean | null; confianza_es_ti: number | null; familias: string[] } | null`;
    - acciones del hook `acceptLlmProposal(expediente)` y `markTiWithoutFamily(expediente)`.

- [ ] **Step 1: Tests que fallan**

`tests/test_unit_rutas_feedback_cola_desacuerdo.py`:

```python
"""La cola por desacuerdo, por su ruta (plan de tres niveles, F1).

La cola por incertidumbre ordena por un modelo que dice «sí» a casi todo; la
de desacuerdo pone delante lo que reglas, LLM y modelo no ven igual, que es
donde una etiqueta humana informa. Aquí se prueba la ruta sin BD: qué
estrategia llama a qué y qué forma tiene cada ítem.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

_CANDIDATO: dict[str, Any] = {
    "id_externo": "EXP-9",
    "titulo": "Manteniment del gestor documental",
    "descripcion": "",
    "cpv": "72267000-4",
    "importe": 1000.0,
    "organo_contratacion": "Ajuntament",
    "ccaa": "Cataluña",
    "fecha_publicacion": "2026-09-20",
    "url": None,
    "tecnologia": "GESTION_DOCUMENTAL",
    "ml_tecnologias": None,
    "ml_proba_max": None,
    "ml_tech_principal": None,
    "ml_proba": 0.97,
    "motivo": "llm_no_reglas_si",
    "llm_es_ti": False,
    "llm_confianza_es_ti": 0.7,
    "llm_familias": [],
}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    from api.app import app
    from api.routes.dual_auth import require_any_auth
    import api.routes.feedback as rutas
    import db.repositories.revision_ti as revision

    monkeypatch.setattr(revision, "candidatos_desacuerdo", lambda limit: [dict(_CANDIDATO)])
    monkeypatch.setattr(rutas, "_cargar_tech_classifier", lambda: None)
    app.dependency_overrides[require_any_auth] = lambda: {"user_id": 1, "is_admin": True}
    try:
        yield TestClient(app, raise_server_exceptions=True)
    finally:
        app.dependency_overrides.clear()


def test_la_cola_por_desacuerdo_trae_el_motivo_y_la_propuesta_del_llm(client: TestClient) -> None:
    cuerpo = client.get("/api/v1/feedback/queue?strategy=desacuerdo&limit=5").json()
    assert cuerpo["strategy"] == "desacuerdo"
    item = cuerpo["items"][0]
    assert item["motivo"] == "llm_no_reglas_si"
    assert item["llm"] == {"es_ti": False, "confianza_es_ti": 0.7, "familias": []}
    assert item["confidence"] == pytest.approx(0.97)
```

(`_cargar_tech_classifier` es la extracción, en función de módulo, de la carga perezosa del `TechnologyClassifier` que hoy vive dentro de `feedback_queue`. Hacerla es parte del Step 3, y permite probar la ruta sin el artefacto de 11 MB.)

`tests/test_revision_ti_desacuerdo.py` (integración, con la fixture `tmp_db` que ya usan los tests de `licitacion_tecnologia_pliego`). Siembra cinco licitaciones:
- A: `tecnologia='ERP'` y marcador `__no_es_ti__`;
- B: sin tecnología, CPV `79000000-4` y marcador `__es_ti__`;
- C: sin tecnología, CPV `72000000-5` y marcador `__no_es_ti__`;
- D: `tecnologia='SAP'`, familias LLM `{'ORACLE'}` y marcador `__es_ti__`;
- E: como A, pero con una fila `revision_ti` en `ml_feedback`.

Comprueba que `candidatos_desacuerdo(10)` devuelve A, B, C y D en ese orden, con los motivos `llm_no_reglas_si`, `llm_si_reglas_no`, `llm_no_cpv_si` y `familias_distintas`, y **no** devuelve E.

`queue-item-card.test.tsx` (vitest + Testing Library, igual que los tests de `web/src/app/(dashboard)/ops/__tests__/views-shared.test.tsx`). Renderiza `QueueItemCard` con `item.llm = { es_ti: true, confianza_es_ti: 0.9, familias: ["DESARROLLO"] }` y `item.motivo = "familias_distintas"`, y comprueba:
- que se ve «Propuesta del LLM: es TI · DESARROLLO»;
- que el botón «Aceptar propuesta» llama a `onAcceptLlm`;
- que el botón «No es TI» llama a `onNotRelevant`;
- que con `item.llm = null` el botón «Aceptar propuesta» no se pinta.

- [ ] **Step 2: Verificar que fallan**

Run:
```bash
ENV=dev PYTHONPATH="$PWD" "$PY" -m pytest tests/test_unit_rutas_feedback_cola_desacuerdo.py -q -p no:cacheprovider
cd web && npx vitest run "src/app/(dashboard)/ops/_components/active-learning/__tests__/queue-item-card.test.tsx"
```
Expected: FAIL (`ModuleNotFoundError: db.repositories.revision_ti`; el texto «Propuesta del LLM» no existe).

- [ ] **Step 3: Implementación**

1. `db/repositories/revision_ti.py`:
   ```python
   """Candidatos de la revisión humana por desacuerdo (plan de tres niveles, F1).

   Una etiqueta humana informa donde las fuentes no coinciden. Las reglas son
   `licitaciones.tecnologia` y el CPV; el LLM, el marcador de `llm_es_ti` y las
   familias de `llm_metadata`; el modelo, `ml_proba`. Lo que ya revisó una
   persona con `revision_ti` no vuelve.
   """

   from __future__ import annotations

   from typing import Any

   from db.database import connect_read
   from db.repositories.base import rows_to_dicts
   from db.repositories.feedback import FUENTE_REVISION_TI
   from db.repositories.tecnologia_pliego import (
       ES_TI_SENTINEL,
       METHOD_ES_TI,
       NO_ES_TI_SENTINEL,
       SENTINELS,
   )

   MOTIVOS: tuple[str, ...] = (
       "llm_no_reglas_si",
       "llm_si_reglas_no",
       "llm_no_cpv_si",
       "familias_distintas",
       "modelo_dudoso",
   )

   #: Algún código CPV 48/72 en el campo, con cualquier separador (PSCP une con `||`).
   _CPV_TI_SQL = "coalesce(l.cpv, '') ~ '(^|[^0-9])(48|72)[0-9]{6}'"

   _SQL = f"""
   WITH es_ti AS (
       SELECT DISTINCT ON (licitacion_id) licitacion_id, tecnologia AS marcador, evidence_json
       FROM licitacion_tecnologia_pliego
       WHERE method = %(method_es_ti)s
       ORDER BY licitacion_id, computed_at DESC
   ), familias AS (
       SELECT licitacion_id, array_agg(tecnologia ORDER BY tecnologia) AS llm_familias
       FROM licitacion_tecnologia_pliego
       WHERE method = 'llm_metadata' AND tecnologia <> ALL(%(sentinels)s) AND score >= %(min_score)s
       GROUP BY licitacion_id
   ), candidatos AS (
       SELECT l.id_externo, l.titulo, l.descripcion, l.cpv, l.importe, l.organo_contratacion,
              l.ccaa, l.fecha_publicacion, l.url, l.tecnologia, l.ml_tecnologias,
              l.ml_proba_max, l.ml_tech_principal, l.ml_proba,
              e.marcador, e.evidence_json AS llm_evidencia, f.llm_familias,
              CASE
                WHEN e.marcador = %(no_es_ti)s AND coalesce(l.tecnologia, '') <> ''
                  THEN 'llm_no_reglas_si'
                WHEN e.marcador = %(es_ti)s AND coalesce(l.tecnologia, '') = '' AND NOT ({_CPV_TI_SQL})
                  THEN 'llm_si_reglas_no'
                WHEN e.marcador = %(no_es_ti)s AND {_CPV_TI_SQL}
                  THEN 'llm_no_cpv_si'
                WHEN f.llm_familias IS NOT NULL AND coalesce(l.tecnologia, '') <> ''
                     AND NOT (f.llm_familias && string_to_array(replace(l.tecnologia, ' ', ''), ','))
                  THEN 'familias_distintas'
                WHEN l.ml_proba BETWEEN 0.3 AND 0.7
                  THEN 'modelo_dudoso'
              END AS motivo
       FROM licitaciones l
       LEFT JOIN es_ti e ON e.licitacion_id = l.id_externo
       LEFT JOIN familias f ON f.licitacion_id = l.id_externo
       WHERE NOT EXISTS (
           SELECT 1 FROM ml_feedback r
           WHERE r.expediente = l.id_externo AND r.source = %(revision)s
       )
   )
   SELECT * FROM candidatos
   WHERE motivo IS NOT NULL
   ORDER BY array_position(%(motivos)s::text[], motivo), fecha_publicacion DESC NULLS LAST
   LIMIT %(limit)s
   """  # Interpola solo el predicado constante del módulo.


   def candidatos_desacuerdo(limit: int) -> list[dict[str, Any]]:
       """Hasta ``limit`` licitaciones sin revisar, primero las de desacuerdo más grave."""
       from config import settings

       with connect_read() as c:
           filas = rows_to_dicts(
               c.execute(
                   _SQL,
                   {
                       "method_es_ti": METHOD_ES_TI,
                       "sentinels": list(SENTINELS),
                       "min_score": settings.PLIEGO_TECH_MIN_SCORE,
                       "es_ti": ES_TI_SENTINEL,
                       "no_es_ti": NO_ES_TI_SENTINEL,
                       "revision": FUENTE_REVISION_TI,
                       "motivos": list(MOTIVOS),
                       "limit": max(1, min(int(limit), 200)),
                   },
               )
           )
       for fila in filas:
           marcador = fila.pop("marcador", None)
           fila["llm_es_ti"] = (
               True if marcador == ES_TI_SENTINEL else False if marcador == NO_ES_TI_SENTINEL else None
           )
           fila["llm_confianza_es_ti"] = _confianza(fila.pop("llm_evidencia", None))
           fila["llm_familias"] = list(fila.get("llm_familias") or [])
       return filas
   ```
   Añade `_confianza(evidence_json: str | None) -> float | None`: lee el JSON y devuelve `evidence[0]["confianza"]` si es número, y `None` en cualquier otro caso. Escribe el `True if … else …` anidado como un `if/elif` legible.

2. `api/routes/feedback.py`:
   - `QueueLlmBlock(BaseModel)`, con docstring de una línea;
   - `FeedbackQueueItem`, que añade `motivo: str | None = None` y `llm: QueueLlmBlock | None = None`;
   - extrae `_cargar_tech_classifier() -> Any` de `feedback_queue`, con el mismo `try/except` y log;
   - la descripción de `strategy` pasa a `"desacuerdo | uncertainty | random"`;
   - una rama nueva antes de `uncertainty`:
     ```python
     if strategy == "desacuerdo":
         from db.repositories.revision_ti import candidatos_desacuerdo

         candidatos = await run_db(candidatos_desacuerdo, limit)
         for c in candidatos:
             p = float(c["ml_proba"]) if c.get("ml_proba") is not None else 0.5
             c["confidence"], c["uncertainty"] = p, abs(p - 0.5)
         items = _build_queue_items(candidatos, include_model=True, tech_classifier=tech_clf)
         for item, c in zip(items, candidatos, strict=True):
             item["motivo"] = c["motivo"]
             item["llm"] = {
                 "es_ti": c["llm_es_ti"],
                 "confianza_es_ti": c["llm_confianza_es_ti"],
                 "familias": c["llm_familias"],
             }
         return FeedbackQueueResult(
             items=[FeedbackQueueItem(**item) for item in items], strategy=strategy, model_version=None
         )
     ```
     Lee `_build_queue_items` antes: si ya fija `confidence`/`uncertainty` desde otra clave, respeta su convención.
   - El docstring de `feedback_queue` añade una línea sobre `desacuerdo`. Es contrato: regenera después.

3. Contrato:
   ```bash
   ENV=dev PYTHONPATH="$PWD" "$PY" scripts/export_openapi.py
   cd web && npm ci --prefer-offline --no-audit --no-fund && npm run codegen:file
   ```
   Revisa el diff de `web/src/generated/api.d.ts`: solo tienen que aparecer `QueueLlmBlock`, `motivo`/`llm` y los textos de la ruta.

4. Web:
   - `use-active-learning.ts`:
     - `Strategy`, con estado inicial `"desacuerdo"`;
     - `QueueItem.motivo` y `QueueItem.llm`;
     - `acceptLlmProposal(expediente)` busca el ítem, y si `item.llm?.es_ti == null` no hace nada. Si no, llama a `submitFeedback.mutate({expediente, relevante: item.llm.es_ti, nota, tecnologia: item.llm.familias[0] ?? null, tecnologias_secundarias: item.llm.familias.slice(1)})`;
     - `markTiWithoutFamily(expediente)` envía `relevante: true` sin tecnologías;
     - ambas se exponen en `ActiveLearning`.
   - `labeling-queue.tsx`: el botón «Desacuerdo» va primero en el grupo «Estrategia».
   - `queue-item-card.tsx`:
     - props nuevas `onAcceptLlm` y `onTiWithoutFamily`;
     - bajo la cabecera, si `item.motivo`, un `Badge` con el texto de este mapa (si el motivo no está en él, se muestra tal cual):
       ```ts
       const MOTIVO_LEGIBLE: Record<string, string> = {
         llm_no_reglas_si: "El LLM dice que no es TI; las reglas, que sí",
         llm_si_reglas_no: "El LLM dice que es TI; ni las reglas ni el CPV lo ven",
         llm_no_cpv_si: "El CPV es de informática; el LLM dice que no es TI",
         familias_distintas: "El LLM y las reglas ven familias distintas",
         modelo_dudoso: "El modelo no está seguro",
       };
       ```
     - si `item.llm`, una línea «Propuesta del LLM: es TI · DESARROLLO» o «Propuesta del LLM: no es TI», con la confianza en porcentaje, y el botón «Aceptar propuesta» (`onAcceptLlm`);
     - «Ninguna / no relevante» pasa a «No es TI»;
     - «Confirmar etiqueta» / «Confirmar: X» pasan a «Es TI: X» (sin cambiar la lógica);
     - botón nuevo «Es TI, sin familia» (`onTiWithoutFamily`).
   - El padre que pinta `QueueItemCard` pasa las dos acciones nuevas del hook.

- [ ] **Step 4: Verificar que pasan**

Run:
```bash
ENV=dev PYTHONPATH="$PWD" "$PY" -m pytest tests/test_unit_rutas_feedback_cola_desacuerdo.py tests/test_routes_feedback.py tests/test_feedback_queue_model_block.py -q -p no:cacheprovider -m unit
cd web && npm run typecheck && npx eslint "src/app/(dashboard)/ops" && npx vitest run "src/app/(dashboard)/ops"
```
Expected: PASS. `tests/test_revision_ti_desacuerdo.py` se reporta como no ejecutado (Postgres).

- [ ] **Step 5: Commit**

`feat(ops): la cola de etiquetado prioriza el desacuerdo entre reglas, LLM y modelo`

---

### Tarea 5: Golden set real (`golden_ti.jsonl`) y su exportación

**Files:**
- Create: `services/ml/golden_ti.py`
- Create: `scripts/exportar_golden_ti.py`
- Create: `tests/fixtures/golden_ti.jsonl` (solo cabecera `#`)
- Modify: `db/repositories/feedback.py`: `FeedbackRepository.filas_revision_ti()`.
- Test: `tests/test_golden_ti.py` (unit) y `tests/test_feedback_revision_ti_db.py` (integración).

**Interfaces:**
- Consumes: `FUENTE_REVISION_TI` (Tarea 3) y `TECH_LABELS`/`TECH_LABEL_TIPO` (Tarea 1).
- Produces:
  - `services.ml.golden_ti.EjemploGoldenTi`: dataclass `frozen` con `id_externo: str`, `fuente: str`, `fecha: str`, `titulo: str`, `descripcion: str`, `cpv: str | None`, `es_ti: bool`, `familias: tuple[str, ...]`, `fabricantes: tuple[str, ...]`, `etiquetado_por: str`, `etiquetado_at: str` y `split: Literal["tune", "holdout"]`.
  - `RUTA_GOLDEN_TI: Path`.
  - `cargar_golden_ti(path: Path | None = None) -> list[EjemploGoldenTi]`.
  - `asignar_splits(ejemplos: list[EjemploGoldenTi]) -> list[EjemploGoldenTi]`.
  - `ejemplo_desde_fila(fila: dict[str, Any]) -> EjemploGoldenTi`.
  - `a_linea(ejemplo: EjemploGoldenTi) -> str`.
  - `FeedbackRepository.filas_revision_ti() -> list[dict[str, Any]]`.

- [ ] **Step 1: Tests que fallan**

`tests/test_golden_ti.py`:

```python
"""El golden set real de «¿es TI?» y familias (plan de tres niveles, F2).

Sustituye a los 27 ejemplos de `golden_set.jsonl` como gate del binario: sale
de la revisión humana (`ml_feedback`, `source='revision_ti'`), lleva fuente y
fecha, y su holdout es el 50 % más reciente, fijo.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from services.ml.golden_ti import (
    EjemploGoldenTi,
    a_linea,
    asignar_splits,
    cargar_golden_ti,
    ejemplo_desde_fila,
)


def _ejemplo(id_: str, fecha: str, **cambios: object) -> EjemploGoldenTi:
    base = EjemploGoldenTi(
        id_externo=id_,
        fuente="pscp",
        fecha=fecha,
        titulo="t",
        descripcion="",
        cpv=None,
        es_ti=True,
        familias=(),
        fabricantes=(),
        etiquetado_por="humano",
        etiquetado_at="2026-09-28T00:00:00+00:00",
        split="tune",
    )
    return replace(base, **cambios)  # type: ignore[arg-type]  # cambios de test


def test_el_holdout_es_la_mitad_mas_reciente() -> None:
    ejemplos = [_ejemplo(f"E{i}", f"2026-0{i}-01") for i in range(1, 5)]
    splits = {e.id_externo: e.split for e in asignar_splits(ejemplos)}
    assert splits == {"E1": "tune", "E2": "tune", "E3": "holdout", "E4": "holdout"}


def test_una_fila_de_revision_separa_familias_de_fabricantes() -> None:
    fila = {
        "expediente": "EXP-1",
        "fuente": "placsp",
        "fecha_publicacion": "2026-09-01",
        "titulo": "Implantación de SAP S/4HANA",
        "descripcion": None,
        "cpv": "72000000",
        "relevante": 1,
        "tecnologia": "ERP",
        "tecnologias_secundarias": '["SAP"]',
        "created_at": "2026-09-28T10:00:00+00:00",
    }
    ejemplo = ejemplo_desde_fila(fila)
    assert ejemplo.es_ti is True
    assert ejemplo.familias == ("ERP",)
    assert ejemplo.fabricantes == ("SAP",)
    assert ejemplo.descripcion == ""


def test_ida_y_vuelta_por_el_fichero(tmp_path: Path) -> None:
    ruta = tmp_path / "golden.jsonl"
    ejemplo = _ejemplo("E1", "2026-09-01", familias=("ERP",), split="holdout")
    ruta.write_text("# cabecera\n\n" + a_linea(ejemplo) + "\n", encoding="utf-8")
    assert cargar_golden_ti(ruta) == [ejemplo]


def test_una_etiqueta_fuera_del_vocabulario_es_un_error(tmp_path: Path) -> None:
    ruta = tmp_path / "golden.jsonl"
    ruta.write_text(a_linea(_ejemplo("E1", "2026-09-01", familias=("NO_EXISTE",))), encoding="utf-8")
    with pytest.raises(ValueError, match="NO_EXISTE"):
        cargar_golden_ti(ruta)


def test_el_fichero_del_repo_carga() -> None:
    """Hoy solo tiene la cabecera: vacío es válido, roto no."""
    assert isinstance(cargar_golden_ti(), list)
```

`tests/test_feedback_revision_ti_db.py` (integración): siembra dos filas `revision_ti` del mismo expediente con distinto `created_at`, más una `human`. Comprueba que `filas_revision_ti()` devuelve una sola fila, la más reciente, con las columnas de `licitaciones` unidas (`fuente`, `fecha_publicacion`, `titulo`, `descripcion`, `cpv`).

- [ ] **Step 2: Verificar que fallan**

Run: `ENV=dev PYTHONPATH="$PWD" "$PY" -m pytest tests/test_golden_ti.py -q -p no:cacheprovider`
Expected: FAIL (`ModuleNotFoundError: services.ml.golden_ti`).

- [ ] **Step 3: Implementación**

- `services/ml/golden_ti.py`:
  - `RUTA_GOLDEN_TI = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "golden_ti.jsonl"`.
  - `ejemplo_desde_fila` reparte `tecnologia` y `tecnologias_secundarias` (JSON) en `familias` y `fabricantes` según `TECH_LABEL_TIPO`, sin repetidos y en orden. `etiquetado_por="humano"`, `etiquetado_at=fila["created_at"]`, `es_ti=bool(fila["relevante"])` y `split="tune"`; el reparto lo hace `asignar_splits`.
  - `asignar_splits` ordena por `(fecha, id_externo)`, y la segunda mitad (redondeando hacia abajo la primera) es `holdout`.
  - `a_linea` es `json.dumps(asdict(e) con tuplas a listas, ensure_ascii=False, sort_keys=True)`.
  - `cargar_golden_ti` ignora las líneas vacías y las `#`, valida `split ∈ {"tune","holdout"}` y que familias y fabricantes estén en `TECH_LABELS` (`ValueError` con el valor malo), y devuelve la lista.
- `db/repositories/feedback.py`:
  ```python
  def filas_revision_ti(self) -> list[dict[str, Any]]:
      """La revisión humana vigente por expediente, con lo que hace falta del anuncio."""
      with connect_read() as c:
          cur = c.execute(
              "SELECT DISTINCT ON (f.expediente) f.expediente, f.relevante, f.tecnologia, "
              "f.tecnologias_secundarias, f.created_at, l.fuente, l.fecha_publicacion, "
              "l.titulo, l.descripcion, l.cpv "
              "FROM ml_feedback f JOIN licitaciones l ON l.id_externo = f.expediente "
              "WHERE f.source = %s ORDER BY f.expediente, f.created_at DESC, f.id DESC",
              (FUENTE_REVISION_TI,),
          )
          return rows_to_dicts(cur)
  ```
- `scripts/exportar_golden_ti.py` sigue el patrón de los scripts del repo: `sys.path` y `get_logger`. Hace `ejemplos = asignar_splits([ejemplo_desde_fila(f) for f in FeedbackRepository().filas_revision_ti()])` y escribe `RUTA_GOLDEN_TI` con la cabecera (qué es, de dónde sale, cómo se regenera) y una línea por ejemplo, ordenadas por fecha, con `\n`. Imprime `n`, positivos y el tamaño de cada mitad, y acepta `--salida <ruta>`.
- `tests/fixtures/golden_ti.jsonl`: solo la cabecera `#`, que dice que se genera con `ENV=dev PYTHONPATH="$PWD" python scripts/exportar_golden_ti.py` tras la revisión humana y que no se edita a mano.

- [ ] **Step 4: Verificar que pasan**

Run: `ENV=dev PYTHONPATH="$PWD" "$PY" -m pytest tests/test_golden_ti.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Commit**

`feat(ml): golden set real de «¿es TI?» exportado de la revisión humana`

---

### Tarea 6: Acuerdo LLM↔humanos (la regla de §3.5)

**Files:**
- Create: `services/ml/acuerdo_llm.py`
- Create: `scripts/medir_acuerdo_llm.py`
- Modify: `db/repositories/tecnologia_pliego.py`: `respuestas_llm_vigentes`.
- Test: `tests/test_acuerdo_llm.py` (unit) y un test de integración en `tests/test_tech_signal_db.py`.

**Interfaces:**
- Consumes: `EjemploGoldenTi` y `cargar_golden_ti` (Tarea 5); `METHOD_ES_TI` y los sentinels (Tarea 2).
- Produces:
  - `services.ml.acuerdo_llm.RespuestaLlm(NamedTuple)`: `es_ti: bool | None`, `familias: frozenset[str]`.
  - `AcuerdoLlm(NamedTuple)`: `n_comparables: int`, `acuerdo_es_ti: float | None`, `f1_por_familia: dict[str, float]`, `sin_soporte: tuple[str, ...]`, `apto: bool`, `motivos: tuple[str, ...]`.
  - `medir_acuerdo(golden: list[EjemploGoldenTi], respuestas: dict[str, RespuestaLlm]) -> AcuerdoLlm`.
  - Constantes `ACUERDO_MIN_ES_TI = 0.90`, `F1_MIN_FAMILIA = 0.80` y `SOPORTE_MIN_FAMILIA = 10`.
  - `TecnologiaPliegoRepository.respuestas_llm_vigentes(licitacion_ids: list[str]) -> dict[str, dict[str, Any]]`, con `{"es_ti": bool | None, "familias": list[str]}` por id.

- [ ] **Step 1: Tests que fallan**

`tests/test_acuerdo_llm.py`:

```python
"""¿Se pueden usar las etiquetas del LLM para entrenar? (spec §3.5).

Solo si coinciden con las humanas: ≥ 0,90 en «¿es TI?» y ≥ 0,80 de F1 en cada
familia con soporte suficiente en el golden.
"""

from __future__ import annotations

from dataclasses import replace

from services.ml.acuerdo_llm import RespuestaLlm, medir_acuerdo
from services.ml.golden_ti import EjemploGoldenTi


def _golden(id_: str, es_ti: bool, familias: tuple[str, ...] = ()) -> EjemploGoldenTi:
    return EjemploGoldenTi(
        id_externo=id_,
        fuente="pscp",
        fecha="2026-09-01",
        titulo="t",
        descripcion="",
        cpv=None,
        es_ti=es_ti,
        familias=familias,
        fabricantes=(),
        etiquetado_por="humano",
        etiquetado_at="2026-09-28",
        split="holdout",
    )


def test_acuerdo_perfecto_es_apto() -> None:
    golden = [_golden(f"G{i}", True, ("DESARROLLO",)) for i in range(10)]
    respuestas = {g.id_externo: RespuestaLlm(True, frozenset({"DESARROLLO"})) for g in golden}
    acuerdo = medir_acuerdo(golden, respuestas)
    assert acuerdo.acuerdo_es_ti == 1.0
    assert acuerdo.f1_por_familia == {"DESARROLLO": 1.0}
    assert acuerdo.apto is True


def test_por_debajo_del_umbral_de_es_ti_no_es_apto() -> None:
    golden = [_golden(f"G{i}", True) for i in range(10)]
    respuestas = {g.id_externo: RespuestaLlm(i >= 2, frozenset()) for i, g in enumerate(golden)}
    acuerdo = medir_acuerdo(golden, respuestas)
    assert acuerdo.acuerdo_es_ti == 0.8
    assert acuerdo.apto is False
    assert any("es_ti" in m for m in acuerdo.motivos)


def test_una_familia_con_poco_soporte_no_decide() -> None:
    golden = [_golden("G0", True, ("GIS",))] + [_golden(f"G{i}", True) for i in range(1, 10)]
    respuestas = {g.id_externo: RespuestaLlm(True, frozenset()) for g in golden}
    acuerdo = medir_acuerdo(golden, respuestas)
    assert "GIS" in acuerdo.sin_soporte
    assert "GIS" not in acuerdo.f1_por_familia
    assert acuerdo.apto is True


def test_sin_respuesta_del_llm_no_cuenta() -> None:
    golden = [_golden("G0", True), _golden("G1", False)]
    respuestas = {"G0": RespuestaLlm(True, frozenset()), "G1": RespuestaLlm(None, frozenset())}
    acuerdo = medir_acuerdo(golden, respuestas)
    assert acuerdo.n_comparables == 1
```

Añade a `tests/test_tech_signal_db.py` (integración) un test que siembre, para una licitación:
- `llm_metadata` v2 con `ORACLE`, más antigua;
- `llm_metadata` v3 con `DESARROLLO`;
- `llm_es_ti` v3 con `__es_ti__`.

Comprueba que `respuestas_llm_vigentes([id])` da `{"es_ti": True, "familias": ["DESARROLLO"]}`.

- [ ] **Step 2: Verificar que fallan**

Run: `ENV=dev PYTHONPATH="$PWD" "$PY" -m pytest tests/test_acuerdo_llm.py -q -p no:cacheprovider`
Expected: FAIL (`ModuleNotFoundError: services.ml.acuerdo_llm`).

- [ ] **Step 3: Implementación**

- `services/ml/acuerdo_llm.py`:
  - Solo cuentan los ejemplos del golden con respuesta del LLM y `es_ti is not None` (`n_comparables`).
  - `acuerdo_es_ti` es la fracción de coincidencias, o `None` si `n_comparables == 0`.
  - Una familia se evalúa si su soporte humano (positivos en el golden comparable) es `>= SOPORTE_MIN_FAMILIA`. Su F1 se calcula sobre los ejemplos humanos `es_ti=True`, a mano y sin sklearn: `2·tp / (2·tp + fp + fn)`, o 1.0 si los tres son 0. Las demás van a `sin_soporte`, ordenadas.
  - `apto` exige `acuerdo_es_ti` no `None` y `>= ACUERDO_MIN_ES_TI`, y todas las evaluadas `>= F1_MIN_FAMILIA`.
  - `motivos` explica cada incumplimiento, p. ej. `"es_ti 0.80 < 0.90"` y `"DESARROLLO f1 0.62 < 0.80"`.
- `TecnologiaPliegoRepository.respuestas_llm_vigentes`:
  - Por licitación, la versión vigente (la de la fila más reciente por `computed_at`, con la versión como desempate) de `llm_metadata` y de `llm_es_ti`, con la misma ventana `FIRST_VALUE … OVER (PARTITION BY licitacion_id, method …)` que `etiquetas_tecnologia_no_circulares`.
  - `es_ti` sale del marcador; `familias`, de las filas de `llm_metadata` no sentinel con `score >= settings.PLIEGO_TECH_MIN_SCORE`.
- `scripts/medir_acuerdo_llm.py`:
  - Carga el golden, pide `respuestas_llm_vigentes` de sus ids y convierte a `RespuestaLlm`.
  - Imprime `n_comparables`, el acuerdo en es_ti, la F1 por familia, las familias sin soporte y el veredicto `APTO`/`NO APTO` con sus motivos.
  - Sale con 0 siempre: es un informe, no un gate.

- [ ] **Step 4: Verificar que pasan**

Run: `ENV=dev PYTHONPATH="$PWD" "$PY" -m pytest tests/test_acuerdo_llm.py tests/test_golden_ti.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Commit**

`feat(ml): el informe de acuerdo LLM↔humanos decide si las etiquetas del LLM pueden entrenar`

---

### Cierre de la fase

- [ ] Suite unitaria entera: `ENV=dev PYTHONPATH="$PWD" "$PY" -m pytest tests/ -m "unit and not slow" -q -p no:cacheprovider`. Solo el rojo de base conocido.
- [ ] `"$PY" -m ruff check .`, `"$PY" -m ruff format --check .` y `ENV=dev "$PY" -m mypy .` (5 errores conocidos).
- [ ] Web: `cd web && npm run typecheck && npx eslint src && npm run test`.
- [ ] En `docs/plans/2026-09-27-clasificacion-tres-niveles.md` §6, anotar F1 como hecha, con los commits, y lo que queda para F2 (lanzar el LLM sobre la muestra con OK explícito, la revisión humana y `scripts/exportar_golden_ti.py`).
- [ ] Lista de los tests de integración escritos y no ejecutados, para el PR.

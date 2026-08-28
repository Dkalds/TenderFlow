"""Dedupe cross-fuente de licitaciones (Fase 5.2, RFC 20260611-1).

Con varias fuentes (PLACSP, TED, PSCP) el mismo contrato puede entrar dos
veces — los órganos catalanes publican en PSCP y una parte llega también a
PLACSP. Sin dedupe, las métricas competitivas (cuota, HHI, renovaciones)
contarían el contrato duplicado.

Estrategia: **marcado reversible, nunca merge físico**. Las filas duplicadas
se registran en ``licitaciones_duplicados`` apuntando a su canónica y las
consultas analíticas las excluyen vía :func:`exclude_duplicados_sql`.

Clave débil de matching: órgano normalizado (lower, sin acentos, sin formas
societarias) + expediente nacional (el id natural sin namespace de fuente) +
CPV a 4 dígitos.

- Match completo (órgano + expediente + CPV4) → confianza 1.0, ``confirmed``.
- Órgano + expediente sin CPV coincidente → confianza 0.8, ``pending``
  (cola de revisión humana, mismo patrón que ``empresa_review_queue``;
  el status vive en la propia tabla, preferencia del RFC).

Canónico: la fila PLACSP cuando existe (más detalle de adjudicación);
si no, la más antigua por fecha de publicación/extracción; y a igualdad de
fechas, la de ``id_externo`` menor. El último desempate no es cosmético: sin él
la canónica la decidía el orden en que la consulta devolvía las filas, o sea
que podía cambiar entre ejecuciones y llevarse consigo la URL que el sitemap
publica para ese contrato.

**Segundo caso, misma fuente.** Lo anterior empareja fuentes distintas por
expediente natural, y por construcción no puede ver una fuente que reemite el
mismo contrato con otro ``id_externo`` — que es lo que hacen TED (un
``publication-number`` por anuncio) y PSCP (cae al ``id`` de la fila cuando no
hay ``codi_expedient``). Eso lo cubre :func:`detect_republicaciones`, con la
clave órgano + CPV4 + año-mes + título y marcando siempre ``pending``: ver su
docstring para por qué no puede marcar ``confirmed``.

El SQL de ese detector vive en ``db/repositories/dedupe.py`` (ADR-022). Aquí se
queda la lógica de dominio: construir la clave, agrupar y elegir canónica.

La detección es incremental: cursor por fuente en ``ingestion_cursors``
(``dedupe_<fuente>``, watermark = max ``fecha_extraccion`` procesada), solo
evalúa filas nuevas de la pasada — sin full scan de pares.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from db.database import connect, connect_read, get_cursor, set_cursor
from db.repositories import dedupe as dedupe_repo
from db.repositories.base import rows_to_dicts

# Reexport: el fragmento SQL bajó a ``db/sql_fragments.py`` (ADR-022) para que
# ``db/`` pueda interpolarlo sin importar hacia arriba (ADR-024). La lógica de
# dominio del dedupe —matching, marcado, cursor— se queda aquí. Los call-sites
# de ``services/`` siguen importándolo de este módulo, así que el guardrail
# textual de ``tests/test_dedup_guardrail.py`` sigue viendo lo que vigila.
from db.sql_fragments import exclude_duplicados_sql as exclude_duplicados_sql
from db.sql_fragments import periodo_canonico, plegar_organo
from observability.logging import get_logger
from observability.runtime_metrics import dedupe_marked_total, dedupe_match_rate
from services.normalization import normalize_company

log = get_logger(__name__)

CONFIANZA_EXACTA = 1.0
CONFIANZA_REVISION = 0.8


def normalize_organo(name: str | None) -> str | None:
    """Órgano plegado para matching: sin acentos, sin formas societarias, lower."""
    normalized = normalize_company(name)
    return normalized.lower() if normalized else None


def natural_expediente(id_externo: str) -> str:
    """Expediente nacional: el id natural sin el namespace de fuente (ADR-009)."""
    _, sep, rest = id_externo.partition(":")
    return rest if sep else id_externo


def _cpv4(cpv: str | None) -> str | None:
    if not cpv:
        return None
    digits = cpv.strip()[:4]
    return digits if len(digits) == 4 and digits.isdigit() else None


def match_key(organo: str | None, expediente: str, cpv: str | None) -> str | None:
    """Clave débil de matching; None si faltan órgano o expediente."""
    organo_norm = normalize_organo(organo)
    if not organo_norm or not expediente:
        return None
    return f"{organo_norm}|{expediente}|{_cpv4(cpv) or ''}"


def normalize_titulo(titulo: str | None) -> str | None:
    """Título plegado para matching de reemisiones; ``None`` si no hay título.

    Espeja ``db.sql_fragments.titulo_normalizado_sql`` (``lower(btrim(...))``),
    que es la definición que aplica la superficie pública. Las dos tienen que
    dar el mismo resultado o el detector marcaría pares que la proyección no
    colapsa —y al revés—, y nadie se enteraría hasta ver dos veces el mismo
    contrato en un hub.

    Diferencia conocida y aceptada: ``str.strip()`` retira también tabuladores
    y saltos de línea, mientras que ``btrim`` de Postgres solo retira espacios.
    Python pliega por tanto un pelo más, así que el detector puede proponer a
    revisión un par que el SQL no colapsa. Ese lado del error es el barato: una
    entrada de más en una cola humana, no un contrato escondido.
    """
    plegado = (titulo or "").strip().lower()
    return plegado or None


def republicacion_key(
    organo: str | None, titulo: str | None, cpv: str | None, *, periodo: str = ""
) -> str | None:
    """Clave de reemisión: órgano + CPV4 + año-mes + título. ``None`` si falta alguno.

    Es la clave que usa la superficie pública (``db.sql_fragments``), y **no**
    la de :func:`match_key`. El motivo está en el docstring de aquel módulo:
    tanto TED como PSCP acuñan un ``id_externo`` por anuncio y no por contrato,
    así que el expediente natural difiere precisamente en el caso que hay que
    detectar. Lo que se repite palabra por palabra es el título publicado.

    El órgano se pliega con :func:`db.sql_fragments.plegar_organo` —el gemelo
    exacto de ``organo_normalizado_sql``— y no con :func:`normalize_organo`, que
    además retira formas societarias. Antes se usaba el segundo, y eso hacía que
    el detector plegara **más** que el SQL: proponía a revisión pares que la
    proyección no colapsa. Con el gemelo, las dos definiciones no pueden
    divergir sin que se vea.

    ``periodo`` es el año-mes de :func:`db.sql_fragments.periodo_canonico`. Es
    opcional para que las pruebas puedan interrogar la clave sin fabricar
    fechas, pero el detector siempre lo pasa: sin él, un órgano que licita el
    mismo objeto todos los años produce una única clave para todas sus
    ediciones.
    """
    organo_norm = plegar_organo(organo)
    titulo_norm = normalize_titulo(titulo)
    if not organo_norm or not titulo_norm:
        return None
    return f"{organo_norm}|{_cpv4(cpv) or ''}|{periodo}|{titulo_norm}"


@dataclass
class DedupeResult:
    fuente: str
    evaluadas: int = 0
    confirmados: int = 0
    pendientes: int = 0
    detalles: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, int | str]:
        return {
            "fuente": self.fuente,
            "evaluadas": self.evaluadas,
            "confirmados": self.confirmados,
            "pendientes": self.pendientes,
        }


def _rango_canonico(row: dict[str, Any]) -> tuple[bool, str, str, str]:
    """Orden de preferencia de canónica; menor gana.

    Espeja ``db.sql_fragments._rango_canonico_sql`` campo a campo. Termina en
    ``id_externo`` —la clave primaria— para que el orden sea **total**: sin ese
    desempate, dos filas con las mismas fechas quedaban decididas por el orden
    de los argumentos, o sea por el orden en que la consulta devolvió las filas.
    Eso hacía que la canónica pudiera cambiar entre ejecuciones, y con ella la
    URL que el sitemap publica para ese contrato.
    """
    return (
        str(row.get("fuente")) != "placsp",
        str(row.get("fecha_publicacion") or "9999"),
        str(row.get("fecha_extraccion") or "9999"),
        str(row["id_externo"]),
    )


def _pick_canonical(a: dict[str, Any], b: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """(canónica, duplicada): PLACSP gana; si no, la más antigua; si no, la de id menor."""
    return (a, b) if _rango_canonico(a) <= _rango_canonico(b) else (b, a)


def detect_duplicates(*, fuente: str) -> DedupeResult:
    """Detecta duplicados cross-fuente entre las filas nuevas de ``fuente``.

    Pensado para engancharse en ``_post_ingestion`` del runner de conectores
    (fail-open en el llamador) o ejecutarse manualmente tras un backfill.
    """
    result = DedupeResult(fuente=fuente)
    cursor_source = f"dedupe_{fuente}"
    watermark = str((get_cursor(cursor_source) or {}).get("last_seen_updated") or "")

    with connect_read() as c:
        nuevas = rows_to_dicts(
            c.execute(
                "SELECT id_externo, organo_contratacion, cpv, fuente, "
                "       fecha_publicacion, fecha_extraccion "
                "FROM licitaciones WHERE fuente = %s AND fecha_extraccion > %s",
                (fuente, watermark),
            )
        )
        if not nuevas:
            return result
        # Índice expediente → filas del resto de fuentes. Un solo SELECT de
        # columnas ligeras por pasada; el coste por fila nueva es O(1).
        otras = rows_to_dicts(
            c.execute(
                "SELECT id_externo, organo_contratacion, cpv, fuente, "
                "       fecha_publicacion, fecha_extraccion "
                "FROM licitaciones WHERE fuente != %s",
                (fuente,),
            )
        )
    por_expediente: dict[str, list[dict[str, Any]]] = {}
    for row in otras:
        por_expediente.setdefault(natural_expediente(row["id_externo"]), []).append(row)

    marcas: list[tuple[str, str, str, float, str]] = []
    max_extraccion = watermark
    for row in nuevas:
        result.evaluadas += 1
        if (row.get("fecha_extraccion") or "") > max_extraccion:
            max_extraccion = str(row["fecha_extraccion"])
        expediente = natural_expediente(row["id_externo"])
        organo_norm = normalize_organo(row.get("organo_contratacion"))
        if not expediente or not organo_norm:
            continue
        for candidata in por_expediente.get(expediente, []):
            if normalize_organo(candidata.get("organo_contratacion")) != organo_norm:
                continue
            cpv_row, cpv_cand = _cpv4(row.get("cpv")), _cpv4(candidata.get("cpv"))
            if cpv_row and cpv_cand and cpv_row == cpv_cand:
                confianza, status = CONFIANZA_EXACTA, "confirmed"
            else:
                confianza, status = CONFIANZA_REVISION, "pending"
            canonica, duplicada = _pick_canonical(row, candidata)
            clave = match_key(row.get("organo_contratacion"), expediente, row.get("cpv")) or ""
            marcas.append(
                (duplicada["id_externo"], canonica["id_externo"], clave, confianza, status)
            )
            source_pair = "|".join(sorted((str(row["fuente"]), str(candidata["fuente"]))))
            dedupe_marked_total.labels(source_pair=source_pair, status=status).inc()
            if status == "confirmed":
                result.confirmados += 1
            else:
                result.pendientes += 1
            result.detalles.append(
                {
                    "duplicada": duplicada["id_externo"],
                    "canonica": canonica["id_externo"],
                    "confianza": confianza,
                    "status": status,
                }
            )

    if marcas:
        with connect() as c:
            c.executemany(
                "INSERT INTO licitaciones_duplicados "
                "(licitacion_id, canonical_id, clave_match, confianza, status) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT(licitacion_id) DO NOTHING",
                marcas,
            )
    if max_extraccion and max_extraccion != watermark:
        set_cursor(cursor_source, last_seen_updated=max_extraccion)
    if result.evaluadas:
        # Solo se actualiza cuando hubo filas nuevas: una pasada vacía no debe
        # arrastrar el gauge a 0 y disparar la alerta de banda en falso.
        rate = (result.confirmados + result.pendientes) / result.evaluadas
        dedupe_match_rate.labels(fuente=fuente).set(rate)
    if result.confirmados or result.pendientes:
        log.info("dedupe_detected", **result.as_dict())
    return result


def _clave_de_fila(row: dict[str, Any]) -> str | None:
    """Clave de reemisión de una fila, con su año-mes. ``None`` si no la tiene."""
    return republicacion_key(
        row.get("organo_contratacion"),
        row.get("titulo"),
        row.get("cpv"),
        periodo=periodo_canonico(row.get("fecha_publicacion"), row.get("fecha_extraccion")),
    )


def detect_republicaciones(*, fuente: str) -> DedupeResult:
    """Detecta reemisiones del mismo contrato entre las filas nuevas de ``fuente``.

    :func:`detect_duplicates` no las ve, y no por olvido: consulta candidatas
    con ``fuente != %s`` y empareja por expediente natural. Para dos filas de
    la misma fuente con el mismo expediente natural el ``id_externo`` sería el
    mismo —es ``fuente:expediente``— y el upsert las habría fundido en una. O
    sea que ese emparejamiento, aplicado a una sola fuente, no puede encontrar
    nada por construcción.

    Lo que sí ocurre es que la fuente acuñe un id **por anuncio**: TED da un
    ``publication-number`` nuevo a cada corrigendo y a cada adjudicación, y el
    conector de PSCP cae al ``id`` de la fila cuando el registro no trae
    ``codi_expedient``. Ahí el expediente natural difiere y el título no. De
    ahí :func:`republicacion_key`.

    **Todo lo que marca va como ``pending``**, nunca ``confirmed``. Coincidir
    en órgano, CPV4, año-mes y título es fuerte para decidir qué se publica —dos
    filas así sirven la misma página— pero no lo bastante para retirar un contrato de
    la cuota de mercado o del HHI sin que lo mire un humano: dos lotes de un
    acuerdo marco pueden compartir las tres cosas. El error de marcar de menos
    aquí lo tapa la proyección pública, que no depende de este job; el de
    marcar de más ensuciaría las métricas competitivas para siempre.

    **El índice de candidatas se filtra como la superficie pública.** Solo
    entran filas *publicables* —umbral de sustancia y sin duplicado confirmado,
    ver ``db/repositories/dedupe.py``— y de **cualquier** fuente, no solo de
    ``fuente``. Las dos cosas espejan lo que hace ``fila_canonica_sql``, y no
    hacerlo tenía consecuencias distintas: sin el filtro de publicabilidad el
    job podía proponer como canónica una fila que la superficie no publica, y en
    cuanto un humano confirmara el par el contrato desaparecía entero; sin
    abrir el índice a otras fuentes, los pares PLACSP↔PSCP que el SQL sí colapsa
    no llegaban nunca a la cola.

    Volumen: la primera pasada sobre una fuente sin cursor evalúa la fuente
    entera y puede encolar muchísima revisión (PSCP aporta ~566k filas). En
    régimen solo mira lo llegado desde el watermark, como el resto del módulo.
    El índice se acota además a los órganos de las filas nuevas: el diseño
    anterior materializaba la fuente entera —~1,7 M filas de PSCP como lista de
    dicts— en cada pasada con al menos una fila nueva.
    """
    result = DedupeResult(fuente=fuente)
    cursor_source = f"republicacion_{fuente}"
    watermark = str((get_cursor(cursor_source) or {}).get("last_seen_updated") or "")

    nuevas = dedupe_repo.filas_nuevas_de_fuente(fuente, watermark)
    if not nuevas:
        return result

    # Solo se indexa lo que puede emparejar con algo de esta pasada: las claves
    # de las filas nuevas acotan qué se guarda, y sus órganos acotan qué se pide.
    # Si no sale ninguna clave el índice queda vacío y no se marca nada, pero el
    # bucle de abajo se recorre igual: es el que mueve el watermark, y saltárselo
    # dejaría la pasada repitiendo las mismas filas para siempre.
    claves_buscadas = {clave for row in nuevas if (clave := _clave_de_fila(row))}
    organos = sorted({o for row in nuevas if (o := plegar_organo(row.get("organo_contratacion")))})

    por_clave: dict[str, list[dict[str, Any]]] = {}
    for row in dedupe_repo.iter_filas_publicables_de_organos(organos):
        clave = _clave_de_fila(row)
        if clave is not None and clave in claves_buscadas:
            por_clave.setdefault(clave, []).append(row)

    marcas: list[tuple[str, str, str, float, str]] = []
    max_extraccion = watermark
    for row in nuevas:
        result.evaluadas += 1
        if (row.get("fecha_extraccion") or "") > max_extraccion:
            max_extraccion = str(row["fecha_extraccion"])
        clave = _clave_de_fila(row)
        if not clave:
            continue
        grupo = por_clave.get(clave, [])
        # Se compara contra el grupo *menos la propia fila*, y no con
        # `len(grupo) < 2`: la fila nueva puede no ser publicable y por tanto no
        # estar en el índice, y ese es justo el caso en que hay que marcarla
        # (esconde la copia pobre y deja viva la buena).
        if not [gemela for gemela in grupo if gemela["id_externo"] != row["id_externo"]]:
            continue
        # La canónica se elige sobre el grupo entero y no par a par: con tres o
        # más reemisiones, decidir por pares dejaría a cada duplicada apuntando
        # a una canónica distinta según con quién se comparase.
        canonica = min(grupo, key=_rango_canonico)
        if canonica["id_externo"] == row["id_externo"]:
            continue
        marcas.append(
            (
                str(row["id_externo"]),
                str(canonica["id_externo"]),
                clave,
                CONFIANZA_REVISION,
                "pending",
            )
        )
        # El par puede ser cross-fuente desde que el índice no filtra por fuente:
        # la etiqueta tiene que decir el par real o la métrica mentiría.
        source_pair = "|".join(sorted((str(row["fuente"]), str(canonica["fuente"]))))
        dedupe_marked_total.labels(source_pair=source_pair, status="pending").inc()
        result.pendientes += 1
        result.detalles.append(
            {
                "duplicada": row["id_externo"],
                "canonica": canonica["id_externo"],
                "confianza": CONFIANZA_REVISION,
                "status": "pending",
            }
        )

    dedupe_repo.marcar_duplicados(marcas)
    if max_extraccion and max_extraccion != watermark:
        set_cursor(cursor_source, last_seen_updated=max_extraccion)
    if result.pendientes:
        log.info("dedupe_republicaciones_detected", **result.as_dict())
    return result


def review_pending(limit: int = 100) -> list[dict[str, Any]]:
    """Cola de revisión humana: matches con confianza < 1.0 sin resolver."""
    with connect_read() as c:
        return rows_to_dicts(
            c.execute(
                """
                SELECT d.licitacion_id, d.canonical_id, d.clave_match, d.confianza,
                       d.detectado_en, l.titulo, l.fuente,
                       lc.titulo AS titulo_canonica, lc.fuente AS fuente_canonica
                FROM licitaciones_duplicados d
                JOIN licitaciones l  ON l.id_externo  = d.licitacion_id
                JOIN licitaciones lc ON lc.id_externo = d.canonical_id
                WHERE d.status = 'pending'
                ORDER BY d.detectado_en LIMIT %s
                """,
                (max(1, min(int(limit), 500)),),
            )
        )


def resolve_pending(licitacion_id: str, *, accept: bool, resolved_by: str = "") -> bool:
    """Resuelve un match pendiente: aceptar lo confirma, rechazarlo lo descarta."""
    # resolved_at es TEXT (v39_licitaciones_duplicados) — castear explícitamente
    # evita el error de asignación timestamp→text.
    resolved_at_sql = "NOW()::text"
    with connect() as c:
        cur = c.execute(
            "UPDATE licitaciones_duplicados "  # noqa: S608 — resolved_at_sql es un fragmento constante
            f"SET status = %s, resolved_at = {resolved_at_sql}, resolved_by = %s "
            "WHERE licitacion_id = %s AND status = 'pending'",
            ("confirmed" if accept else "rejected", resolved_by, licitacion_id),
        )
        return bool(cur.rowcount)


def medir_solape(fuente_a: str = "pscp", fuente_b: str = "placsp") -> dict[str, Any]:
    """Mide el solape detectado entre dos fuentes (acceptance del RFC)."""
    with connect_read() as c:
        total_a = c.execute(
            "SELECT COUNT(*) FROM licitaciones WHERE fuente = %s", (fuente_a,)
        ).fetchone()[0]
        solapadas = c.execute(
            """
            SELECT COUNT(*) FROM licitaciones_duplicados d
            JOIN licitaciones l  ON l.id_externo  = d.licitacion_id
            JOIN licitaciones lc ON lc.id_externo = d.canonical_id
            WHERE d.status != 'rejected'
              AND ((l.fuente = %s AND lc.fuente = %s) OR (l.fuente = %s AND lc.fuente = %s))
            """,
            (fuente_a, fuente_b, fuente_b, fuente_a),
        ).fetchone()[0]
    pct = round(solapadas * 100.0 / total_a, 2) if total_a else 0.0
    return {"fuente": fuente_a, "total": total_a, "solapadas": solapadas, "solape_pct": pct}

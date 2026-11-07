"""Persistencia de fichas estructuradas de pliego."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts
from db.sql_fragments import iso_guard, tecnologia_tokens_sql
from shared.estados import abierta_sql

#: Fallos de una ficha que dependen de los **documentos** y no del extractor:
#: repetir la extracción con los mismos documentos da el mismo fallo, así que
#: solo vuelven a ser elegibles cuando un documento del expediente cambia
#: después del fallo. Son subcadenas de los mensajes que escribe
#: ``services/rag/fact_sheet.py`` (``_missing_pages_detail`` y ``_SIN_TEXTO``);
#: ``tests/test_unit_ficha_reintentos.py`` comprueba que siguen ahí.
FALLOS_DE_DOCUMENTOS: tuple[str, ...] = (
    "no referencia ningún pliego descargable",
    "ha publicado el pliego",
    "PLACSP no está respondiendo",
    "siguen en cola de procesado",
    "en un formato que todavía no",
    "sin capa de texto",
    "No se pudo extraer texto de los pliegos",
    "No hay texto por página",
)

#: Fallos del **proveedor** del modelo (credencial, modelo retirado, saturación,
#: tope de reloj): no dicen nada de la ficha, así que se reintentan aunque la
#: versión del extractor no haya cambiado, como mucho una vez cada
#: ``reintento_dias``. Subcadenas de ``llm/providers/__init__.py``,
#: ``llm/client.py`` y ``services/rag/fact_sheet.py``.
FALLOS_DEL_PROVEEDOR: tuple[str, ...] = (
    "El proveedor rechazó la API key",
    "El proveedor no sirve el modelo",
    "no disponible. Modelos soportados",
    "devolvió una respuesta vacía",
    "superó el tope de",
)


def _patrones_like(subcadenas: Sequence[str]) -> list[str]:
    """``%subcadena%`` para ``LIKE ANY``; ninguna lleva ``%`` ni ``_`` propios."""
    return [f"%{s}%" for s in subcadenas]


class TenderFactSheetsRepository:
    """Repositorio fino para ``tender_fact_sheets``."""

    def list_pending_licitaciones(
        self,
        *,
        extraction_version: str,
        limit: int = 20,
        casan_regla: Sequence[str] = (),
        reintento_dias: int = 7,
        ahora: datetime | None = None,
    ) -> list[str]:
        """Licitaciones con páginas persistidas y pendientes de una ficha
        vigente. "Pendiente" cubre tres casos, en este orden de prioridad
        (el lote LLM es el caro, así que nunca-intentadas van primero):

        1. Sin fila en ``tender_fact_sheets`` -- nunca se procesó. Dentro de
           este grupo, tech-relevantes primero (mismo criterio que
           ``DocumentosRepository.list_pendientes``).
        2. Fila con ``extraction_version`` distinta a la vigente y
           ``status != 'failed'`` -- un bump del extractor (ej. la pregunta
           añadió ``technologies`` en v2) la deja stale.
        3. ``status = 'failed'`` que **merece otro intento**, por
           ``updated_at ASC``. Solo si la licitación sigue abierta con plazo
           o tiene oportunidad o favorito (demanda 0-1): cerrada y sin nadie
           mirándola, otra ficha fallida no la va a abrir nadie. Y solo si el
           fallo puede no repetirse:

           - de los documentos (:data:`FALLOS_DE_DOCUMENTOS`: sin pliego
             descargable, PLACSP aún no lo ha publicado…): cuando algún
             documento del expediente cambió después del fallo. Es lo que
             espera, y la versión del extractor no lo arregla;
           - de una versión anterior del extractor: una vez por versión. La
             extracción reescribe la fila con la vigente, así que si vuelve a
             fallar ya no entra por aquí;
           - del proveedor (:data:`FALLOS_DEL_PROVEEDOR`) con la versión
             vigente: una vez cada ``reintento_dias``.

           El resto con la versión vigente (el modelo devolvió JSON roto o un
           objeto inválido para *ese* pliego) no se reintenta hasta el
           siguiente bump o hasta que cambien sus documentos.

           shortcut: sin columna ``attempts``, el tope de intentos sale de
           la versión, de los documentos y del plazo (≤ plazo restante /
           ``reintento_dias`` para los del proveedor); con una migración que
           añada el contador, el tope pasaría a ser explícito.

        Por encima de esos tres casos manda la **demanda**: oportunidad
        abierta (0), favorito (1), ``casan_regla`` (2), abierta con plazo que
        encaja con las tecnologías de alguna organización (3), abierta con
        plazo (4) y el resto (5). ``casan_regla`` son los ``id_externo``
        abiertos con plazo vigente que casan con alguna regla de vigilancia
        activa (D52 del plan 2026-10). Llegan ya calculados porque el casado
        vive en ``services/watchlist_rules.py`` y ``db/`` no puede importarlo:
        aquí solo se ordena con ellos.

        El **encaje tecnológico** es el del Radar: algún código de
        ``OrganizationSettings.tecnologias`` está en el CSV de ``tecnologia``
        (:func:`db.sql_fragments.tecnologia_tokens_sql`, la expresión del
        filtro de ámbito) o en ``ml_tecnologias``, que el trigger de ``v136``
        deriva de ``licitacion_tecnologia_score`` (clasificador, LLM y señal
        del pliego) — las dos señales de
        :func:`db.sql_fragments.universo_tecnologico_sql`. Las tecnologías de
        todas las organizaciones se juntan antes en un único array, así que el
        coste por candidata no crece con el número de organizaciones: el
        recorrido de ``organizations`` es uno por lote.

        «Abierta con plazo» es la de ``scoring_candidates`` y de
        ``services.watchlist_rules._clausulas_universo_puntuable``: estado no
        terminal y ``fecha_limite`` de hoy en adelante. ``ahora`` fija el reloj
        (hoy y el corte de ``reintento_dias``) para los tests.
        """
        ahora = ahora or datetime.now(UTC)
        hoy_iso = ahora.date().isoformat()
        corte_reintento = (ahora - timedelta(days=max(0, int(reintento_dias)))).isoformat()
        tokens_tec = tecnologia_tokens_sql("b.tecnologia")
        tokens_ml = tecnologia_tokens_sql("b.ml_tecnologias")
        with connect_read() as c:
            rows = c.execute(
                "WITH tecnologias_org AS ("
                # Todas las tecnologías declaradas por alguna organización, en
                # un array. `pg_input_is_valid` dentro del CASE: un
                # `settings_json` corrupto no puede tumbar el lote nocturno
                # (OrganizationRepository.get_settings lo lee como `{}`).
                "  SELECT COALESCE(array_agg(DISTINCT upper(trim(t.codigo))), "
                "                  '{}'::text[]) AS codigos "
                "  FROM organizations o "
                "  CROSS JOIN LATERAL (SELECT CASE "
                "    WHEN pg_input_is_valid(o.settings_json, 'jsonb') "
                "    THEN o.settings_json::jsonb -> 'tecnologias' END AS v) s "
                "  CROSS JOIN LATERAL jsonb_array_elements_text(CASE "
                "    WHEN jsonb_typeof(s.v) = 'array' THEN s.v ELSE '[]'::jsonb END) "
                "    AS t(codigo) "
                "  WHERE o.settings_json LIKE '%%\"tecnologias\"%%'"
                "), candidatos AS ("
                "  SELECT DISTINCT d.licitacion_id FROM documento_pages dp "
                # Un expediente con solo páginas de acta no tiene pliego que
                # extraer (spec de las puntuaciones del acta, §3.3).
                "  JOIN documentos d ON d.id = dp.documento_id AND d.tipo <> 'acta'"
                "), base AS ("
                "  SELECT c.licitacion_id, l.tecnologia, l.ml_tecnologias, "
                "  tf.licitacion_id IS NULL AS sin_ficha, tf.status, "
                "  tf.extraction_version, COALESCE(tf.error_detail, '') AS error_detail, "
                "  tf.updated_at, "
                f"  ({abierta_sql('l.estado')} AND {iso_guard('l.fecha_limite')} "
                "    AND l.fecha_limite >= %s) AS abierta "
                "  FROM candidatos c "
                "  JOIN licitaciones l ON l.id_externo = c.licitacion_id "
                "  LEFT JOIN tender_fact_sheets tf ON tf.licitacion_id = c.licitacion_id "
                "  WHERE tf.licitacion_id IS NULL "
                "     OR tf.status = 'failed' "
                "     OR tf.extraction_version != %s"
                "), clasificados AS ("
                "  SELECT b.*, "
                "  CASE "
                "    WHEN b.sin_ficha THEN 0 "
                "    WHEN b.status != 'failed' THEN 1 "
                "    ELSE 2 "
                "  END AS tier, "
                "  CASE "
                "    WHEN b.tecnologia IS NOT NULL AND b.tecnologia != '' THEN 0 "
                "    WHEN b.ml_tecnologias IS NOT NULL AND b.ml_tecnologias != '' THEN 1 "
                "    ELSE 2 "
                "  END AS tech_priority, "
                # Demanda real primero: un expediente que alguien convirtió en
                # oportunidad o marcó como favorito es el que va a abrir la
                # pestaña Pliego hoy. Con 25 fichas por pasada frente a cientos de
                # documentos descargados, el orden decide si la promesa «qué pide
                # el pliego» se cumple para quien la está mirando o para nadie.
                "  CASE WHEN EXISTS (SELECT 1 FROM pursuits p "
                "        WHERE p.licitacion_id = b.licitacion_id "
                "        AND p.status NOT IN ('won', 'lost', 'withdrawn')) THEN 0 "
                "       WHEN EXISTS (SELECT 1 FROM watchlist_items w "
                "        WHERE w.id_externo = b.licitacion_id) THEN 1 "
                # Lo abierto que casa con una regla de vigilancia es lo que el
                # resumen diario va a enseñar: sin ficha, el correo no puede
                # decir qué pide el pliego (D52, B3 del plan 2026-10).
                "       WHEN b.licitacion_id = ANY(%s::text[]) THEN 2 "
                # Lo abierto que el Radar de alguna organización le enseña por
                # su ámbito tecnológico: con una regla por organización como
                # mucho, el nivel 2 casi siempre está vacío.
                "       WHEN b.abierta AND ("
                f"         (b.tecnologia IS NOT NULL AND {tokens_tec} && tec_org.codigos) "
                f"         OR (b.ml_tecnologias IS NOT NULL AND {tokens_ml} && tec_org.codigos)"
                "       ) THEN 3 "
                # Y lo abierto antes que lo cerrado: una ficha de un expediente
                # adjudicado no la va a abrir nadie para decidir si se presenta.
                "       WHEN b.abierta THEN 4 "
                "       ELSE 5 END AS demanda "
                "  FROM base b CROSS JOIN tecnologias_org tec_org"
                ") "
                "SELECT licitacion_id FROM clasificados k "
                "WHERE k.tier <> 2 OR ((k.abierta OR k.demanda <= 1) AND CASE "
                "  WHEN k.error_detail LIKE ANY(%s::text[]) THEN EXISTS ("
                "    SELECT 1 FROM documentos d WHERE d.licitacion_id = k.licitacion_id "
                "    AND d.tipo <> 'acta' AND d.updated_at > k.updated_at) "
                "  WHEN k.extraction_version != %s THEN TRUE "
                "  ELSE k.error_detail LIKE ANY(%s::text[]) AND k.updated_at < %s "
                "END) "
                # tech_priority solo desempata dentro del tier 0 (nunca-intentadas):
                # en tier 1/2 debe ser updated_at ASC puro, o un backlog de failed/
                # stale tech-relevantes por encima del límite del batch deja
                # bloqueadas para siempre justo las licitaciones sin ninguna señal
                # de tecnología todavía -- las que este selector existe para descubrir.
                # `demanda` va antes que el tier: una ficha stale de una oportunidad
                # abierta importa más que una nunca intentada que nadie mira.
                "ORDER BY demanda, tier, CASE WHEN tier = 0 THEN tech_priority ELSE 0 END, "
                "updated_at ASC, licitacion_id "
                "LIMIT %s",
                (
                    hoy_iso,
                    extraction_version,
                    list(casan_regla),
                    _patrones_like(FALLOS_DE_DOCUMENTOS),
                    extraction_version,
                    _patrones_like(FALLOS_DEL_PROVEEDOR),
                    corte_reintento,
                    max(1, min(int(limit), 200)),
                ),
            ).fetchall()
            return [str(row[0]) for row in rows]

    def list_candidatas_golden(
        self, *, por_grupo: int = 15, fuente: str | None = None
    ) -> list[dict[str, Any]]:
        """Expedientes con texto de pliego, para elegir los casos del golden.

        Lo consume ``scripts/capturar_ficha_golden.py --listar``. Entra todo
        expediente con alguna página de texto, **tenga ficha o no**: los que no
        la tienen, o la tienen ``failed``, son justo donde hay que medir lo que
        la ficha omite (``docs/plans/2026-10-eval-ficha-pliego.md`` §3).

        El tope es **por fuente y grupo** (``sin_ficha``, ``fallida``,
        ``pobre`` con menos de cinco hechos, ``rica``), no global: con un
        ``LIMIT`` sobre la lista ordenada por fuente, la primera fuente la
        llenaba entera y ni las demás ni las fichas ricas llegaban a verse.
        ``total_grupo`` dice cuántas hay en el grupo, se enseñen o no. Dentro
        de cada grupo, primero las de más hechos y, a igualdad, las de más
        páginas.

        ``lotes`` y ``formulas`` salen del JSON de la ficha y valen 0 si no hay
        ficha, si no trae datos o si la clave no es una lista: el listado sirve
        para elegir, no para validar la fila.
        """
        with connect_read() as c:
            cur = c.execute(
                "WITH paginas AS ("
                "  SELECT d.licitacion_id, "
                "         COUNT(DISTINCT d.id) AS documentos, "
                "         COUNT(*) AS paginas, "
                "         COUNT(*) FILTER (WHERE dp.ocr) AS paginas_ocr "
                "  FROM documento_pages dp "
                "  JOIN documentos d ON d.id = dp.documento_id "
                # `octet_length` lee el tamaño sin descomprimir el texto de
                # cada página, que es lo que haría compararlo con ''.
                # Las páginas del acta no son pliego (spec §3.3).
                "  WHERE octet_length(dp.texto) > 0 AND d.tipo <> 'acta' "
                "  GROUP BY d.licitacion_id"
                "), candidatas AS ("
                "  SELECT p.licitacion_id, l.fuente, p.documentos, p.paginas, p.paginas_ocr, "
                "         tf.status, tf.extraction_version, tf.field_count, "
                "         CASE WHEN jsonb_typeof(f.datos -> 'lots') = 'array' "
                "              THEN jsonb_array_length(f.datos -> 'lots') ELSE 0 END AS lotes, "
                "         CASE WHEN jsonb_typeof(f.datos -> 'price_formula') = 'array' "
                "              THEN jsonb_array_length(f.datos -> 'price_formula') ELSE 0 END "
                "           AS formulas, "
                "         CASE WHEN tf.licitacion_id IS NULL THEN 'sin_ficha' "
                "              WHEN tf.status = 'failed' THEN 'fallida' "
                "              WHEN tf.field_count < 5 THEN 'pobre' "
                "              ELSE 'rica' END AS grupo "
                "  FROM paginas p "
                "  JOIN licitaciones l ON l.id_externo = p.licitacion_id "
                "  LEFT JOIN tender_fact_sheets tf ON tf.licitacion_id = p.licitacion_id "
                # `data_json` es `text`: se convierte aquí una sola vez, y una
                # cadena vacía se trata como «sin datos» en vez de romper el cast.
                "  LEFT JOIN LATERAL ("
                "    SELECT NULLIF(tf.data_json, '')::jsonb AS datos"
                "  ) f ON TRUE "
                "  WHERE (%s::text IS NULL OR l.fuente = %s)"
                "), numeradas AS ("
                "  SELECT c.*, "
                "         ROW_NUMBER() OVER ("
                "           PARTITION BY c.fuente, c.grupo "
                "           ORDER BY COALESCE(c.field_count, 0) DESC, c.paginas DESC, c.licitacion_id"
                "         ) AS orden, "
                "         COUNT(*) OVER (PARTITION BY c.fuente, c.grupo) AS total_grupo "
                "  FROM candidatas c"
                ") "
                "SELECT licitacion_id, fuente, grupo, documentos, paginas, paginas_ocr, status, "
                "       extraction_version, field_count, lotes, formulas, total_grupo "
                "FROM numeradas "
                "WHERE orden <= %s "
                "ORDER BY fuente, grupo, orden",
                (fuente, fuente, max(1, min(int(por_grupo), 200))),
            )
            return rows_to_dicts(cur)

    def get(self, licitacion_id: str) -> dict[str, Any] | None:
        """Ficha persistida; ``facts`` se devuelve como objeto Python."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT licitacion_id, status, extraction_version, model, data_json, "
                "field_count, evidence_count, error_detail, extracted_at, updated_at "
                "FROM tender_fact_sheets WHERE licitacion_id = %s",
                (licitacion_id,),
            )
            rows = rows_to_dicts(cur)
        if not rows:
            return None
        row = rows[0]
        raw = row.pop("data_json", None)
        row["facts"] = json.loads(str(raw)) if raw else None
        return row

    def get_many(self, licitacion_ids: list[str]) -> dict[str, dict[str, object]]:
        """Las fichas de varias licitaciones en una consulta, por ``licitacion_id``.

        Misma forma por fila que :meth:`get`. Las que no tienen ficha no
        aparecen. Existe para el resumen diario (B3 del plan 2026-10), que
        enseña la solvencia de cada licitación del correo: una consulta por
        licitación sería un N+1 por destinatario.
        """
        if not licitacion_ids:
            return {}
        with connect_read() as c:
            cur = c.execute(
                "SELECT licitacion_id, status, extraction_version, model, data_json, "
                "field_count, evidence_count, error_detail, extracted_at, updated_at "
                "FROM tender_fact_sheets WHERE licitacion_id = ANY(%s)",
                (list(licitacion_ids),),
            )
            rows = rows_to_dicts(cur)
        fichas: dict[str, dict[str, object]] = {}
        for row in rows:
            raw = row.pop("data_json", None)
            row["facts"] = json.loads(str(raw)) if raw else None
            fichas[str(row["licitacion_id"])] = row
        return fichas

    def upsert(
        self,
        *,
        licitacion_id: str,
        status: str,
        extraction_version: str,
        model: str | None,
        facts: dict[str, Any] | None,
        field_count: int,
        evidence_count: int,
        error_detail: str | None = None,
    ) -> None:
        """Inserta o reemplaza de forma idempotente la ficha vigente.

        Un ``failed`` **nunca** pisa una ficha ``extracted``/``needs_review``: la
        ficha es dato compartido entre organizaciones y una regeneración fallida
        (presupuesto LLM agotado, proveedor caído) no es motivo para borrar la
        buena. El fallo queda en el log de quien lo provocó; la ficha vieja
        sigue siendo candidata a reextraerse por versión.
        """
        now = now_utc_iso()
        data_json = (
            json.dumps(facts, ensure_ascii=False, separators=(",", ":"))
            if facts is not None
            else None
        )
        extracted_at = now if status in ("extracted", "needs_review") else None
        with connect() as c:
            c.execute(
                "INSERT INTO tender_fact_sheets "
                "(licitacion_id, status, extraction_version, model, data_json, "
                "field_count, evidence_count, error_detail, extracted_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT(licitacion_id) DO UPDATE SET "
                "status=excluded.status, extraction_version=excluded.extraction_version, "
                "model=excluded.model, data_json=excluded.data_json, "
                "field_count=excluded.field_count, evidence_count=excluded.evidence_count, "
                "error_detail=excluded.error_detail, extracted_at=excluded.extracted_at, "
                "updated_at=excluded.updated_at "
                "WHERE NOT (excluded.status = 'failed' "
                "AND tender_fact_sheets.status IN ('extracted', 'needs_review'))",
                (
                    licitacion_id,
                    status,
                    extraction_version,
                    model,
                    data_json,
                    field_count,
                    evidence_count,
                    error_detail,
                    extracted_at,
                    now,
                ),
            )

"""Lecturas de ``licitaciones`` para el clasificador: etiquetado, scores y drift."""

from __future__ import annotations

import json
from typing import Final

from sqlalchemy import select

from db.database import connect_read
from db.models import compile_query, licitacion_tecnologia_score
from db.repositories.base import cota_hasta, rows_to_dicts, typed_rows
from db.repositories.feedback import FUENTE_REVISION_TI, FUENTES_HUMANAS
from db.repositories.licitaciones.filas import (
    CandidatoEtiquetadoRow,
    DriftRow,
    TechScoreRow,
    ZonaIncertidumbreRow,
)
from observability.logging import get_logger

# El nombre de antes de partir el módulo: `logger` sale en cada línea de log.
log = get_logger("db.repositories.licitaciones")


#: Prefijo de ``ml_feedback.source`` con el que se guardan los reportes de dato
#: (F6.2). Vive aquí y no en ``services/`` porque quien tiene que conocerlo es el
#: SQL que decide qué sigue sin etiquetar; ``services.reportes_dato`` lo importa.
PREFIJO_REPORTE: Final = "reporte:"


def etiqueta_humana(
    source: str, relevante: int | None, tecnologia: str | None, secundarias: str | None
) -> str | None:
    """CSV de familias de una fila humana, o ``None`` si no se pronuncia.

    ``""`` es un negativo de verdad, y solo la produce ``revision_ti``: su
    `relevante` es «es TI», así que una fila suya sin tecnología sí es un
    pronunciamiento genuino (ninguna familia). Una fila heredada (cualquier
    ``source`` distinto de ``revision_ti``) sin tecnología **nunca** se
    pronuncia, sea cual sea su `relevante`: antes del plan de tres niveles
    `relevante` significaba «es SAP», no «es TI», así que ni un
    `relevante=0` ni un `relevante=1` sin tecnología dicen nada sobre las
    familias -- de ahí que `relevante` no entre en la condición de abajo.
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
    if not etiquetas and source != FUENTE_REVISION_TI:
        return None
    return ",".join(dict.fromkeys(e for e in etiquetas if e))


class MlMixin:
    """Lecturas que alimentan el entrenamiento y la vigilancia del modelo."""

    def get_text_for_ml(self, id_externo: str) -> tuple[str, str, str | None] | None:
        """Devuelve (titulo, descripcion, tecnologia) o None."""
        with connect_read() as c:
            row = c.execute(
                "SELECT titulo, descripcion, tecnologia FROM licitaciones WHERE id_externo = %s",
                (id_externo,),
            ).fetchone()
        return (str(row[0] or ""), str(row[1] or ""), row[2]) if row else None

    def get_unlabelled_candidates(self, limit: int = 500) -> list[CandidatoEtiquetadoRow]:
        """Licitaciones sin etiqueta humana en ml_feedback, para active learning.

        «Sin etiquetar» significa **sin etiqueta**, no «sin fila»:
        ``ml_feedback`` es también la cola de los reportes de dato
        (``services/reportes_dato.py``, que escribe ``source = 'reporte:<tipo>'``),
        y sin el predicado cualquier usuario sacaba un expediente de la cola de
        etiquetado con sólo reportarlo.

        El filtro excluye el prefijo de reporte y **no** compara con ``'human'``:
        el job de LLM escribe ``llm_batch`` precisamente para vaciar esta cola
        sin realimentar al modelo (``scheduler/jobs/llm_tech_labeling.py``), así
        que exigir ``human`` habría devuelto a la cola todo lo que ya etiquetó.
        """
        with connect_read() as c:
            cur = c.execute(
                "SELECT l.id_externo, l.titulo, l.descripcion, l.cpv, l.importe, "
                "l.organo_contratacion, l.ccaa, l.fecha_publicacion, l.url, "
                "l.tecnologia, l.ml_tecnologias, l.ml_proba_max, l.ml_tech_principal "
                "FROM licitaciones l "
                "LEFT JOIN ml_feedback f "
                f"  ON l.id_externo = f.expediente AND f.source NOT LIKE '{PREFIJO_REPORTE}%%' "
                "WHERE f.expediente IS NULL "
                "ORDER BY l.fecha_publicacion DESC LIMIT %s",
                (limit,),
            )
            return typed_rows(CandidatoEtiquetadoRow, rows_to_dicts(cur))

    def etiquetas_tecnologia_no_circulares(self) -> dict[str, dict[str, str | None]]:
        """Etiquetas de tecnología **independientes del regex de keywords**.

        El clasificador multi-etiqueta se entrenaba sobre la columna
        ``licitaciones.tecnologia``, que la producen los conectores llamando a
        ``matches_technology(titulo, ...)``: el mismo regex aplicado al mismo
        texto que ve el modelo. ``Y[:, j] == 1`` era entonces una función
        determinista y perfectamente aprendible del propio input, así que todas
        las métricas medían cuánto **imita** el modelo al regex, no cuánta
        tecnología detecta.

        Este método aporta las dos fuentes que sí son independientes, para que
        ``services.ml.tech_classifier._resolver_label_column`` las priorice sobre
        las keywords:

        - ``tecnologia_humana``: CSV desde el feedback humano más reciente de
          cada expediente (``ml_feedback`` con ``source`` en
          :data:`db.repositories.feedback.FUENTES_HUMANAS` — ``revision_ti``
          desde el plan de clasificación en tres niveles, y ``human``,
          histórico), uniendo ``tecnologia`` y el JSON de
          ``tecnologias_secundarias`` vía :func:`etiqueta_humana`. Una fila
          ``human`` sin tecnología **no** se pronuncia, sea cual sea su
          ``relevante`` (0 o 1): `relevante` significaba «es SAP», no «es
          TI», así que esa fila no dice nada sobre las familias.
        - ``tecnologia_llm``: CSV ``TECNOLOGIA:score`` desde
          ``licitacion_tecnologia_pliego`` con ``method IN ('llm_metadata',
          'llm')``. Solo la **versión vigente** de cada ``(licitación,
          method)`` —la ``signal_version`` de su fila más reciente por
          ``computed_at``—: un cambio de prompt o de modelo no puede mezclar
          respuestas viejas y nuevas en la misma etiqueta.
        - El marcador de nivel 1 (``__es_ti__``/``__no_es_ti__``, plan de
          clasificación en tres niveles) vive DENTRO de ese mismo
          ``method='llm_metadata'`` -- junto a las familias, en la misma
          fila de ``scores`` de ``upsert_signals`` -- porque la CHECK
          ``ck_lic_tec_pliego_method`` de la tabla no admite un ``method``
          propio sin migración (F5). Cuenta como pronunciamiento (igual que
          ``__no_signal__``) pero nunca como etiqueta de familia: contestar
          si el contrato es TI no es nombrar una tecnología. Si la MISMA
          versión vigente de ese ``method`` también trae
          ``__sin_evidencia__``, el grupo entero (licitación, method) NO se
          pronuncia aunque el marcador esté ahí -- son respuestas
          independientes, pero «sin evidencia» manda dentro de su propio
          ``method``; el agrupado es por ``(licitación, method)`` y no solo
          por licitación precisamente para que esto no tape lo que diga
          OTRO ``method`` de la misma licitación (p. ej. la ficha de pliego,
          ``llm``).

        Convención de ausencia, que es la parte que importa para no inventar
        etiquetas:

        - ``None`` → esa fuente **no se pronunció** sobre la licitación. Para
          el LLM incluye el sentinel ``__sin_evidencia__``: afirmó tecnologías
          y ninguna sostuvo su cita, así que no hay respuesta que creer (y
          arrastra consigo el marcador de nivel 1 si lo hubiera, ver arriba).
          Para el humano, una fila heredada sin tecnología (ver
          :func:`etiqueta_humana`) — ausente del dict, no con valor ``None``.
        - ``""`` (cadena vacía) → la fuente la revisó y declaró que no tiene
          ninguna tecnología. Es un negativo de verdad, no un desconocido.
          Para el LLM eso son las filas con el sentinel ``__no_signal__`` --
          y, sin más familias en su misma versión vigente, también las del
          marcador de nivel 1 solo (``__es_ti__``/``__no_es_ti__``) --; para
          el humano, únicamente una fila ``revision_ti`` sin tecnología
          —nunca una ``human`` heredada, sea cual sea su ``relevante``.

        Returns:
            ``{id_externo: {"tecnologia_humana": ..., "tecnologia_llm": ...}}``
            con solo las licitaciones sobre las que alguna fuente se pronunció.
        """
        from db.repositories.tecnologia_pliego import (
            ES_TI_SENTINEL,
            NO_ES_TI_SENTINEL,
            NO_SIGNAL_SENTINEL,
            SIN_EVIDENCIA_SENTINEL,
        )

        salida: dict[str, dict[str, str | None]] = {}
        with connect_read() as c:
            # Feedback humano: la fila más reciente por expediente. ml_feedback
            # no tiene unique por expediente, así que sin el DISTINCT ON la
            # etiqueta dependería del orden de filas — no determinista.
            cur = c.execute(
                "SELECT DISTINCT ON (expediente) expediente, source, relevante, "
                "tecnologia, tecnologias_secundarias "
                "FROM ml_feedback WHERE source = ANY(%s) "
                "ORDER BY expediente, created_at DESC, id DESC",
                (list(FUENTES_HUMANAS),),
            )
            for expediente, source, relevante, tecnologia, secundarias in cur.fetchall():
                etiqueta = etiqueta_humana(
                    str(source),
                    relevante,
                    str(tecnologia) if tecnologia is not None else None,
                    str(secundarias) if secundarias is not None else None,
                )
                if etiqueta is None:
                    continue
                salida.setdefault(str(expediente), {})["tecnologia_humana"] = etiqueta

            # Señal LLM por pliego, con su score para que el consumidor filtre.
            # Sin JOIN: `licitacion_tecnologia_pliego.licitacion_id` ES el
            # `id_externo` (así lo declara su propia FK), y `licitaciones` no
            # tiene columna `id`. El `JOIN licitaciones l ON l.id =
            # p.licitacion_id` que había aquí lanzaba `UndefinedColumn` en
            # cada llamada; `train_from_db` lo capturaba y degradaba a
            # etiquetas circulares con un warning, así que el fallo nunca se
            # vio como fallo — solo como un clasificador que imitaba el regex.
            #
            # Versión vigente por (licitación, method): `upsert_signals`
            # reescribe todas las filas de un method con la versión nueva, pero
            # la lectura no se apoya en eso — un backfill o un escritor nuevo
            # bastan para que convivan dos prompts. Por method y no por
            # licitación: la ficha de pliego (`llm`) y la metadata
            # (`llm_metadata`) son carriles independientes. `computed_at` es
            # texto ISO 8601 en UTC (`now_utc_iso`), así que ordena igual que el
            # instante; la versión desempata para que el resultado no dependa
            # del plan. Se trae `method` (no solo `licitacion_id`) porque el
            # agrupado de abajo es por `(licitación, method)`: el marcador de
            # nivel 1 y `__sin_evidencia__` pueden convivir en la misma
            # versión vigente del MISMO `method` (van en la misma llamada de
            # `upsert_signals`, ver su docstring), y "sin evidencia" tiene que
            # ganar ahí sin tapar lo que diga el OTRO `method`.
            cur = c.execute(
                "SELECT licitacion_id, method, tecnologia, score FROM ("
                "  SELECT p.licitacion_id, p.method, p.tecnologia, p.score, p.signal_version, "
                "         FIRST_VALUE(p.signal_version) OVER ("
                "           PARTITION BY p.licitacion_id, p.method "
                "           ORDER BY p.computed_at DESC, p.signal_version DESC"
                "         ) AS version_vigente "
                "  FROM licitacion_tecnologia_pliego p "
                "  WHERE p.method IN ('llm_metadata', 'llm')"
                ") vigentes "
                "WHERE signal_version = version_vigente"
            )
            grupos: dict[tuple[str, str], list[tuple[str, float]]] = {}
            for id_externo, method, tecnologia, score in cur.fetchall():
                clave = (str(id_externo), str(method))
                grupos.setdefault(clave, []).append((str(tecnologia), float(score or 0.0)))

            por_licitacion: dict[str, list[str]] = {}
            revisadas: set[str] = set()
            for (id_externo, _method), filas_grupo in grupos.items():
                tecnologias = {tech for tech, _ in filas_grupo}
                # "Sin evidencia" gana dentro de SU (licitación, method): si
                # este grupo trae `__sin_evidencia__`, no se pronuncia entero
                # -- ni aunque también traiga el marcador de nivel 1, que
                # vive en el mismo method por la CHECK de la tabla (ver
                # arriba). Un `method` distinto de la MISMA licitación (otro
                # grupo) sigue contando aparte.
                if SIN_EVIDENCIA_SENTINEL in tecnologias:
                    continue
                revisadas.add(id_externo)
                for tech, score in filas_grupo:
                    if tech in (NO_SIGNAL_SENTINEL, ES_TI_SENTINEL, NO_ES_TI_SENTINEL):
                        continue
                    por_licitacion.setdefault(id_externo, []).append(
                        f"{tech.strip().upper()}:{score:.4f}"
                    )
            for licitacion_id in revisadas:
                salida.setdefault(licitacion_id, {})["tecnologia_llm"] = ",".join(
                    por_licitacion.get(licitacion_id, [])
                )

        log.info(
            "etiquetas_tecnologia_no_circulares",
            n_licitaciones=len(salida),
            n_humanas=sum(1 for v in salida.values() if v.get("tecnologia_humana") is not None),
            n_llm=sum(1 for v in salida.values() if v.get("tecnologia_llm") is not None),
        )
        return salida

    def get_unlabelled_random(self, limit: int = 20) -> list[CandidatoEtiquetadoRow]:
        """Muestra aleatoria sin etiquetar. Mismo criterio que
        :meth:`get_unlabelled_candidates`: se excluyen las etiquetas (humanas y
        de LLM), no los reportes de dato."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT l.id_externo, l.titulo, l.descripcion, l.cpv, l.importe, "
                "l.organo_contratacion, l.ccaa, l.fecha_publicacion, l.url, "
                "l.tecnologia, l.ml_tecnologias, l.ml_proba_max, l.ml_tech_principal "
                "FROM licitaciones l "
                "LEFT JOIN ml_feedback f "
                f"  ON l.id_externo = f.expediente AND f.source NOT LIKE '{PREFIJO_REPORTE}%%' "
                "WHERE f.expediente IS NULL "
                "ORDER BY RANDOM() LIMIT %s",
                (limit,),
            )
            return typed_rows(CandidatoEtiquetadoRow, rows_to_dicts(cur))

    def tech_scores_for(self, id_externo: str) -> list[TechScoreRow]:
        """Devuelve scores por tecnología desde ``licitacion_tecnologia_score``."""
        stmt = (
            select(
                licitacion_tecnologia_score.c.tecnologia,
                licitacion_tecnologia_score.c.probabilidad,
                licitacion_tecnologia_score.c.threshold_aplicado,
                licitacion_tecnologia_score.c.computed_at,
            )
            .where(licitacion_tecnologia_score.c.licitacion_id == id_externo)
            .order_by(licitacion_tecnologia_score.c.probabilidad.desc())
        )
        sql, params = compile_query(stmt)
        with connect_read() as c:
            return typed_rows(TechScoreRow, rows_to_dicts(c.execute(sql, params)))

    def load_uncertainty_zone(self, lo: float, hi: float, limit: int) -> list[ZonaIncertidumbreRow]:
        """Licitaciones con ``ml_proba`` en zona de incertidumbre (active learning)."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT id_externo, titulo, descripcion, organo_contratacion, importe, "
                "fecha_publicacion, cpv, ml_proba FROM licitaciones "
                "WHERE ml_proba IS NOT NULL AND ml_proba BETWEEN %s AND %s "
                "ORDER BY (importe IS NULL), importe DESC, ml_proba LIMIT %s",
                (lo, hi, limit),
            )
            return typed_rows(ZonaIncertidumbreRow, rows_to_dicts(cur))

    def load_drift_window(self, start: str, end: str) -> list[DriftRow]:
        """Carga licitaciones de un rango de fechas para drift detection (ambos días incluidos)."""
        hasta, valor_hasta = cota_hasta("fecha_publicacion", end)
        with connect_read() as c:
            cur = c.execute(
                "SELECT importe, cpv, ccaa, tecnologia, estado "
                "FROM licitaciones "
                "WHERE fecha_publicacion >= %s AND " + hasta,
                (start, valor_hasta),
            )
            return typed_rows(DriftRow, rows_to_dicts(cur))

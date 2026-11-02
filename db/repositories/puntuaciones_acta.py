"""Persistencia de las puntuaciones que el acta de la mesa da a cada licitador (v169).

Dos tablas, las dos de mercado (sin ``organization_id``):

* ``acta_extracciones``: una fila por expediente con el resultado de la lectura
  del acta (``ok``, ``sin_tabla``, ``sin_acta``, ``error``) y la versión de la
  extracción que la produjo. Sin ella no se sabe si un expediente sin
  puntuaciones está sin leer o leído y vacío, y se repetiría la llamada al
  modelo en cada pasada.
* ``acta_puntuaciones``: una fila por licitador, criterio y lote, con la página
  y la cita de donde salió.

La escritura es :meth:`PuntuacionesActaRepository.guardar`: reemplaza el
expediente entero en una transacción, así que repetirla no duplica (AGENTS.md
§3.2) y nadie lee un expediente a medio escribir.

Las lecturas que arman la ficha (``get_extraccion``, ``list_puntuaciones``,
``adjudicatarios_por_lote``, ``nombres_de_organizacion``) devuelven los datos
tal como están: normalizar nombres y decidir qué es «mi empresa» es del
servicio, no de la capa que posee el SQL.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal, TypedDict

from db.database import connect, connect_read
from db.repositories.base import rows_to_dicts, typed_rows
from db.repositories.documentos import TIPO_ACTA, _sin_publicar_sql

ActaStatus = Literal["ok", "sin_tabla", "sin_acta", "error"]


class ActaExtraccionRow(TypedDict):
    """Una fila de ``acta_extracciones``."""

    licitacion_id: str
    status: ActaStatus
    extraction_version: str
    model: str | None
    documentos_leidos: int
    error_detail: str | None
    extracted_at: datetime | None


class PuntuacionNueva(TypedDict):
    """Una puntuación tal como la escribe el job, ya validada contra su cita."""

    lote_numero: str | None
    licitador_nombre: str
    licitador_normalizado: str
    criterio: str | None
    puntos: float | None
    puntos_max: float | None
    es_precio: bool | None
    excluida: bool
    documento_id: int
    pagina: int
    cita: str


class PuntuacionRow(PuntuacionNueva):
    """Una puntuación tal como la lee la ficha."""

    id: int


class ExpedienteActaPendiente(TypedDict):
    """Un expediente cuyo acta toca leer (o volver a leer)."""

    licitacion_id: str
    tiene_acta: bool


class AdjudicatarioLote(TypedDict):
    """A quién se adjudicó un lote (``lote_numero`` ``None`` = sin lote resuelto)."""

    lote_numero: str | None
    nombre: str | None
    nif: str | None


_COLUMNAS_EXTRACCION = (
    "licitacion_id, status, extraction_version, model, documentos_leidos, error_detail, "
    "extracted_at"
)
_COLUMNAS_PUNTUACION = (
    "id, lote_numero, licitador_nombre, licitador_normalizado, criterio, puntos, puntos_max, "
    "es_precio, excluida, documento_id, pagina, cita"
)

# ``extracted_at`` es el instante de una lectura que llegó a una conclusión
# (``ok`` o ``sin_tabla``); con ``error`` o ``sin_acta`` queda en ``NULL``. Va
# pareado con las puntuaciones: ``guardar`` siempre las reemplaza, así que tras
# un ``error`` o un ``sin_acta`` no queda ningún dato leído que esa fecha pueda
# respaldar, y conservar la de una lectura anterior mentiría sobre lo guardado.
_UPSERT_EXTRACCION_SQL = (
    "INSERT INTO acta_extracciones "
    "(licitacion_id, status, extraction_version, model, documentos_leidos, error_detail, "
    " extracted_at, updated_at) "
    "VALUES (%s, %s, %s, %s, %s, %s, "
    "        CASE WHEN %s::text IN ('ok', 'sin_tabla') THEN now() END, now()) "
    "ON CONFLICT (licitacion_id) DO UPDATE SET "
    "  status = EXCLUDED.status, "
    "  extraction_version = EXCLUDED.extraction_version, "
    "  model = EXCLUDED.model, "
    "  documentos_leidos = EXCLUDED.documentos_leidos, "
    "  error_detail = EXCLUDED.error_detail, "
    "  extracted_at = EXCLUDED.extracted_at, "
    "  updated_at = now()"
)

_INSERT_PUNTUACION_SQL = (
    "INSERT INTO acta_puntuaciones "
    "(licitacion_id, lote_numero, licitador_nombre, licitador_normalizado, criterio, "
    " puntos, puntos_max, es_precio, excluida, documento_id, pagina, cita) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)

# Las fuentes de ``licitaciones.fuente`` cuya ingesta pasa por
# ``scraper.codice_parser.parse_document_references``, que es lo único que
# referencia las actas (``documentos.tipo = 'acta'``): el feed ``placsp``, su
# carril de ZIP mensuales ``bulk_YYYYMM`` y ``placsp_agregadas`` (misma
# comprobación del prefijo que ``db.sql_fragments.rango_de_fuente_sql``: ``left``
# y no ``LIKE``, que aquí exigiría duplicar el ``%``). Con cualquier otra
# (``pscp``, ``ted``, los RSS autonómicos, ``placsp_menores``…) no se ingiere
# ningún acta: marcar ``sin_acta`` allí diría «PLACSP no publicó acta» de un
# expediente que PLACSP ni siquiera lleva. Alias ``li``, el de ``_PENDIENTES_SQL``.
_FUENTES_CON_ACTAS_SQL = (
    "(li.fuente IN ('placsp', 'placsp_agregadas') OR left(li.fuente, 5) = 'bulk_')"
)

# Un expediente es de la pasada si alguien lo sigue (``pursuits``), viene de una
# fuente que ingiere actas, ya tiene adjudicatario publicado y su lectura del
# acta falta, es de otra versión, falló, dijo «sin acta» y desde entonces llegó
# una, o dijo «sin tabla» y todavía le queda un acta publicable por descargar
# (``_MAX_ACTAS`` por lectura: las de más esperan en ``pending``; mismo
# «publicable» que ``DocumentosRepository.list_pendientes``). ``DISTINCT`` en la
# subconsulta y no en la consulta: así el ``ORDER BY`` puede usar ``x.updated_at``
# (lo no leído nunca primero, después lo que lleva más tiempo sin intentarse) y
# el ``LIMIT`` no deja a los nuevos detrás de los ``error`` que se reencolan.
_PENDIENTES_SQL = (
    "SELECT l.licitacion_id, "
    "       EXISTS (SELECT 1 FROM documentos d "
    "                WHERE d.licitacion_id = l.licitacion_id AND d.tipo = %(tipo)s) AS tiene_acta "
    "  FROM (SELECT DISTINCT p.licitacion_id FROM pursuits p "
    "          JOIN licitaciones li ON li.id_externo = p.licitacion_id "
    f"        WHERE {_FUENTES_CON_ACTAS_SQL}) l "
    "  LEFT JOIN acta_extracciones x ON x.licitacion_id = l.licitacion_id "
    " WHERE EXISTS (SELECT 1 FROM adjudicaciones a WHERE a.licitacion_id = l.licitacion_id) "
    "   AND (x.licitacion_id IS NULL "
    "        OR x.extraction_version <> %(version)s "
    "        OR x.status = 'error' "
    "        OR (x.status = 'sin_acta' "
    "            AND EXISTS (SELECT 1 FROM documentos d "
    "                         WHERE d.licitacion_id = l.licitacion_id AND d.tipo = %(tipo)s)) "
    "        OR (x.status = 'sin_tabla' "
    "            AND EXISTS (SELECT 1 FROM documentos d "
    "                          JOIN licitaciones lic ON lic.id_externo = d.licitacion_id "
    "                         WHERE d.licitacion_id = l.licitacion_id AND d.tipo = %(tipo)s "
    "                           AND d.status = 'pending' "
    f"                          AND NOT {_sin_publicar_sql('d', 'lic')}))) "
    " ORDER BY x.updated_at NULLS FIRST, l.licitacion_id "
    " LIMIT %(limite)s"
)

# Las seis formas con que la organización puede aparecer escrita en un acta.
# ``empresa_id`` no es columna de ``organization_nifs``: se llega por el NIF
# canónico del maestro, como en ``OrganizationNifRepository.empresa_ids``. La
# segunda fuente cubre las adjudicaciones que el maestro ya resolvió a esa
# empresa aunque su NIF se publicara con otra forma (``idx_adj_empresa``). La
# última antes del nombre de la organización es la razón social que la propia
# organización declaró para ese NIF.
_NOMBRES_ORGANIZACION_SQL = (
    "SELECT a.nombre FROM organization_nifs n "
    "  JOIN adjudicaciones a ON a.nif = n.nif "
    " WHERE n.organization_id = %(org)s "
    "UNION "
    "SELECT a.nombre FROM organization_nifs n "
    "  JOIN empresas e ON e.nif_canonico = n.nif "
    "  JOIN adjudicaciones a ON a.empresa_id = e.empresa_id "
    " WHERE n.organization_id = %(org)s "
    "UNION "
    "SELECT e.nombre_canonico FROM organization_nifs n "
    "  JOIN empresas e ON e.nif_canonico = n.nif "
    " WHERE n.organization_id = %(org)s "
    "UNION "
    "SELECT al.alias_normalizado FROM organization_nifs n "
    "  JOIN empresas e ON e.nif_canonico = n.nif "
    "  JOIN empresa_aliases al ON al.empresa_id = e.empresa_id "
    " WHERE n.organization_id = %(org)s "
    "UNION "
    "SELECT n.razon_social FROM organization_nifs n "
    " WHERE n.organization_id = %(org)s AND n.razon_social IS NOT NULL "
    "UNION "
    "SELECT o.name FROM organizations o WHERE o.id = %(org)s "
    "ORDER BY 1"
)


class PuntuacionesActaRepository:
    """Lectura y escritura de ``acta_extracciones`` y ``acta_puntuaciones``."""

    def get_extraccion(self, licitacion_id: str) -> ActaExtraccionRow | None:
        """El estado de la lectura del acta del expediente, o ``None`` si no se ha intentado."""
        with connect_read() as conn:
            cur = conn.execute(
                f"SELECT {_COLUMNAS_EXTRACCION} FROM acta_extracciones WHERE licitacion_id = %s",
                (licitacion_id,),
            )
            filas = typed_rows(ActaExtraccionRow, rows_to_dicts(cur))
        return filas[0] if filas else None

    def tiene_actas(self, licitacion_id: str) -> bool:
        """Si el expediente tiene al menos un documento de tipo ``acta``."""
        with connect_read() as conn:
            fila = conn.execute(
                "SELECT EXISTS (SELECT 1 FROM documentos WHERE licitacion_id = %s AND tipo = %s)",
                (licitacion_id, TIPO_ACTA),
            ).fetchone()
        return bool(fila[0]) if fila else False

    def list_puntuaciones(self, licitacion_id: str) -> list[PuntuacionRow]:
        """Las puntuaciones del expediente, en el orden en que el job las escribió.

        Ese orden es el del acta (las filas se insertan una tras otra en
        ``guardar``), que es el que una persona espera ver en cada licitador.
        """
        with connect_read() as conn:
            cur = conn.execute(
                f"SELECT {_COLUMNAS_PUNTUACION} FROM acta_puntuaciones "
                "WHERE licitacion_id = %s ORDER BY id",
                (licitacion_id,),
            )
            return typed_rows(PuntuacionRow, rows_to_dicts(cur))

    def guardar(
        self,
        licitacion_id: str,
        *,
        status: ActaStatus,
        extraction_version: str,
        model: str | None,
        documentos_leidos: int,
        error_detail: str | None,
        filas: Sequence[PuntuacionNueva],
    ) -> None:
        """Deja el expediente con esta lectura y estas puntuaciones, y nada más.

        Una sola transacción: el estado de la extracción se inserta o se
        actualiza, y las puntuaciones del expediente se borran y se vuelven a
        insertar. Repetirla con lo mismo deja lo mismo; con ``filas`` vacías
        (``sin_tabla``, ``sin_acta``, ``error``) deja la extracción y ninguna
        puntuación. Siempre reemplaza, también con ``error``: lo leído antes se
        pierde, y por eso ``extracted_at`` solo se marca con ``ok`` y
        ``sin_tabla``.

        Dos filas con el mismo lote, licitador y criterio chocan con
        ``uq_acta_puntuaciones_fila`` y la transacción entera se deshace: quien
        llama es quien deduplica.
        """
        with connect() as conn:
            conn.execute(
                _UPSERT_EXTRACCION_SQL,
                (
                    licitacion_id,
                    status,
                    extraction_version,
                    model,
                    documentos_leidos,
                    error_detail,
                    status,
                ),
            )
            conn.execute("DELETE FROM acta_puntuaciones WHERE licitacion_id = %s", (licitacion_id,))
            if filas:
                conn.executemany(
                    _INSERT_PUNTUACION_SQL,
                    [
                        (
                            licitacion_id,
                            fila["lote_numero"],
                            fila["licitador_nombre"],
                            fila["licitador_normalizado"],
                            fila["criterio"],
                            fila["puntos"],
                            fila["puntos_max"],
                            fila["es_precio"],
                            fila["excluida"],
                            fila["documento_id"],
                            fila["pagina"],
                            fila["cita"],
                        )
                        for fila in filas
                    ],
                )

    def expedientes_pendientes(
        self, *, extraction_version: str, limit: int = 200
    ) -> list[ExpedienteActaPendiente]:
        """Expedientes que alguien sigue, ya adjudicados, cuya lectura del acta toca hacer.

        Un expediente con pursuits de dos organizaciones sale una vez: lo que se
        lee es el acta, que es de mercado.

        Solo de las fuentes que ingieren actas (:data:`_FUENTES_CON_ACTAS_SQL`):
        un expediente de ``pscp`` o de ``ted`` no sale, no tiene fila en
        ``acta_extracciones`` y la ficha no dice nada de actas.

        Salen los que no tienen fila en ``acta_extracciones``, los de otra
        versión de la extracción, los que quedaron en ``error``, los que
        quedaron en ``sin_acta`` cuando desde entonces llegó un documento
        ``acta`` y los que quedaron en ``sin_tabla`` mientras les queda un acta
        publicable por descargar (la lectura baja ``_MAX_ACTAS`` por pasada y
        las de más esperan en ``pending``). ``ok`` y ``sin_tabla`` sin actas
        pendientes de la versión vigente no vuelven.

        Lee los ``pursuits`` de todas las organizaciones, así que se llama sin
        contexto de tenant (el job del scheduler), no desde el ámbito de una
        petición: con la organización fijada, las políticas RLS de v128 lo
        acotarían a la suya.
        """
        # shortcut: reencola 'error' en cada pasada, sin tope; poner un tope por updated_at si las oportunidades pasan del centenar
        with connect_read() as conn:
            cur = conn.execute(
                _PENDIENTES_SQL,
                {"tipo": TIPO_ACTA, "version": extraction_version, "limite": limit},
            )
            return typed_rows(ExpedienteActaPendiente, rows_to_dicts(cur))

    def adjudicatarios_por_lote(self, licitacion_id: str) -> list[AdjudicatarioLote]:
        """A quién se adjudicó cada lote del expediente (``lote_numero`` ``None`` si no hay lote)."""
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT l.numero AS lote_numero, a.nombre, a.nif "
                "FROM adjudicaciones a LEFT JOIN lotes l ON l.id = a.lote_id "
                "WHERE a.licitacion_id = %s ORDER BY a.id",
                (licitacion_id,),
            )
            return typed_rows(AdjudicatarioLote, rows_to_dicts(cur))

    def nombres_de_organizacion(self, organization_id: int) -> list[str]:
        """Los nombres con que la organización puede figurar en un acta, sin normalizar.

        Unión de: el nombre con que se adjudicó a los NIF que declaró
        (``adjudicaciones.nombre``), el de las adjudicaciones que el maestro ya
        resolvió a la empresa de esos NIF (``adjudicaciones.empresa_id``), el
        nombre canónico y los alias del maestro de empresas para esos mismos
        NIF, la razón social que la organización declaró junto a cada NIF, y el
        nombre de la propia organización. Normalizarlos y compararlos
        con ``licitador_normalizado`` es del servicio.

        El cruce por NIF es por igualdad (usa ``idx_adj_nif``): una adjudicación
        cuyo NIF se publicó con separadores no aporta su nombre por esa vía, y
        queda cubierta por la resolución a ``empresa_id`` (``idx_adj_empresa``).
        """
        with connect_read() as conn:
            filas = conn.execute(_NOMBRES_ORGANIZACION_SQL, {"org": organization_id}).fetchall()
        return [str(fila[0]) for fila in filas if fila[0]]

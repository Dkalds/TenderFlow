"""Persistencia de la cola de trabajo (`jobs`) — plan 2026-09 v2, S5.1.

**Todo el SQL de la cola vive aquí** (ADR-022). ``shared/jobs.py`` es la capa de
dominio (qué tipos existen, qué handler ejecuta cada uno, cuándo se reintenta) y
no escribe una sola sentencia.

La pieza que hace correcta la cola es la reclamación::

    WITH candidato AS (
        SELECT id FROM jobs
         WHERE estado = 'pending' AND run_after <= now()
         ORDER BY run_after, id
         FOR UPDATE SKIP LOCKED
         LIMIT 1
    )
    UPDATE jobs … FROM candidato …

``FOR UPDATE`` toma el row lock dentro de la transacción, así que ningún otro
consumidor puede tomar esa fila mientras dure; ``SKIP LOCKED`` hace que el
segundo consumidor **salte** a la siguiente en vez de esperar, que es lo que
convierte la tabla en una cola y no en un embudo. El ``UPDATE`` a ``running``
viaja en la misma transacción que el ``SELECT``: si el proceso muere entre
ambos, no hay ambos — o la fila sigue ``pending`` o ya está reclamada.

``intentos`` se incrementa **al reclamar**, no al fallar. Es lo que acota
también los fallos que no dejan traza (el proceso muere a mitad): el job vuelve
a ``pending`` por ``reclamar_caducados`` con su intento ya contado, en vez de
girar para siempre.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from db.database import connect, connect_read

#: Columnas que devuelve cualquier lectura. Una sola constante para que el
#: mapeo a ``shared.jobs.Job`` no dependa del orden que escriba cada consulta.
_COLUMNAS = (
    "id",
    "tipo",
    "payload_json",
    "organization_id",
    "estado",
    "intentos",
    "run_after",
    "locked_by",
    "locked_at",
    "resultado_json",
    "error_detail",
    "created_at",
    "updated_at",
)

_SELECT = ", ".join(_COLUMNAS)
_RETURNING = ", ".join(f"j.{c}" for c in _COLUMNAS)


def _fila(valores: Any) -> dict[str, Any]:
    """Empareja una tupla del cursor con :data:`_COLUMNAS`."""
    return dict(zip(_COLUMNAS, valores, strict=True))


class JobsRepository:
    """Repositorio fino para ``jobs``. Sin lógica de reintento ni de handlers."""

    # ── Escritura ────────────────────────────────────────────────────────

    def insertar(
        self,
        *,
        tipo: str,
        payload_json: str,
        organization_id: int | None,
        run_after: datetime | None = None,
    ) -> int:
        """Inserta un job ``pending`` y devuelve su id.

        ``run_after`` a ``None`` significa «reclamable ya»: se deja el
        ``DEFAULT NOW()`` de la columna en vez de calcular el instante en el
        proceso, para que el reloj de referencia sea siempre el del servidor
        (el mismo que compara ``claim``).
        """
        with connect() as c:
            if run_after is None:
                fila = c.execute(
                    "INSERT INTO jobs (tipo, payload_json, organization_id) "
                    "VALUES (%s, %s, %s) RETURNING id",
                    (tipo, payload_json, organization_id),
                ).fetchone()
            else:
                fila = c.execute(
                    "INSERT INTO jobs (tipo, payload_json, organization_id, run_after) "
                    "VALUES (%s, %s, %s, %s) RETURNING id",
                    (tipo, payload_json, organization_id, run_after),
                ).fetchone()
        return int(fila[0])

    def reclamar(
        self, *, worker_id: str, tipos: tuple[str, ...] | None = None
    ) -> dict[str, Any] | None:
        """Toma el job reclamable más antiguo, o ``None`` si no hay ninguno.

        ``tipos`` acota qué sabe ejecutar este consumidor: el worker de Render
        pide los tipos a demanda y el cierre de la pasada pide los suyos, sobre
        la misma tabla (D14). Sin filtro, un consumidor se llevaría trabajo que
        no sabe ejecutar y lo haría fallar tres veces antes de rendirse.
        """
        filtro_tipo = "" if tipos is None else " AND tipo = ANY(%s)"
        params: list[Any] = []
        if tipos is not None:
            params.append(list(tipos))
        params.append(worker_id)

        with connect() as c:
            fila = c.execute(
                "WITH candidato AS ("
                "  SELECT id FROM jobs"
                "   WHERE estado = 'pending' AND run_after <= NOW()" + filtro_tipo + ""
                "   ORDER BY run_after, id"
                "   FOR UPDATE SKIP LOCKED"
                "   LIMIT 1"
                ") "
                "UPDATE jobs j SET estado = 'running', locked_by = %s, locked_at = NOW(), "
                "intentos = j.intentos + 1, updated_at = NOW() "
                "FROM candidato c WHERE j.id = c.id "
                "RETURNING " + _RETURNING,
                tuple(params),
            ).fetchone()
        return _fila(fila) if fila else None

    def marcar_terminado(self, job_id: int, *, resultado_json: str | None) -> None:
        """``done``: suelta el lock y guarda el resultado."""
        with connect() as c:
            c.execute(
                "UPDATE jobs SET estado = 'done', resultado_json = %s, error_detail = NULL, "
                "locked_by = NULL, locked_at = NULL, updated_at = NOW() WHERE id = %s",
                (resultado_json, job_id),
            )

    def marcar_fallido(self, job_id: int, *, error_detail: str) -> None:
        """``failed`` definitivo: se agotaron los intentos."""
        with connect() as c:
            c.execute(
                "UPDATE jobs SET estado = 'failed', error_detail = %s, "
                "locked_by = NULL, locked_at = NULL, updated_at = NOW() WHERE id = %s",
                (error_detail[:4000], job_id),
            )

    def reprogramar(self, job_id: int, *, error_detail: str, run_after: datetime) -> None:
        """Devuelve el job a ``pending`` con su próxima ventana (backoff).

        ``error_detail`` se conserva entre intentos a propósito: si el job acaba
        agotando los reintentos, el detalle del último fallo ya está escrito
        aunque el proceso que lo intentó muriera sin poder contarlo.
        """
        with connect() as c:
            c.execute(
                "UPDATE jobs SET estado = 'pending', run_after = %s, error_detail = %s, "
                "locked_by = NULL, locked_at = NULL, updated_at = NOW() WHERE id = %s",
                (run_after, error_detail[:4000], job_id),
            )

    def reclamar_caducados(self, *, ttl_segundos: int) -> list[int]:
        """Devuelve a ``pending`` los ``running`` cuyo lock caducó.

        Es la red que hace verdad la promesa de S5.3: un despliegue mata al
        worker en mitad de una extracción, su ``locked_at`` deja de refrescarse
        y, pasado el TTL, otro worker la termina. Sin esto el job se quedaría
        ``running`` para siempre y el usuario sondeando un estado muerto.

        El ``make_interval`` va parametrizado y no interpolado: el TTL viene de
        configuración y no tiene por qué ser un literal de confianza.
        """
        with connect() as c:
            filas = c.execute(
                "UPDATE jobs SET estado = 'pending', locked_by = NULL, locked_at = NULL, "
                "updated_at = NOW() "
                "WHERE estado = 'running' AND locked_at IS NOT NULL "
                "AND locked_at < NOW() - make_interval(secs => %s) "
                "RETURNING id",
                (float(ttl_segundos),),
            ).fetchall()
        return [int(f[0]) for f in filas]

    # ── Lectura ──────────────────────────────────────────────────────────

    def obtener(self, job_id: int) -> dict[str, Any] | None:
        """Job por id, sin filtrar por organización (eso lo decide la ruta)."""
        with connect_read() as c:
            fila = c.execute(
                f"SELECT {_SELECT} FROM jobs WHERE id = %s",
                (job_id,),
            ).fetchone()
        return _fila(fila) if fila else None

    def buscar_activo(
        self,
        *,
        tipo: str,
        campo: str,
        valor: str,
        organization_id: int | None = None,
        filtrar_organizacion: bool = False,
    ) -> dict[str, Any] | None:
        """Job ``pending``/``running`` de ese tipo cuyo payload lleva ``campo=valor``.

        Sirve a dos cosas a la vez, y por eso es una sola consulta: la
        deduplicación al encolar (dos clics en «Extraer ficha» no lanzan dos
        extracciones) y la lectura de estado de ``…/ficha-pliego/estado``, que
        desde S5.2 pregunta a la cola en vez de a una bandera en caché.

        ``filtrar_organizacion`` distingue las dos, y no basta con mirar si
        ``organization_id`` viene a ``None``: la deduplicación tiene que acotarse
        SIEMPRE a la organización que encola —incluido el trabajo del sistema,
        que no tiene ninguna—, porque un job compartido entre dos
        organizaciones se le devolvería a la segunda como suyo y su
        ``GET /jobs/{id}`` le respondería 404. Por eso la comparación es
        ``IS NOT DISTINCT FROM``: con ``= NULL`` ninguna fila casaría y el
        trabajo del sistema se duplicaría en cada intento. La lectura de estado,
        en cambio, pregunta a propósito sin filtro: la ficha del pliego es dato
        compartido y que la esté extrayendo otra organización es una respuesta
        correcta a «¿hay una extracción en curso?».

        El campo se busca con ``payload_json::jsonb ->> %s``: el nombre viaja
        como parámetro, no concatenado, así que no hay forma de inyectar por
        ahí. Sin índice funcional a propósito — la cola activa es corta por
        construcción y un índice sobre una expresión JSON costaría en cada
        escritura para ahorrar en un scan de decenas de filas.
        """
        filtro_org = ""
        params: list[Any] = [tipo, campo, valor]
        if filtrar_organizacion:
            filtro_org = " AND organization_id IS NOT DISTINCT FROM %s"
            params.append(organization_id)

        with connect_read() as c:
            fila = c.execute(
                f"SELECT {_SELECT} FROM jobs "
                "WHERE tipo = %s AND estado IN ('pending', 'running') "
                "AND payload_json::jsonb ->> %s = %s" + filtro_org + " "
                "ORDER BY id LIMIT 1",
                tuple(params),
            ).fetchone()
        return _fila(fila) if fila else None

    def contar_por_estado(self) -> dict[str, int]:
        """Recuento por estado, para el diagnóstico del worker y de ops."""
        with connect_read() as c:
            filas = c.execute("SELECT estado, COUNT(*) FROM jobs GROUP BY estado").fetchall()
        return {str(f[0]): int(f[1]) for f in filas}

    def listar_por_ids(self, ids: list[int]) -> list[dict[str, Any]]:
        """Los jobs indicados, en el orden en que Postgres los devuelva.

        Lo usa el cierre post-ingesta (S5.4) para releer de una vez el
        resultado de los pasos que encoló, en vez de una consulta por paso.
        """
        if not ids:
            return []
        with connect_read() as c:
            filas = c.execute(
                f"SELECT {_SELECT} FROM jobs WHERE id = ANY(%s)",
                ([int(i) for i in ids],),
            ).fetchall()
        return [_fila(f) for f in filas]


__all__ = ["JobsRepository"]

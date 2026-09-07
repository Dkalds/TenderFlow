"""Persistencia del perfil de capacidad de una organización (S2.2).

Las cuatro tablas de ``v112`` —certificaciones, facturación, referencias y
perfiles de equipo— son un solo concepto de producto: «con qué puede
acreditarse esta organización». Se leen y se escriben juntas, en una
transacción, y por eso tienen un único repositorio en vez de cuatro.

También vive aquí el sellado del checklist en ``pursuit_events``
(:func:`seal_checklist_evaluated`). No es capacidad, pero es SQL de S2 y
ADR-022 no admite SQL fuera de ``db/``: el escritor de eventos de pursuit
(``PursuitRepository._append_event``) es privado y su fichero pertenece a otro
stream, así que duplicar aquí el ``INSERT ... ON CONFLICT DO NOTHING`` —seis
líneas contra la misma tabla y el mismo índice único— cuesta menos que abrir
una API pública en un fichero que este stream no puede tocar. Cuando los
streams converjan, su sitio natural es ``PursuitRepository``.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts

# Las cuatro consultas seleccionan **exactamente** los campos que publica
# ``OrganizationCapabilities`` más ``created_at``, que no se publica: sirve
# para calcular la marca del perfil y se descarta antes de devolver la fila.
# El ``id`` de la fila no se selecciona en absoluto —nadie lo consume, y los
# DTO declaran ``extra="forbid"`` justamente para no publicar contabilidad
# interna de la tabla—. Enumerar aquí lo que sale es lo que hace que la
# validación de arriba sea directa en vez de una lista de campos a ignorar.
_CERTIFICACIONES = (
    "SELECT nombre, ambito, vigente_hasta, created_at "
    "FROM organization_certifications WHERE organization_id = %s ORDER BY nombre"
)
_FACTURACION = (
    "SELECT ejercicio, importe_eur, created_at "
    "FROM organization_revenues WHERE organization_id = %s ORDER BY ejercicio DESC"
)
_REFERENCIAS = (
    "SELECT organo, importe_eur, anio, tecnologia, expediente_id, created_at "
    "FROM organization_references WHERE organization_id = %s ORDER BY anio DESC, id"
)
_PERFILES = (
    "SELECT rol, anios, cantidad, created_at "
    "FROM organization_team_profiles WHERE organization_id = %s ORDER BY rol"
)


def _float(value: Any) -> float | None:
    """``NUMERIC`` llega como ``Decimal``; los DTO declaran ``float``.

    Se convierte aquí y no en el servicio para que ninguna capa de arriba
    tenga que saber de qué tipo SQL viene un importe.
    """
    return None if value is None else float(value)


class OrganizationCapabilitiesRepository:
    """Lee y reemplaza el perfil de capacidad completo de una organización."""

    def get(self, organization_id: int) -> dict[str, Any]:
        """El perfil entero, con las claves exactas de ``OrganizationCapabilities``.

        Una organización sin perfil devuelve las cuatro listas vacías. Lo que
        devuelve es directamente validable con el DTO —``extra="forbid"``
        incluido—: no lleva ``id`` de fila, ni ``created_at``, ni la marca
        ``updated_at``, que es metadato del perfil y no un campo suyo. Quien
        necesite la marca usa :meth:`get_with_updated_at`.
        """
        perfil, _ = self.get_with_updated_at(organization_id)
        return perfil

    def get_with_updated_at(self, organization_id: int) -> tuple[dict[str, Any], datetime | None]:
        """El perfil y cuándo se escribió por última vez.

        Van juntos en un solo viaje porque la marca sale de los ``created_at``
        de esas mismas filas: pedirla aparte serían cuatro consultas más para
        un dato que ya está en la mano.

        La marca del perfil es la escritura más reciente de cualquiera de las
        cuatro tablas. No hay columna por fila porque el PUT reemplaza el
        conjunto entero: una marca por fila mediría el reemplazo, no el cambio
        real.
        """
        with connect_read() as conn:
            certificaciones = rows_to_dicts(conn.execute(_CERTIFICACIONES, (organization_id,)))
            facturacion = rows_to_dicts(conn.execute(_FACTURACION, (organization_id,)))
            referencias = rows_to_dicts(conn.execute(_REFERENCIAS, (organization_id,)))
            perfiles = rows_to_dicts(conn.execute(_PERFILES, (organization_id,)))

        marcas: list[datetime] = []
        for grupo in (certificaciones, facturacion, referencias, perfiles):
            for fila in grupo:
                marca = fila.pop("created_at", None)
                if isinstance(marca, datetime):
                    marcas.append(marca)

        for fila in facturacion:
            fila["importe_eur"] = _float(fila["importe_eur"])
        for fila in referencias:
            fila["importe_eur"] = _float(fila["importe_eur"])
        for fila in perfiles:
            fila["anios"] = _float(fila["anios"])

        perfil: dict[str, Any] = {
            "certificaciones": certificaciones,
            "facturacion": facturacion,
            "referencias": referencias,
            "perfiles_equipo": perfiles,
        }
        return perfil, (max(marcas) if marcas else None)

    def replace(
        self,
        organization_id: int,
        *,
        certificaciones: list[dict[str, Any]],
        facturacion: list[dict[str, Any]],
        referencias: list[dict[str, Any]],
        perfiles_equipo: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], datetime | None]:
        """Reemplaza el perfil completo y lo relee. Todo o nada: una transacción.

        Un perfil a medias es peor que ninguno: el checklist contestaría
        ``no_cumple`` por un dato que sí existe pero que aún no se ha vuelto a
        insertar.

        Devuelve lo mismo que :meth:`get_with_updated_at` —perfil y marca—
        porque quien acaba de escribir es justo quien tiene que poder enseñar
        cuándo se escribió.
        """
        now = now_utc_iso()
        with connect() as conn:
            # Cuatro DELETE escritos enteros y no un bucle sobre nombres de
            # tabla interpolados: el nombre de tabla no admite placeholder, y
            # el SQL literal es lo que hace que no haya nada que revisar.
            conn.execute(
                "DELETE FROM organization_certifications WHERE organization_id = %s",
                (organization_id,),
            )
            conn.execute(
                "DELETE FROM organization_revenues WHERE organization_id = %s",
                (organization_id,),
            )
            conn.execute(
                "DELETE FROM organization_references WHERE organization_id = %s",
                (organization_id,),
            )
            conn.execute(
                "DELETE FROM organization_team_profiles WHERE organization_id = %s",
                (organization_id,),
            )
            for cert in certificaciones:
                conn.execute(
                    "INSERT INTO organization_certifications "
                    "(organization_id, nombre, ambito, vigente_hasta, created_at) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (
                        organization_id,
                        cert["nombre"],
                        cert.get("ambito", "company"),
                        cert.get("vigente_hasta"),
                        now,
                    ),
                )
            for fila in facturacion:
                conn.execute(
                    "INSERT INTO organization_revenues "
                    "(organization_id, ejercicio, importe_eur, created_at) "
                    "VALUES (%s, %s, %s, %s)",
                    (organization_id, fila["ejercicio"], fila["importe_eur"], now),
                )
            for ref in referencias:
                conn.execute(
                    "INSERT INTO organization_references "
                    "(organization_id, organo, importe_eur, anio, tecnologia, "
                    " expediente_id, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (
                        organization_id,
                        ref["organo"],
                        ref.get("importe_eur"),
                        ref["anio"],
                        ref.get("tecnologia"),
                        ref.get("expediente_id"),
                        now,
                    ),
                )
            for perfil in perfiles_equipo:
                conn.execute(
                    "INSERT INTO organization_team_profiles "
                    "(organization_id, rol, anios, cantidad, created_at) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (organization_id, perfil["rol"], perfil["anios"], perfil["cantidad"], now),
                )
        return self.get_with_updated_at(organization_id)


def seal_checklist_evaluated(
    *,
    pursuit_id: int,
    organization_id: int,
    actor_user_id: int,
    payload: dict[str, Any],
    idempotency_key: str,
) -> bool:
    """Sella ``checklist_evaluated`` en el ledger. ``True`` si escribió fila.

    ``uq_pursuit_events_idempotency (pursuit_id, idempotency_key)`` de ``v61``
    es lo que garantiza «una vez por versión de ficha»: la clave la compone
    ``services/go_no_go.py`` con la versión del extractor y la fecha de la
    ficha, así que reevaluar la misma ficha no vuelve a sellar y una ficha
    reextraída sí. Sin esa clave, abrir la pestaña Decisión diez veces
    escribiría diez eventos en un ledger que es append-only por trigger.
    """
    with connect() as conn:
        row = conn.execute(
            "INSERT INTO pursuit_events "
            "(pursuit_id, organization_id, event_type, actor_user_id, "
            " payload_json, idempotency_key, created_at) "
            "VALUES (%s, %s, 'checklist_evaluated', %s, %s, %s, %s) "
            "ON CONFLICT DO NOTHING RETURNING id",
            (
                pursuit_id,
                organization_id,
                actor_user_id,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                idempotency_key,
                now_utc_iso(),
            ),
        ).fetchone()
    return row is not None

"""Persistencia de la cartera de contratos (F4.3) y de las plantillas de
organización (F6.4).

Las dos son de organización. La cartera además es **derivada**: cada fila es la
continuación de una oportunidad ganada, no un registro paralelo que alguien
tenga que mantener al día.
"""

from __future__ import annotations

import json
from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts

__all__ = ["CarteraRepository", "PlantillasRepository"]


class CarteraRepository:
    """Contratos ganados que siguen en ejecución."""

    def list_for_organization(self, organization_id: int) -> list[dict[str, Any]]:
        """La cartera, con lo que hace falta para pintarla y para decidir.

        Une contra `licitaciones` porque la cartera se lee por órgano y por
        tecnología, y guardar esos campos duplicados aquí los dejaría viejos en
        cuanto la ingesta corrigiera uno.
        """
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT c.id, c.organization_id, c.pursuit_id, c.licitacion_id, "
                "       c.fecha_inicio, c.fecha_fin_efectiva, c.fecha_fin_origen, "
                "       c.importe_adjudicado, c.prorrogas_aplicadas, "
                "       c.renovacion_pursuit_id, c.created_at, c.updated_at, "
                "       l.titulo, l.organo_contratacion, l.tecnologia, l.cpv "
                "FROM contratos_cartera c "
                "JOIN licitaciones l ON l.id_externo = c.licitacion_id "
                "WHERE c.organization_id = %s "
                "ORDER BY c.fecha_fin_efectiva NULLS LAST, c.id",
                (organization_id,),
            )
            return rows_to_dicts(cur)

    def get_by_pursuit(self, organization_id: int, pursuit_id: int) -> dict[str, Any] | None:
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT id, organization_id, pursuit_id, licitacion_id, fecha_inicio, "
                "       fecha_fin_efectiva, fecha_fin_origen, importe_adjudicado, "
                "       prorrogas_aplicadas, renovacion_pursuit_id, created_at, updated_at "
                "FROM contratos_cartera WHERE organization_id = %s AND pursuit_id = %s",
                (organization_id, pursuit_id),
            )
            filas = rows_to_dicts(cur)
        return filas[0] if filas else None

    def upsert(
        self,
        *,
        organization_id: int,
        pursuit_id: int,
        licitacion_id: str,
        fecha_inicio: str | None,
        fecha_fin_efectiva: str | None,
        fecha_fin_origen: str | None,
        importe_adjudicado: float | None,
        prorrogas_aplicadas: int = 0,
    ) -> dict[str, Any]:
        """Crea o actualiza la entrada de cartera de una oportunidad ganada.

        Idempotente por ``pursuit_id``. El ``DO UPDATE`` es lo que permite que
        una prórroga registrada después mueva la fecha de fin sin que nadie
        borre y vuelva a crear la fila — y sin perder ``renovacion_pursuit_id``,
        que no se toca aquí.
        """
        ahora = now_utc_iso()
        with connect() as conn:
            cur = conn.execute(
                "INSERT INTO contratos_cartera "
                "(organization_id, pursuit_id, licitacion_id, fecha_inicio, "
                " fecha_fin_efectiva, fecha_fin_origen, importe_adjudicado, "
                " prorrogas_aplicadas, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (pursuit_id) DO UPDATE SET "
                "  fecha_inicio = EXCLUDED.fecha_inicio, "
                "  fecha_fin_efectiva = EXCLUDED.fecha_fin_efectiva, "
                "  fecha_fin_origen = EXCLUDED.fecha_fin_origen, "
                "  importe_adjudicado = EXCLUDED.importe_adjudicado, "
                "  prorrogas_aplicadas = EXCLUDED.prorrogas_aplicadas, "
                "  updated_at = EXCLUDED.updated_at "
                "RETURNING id, organization_id, pursuit_id, licitacion_id, fecha_inicio, "
                "  fecha_fin_efectiva, fecha_fin_origen, importe_adjudicado, "
                "  prorrogas_aplicadas, renovacion_pursuit_id, created_at, updated_at",
                (
                    organization_id,
                    pursuit_id,
                    licitacion_id,
                    fecha_inicio,
                    fecha_fin_efectiva,
                    fecha_fin_origen,
                    importe_adjudicado,
                    prorrogas_aplicadas,
                    ahora,
                    ahora,
                ),
            )
            filas = rows_to_dicts(cur)
        return filas[0]

    def marcar_renovacion(
        self, *, organization_id: int, cartera_id: int, renovacion_pursuit_id: int
    ) -> bool:
        """Ata la oportunidad de renovación al contrato. ``False`` si ya tenía.

        El ``IS NULL`` en el ``WHERE`` es la idempotencia de «preparar
        renovación»: dos clics seguidos no crean dos oportunidades, porque el
        segundo no encuentra fila que actualizar y el servicio lo lee así.
        """
        with connect() as conn:
            cur = conn.execute(
                "UPDATE contratos_cartera SET renovacion_pursuit_id = %s, updated_at = %s "
                "WHERE organization_id = %s AND id = %s AND renovacion_pursuit_id IS NULL",
                (renovacion_pursuit_id, now_utc_iso(), organization_id, cartera_id),
            )
            return bool(cur.rowcount > 0)

    def vencen_entre(self, *, desde_iso: str, hasta_iso: str) -> list[dict[str, Any]]:
        """Contratos cuyo fin efectivo cae en la ventana. Lo usa el job de avisos."""
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT c.id, c.organization_id, c.pursuit_id, c.licitacion_id, "
                "       c.fecha_fin_efectiva, l.titulo, l.organo_contratacion "
                "FROM contratos_cartera c "
                "JOIN licitaciones l ON l.id_externo = c.licitacion_id "
                "WHERE c.fecha_fin_efectiva IS NOT NULL "
                "  AND c.fecha_fin_efectiva >= %s AND c.fecha_fin_efectiva < %s "
                "ORDER BY c.fecha_fin_efectiva",
                (desde_iso, hasta_iso),
            )
            return rows_to_dicts(cur)


class PlantillasRepository:
    """Reglas, vistas y etiquetas que hereda un miembro nuevo (F6.4)."""

    def list_for_organization(
        self, organization_id: int, tipo: str | None = None
    ) -> list[dict[str, Any]]:
        clauses = ["organization_id = %s"]
        params: list[Any] = [organization_id]
        if tipo is not None:
            clauses.append("tipo = %s")
            params.append(tipo)
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT id, organization_id, tipo, nombre, contenido_json, "
                "       created_by_user_id, created_at "
                "FROM plantillas_organizacion WHERE " + " AND ".join(clauses) + " ORDER BY id",
                tuple(params),
            )
            filas = rows_to_dicts(cur)
        for fila in filas:
            try:
                fila["contenido"] = json.loads(str(fila.pop("contenido_json")))
            except (TypeError, ValueError, json.JSONDecodeError):
                fila["contenido"] = {}
        return filas

    def create(
        self,
        *,
        organization_id: int,
        tipo: str,
        nombre: str,
        contenido: dict[str, Any],
        user_id: int | None,
    ) -> int:
        with connect() as conn:
            cur = conn.execute(
                "INSERT INTO plantillas_organizacion "
                "(organization_id, tipo, nombre, contenido_json, created_by_user_id, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    organization_id,
                    tipo,
                    nombre.strip(),
                    json.dumps(contenido, ensure_ascii=False, sort_keys=True),
                    user_id,
                    now_utc_iso(),
                ),
            )
            fila = cur.fetchone()
        return int(fila[0])

    def delete(self, organization_id: int, plantilla_id: int) -> bool:
        with connect() as conn:
            cur = conn.execute(
                "DELETE FROM plantillas_organizacion WHERE organization_id = %s AND id = %s",
                (organization_id, plantilla_id),
            )
            return bool(cur.rowcount > 0)

    def reservar_aplicacion(self, organization_id: int, user_id: int) -> bool:
        """``True`` si es la primera vez que se aplica a este miembro.

        La idempotencia se resuelve **con la clave única, no comprobando
        antes**: entre un ``SELECT`` y un ``INSERT`` caben dos activaciones
        simultáneas de la misma membresía, y el resultado serían las reglas
        duplicadas que F6.4 dice explícitamente que no puede haber.
        """
        with connect() as conn:
            cur = conn.execute(
                "INSERT INTO plantillas_aplicadas "
                "(organization_id, user_id, aplicada_en, copias) "
                "VALUES (%s, %s, %s, 0) "
                "ON CONFLICT (organization_id, user_id) DO NOTHING",
                (organization_id, user_id, now_utc_iso()),
            )
            return bool(cur.rowcount > 0)

    def registrar_copias(self, organization_id: int, user_id: int, copias: int) -> None:
        with connect() as conn:
            conn.execute(
                "UPDATE plantillas_aplicadas SET copias = %s "
                "WHERE organization_id = %s AND user_id = %s",
                (copias, organization_id, user_id),
            )

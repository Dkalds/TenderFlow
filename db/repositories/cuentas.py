"""Persistencia de cuentas objetivo (F1.5) y etiquetas de organización (F1.6).

Las dos son de **ámbito de organización**, no de usuario: seguir un órgano y
etiquetar una oportunidad son decisiones de equipo, y un comercial que se va
no debe llevarse la cartera de cuentas con él. Por eso ninguna consulta de
este módulo acepta ``user_key``: todas exigen ``organization_id``, y ése es el
aislamiento que el test comprueba.
"""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts
from db.sql_fragments import plegar_organo

__all__ = [
    "ActividadRepository",
    "CuentasRepository",
    "EtiquetasRepository",
    "SegmentoRepository",
    "normalizar_nombre",
]


def normalizar_nombre(valor: str) -> str:
    """Clave de identidad de una etiqueta: plegada, en minúsculas, sin dobles
    espacios. «Q4» y « q4 » son la misma etiqueta escrita dos veces."""
    return " ".join(str(valor).strip().lower().split())


class CuentasRepository:
    """Órganos que una organización sigue como cuenta objetivo."""

    def list_for_organization(self, organization_id: int) -> list[dict[str, Any]]:
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT id, organization_id, organo_nombre, organo_norm, organo_id, "
                "created_by_user_id, created_at, nota "
                "FROM cuentas_objetivo WHERE organization_id = %s "
                "ORDER BY organo_nombre",
                (organization_id,),
            )
            return rows_to_dicts(cur)

    def get(self, organization_id: int, cuenta_id: int) -> dict[str, Any] | None:
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT id, organization_id, organo_nombre, organo_norm, organo_id, "
                "created_by_user_id, created_at, nota "
                "FROM cuentas_objetivo WHERE organization_id = %s AND id = %s",
                (organization_id, cuenta_id),
            )
            filas = rows_to_dicts(cur)
        return filas[0] if filas else None

    def follow(
        self,
        *,
        organization_id: int,
        organo_nombre: str,
        user_id: int | None,
        nota: str | None = None,
    ) -> dict[str, Any]:
        """Sigue un órgano. **Idempotente**: seguir dos veces no duplica.

        El plegado sale de ``plegar_organo``, el mismo que usan los agregados.
        Si aquí se plegara distinto, «Ayuntamiento de Alcalá» seguido desde
        Mercado y desde Cuentas serían dos cuentas para el mismo órgano.

        El ``DO UPDATE`` sobre la nota y no un ``DO NOTHING``: volver a seguir
        algo que ya sigues con una nota nueva es una edición, y descartarla en
        silencio dejaría al usuario creyendo que la guardó.
        """
        norm = plegar_organo(organo_nombre) or normalizar_nombre(organo_nombre)
        with connect() as conn:
            cur = conn.execute(
                "INSERT INTO cuentas_objetivo "
                "(organization_id, organo_nombre, organo_norm, created_by_user_id, "
                " created_at, nota) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (organization_id, organo_norm) DO UPDATE SET "
                "  nota = COALESCE(EXCLUDED.nota, cuentas_objetivo.nota) "
                "RETURNING id, organization_id, organo_nombre, organo_norm, organo_id, "
                "  created_by_user_id, created_at, nota",
                (organization_id, organo_nombre.strip(), norm, user_id, now_utc_iso(), nota),
            )
            filas = rows_to_dicts(cur)
        return filas[0]

    def unfollow(self, organization_id: int, cuenta_id: int) -> bool:
        with connect() as conn:
            cur = conn.execute(
                "DELETE FROM cuentas_objetivo WHERE organization_id = %s AND id = %s",
                (organization_id, cuenta_id),
            )
            return bool(cur.rowcount > 0)

    def organos_seguidos(self, organization_id: int) -> list[str]:
        """Los nombres normalizados, para cruzar con alertas y publicaciones."""
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT organo_norm FROM cuentas_objetivo WHERE organization_id = %s",
                (organization_id,),
            )
            return [str(row[0]) for row in cur.fetchall()]

    def organizaciones_que_siguen(self, organo_norm: str) -> list[int]:
        """Qué organizaciones siguen este órgano. Lo consume el job de alertas.

        Es la consulta inversa de :meth:`organos_seguidos` y existe porque el
        job recorre publicaciones, no organizaciones: preguntarle a cada
        organización si sigue cada órgano sería el producto cartesiano.
        """
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT DISTINCT organization_id FROM cuentas_objetivo WHERE organo_norm = %s",
                (organo_norm,),
            )
            return [int(row[0]) for row in cur.fetchall()]


class EtiquetasRepository:
    """Etiquetas libres por organización y sus aplicaciones (D38)."""

    def list_for_organization(self, organization_id: int) -> list[dict[str, Any]]:
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT id, organization_id, nombre, nombre_norm, color, "
                "created_by_user_id, created_at "
                "FROM etiquetas WHERE organization_id = %s ORDER BY nombre",
                (organization_id,),
            )
            return rows_to_dicts(cur)

    def count(self, organization_id: int) -> int:
        with connect_read() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM etiquetas WHERE organization_id = %s",
                (organization_id,),
            ).fetchone()
        return int(row[0]) if row else 0

    def create(
        self, *, organization_id: int, nombre: str, color: str, user_id: int | None
    ) -> dict[str, Any] | None:
        """Crea una etiqueta. ``None`` si ya existía con ese nombre.

        El ``DO NOTHING`` distingue «ya existe» de «se creó» por el número de
        filas devueltas, que es lo que la ruta convierte en 200 o 201. Un
        ``DO UPDATE`` habría cambiado el color de la etiqueta existente sin
        que nadie lo pidiera.
        """
        with connect() as conn:
            cur = conn.execute(
                "INSERT INTO etiquetas "
                "(organization_id, nombre, nombre_norm, color, created_by_user_id, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (organization_id, nombre_norm) DO NOTHING "
                "RETURNING id, organization_id, nombre, nombre_norm, color, "
                "  created_by_user_id, created_at",
                (
                    organization_id,
                    nombre.strip(),
                    normalizar_nombre(nombre),
                    color,
                    user_id,
                    now_utc_iso(),
                ),
            )
            filas = rows_to_dicts(cur)
        return filas[0] if filas else None

    def delete(self, organization_id: int, etiqueta_id: int) -> bool:
        """Borra una etiqueta y, en cascada, sus aplicaciones (FK ON DELETE)."""
        with connect() as conn:
            cur = conn.execute(
                "DELETE FROM etiquetas WHERE organization_id = %s AND id = %s",
                (organization_id, etiqueta_id),
            )
            return bool(cur.rowcount > 0)

    def aplicar(
        self,
        *,
        organization_id: int,
        etiqueta_id: int,
        objeto_tipo: str,
        objeto_id: str,
        user_id: int | None,
    ) -> bool:
        """Aplica una etiqueta a un objeto. ``False`` si la etiqueta no es de
        esta organización — que es el control de aislamiento, y va en el
        ``WHERE`` del ``INSERT ... SELECT`` y no en una comprobación previa
        para que no haya ventana entre comprobar y escribir.
        """
        with connect() as conn:
            cur = conn.execute(
                "INSERT INTO etiquetas_aplicadas "
                "(organization_id, etiqueta_id, objeto_tipo, objeto_id, "
                " aplicada_por_user_id, created_at) "
                "SELECT %s, e.id, %s, %s, %s, %s FROM etiquetas e "
                "WHERE e.id = %s AND e.organization_id = %s "
                "ON CONFLICT (etiqueta_id, objeto_tipo, objeto_id) DO NOTHING",
                (
                    organization_id,
                    objeto_tipo,
                    objeto_id,
                    user_id,
                    now_utc_iso(),
                    etiqueta_id,
                    organization_id,
                ),
            )
            return bool(cur.rowcount > 0)

    def quitar(
        self, *, organization_id: int, etiqueta_id: int, objeto_tipo: str, objeto_id: str
    ) -> bool:
        with connect() as conn:
            cur = conn.execute(
                "DELETE FROM etiquetas_aplicadas WHERE organization_id = %s "
                "AND etiqueta_id = %s AND objeto_tipo = %s AND objeto_id = %s",
                (organization_id, etiqueta_id, objeto_tipo, objeto_id),
            )
            return bool(cur.rowcount > 0)

    def por_objeto(
        self, organization_id: int, objeto_tipo: str, objeto_ids: list[str]
    ) -> dict[str, list[dict[str, Any]]]:
        """``{objeto_id: [etiqueta, ...]}`` para pintar una lista de una vez.

        Una consulta por fila sería una por tarjeta del Radar; ésta resuelve
        la página entera.
        """
        if not objeto_ids:
            return {}
        marcadores = ", ".join(["%s"] * len(objeto_ids))
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT a.objeto_id, e.id, e.nombre, e.color "
                "FROM etiquetas_aplicadas a "
                "JOIN etiquetas e ON e.id = a.etiqueta_id "
                "WHERE a.organization_id = %s AND a.objeto_tipo = %s "
                f"  AND a.objeto_id IN ({marcadores}) "
                "ORDER BY e.nombre",
                (organization_id, objeto_tipo, *objeto_ids),
            )
            filas = rows_to_dicts(cur)
        agrupado: dict[str, list[dict[str, Any]]] = {}
        for fila in filas:
            agrupado.setdefault(str(fila["objeto_id"]), []).append(
                {"id": int(fila["id"]), "nombre": str(fila["nombre"]), "color": str(fila["color"])}
            )
        return agrupado

    def objetos_con_etiqueta(
        self, organization_id: int, etiqueta_id: int, objeto_tipo: str
    ) -> list[str]:
        """Los objetos que llevan una etiqueta. Es el filtro «por etiqueta»."""
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT objeto_id FROM etiquetas_aplicadas "
                "WHERE organization_id = %s AND etiqueta_id = %s AND objeto_tipo = %s",
                (organization_id, etiqueta_id, objeto_tipo),
            )
            return [str(row[0]) for row in cur.fetchall()]


class SegmentoRepository:
    """Cruce de una adjudicación con lo que una organización tiene abierto.

    Es lo que convierte «un competidor vigilado ha ganado algo» en «ha ganado
    **en tu terreno**» (F3.4): sin el cruce, la alerta de competidor es un
    boletín de todo lo que hace una empresa, y quien vigila a tres grandes
    recibe veinte adjudicaciones al día que no le tocan.
    """

    def es_mi_segmento(
        self, organization_id: int, *, organo_norm: str | None, cpv: str | None
    ) -> dict[str, Any] | None:
        """Por qué esta adjudicación toca a esta organización, o ``None``.

        Devuelve el **motivo** —cuenta objetivo seguida, u oportunidad abierta
        en el mismo CPV— y no un booleano, porque el aviso tiene que poder
        decirlo: «ha ganado en un órgano que sigues» y «ha ganado en un CPV
        donde tienes tres ofertas abiertas» piden reacciones distintas.

        Se comprueban las dos cosas en una consulta con ``UNION ALL`` y
        ``LIMIT 1``: basta con una razón, y dos consultas por adjudicación
        multiplicarían el coste del job por el número de organizaciones.
        """
        if not organo_norm and not cpv:
            return None
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT 'cuenta' AS motivo, organo_nombre AS referencia "
                "FROM cuentas_objetivo "
                "WHERE organization_id = %s AND organo_norm = %s "
                "UNION ALL "
                "SELECT 'oportunidad_abierta', l.titulo "
                "FROM pursuits p "
                "JOIN licitaciones l ON l.id_externo = p.licitacion_id "
                "WHERE p.organization_id = %s "
                "  AND p.status NOT IN ('won', 'lost', 'withdrawn') "
                "  AND l.cpv IS NOT NULL AND %s IS NOT NULL "
                "  AND substr(l.cpv, 1, 4) = substr(%s, 1, 4) "
                "LIMIT 1",
                (organization_id, organo_norm or "", organization_id, cpv, cpv),
            )
            filas = rows_to_dicts(cur)
        return filas[0] if filas else None

    def organizaciones_activas(self) -> list[int]:
        """Organizaciones con algo que vigilar: una cuenta o una oferta abierta.

        Acota el bucle del job a las que pueden recibir el aviso, en vez de
        recorrer todas las organizaciones para descartar la mayoría.
        """
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT DISTINCT organization_id FROM cuentas_objetivo "
                "UNION "
                "SELECT DISTINCT organization_id FROM pursuits "
                "WHERE status NOT IN ('won', 'lost', 'withdrawn')"
            )
            return [int(row[0]) for row in cur.fetchall()]


class ActividadRepository:
    """Feed de lo que hizo el equipo (F4.5).

    Lee del ledger ``pursuit_events``, no de ``pursuits.updated_at``: la
    columna dice que algo se tocó, y el ledger dice **qué**. Un feed de
    actividad que sólo pueda decir «alguien modificó una oportunidad» no es un
    feed, es un contador.
    """

    #: Eventos que un `member` **no** ve. Invitaciones y cambios de rol son
    #: administración, y el feed de actividad no es el sitio donde enterarse de
    #: quién ha entrado o a quién han cambiado de rol.
    EVENTOS_ADMIN: frozenset[str] = frozenset(
        {"membership_added", "membership_updated", "membership_revoked", "invitacion_enviada"}
    )

    def feed(
        self,
        organization_id: int,
        *,
        antes_de_id: int | None = None,
        actor_user_id: int | None = None,
        incluir_admin: bool = True,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Página del feed, del más reciente al más antiguo.

        Se pagina por ``id`` descendente y no por ``created_at``: el ledger es
        append-only, así que el id ya es el orden temporal, y con la fecha dos
        eventos del mismo segundo podrían repetirse o perderse entre páginas.
        """
        clauses = ["e.organization_id = %s"]
        params: list[Any] = [organization_id]
        if antes_de_id is not None:
            clauses.append("e.id < %s")
            params.append(antes_de_id)
        if actor_user_id is not None:
            clauses.append("e.actor_user_id = %s")
            params.append(actor_user_id)
        if not incluir_admin and self.EVENTOS_ADMIN:
            marcadores = ", ".join(["%s"] * len(self.EVENTOS_ADMIN))
            clauses.append(f"e.event_type NOT IN ({marcadores})")
            params.extend(sorted(self.EVENTOS_ADMIN))

        with connect_read() as conn:
            cur = conn.execute(
                "SELECT e.id, e.pursuit_id, e.event_type, e.actor_user_id, e.created_at, "
                "       u.display_name AS actor, p.licitacion_id, p.status, l.titulo "
                "FROM pursuit_events e "
                "JOIN pursuits p ON p.id = e.pursuit_id "
                "JOIN licitaciones l ON l.id_externo = p.licitacion_id "
                "LEFT JOIN users u ON u.id = e.actor_user_id "
                "WHERE " + " AND ".join(clauses) + " "
                "ORDER BY e.id DESC LIMIT %s",
                (*params, max(1, min(limit, 200))),
            )
            return rows_to_dicts(cur)

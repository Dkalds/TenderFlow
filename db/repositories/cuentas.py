"""Persistencia de cuentas objetivo (F1.5) y etiquetas de organización (F1.6).

Las dos son de **ámbito de organización**, no de usuario: seguir un órgano y
etiquetar una oportunidad son decisiones de equipo, y un comercial que se va
no debe llevarse la cartera de cuentas con él. Por eso ninguna consulta de
este módulo acepta ``user_key``: todas exigen ``organization_id``, y ése es el
aislamiento que el test comprueba.

Una cuenta es un **cliente**, no un órgano (v145): tiene nombre propio y uno o
varios órganos de contratación en ``cuenta_organos``. Todo lo que casa una
cuenta contra el corpus —avisos, cruce de competidores, resumen y ficha— lo
hace por sus órganos, comparando ``cuenta_organos.organo_norm`` con
:func:`organo_normalizado_sql`, que tiene índice propio desde v146.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from psycopg import errors as pg_errors

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts
from db.repositories.pursuits import _ESTADOS_TERMINALES_SQL
from db.repositories.renovaciones import rango_vencimiento_sql
from db.sql_fragments import (
    exclude_duplicados_sql,
    fecha_fin_origen_sql,
    fecha_fin_sql,
    fold_expr,
    organo_normalizado_sql,
    plegar_organo,
    technology_observed_sql,
)
from shared.estados import abierta_sql

__all__ = [
    "ActividadRepository",
    "CuentasRepository",
    "EtiquetasRepository",
    "NombreOcupadoError",
    "OrganoOcupadoError",
    "SegmentoRepository",
    "clave_de_nombre",
    "clave_de_organo",
    "normalizar_nombre",
]

#: Resultado de quitar un órgano de una cuenta.
QuitaOrgano = Literal["quitado", "no_existe", "ultimo"]


def normalizar_nombre(valor: str) -> str:
    """Clave de identidad de una etiqueta: plegada, en minúsculas, sin dobles
    espacios. «Q4» y « q4 » son la misma etiqueta escrita dos veces."""
    return " ".join(str(valor).strip().lower().split())


def clave_de_organo(nombre: str) -> str:
    """``organo_norm`` de un órgano: su identidad dentro de una organización.

    Único sitio donde se calcula. La usan el alta, el filtro «¿este órgano ya
    es de una cuenta?» del botón de Mercado y el buscador de órganos: si
    plegaran distinto, el botón diría «no lo sigues» de un órgano que sí es de
    una cuenta. Pliega con ``plegar_organo``, el gemelo Python de
    ``organo_normalizado_sql``: los avisos, el cruce de competidores y la ficha
    casan contra ``licitaciones`` con esa expresión, y un órgano plegado de
    otra forma no casaría con sus propias publicaciones.
    """
    return plegar_organo(nombre) or normalizar_nombre(nombre)


def clave_de_nombre(nombre: str) -> str:
    """``nombre_norm`` de una cuenta: plegada como un órgano y sin espacios
    repetidos. «Ayuntamiento de Alcalá» y «AYUNTAMIENTO  DE ALCALA» son la
    misma cuenta escrita dos veces. Gemela de ``_CLAVE_NOMBRE_SQL`` en v145."""
    return " ".join((plegar_organo(nombre) or "").split())


class OrganoOcupadoError(Exception):
    """Un órgano ya pertenece a otra cuenta de la organización.

    Lo lanza la escritura cuando la unicidad ``(organization_id, organo_norm)``
    de ``cuenta_organos`` la rechaza, dentro de la transacción: la excepción la
    deshace entera, así que una cuenta nueva no queda a medias.
    """

    def __init__(self, organo_norm: str) -> None:
        super().__init__(organo_norm)
        self.organo_norm = organo_norm


class NombreOcupadoError(Exception):
    """Otra cuenta de la organización ya se llama así."""


#: Columnas de una cuenta. ``nombre`` cae al órgano legado para las filas que
#: escribió el código anterior a v145 durante el despliegue.
_COLS_CUENTA = (
    "c.id, c.organization_id, COALESCE(c.nombre, c.organo_nombre) AS nombre, "
    "c.organo_nombre AS legado_organo_nombre, c.organo_norm AS legado_organo_norm, "
    "c.organo_id AS legado_organo_id, c.created_by_user_id, c.created_at, c.nota"
)

#: Orden de la lista: por nombre plegado, que es el que ve el usuario sin que
#: una tilde o una mayúscula lo muevan de sitio.
_ORDEN_CUENTAS = "ORDER BY COALESCE(c.nombre_norm, lower(c.organo_nombre)), c.id"

#: Universo de las cifras de la ficha y del resumen. Es el analítico del
#: producto (ADR-026): deja fuera las fuentes regionales que traen el censo
#: entero de su comunidad —``pscp_observed`` son ~584k filas de Cataluña de
#: cualquier materia—, que el criterio de F1.5 prohíbe sumar como censo.
_UNIVERSO = technology_observed_sql("l")

#: Plazo de ofertas abierto hoy: estado no terminal y fecha límite no pasada.
#: Sin la fecha, «abierta» contaría expedientes de 2019 que nadie cerró.
_ABIERTA = (
    f"({abierta_sql('l.estado')} "
    "AND substr(l.fecha_limite, 1, 10) >= to_char(CURRENT_DATE, 'YYYY-MM-DD'))"
)

#: Licitaciones de los órganos de las cuentas: el cruce que usan todos los
#: bloques. Va por el índice por expresión de v146.
_JOIN_LICITACIONES = f"JOIN licitaciones l ON {organo_normalizado_sql('l')} = co.organo_norm "


def _componer(cuentas: list[dict[str, Any]], organos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cada cuenta con sus órganos, en la forma del DTO ``CuentaObjetivo``.

    ``organo_nombre``/``organo_norm``/``organo_id`` son el contrato anterior a
    v145, cuando una cuenta era un órgano: ahora dicen el **primer** órgano de
    la cuenta, que en una cuenta de un solo órgano es exactamente lo que
    decían. Una fila sin órganos —sólo puede escribirla el código anterior
    durante el despliegue— cae a sus columnas legadas.
    """
    por_cuenta: dict[int, list[dict[str, Any]]] = {}
    for organo in organos:
        por_cuenta.setdefault(int(organo["cuenta_id"]), []).append(
            {
                "id": int(organo["id"]),
                "organo_nombre": str(organo["organo_nombre"]),
                "organo_norm": str(organo["organo_norm"]),
                "organo_id": organo.get("organo_id"),
            }
        )
    compuestas: list[dict[str, Any]] = []
    for cuenta in cuentas:
        propios = por_cuenta.get(int(cuenta["id"]), [])
        primero = propios[0] if propios else None
        nombre = str(cuenta.get("nombre") or (primero or {}).get("organo_nombre") or "")
        compuestas.append(
            {
                "id": int(cuenta["id"]),
                "organization_id": int(cuenta["organization_id"]),
                "nombre": nombre,
                "organo_nombre": (
                    primero["organo_nombre"]
                    if primero
                    else str(cuenta.get("legado_organo_nombre") or nombre)
                ),
                "organo_norm": (
                    primero["organo_norm"]
                    if primero
                    else str(cuenta.get("legado_organo_norm") or "")
                ),
                "organo_id": primero["organo_id"] if primero else cuenta.get("legado_organo_id"),
                "organos": propios,
                "created_by_user_id": cuenta.get("created_by_user_id"),
                "created_at": str(cuenta["created_at"]),
                "nota": cuenta.get("nota"),
            }
        )
    return compuestas


class CuentasRepository:
    """Cuentas objetivo de una organización y los órganos de cada una."""

    # ── Lectura ─────────────────────────────────────────────────────────────

    def _cuentas(
        self, conn: Any, organization_id: int, cuenta_ids: Sequence[int] | None = None
    ) -> list[dict[str, Any]]:
        filtro = "" if cuenta_ids is None else " AND c.id = ANY(%s)"
        params: tuple[Any, ...] = (
            (organization_id,) if cuenta_ids is None else (organization_id, list(cuenta_ids))
        )
        cuentas = rows_to_dicts(
            conn.execute(
                f"SELECT {_COLS_CUENTA} FROM cuentas_objetivo c "
                f"WHERE c.organization_id = %s{filtro} {_ORDEN_CUENTAS}",
                params,
            )
        )
        if not cuentas:
            return []
        organos = rows_to_dicts(
            conn.execute(
                "SELECT id, cuenta_id, organo_nombre, organo_norm, organo_id "
                "FROM cuenta_organos WHERE organization_id = %s AND cuenta_id = ANY(%s) "
                "ORDER BY cuenta_id, id",
                (organization_id, [int(c["id"]) for c in cuentas]),
            )
        )
        return _componer(cuentas, organos)

    def list_for_organization(self, organization_id: int) -> list[dict[str, Any]]:
        with connect_read() as conn:
            return self._cuentas(conn, organization_id)

    def get(self, organization_id: int, cuenta_id: int) -> dict[str, Any] | None:
        with connect_read() as conn:
            filas = self._cuentas(conn, organization_id, [cuenta_id])
        return filas[0] if filas else None

    def get_by_organo(self, organization_id: int, organo_nombre: str) -> dict[str, Any] | None:
        """La cuenta que contiene ese órgano en la organización, o ``None``.

        Compara por :func:`clave_de_organo`, no por el nombre tal cual: el
        panel de Mercado pregunta con la grafía del expediente
        («AYUNTAMIENTO DE ALCALÁ») y el órgano pudo añadirse escrito de otra
        forma («Ayuntamiento de Alcala»). Plegar en el cliente sería una
        tercera copia de la tabla de plegado; por eso pregunta aquí.
        """
        with connect_read() as conn:
            fila = conn.execute(
                "SELECT cuenta_id FROM cuenta_organos "
                "WHERE organization_id = %s AND organo_norm = %s",
                (organization_id, clave_de_organo(organo_nombre)),
            ).fetchone()
            if fila is None:
                return None
            filas = self._cuentas(conn, organization_id, [int(fila[0])])
        return filas[0] if filas else None

    def organos_ocupados(
        self, organization_id: int, organo_norms: Sequence[str]
    ) -> dict[str, dict[str, Any]]:
        """``{organo_norm: {cuenta_id, cuenta_nombre}}`` de los que ya tienen cuenta."""
        if not organo_norms:
            return {}
        with connect_read() as conn:
            filas = rows_to_dicts(
                conn.execute(
                    "SELECT co.organo_norm, co.cuenta_id, "
                    "       COALESCE(c.nombre, c.organo_nombre) AS cuenta_nombre "
                    "FROM cuenta_organos co JOIN cuentas_objetivo c ON c.id = co.cuenta_id "
                    "WHERE co.organization_id = %s AND co.organo_norm = ANY(%s)",
                    (organization_id, list(organo_norms)),
                )
            )
        return {
            str(f["organo_norm"]): {
                "cuenta_id": int(f["cuenta_id"]),
                "cuenta_nombre": str(f["cuenta_nombre"]),
            }
            for f in filas
        }

    # ── Escritura ───────────────────────────────────────────────────────────

    def _insertar_organo(
        self,
        conn: Any,
        *,
        organization_id: int,
        cuenta_id: int,
        organo_nombre: str,
        user_id: int | None,
    ) -> bool:
        """Añade el órgano a la cuenta. ``False`` si ya era de alguna cuenta."""
        fila = conn.execute(
            "INSERT INTO cuenta_organos "
            "(organization_id, cuenta_id, organo_nombre, organo_norm, "
            " created_by_user_id, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (organization_id, organo_norm) DO NOTHING RETURNING id",
            (
                organization_id,
                cuenta_id,
                organo_nombre.strip(),
                clave_de_organo(organo_nombre),
                user_id,
                now_utc_iso(),
            ),
        ).fetchone()
        return fila is not None

    def _insertar_cuenta(
        self, conn: Any, *, organization_id: int, nombre: str, user_id: int | None, nota: str | None
    ) -> int | None:
        """Crea la cuenta sin órganos. ``None`` si otra ya se llama así.

        Las columnas legadas (``organo_*``) quedan a ``NULL``: su unicidad es
        la de v105 y no puede chocar con un ``NULL`` (ver la cabecera de v145).
        """
        fila = conn.execute(
            "INSERT INTO cuentas_objetivo "
            "(organization_id, nombre, nombre_norm, created_by_user_id, created_at, nota) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (organization_id, nombre_norm) DO NOTHING RETURNING id",
            (
                organization_id,
                nombre.strip(),
                clave_de_nombre(nombre),
                user_id,
                now_utc_iso(),
                nota,
            ),
        ).fetchone()
        return int(fila[0]) if fila is not None else None

    def follow(
        self,
        *,
        organization_id: int,
        organo_nombre: str,
        user_id: int | None,
        nota: str | None = None,
    ) -> dict[str, Any]:
        """Sigue un órgano. **Idempotente**: seguir dos veces no duplica.

        Es el alta de un clic —el botón de Mercado y el contrato anterior a
        v145 de ``POST /cuentas`` con ``organo``—, así que decide sola dónde
        cae el órgano, en este orden:

        1. Si ya es de una cuenta, esa cuenta.
        2. Si hay una cuenta que se llama como el órgano, se añade a ella: es
           la cuenta que el equipo creó con ese nombre, y crear otra igual
           sería lo que la unicidad del nombre existe para impedir.
        3. Si no, una cuenta nueva con el nombre del órgano.

        Con ``nota`` la nota de la cuenta se sustituye: volver a seguir algo
        que ya sigues con una nota nueva es una edición, y descartarla en
        silencio dejaría al usuario creyendo que la guardó. Sin ``nota`` la que
        hubiera se queda.

        Dos altas simultáneas del mismo órgano caen en la misma cuenta: la que
        pierde la carrera por el órgano deshace la cuenta vacía que acababa de
        crear y devuelve la de la otra.
        """
        norm = clave_de_organo(organo_nombre)
        with connect() as conn:
            existente = conn.execute(
                "SELECT cuenta_id FROM cuenta_organos WHERE organization_id = %s "
                "AND organo_norm = %s",
                (organization_id, norm),
            ).fetchone()
            if existente is not None:
                cuenta_id = int(existente[0])
            else:
                creada = self._insertar_cuenta(
                    conn,
                    organization_id=organization_id,
                    nombre=organo_nombre,
                    user_id=user_id,
                    nota=nota,
                )
                if creada is not None:
                    cuenta_id = creada
                else:
                    homonima = conn.execute(
                        "SELECT id FROM cuentas_objetivo WHERE organization_id = %s "
                        "AND nombre_norm = %s",
                        (organization_id, clave_de_nombre(organo_nombre)),
                    ).fetchone()
                    if homonima is None:  # pragma: no cover - la unicidad lo impide
                        raise NombreOcupadoError(organo_nombre)
                    cuenta_id = int(homonima[0])
                if not self._insertar_organo(
                    conn,
                    organization_id=organization_id,
                    cuenta_id=cuenta_id,
                    organo_nombre=organo_nombre,
                    user_id=user_id,
                ):
                    # Otra alta se llevó el órgano entre la lectura y el INSERT.
                    if creada is not None:
                        conn.execute("DELETE FROM cuentas_objetivo WHERE id = %s", (creada,))
                    ganadora = conn.execute(
                        "SELECT cuenta_id FROM cuenta_organos WHERE organization_id = %s "
                        "AND organo_norm = %s",
                        (organization_id, norm),
                    ).fetchone()
                    if ganadora is None:  # pragma: no cover - el conflicto implica fila
                        raise OrganoOcupadoError(norm)
                    cuenta_id = int(ganadora[0])
            if nota is not None:
                conn.execute(
                    "UPDATE cuentas_objetivo SET nota = %s WHERE organization_id = %s AND id = %s",
                    (nota, organization_id, cuenta_id),
                )
            filas = self._cuentas(conn, organization_id, [cuenta_id])
        return filas[0]

    def crear(
        self,
        *,
        organization_id: int,
        nombre: str,
        organos: Sequence[str],
        user_id: int | None,
        nota: str | None = None,
    ) -> dict[str, Any] | None:
        """Crea una cuenta con varios órganos, todo o nada.

        ``None`` si otra cuenta de la organización ya se llama así. Lanza
        :class:`OrganoOcupadoError` si algún órgano ya es de otra cuenta; la
        transacción se deshace y no queda cuenta a medias. ``organos`` llega
        sin repetidos por clave: dos grafías del mismo órgano chocarían entre
        sí y parecería que otra cuenta lo tiene.
        """
        with connect() as conn:
            cuenta_id = self._insertar_cuenta(
                conn, organization_id=organization_id, nombre=nombre, user_id=user_id, nota=nota
            )
            if cuenta_id is None:
                return None
            for organo in organos:
                if not self._insertar_organo(
                    conn,
                    organization_id=organization_id,
                    cuenta_id=cuenta_id,
                    organo_nombre=organo,
                    user_id=user_id,
                ):
                    raise OrganoOcupadoError(clave_de_organo(organo))
            filas = self._cuentas(conn, organization_id, [cuenta_id])
        return filas[0]

    def anadir_organos(
        self,
        *,
        organization_id: int,
        cuenta_id: int,
        organos: Sequence[str],
        user_id: int | None,
    ) -> dict[str, Any] | None:
        """Añade órganos a una cuenta. ``None`` si la cuenta no es de la organización.

        Idempotente para los que ya eran de **esta** cuenta. Uno que es de otra
        lanza :class:`OrganoOcupadoError` y deshace los demás: añadir la mitad
        de una selección dejaría al usuario sin saber qué entró.
        """
        with connect() as conn:
            if (
                conn.execute(
                    "SELECT 1 FROM cuentas_objetivo WHERE organization_id = %s AND id = %s "
                    "FOR UPDATE",
                    (organization_id, cuenta_id),
                ).fetchone()
                is None
            ):
                return None
            for organo in organos:
                if self._insertar_organo(
                    conn,
                    organization_id=organization_id,
                    cuenta_id=cuenta_id,
                    organo_nombre=organo,
                    user_id=user_id,
                ):
                    continue
                duena = conn.execute(
                    "SELECT cuenta_id FROM cuenta_organos WHERE organization_id = %s "
                    "AND organo_norm = %s",
                    (organization_id, clave_de_organo(organo)),
                ).fetchone()
                if duena is None or int(duena[0]) != cuenta_id:
                    raise OrganoOcupadoError(clave_de_organo(organo))
            filas = self._cuentas(conn, organization_id, [cuenta_id])
        return filas[0] if filas else None

    def quitar_organo(
        self, *, organization_id: int, cuenta_id: int, cuenta_organo_id: int
    ) -> QuitaOrgano:
        """Quita un órgano de la cuenta, salvo que sea el último.

        Una cuenta sin órganos no casaría con nada y no avisaría de nada, sin
        que la lista lo dijera: para quedarse sin órganos, se deja de seguir.
        El ``FOR UPDATE`` sobre la cuenta serializa dos bajas simultáneas de
        sus dos últimos órganos, que de otro modo contarían dos cada una y la
        dejarían vacía.
        """
        with connect() as conn:
            if (
                conn.execute(
                    "SELECT 1 FROM cuentas_objetivo WHERE organization_id = %s AND id = %s "
                    "FOR UPDATE",
                    (organization_id, cuenta_id),
                ).fetchone()
                is None
            ):
                return "no_existe"
            ids = [
                int(r[0])
                for r in conn.execute(
                    "SELECT id FROM cuenta_organos WHERE organization_id = %s AND cuenta_id = %s",
                    (organization_id, cuenta_id),
                ).fetchall()
            ]
            if cuenta_organo_id not in ids:
                return "no_existe"
            if len(ids) == 1:
                return "ultimo"
            conn.execute(
                "DELETE FROM cuenta_organos WHERE organization_id = %s AND id = %s",
                (organization_id, cuenta_organo_id),
            )
        return "quitado"

    def dejar_organo(
        self, *, organization_id: int, organo_nombre: str
    ) -> Literal["quitado", "cuenta_borrada", "no_seguido"]:
        """Deja de seguir un órgano: la inversa del alta de un clic (:meth:`follow`).

        Si su cuenta tiene más órganos, se quita sólo éste y la cuenta sigue
        avisando por los demás. Si era el único, la cuenta entera se va, con
        sus etiquetas (:meth:`unfollow`): una cuenta sin órganos no avisaría de
        nada. El órgano se busca por su clave plegada, así que la grafía del
        expediente encuentra el que se añadió escrito de otra forma.
        """
        norm = clave_de_organo(organo_nombre)
        with connect() as conn:
            fila = conn.execute(
                "SELECT cuenta_id FROM cuenta_organos WHERE organization_id = %s "
                "AND organo_norm = %s",
                (organization_id, norm),
            ).fetchone()
            if fila is None:
                return "no_seguido"
            cuenta_id = int(fila[0])
            conn.execute(
                "SELECT 1 FROM cuentas_objetivo WHERE organization_id = %s AND id = %s FOR UPDATE",
                (organization_id, cuenta_id),
            )
            restantes = conn.execute(
                "SELECT COUNT(*) FROM cuenta_organos WHERE organization_id = %s "
                "AND cuenta_id = %s AND organo_norm <> %s",
                (organization_id, cuenta_id, norm),
            ).fetchone()
            if restantes is not None and int(restantes[0]) > 0:
                conn.execute(
                    "DELETE FROM cuenta_organos WHERE organization_id = %s AND organo_norm = %s",
                    (organization_id, norm),
                )
                return "quitado"
            # En la misma transacción que el recuento: entre las dos, otra
            # petición podría añadir un órgano y se borraría una cuenta viva.
            return (
                "cuenta_borrada" if self._borrar(conn, organization_id, cuenta_id) else "no_seguido"
            )

    def actualizar(
        self,
        *,
        organization_id: int,
        cuenta_id: int,
        nombre: str | None = None,
        nota: str | None = None,
        cambiar_nota: bool = False,
    ) -> dict[str, Any] | None:
        """Renombra la cuenta y/o cambia su nota. ``None`` si no es de la organización.

        ``cambiar_nota`` distingue «no toques la nota» de «bórrala»: los dos
        llegan como ``nota=None``. Lanza :class:`NombreOcupadoError` si otra
        cuenta ya se llama así.
        """
        asignaciones: list[str] = []
        params: list[Any] = []
        if nombre is not None:
            asignaciones.append("nombre = %s, nombre_norm = %s")
            params.extend([nombre.strip(), clave_de_nombre(nombre)])
        if cambiar_nota:
            asignaciones.append("nota = %s")
            params.append(nota)
        with connect() as conn:
            if asignaciones:
                try:
                    cur = conn.execute(
                        f"UPDATE cuentas_objetivo SET {', '.join(asignaciones)} "
                        "WHERE organization_id = %s AND id = %s",
                        (*params, organization_id, cuenta_id),
                    )
                except pg_errors.UniqueViolation as exc:
                    raise NombreOcupadoError(nombre or "") from exc
                if cur.rowcount == 0:
                    return None
            filas = self._cuentas(conn, organization_id, [cuenta_id])
        return filas[0] if filas else None

    def unfollow(self, organization_id: int, cuenta_id: int) -> bool:
        """Deja de seguir la cuenta: sus órganos en cascada y sus etiquetas.

        Las etiquetas se borran a mano porque ``etiquetas_aplicadas`` es una
        unión polimórfica sin FK al objeto (v105), y en la misma transacción:
        si se quedaran, el filtro «por etiqueta» seguiría devolviendo una cuenta
        que ya no existe. Sólo las de tipo ``cuenta`` con ese id: una
        oportunidad con el mismo número no tiene nada que ver.
        """
        with connect() as conn:
            return self._borrar(conn, organization_id, cuenta_id)

    def _borrar(self, conn: Any, organization_id: int, cuenta_id: int) -> bool:
        """El borrado de :meth:`unfollow`, dentro de la transacción de ``conn``."""
        cur = conn.execute(
            "DELETE FROM cuentas_objetivo WHERE organization_id = %s AND id = %s",
            (organization_id, cuenta_id),
        )
        if cur.rowcount == 0:
            return False
        conn.execute(
            "DELETE FROM etiquetas_aplicadas WHERE organization_id = %s "
            "AND objeto_tipo = 'cuenta' AND objeto_id = %s",
            (organization_id, str(cuenta_id)),
        )
        return True

    # ── Buscador de órganos para el alta ────────────────────────────────────

    def buscar_organos(
        self, organization_id: int, termino: str, limite: int
    ) -> list[dict[str, Any]]:
        """Órganos cuyo nombre contiene ``termino``, con cuántos expedientes
        tienen y de qué cuenta son, si lo son.

        El patrón es el de la paleta de búsqueda (``busqueda._patron``: plegado
        y con los comodines del usuario escapados), para que un órgano que la
        paleta encuentra también lo encuentre el alta de una cuenta.

        Cuenta el corpus entero y no el universo de la ficha: aquí se busca un
        órgano por su nombre, y uno que sólo publica en una fuente regional
        también existe. El número es el que ve el usuario para elegir entre
        grafías parecidas.

        El primer ``LIKE`` no filtra nada que el segundo deje pasar —el
        patrón llega sin espacios en los bordes, y lo que contiene el nombre
        recortado lo contiene el entero—: está para el trigram de órgano de
        v143, cuya expresión es ``fold_expr`` sin ``btrim``. Sin él, cada
        tecla del buscador recorre la tabla entera.
        """
        from db.repositories.busqueda import _patron

        patron = _patron(termino)
        normalizado = organo_normalizado_sql("l")
        with connect_read() as conn:
            return rows_to_dicts(
                conn.execute(
                    "SELECT o.organo_norm, o.organo_nombre, o.expedientes, "
                    "       co.cuenta_id, COALESCE(c.nombre, c.organo_nombre) AS cuenta_nombre "
                    "FROM ("
                    f"  SELECT {normalizado} AS organo_norm, "
                    "          min(l.organo_contratacion) AS organo_nombre, "
                    "          COUNT(*) AS expedientes "
                    "  FROM licitaciones l "
                    f"  WHERE {fold_expr('l.organo_contratacion')} LIKE %s "
                    f"    AND {normalizado} LIKE %s "
                    f"  GROUP BY {normalizado} "
                    "  ORDER BY COUNT(*) DESC LIMIT %s"
                    ") o "
                    "LEFT JOIN cuenta_organos co "
                    "  ON co.organization_id = %s AND co.organo_norm = o.organo_norm "
                    "LEFT JOIN cuentas_objetivo c ON c.id = co.cuenta_id "
                    "ORDER BY o.expedientes DESC, o.organo_nombre",
                    (patron, patron, limite, organization_id),
                )
            )

    # ── Resumen de la lista y ficha (F1.5) ──────────────────────────────────

    def resumen(self, organization_id: int, *, meses_vencimiento: int) -> list[dict[str, Any]]:
        """Por cuenta: abiertas hoy, última publicación, contratos que vencen y
        oportunidades activas. Tres agregados por ``cuenta_id``, uno por tabla.

        Las cuentas sin nada no aparecen: la ausencia es cero y la pone el
        servicio, que es quien sabe qué cuentas hay.
        """
        fecha_fin = fecha_fin_sql()
        with connect_read() as conn:
            publicaciones = rows_to_dicts(
                conn.execute(
                    "SELECT co.cuenta_id, "
                    f"       COUNT(*) FILTER (WHERE {_ABIERTA}) AS abiertas, "
                    "       MAX(l.primera_extraccion) AS ultima_publicacion "
                    "FROM cuenta_organos co "
                    f"{_JOIN_LICITACIONES}"
                    f"WHERE co.organization_id = %s AND {_UNIVERSO} "
                    f"  AND {exclude_duplicados_sql()} "
                    "GROUP BY co.cuenta_id",
                    (organization_id,),
                )
            )
            vencimientos = rows_to_dicts(
                conn.execute(
                    "SELECT co.cuenta_id, COUNT(DISTINCT a.licitacion_id) AS vencen "
                    "FROM cuenta_organos co "
                    f"{_JOIN_LICITACIONES}"
                    "JOIN adjudicaciones a ON a.licitacion_id = l.id_externo "
                    f"WHERE co.organization_id = %s AND {_UNIVERSO} "
                    f"  AND {exclude_duplicados_sql()} "
                    f"  AND {fecha_fin} {rango_vencimiento_sql()} "
                    "GROUP BY co.cuenta_id",
                    (organization_id, meses_vencimiento),
                )
            )
            oportunidades = rows_to_dicts(
                conn.execute(
                    "SELECT co.cuenta_id, COUNT(DISTINCT p.id) AS activas "
                    "FROM pursuits p "
                    "JOIN licitaciones l ON l.id_externo = p.licitacion_id "
                    "JOIN cuenta_organos co ON co.organization_id = p.organization_id "
                    f"  AND co.organo_norm = {organo_normalizado_sql('l')} "
                    "WHERE p.organization_id = %s "
                    f"  AND p.status NOT IN {_ESTADOS_TERMINALES_SQL} "
                    "GROUP BY co.cuenta_id",
                    (organization_id,),
                )
            )
        por_cuenta: dict[int, dict[str, Any]] = {}
        for fila in publicaciones:
            por_cuenta.setdefault(int(fila["cuenta_id"]), {}).update(
                abiertas=int(fila["abiertas"] or 0),
                ultima_publicacion=fila.get("ultima_publicacion"),
            )
        for fila in vencimientos:
            por_cuenta.setdefault(int(fila["cuenta_id"]), {})["vencen"] = int(fila["vencen"] or 0)
        for fila in oportunidades:
            por_cuenta.setdefault(int(fila["cuenta_id"]), {})["oportunidades_activas"] = int(
                fila["activas"] or 0
            )
        return [{"cuenta_id": cuenta_id, **valores} for cuenta_id, valores in por_cuenta.items()]

    def publicaciones_de_cuenta(
        self, organization_id: int, cuenta_id: int, *, dias: int, limit: int
    ) -> tuple[int, list[dict[str, Any]]]:
        """``(total, primeras)``: expedientes vistos por primera vez en los
        últimos ``dias`` días, del más reciente al más antiguo.

        La ventana va por ``primera_extraccion``, como el aviso de publicación
        nueva: es cuando el equipo pudo enterarse, no la fecha que declara una
        fuente que publica con retraso.
        """
        base = (
            "FROM cuenta_organos co "
            f"{_JOIN_LICITACIONES}"
            "WHERE co.organization_id = %s AND co.cuenta_id = %s "
            f"  AND {_UNIVERSO} AND {exclude_duplicados_sql()} "
            "  AND l.primera_extraccion >= "
            "      to_char(CURRENT_DATE - %s * INTERVAL '1 day', 'YYYY-MM-DD') "
        )
        params = (organization_id, cuenta_id, dias)
        with connect_read() as conn:
            fila = conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()
            items = rows_to_dicts(
                conn.execute(
                    "SELECT l.id_externo, l.titulo, l.organo_contratacion AS organo, l.importe, "
                    "       l.importe_tipo, l.fecha_publicacion, l.fecha_limite, "
                    "       l.primera_extraccion, l.url, "
                    f"      COALESCE({_ABIERTA}, false) AS abierta "
                    f"{base}"
                    "ORDER BY l.primera_extraccion DESC, l.id_externo LIMIT %s",
                    (*params, limit),
                )
            )
        return (int(fila[0]) if fila else 0), items

    def vencimientos_de_cuenta(
        self, organization_id: int, cuenta_id: int, *, meses: int, limit: int
    ) -> tuple[int, list[dict[str, Any]]]:
        """``(contratos, filas)``: adjudicaciones de los órganos de la cuenta cuya
        fecha de fin efectiva cae en los próximos ``meses`` meses.

        Cada fila es un par contrato-adjudicatario, como en Renovaciones: una
        UTE o un contrato por lotes con varios adjudicatarios son varias
        empresas a las que desplazar. El total cuenta **contratos**, no pares.
        La fecha es la misma ``fecha_fin_sql`` de Renovaciones y del aviso de
        vencimiento, con su origen para que la UI rotule las estimadas.
        """
        fecha_fin = fecha_fin_sql()
        base = (
            "FROM cuenta_organos co "
            f"{_JOIN_LICITACIONES}"
            "JOIN adjudicaciones a ON a.licitacion_id = l.id_externo "
            "LEFT JOIN empresas e ON e.empresa_id = a.empresa_id "
            "WHERE co.organization_id = %s AND co.cuenta_id = %s "
            f"  AND {_UNIVERSO} AND {exclude_duplicados_sql()} "
            f"  AND {fecha_fin} {rango_vencimiento_sql()} "
        )
        params = (organization_id, cuenta_id, meses)
        with connect_read() as conn:
            fila = conn.execute(f"SELECT COUNT(DISTINCT a.licitacion_id) {base}", params).fetchone()
            items = rows_to_dicts(
                conn.execute(
                    "SELECT a.licitacion_id, l.titulo, l.organo_contratacion AS organo, "
                    "       a.empresa_id, COALESCE(e.nombre_canonico, a.nombre) AS empresa, "
                    "       a.importe_adjudicado, "
                    f"      {fecha_fin} AS fecha_fin, {fecha_fin_origen_sql()} AS fecha_fin_origen "
                    f"{base}"
                    "ORDER BY fecha_fin ASC, a.id ASC LIMIT %s",
                    (*params, limit),
                )
            )
        return (int(fila[0]) if fila else 0), items

    def oportunidades_de_cuenta(
        self, organization_id: int, cuenta_id: int, *, limit: int
    ) -> list[dict[str, Any]]:
        """Oportunidades de la organización sobre expedientes de la cuenta.

        Las activas primero y, dentro, por la próxima acción que antes vence:
        es la pregunta de quien abre la ficha —«¿qué tenemos con este cliente y
        qué toca ahora?»—. Las cerradas van detrás, como historial.

        Sin ``DISTINCT``: el expediente de una oportunidad tiene un solo órgano,
        y un órgano es de una sola cuenta por organización, así que cada
        oportunidad sale una vez.
        """
        with connect_read() as conn:
            return rows_to_dicts(
                conn.execute(
                    "SELECT p.id, p.licitacion_id, p.lote_numero, "
                    "       l.titulo, p.status, p.next_action, p.next_action_due, "
                    "       u.display_name AS responsable, "
                    f"      (p.status NOT IN {_ESTADOS_TERMINALES_SQL}) AS activa "
                    "FROM pursuits p "
                    "JOIN licitaciones l ON l.id_externo = p.licitacion_id "
                    "JOIN cuenta_organos co ON co.organization_id = p.organization_id "
                    f"  AND co.organo_norm = {organo_normalizado_sql('l')} "
                    "LEFT JOIN users u ON u.id = p.responsible_user_id "
                    "WHERE p.organization_id = %s AND co.cuenta_id = %s "
                    "ORDER BY activa DESC, p.next_action_due ASC NULLS LAST, "
                    "         p.updated_at DESC, p.id "
                    "LIMIT %s",
                    (organization_id, cuenta_id, limit),
                )
            )

    # ── Avisos de cuenta (F1.5, por el outbox) ──────────────────────────────

    def publicaciones_nuevas(
        self, *, desde_iso: str, hasta_iso: str, limit: int = 500
    ) -> list[dict[str, Any]]:
        """Expedientes vistos por primera vez en ``(desde_iso, hasta_iso]`` de
        órganos que alguna organización tiene en una cuenta.

        «Publicación nueva» es ``primera_extraccion`` —el primer día que el
        corpus vio el expediente— y no ``fecha_publicacion``: una fuente que
        publica con retraso traería expedientes con fecha de hace un mes, y
        el aviso tiene que salir cuando el comercial puede enterarse, no
        cuando la fuente dice que pasó.

        ``organo`` es el órgano que publicó y ``cuenta_nombre`` el cliente al
        que pertenece: en una cuenta de varios órganos no son lo mismo.

        El universo es el de la ficha (:data:`_UNIVERSO`, sin duplicados
        confirmados): un aviso que la ficha no enseña manda al comercial a
        buscar algo que no está, y el censo catalán de ``pscp_observed`` son
        expedientes de cualquier materia.
        """

        with connect_read() as conn:
            cur = conn.execute(
                "SELECT co.organization_id, co.cuenta_id, co.organo_nombre, "
                "       COALESCE(c.nombre, c.organo_nombre) AS cuenta_nombre, "
                "       l.id_externo, l.titulo, l.importe, l.fecha_limite, "
                "       l.primera_extraccion "
                "FROM licitaciones l "
                f"JOIN cuenta_organos co ON co.organo_norm = {organo_normalizado_sql('l')} "
                "JOIN cuentas_objetivo c ON c.id = co.cuenta_id "
                "WHERE l.primera_extraccion > %s AND l.primera_extraccion <= %s "
                f"  AND {_UNIVERSO} AND {exclude_duplicados_sql()} "
                "ORDER BY l.primera_extraccion, l.id_externo, co.organization_id "
                "LIMIT %s",
                (desde_iso, hasta_iso, limit),
            )
            return rows_to_dicts(cur)

    def vencimientos_entrando(
        self, *, dias_desde: int, dias_hasta: int, limit: int = 500
    ) -> list[dict[str, Any]]:
        """Contratos adjudicados de órganos de alguna cuenta cuya fecha de fin
        efectiva cae entre hoy + ``dias_desde`` y hoy + ``dias_hasta``.

        El productor pide una **franja** pegada al borde de los seis meses y no
        la ventana entera: lo que se avisa es «este contrato acaba de entrar en
        los seis meses», no «estos son todos los que vencen», que ya enseña la
        ficha de la cuenta. La franja tiene anchura para que un cierre caído
        unos días no se salte ningún contrato; la idempotencia la pone el
        productor.

        La fecha es :data:`FECHA_FIN_SQL` (fin explícito, o inicio/adjudicación
        más duración), la misma que usan Renovaciones y la ficha de la cuenta.
        El universo también es el de la ficha, por lo mismo que en
        :meth:`publicaciones_nuevas`.
        """

        fecha_fin = fecha_fin_sql()
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT DISTINCT ON (co.organization_id, l.id_externo) "
                "       co.organization_id, co.cuenta_id, co.organo_nombre, "
                "       COALESCE(c.nombre, c.organo_nombre) AS cuenta_nombre, "
                f"      l.id_externo, l.titulo, {fecha_fin} AS fecha_fin "
                "FROM adjudicaciones a "
                "JOIN licitaciones l ON l.id_externo = a.licitacion_id "
                f"JOIN cuenta_organos co ON co.organo_norm = {organo_normalizado_sql('l')} "
                "JOIN cuentas_objetivo c ON c.id = co.cuenta_id "
                f"WHERE {fecha_fin} BETWEEN "
                "      to_char(CURRENT_DATE + %s * INTERVAL '1 day', 'YYYY-MM-DD') "
                "  AND to_char(CURRENT_DATE + %s * INTERVAL '1 day', 'YYYY-MM-DD') "
                f"  AND {_UNIVERSO} AND {exclude_duplicados_sql()} "
                "ORDER BY co.organization_id, l.id_externo "
                "LIMIT %s",
                (dias_desde, dias_hasta, limit),
            )
            return rows_to_dicts(cur)

    def miembros_activos(self, organization_id: int) -> list[int]:
        """Ids de los miembros activos: a quién avisa una cuenta de equipo."""
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT user_id FROM organization_memberships "
                "WHERE organization_id = %s AND status = 'active' ORDER BY user_id",
                (organization_id,),
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

    def get_by_nombre(self, organization_id: int, nombre: str) -> dict[str, Any] | None:
        """La etiqueta de ese nombre, o ``None``. Busca por ``nombre_norm``,
        que es la clave de identidad y tiene la unique de v105 detrás."""
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT id, organization_id, nombre, nombre_norm, color, "
                "created_by_user_id, created_at "
                "FROM etiquetas WHERE organization_id = %s AND nombre_norm = %s",
                (organization_id, normalizar_nombre(nombre)),
            )
            filas = rows_to_dicts(cur)
        return filas[0] if filas else None

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

    def organizaciones_en_segmento(
        self, *, organo_norm: str | None, cpv: str | None
    ) -> list[tuple[int, dict[str, Any]]]:
        """Qué organizaciones tienen esta adjudicación en su terreno, y por qué.

        Es la consulta **inversa**: el job recorre publicaciones, no
        organizaciones, así que preguntarle a cada organización activa si esta
        adjudicación le toca era el producto cartesiano —doscientas
        organizaciones por veinte adjudicaciones son cuatro mil viajes por
        pasada—. Aquí sale en una.

        Devuelve el motivo y no un booleano porque el aviso tiene que poder
        decirlo: «ha ganado en un órgano que sigues» y «ha ganado en un CPV
        donde tienes ofertas abiertas» piden reacciones distintas. Si las dos
        razones valen, gana la cuenta objetivo: es la que el usuario declaró a
        mano. La referencia de la cuenta es su **nombre** —el cliente—, no el
        órgano concreto: en una cuenta de varios órganos es lo que el equipo
        reconoce.

        El CPV se compara con ``LIKE 'xxxx%'`` y no con ``substr(cpv,1,4)``,
        que envolvía la columna y dejaba ``idx_cpv`` sin usar.

        Los ``%s::text IS NOT NULL`` llevan el cast a propósito. psycopg manda
        los ``str`` y los ``None`` sin tipo (``unknown``), y en un ``IS NOT
        NULL`` Postgres no tiene de dónde inferirlo: sin el cast cada llamada
        fallaba con «could not determine data type of parameter $1», y
        ``_en_mi_segmento`` lo convertía en lista vacía. El «por qué te
        importa» de F3.4 no llegaba a ningún email (run 34517205501: nueve
        adjudicaciones, nueve fallos).
        """
        if not organo_norm and not cpv:
            return []
        prefijo_cpv = str(cpv)[:4] if cpv else None
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT DISTINCT ON (organization_id) organization_id, motivo, referencia "
                "FROM ("
                "  SELECT co.organization_id, 0 AS prioridad, 'cuenta' AS motivo, "
                "         COALESCE(c.nombre, co.organo_nombre) AS referencia "
                "  FROM cuenta_organos co "
                "  JOIN cuentas_objetivo c ON c.id = co.cuenta_id "
                "  WHERE %s::text IS NOT NULL AND co.organo_norm = %s "
                "  UNION ALL "
                "  SELECT p.organization_id, 1, 'oportunidad_abierta', l.titulo "
                "  FROM pursuits p "
                "  JOIN licitaciones l ON l.id_externo = p.licitacion_id "
                "  WHERE %s::text IS NOT NULL "
                "    AND p.status NOT IN ('won', 'lost', 'withdrawn') "
                "    AND l.cpv LIKE %s "
                ") m "
                "ORDER BY organization_id, prioridad",
                (organo_norm, organo_norm or "", prefijo_cpv, f"{prefijo_cpv or ''}%"),
            )
            filas = rows_to_dicts(cur)
        return [
            (
                int(f["organization_id"]),
                {"motivo": str(f["motivo"]), "referencia": f.get("referencia")},
            )
            for f in filas
        ]


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
    #:
    #: Hoy no excluye nada: `pursuit_events` sólo contiene `pursuit.created`,
    #: `pursuit.updated` y `KIT_EVENT_TYPE` —las membresías se registran en el
    #: log de auditoría (`db/events.py`), no en este ledger—. El filtro se deja
    #: puesto porque es el sitio correcto para cuando lleguen, pero la respuesta
    #: **no** puede decirle a un `member` que se le ocultó algo: ver
    #: `services/direccion.py::actividad_de_organizacion`.
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

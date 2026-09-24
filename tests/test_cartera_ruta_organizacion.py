"""F4.3 — las tres rutas de cartera: qué devuelven, en qué orden y a quién.

``GET /api/v1/pursuits/cartera`` (la lista), ``/cartera/resumen`` (sus
agregados) y ``/cartera/{id}/eventos`` (el historial de un contrato). Van
juntas porque comparten escenario y, sobre todo, porque lo que hay que
demostrar es que las tres ven la **misma** cartera: un resumen que contara
sobre otro universo desmentiría la tabla en la misma pantalla.

``tests/test_cartera.py`` fija la aritmética pura (fecha de fin efectiva,
ventana de relicitación). Nada ejercitaba la ruta ni la consulta de
``CarteraRepository``, y es ahí donde se decide lo que la ruta entrega: el JOIN
que trae órgano y tecnología, el orden por fecha de fin con los contratos sin
fecha al final y, sobre todo, el filtro por organización. La cartera es dato
corporativo —importes adjudicados, cuándo se relicita lo que uno ejecuta— y la
de otra organización no puede asomar en la propia.

Las filas se siembran con ``upsert`` directamente: lo que queda fijado aquí es
el camino de lectura. El escritor (cerrar como ganada, resincronización,
«preparar renovación») tiene sus tests en ``tests/test_cartera_escritor*.py``.

``meses_restantes`` se mide contra el reloj de ``services.cartera``. El
escenario lo congela en ``_HOY`` y siembra las fechas relativas a ese mismo
día, así que ni sembrar y pedir en meses distintos ni el paso del tiempo
cambian lo que se comprueba.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, tzinfo
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from api.routes.dual_auth import require_any_auth
from db.repositories.cartera import CarteraRepository
from db.repositories.organizations import OrganizationRepository
from shared.dto import PursuitCreate

_RUTA = "/api/v1/pursuits/cartera"
#: Los agregados de la misma cartera y el historial de un contrato suyo. Se
#: prueban aquí y no aparte porque comparten escenario, ámbito y 403: lo que
#: hay que demostrar es que las tres rutas ven **la misma** cartera.
_RUTA_RESUMEN = f"{_RUTA}/resumen"

_SIN_FECHA = "LIC-CART-SIN-FECHA"
_LEJANO = "LIC-CART-LEJANO"
_CERCANO = "LIC-CART-CERCANO"
_EMPATE = "LIC-CART-EMPATE"
_AJENO = "LIC-CART-AJENO"
_MITAD_DE_MES = "LIC-CART-MITAD-DE-MES"

#: El rechazo por membresía, tal como lo formula ``resolve_organization``.
_NO_MIEMBRO = "No perteneces a esta organización."

#: El «hoy» de estos tests. Un día ya pasado a propósito: si el reloj congelado
#: dejara de aplicarse, el real no volvería a caer en este mes y
#: ``meses_restantes`` fallaría siempre, no un día al azar.
_HOY = date(2025, 3, 10)


class _RelojFijo(datetime):
    """``datetime`` cuyo ``now`` cae siempre en ``_HOY``, a mediodía."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> _RelojFijo:
        return cls(_HOY.year, _HOY.month, _HOY.day, 12, tzinfo=tz or UTC)


class _Sesion:
    """Sustituye ``require_any_auth``: cada test decide quién pide."""

    user_id: int | None = None

    def __call__(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "auth_method": "session",
            "user_key": f"cartera-{self.user_id}",
        }


@pytest.fixture()
def sesion(api_db: Any) -> Iterator[_Sesion]:
    from api.app import app

    principal = _Sesion()
    app.dependency_overrides[require_any_auth] = principal
    try:
        yield principal
    finally:
        app.dependency_overrides.pop(require_any_auth, None)


def _user(email: str) -> int:
    from db.users import create_user

    return create_user(email=email, password_hash="test-hash")  # pragma: allowlist secret


def _licitacion(id_externo: str, *, organo: str, tecnologia: str, cpv: str) -> None:
    from db.database import connect

    with connect() as conn:
        conn.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, organo_contratacion, tecnologia, cpv, "
            " fecha_limite, fecha_extraccion) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                id_externo,
                f"Contrato {id_externo}",
                organo,
                tecnologia,
                cpv,
                "2023-11-15T10:00:00+00:00",
                "2023-11-01T10:00:00+00:00",
            ),
        )


def _primero_de_mes(desplazamiento: int) -> date:
    """El día 1 del mes que queda a ``desplazamiento`` meses de ``_HOY``.

    Día 1 a propósito: el recorte de fin de mes (31 → 28) ya lo fija
    ``tests/test_cartera.py``, y aquí solo importa que los meses restantes y la
    ventana salgan de la fecha sembrada sin un recorte que los enturbie.
    """
    ano, mes = divmod(_HOY.year * 12 + (_HOY.month - 1) + desplazamiento, 12)
    return date(ano, mes + 1, 1)


def _contrato(
    owner: int,
    organization_id: int,
    licitacion_id: str,
    *,
    fin: date | None,
    origen: str | None,
    importe: float,
    prorrogas: int = 0,
) -> None:
    """Oportunidad real en la organización y su entrada de cartera."""
    from services.pursuits import create_pursuit

    creado, _ = create_pursuit(
        owner, PursuitCreate(licitacion_id=licitacion_id, organization_id=organization_id)
    )
    CarteraRepository().upsert(
        organization_id=organization_id,
        pursuit_id=int(creado.id),
        licitacion_id=licitacion_id,
        fecha_inicio="2024-01-15",
        fecha_fin_efectiva=None if fin is None else fin.isoformat(),
        fecha_fin_origen=origen,
        importe_adjudicado=importe,
        prorrogas_aplicadas=prorrogas,
    )


@dataclass(frozen=True)
class _Escenario:
    owner: int
    organizacion: int
    owner_ajeno: int
    organizacion_ajena: int


@pytest.fixture()
def escenario(sesion: _Sesion, monkeypatch: pytest.MonkeyPatch) -> _Escenario:
    """Dos organizaciones con cartera; el orden de inserción no es el esperado.

    Se inserta primero el contrato sin fecha y el cercano después del lejano:
    si la consulta devolviera las filas por ``id`` el orden saldría distinto
    del que se comprueba. El contrato ajeno vence antes que todos los propios,
    así que si el filtro de organización se perdiera aparecería el primero.

    El reloj de ``services.cartera`` queda en ``_HOY`` durante todo el test.
    ``setattr`` exige que el módulo siga teniendo ``datetime``: si dejara de
    importarlo, el escenario falla al montarse en vez de medir contra el reloj
    real sin avisar.
    """
    monkeypatch.setattr("services.cartera.datetime", _RelojFijo)
    owner = _user("owner-cartera@example.test")
    owner_ajeno = _user("owner-cartera-ajena@example.test")
    repo = OrganizationRepository()
    organizacion = int(repo.create_organization("Equipo cartera", owner)["id"])
    organizacion_ajena = int(repo.create_organization("Competidor", owner_ajeno)["id"])

    _licitacion(_SIN_FECHA, organo="Ayuntamiento de Lugo", tecnologia="SAP", cpv="72000000")
    _licitacion(_LEJANO, organo="Diputación de Ourense", tecnologia="SAP", cpv="72200000")
    _licitacion(_CERCANO, organo="Xunta de Galicia", tecnologia="Oracle", cpv="72260000")
    _licitacion(_EMPATE, organo="Concello de Vigo", tecnologia="SAP", cpv="72500000")
    _licitacion(_AJENO, organo="Xunta de Galicia", tecnologia="SAP", cpv="72000000")

    _contrato(owner, organizacion, _SIN_FECHA, fin=None, origen=None, importe=90_000.0)
    _contrato(
        owner, organizacion, _LEJANO, fin=_primero_de_mes(12), origen="publicada", importe=1.0e6
    )
    _contrato(
        owner, organizacion, _CERCANO, fin=_primero_de_mes(4), origen="duracion", importe=250_000.5
    )
    _contrato(
        owner,
        organizacion,
        _EMPATE,
        fin=_primero_de_mes(12),
        origen="prorroga",
        importe=40_000.0,
        prorrogas=1,
    )
    _contrato(
        owner_ajeno,
        organizacion_ajena,
        _AJENO,
        fin=_primero_de_mes(1),
        origen="publicada",
        importe=777_000.0,
    )
    return _Escenario(owner, organizacion, owner_ajeno, organizacion_ajena)


def _cartera(client: TestClient, organization_id: int | None) -> list[dict[str, Any]]:
    params = {} if organization_id is None else {"organization_id": organization_id}
    respuesta = client.get(_RUTA, params=params)
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert isinstance(cuerpo, list)
    return cuerpo


# ── Qué devuelve ──────────────────────────────────────────────────────────


def test_ordena_por_fecha_de_fin_con_los_contratos_sin_fecha_al_final(
    client: TestClient, sesion: _Sesion, escenario: _Escenario
) -> None:
    """Lo que vence antes arriba: es lo que hay que empezar a preparar.

    El empate de fecha se resuelve por antigüedad de la fila, y el contrato sin
    fecha va al final aunque se insertara el primero: no tiene ventana que
    vigilar y ponerlo arriba taparía los que sí la tienen.
    """
    sesion.user_id = escenario.owner

    cartera = _cartera(client, escenario.organizacion)

    assert [c["licitacion_id"] for c in cartera] == [_CERCANO, _LEJANO, _EMPATE, _SIN_FECHA]


def test_cada_contrato_trae_su_licitacion_y_la_ventana_de_su_fecha(
    client: TestClient, sesion: _Sesion, escenario: _Escenario
) -> None:
    """Órgano y tecnología salen de ``licitaciones``; la ventana, de la fecha."""
    sesion.user_id = escenario.owner

    por_id = {c["licitacion_id"]: c for c in _cartera(client, escenario.organizacion)}

    cercano = por_id[_CERCANO]
    assert cercano["organization_id"] == escenario.organizacion
    assert cercano["titulo"] == f"Contrato {_CERCANO}"
    assert cercano["organo_contratacion"] == "Xunta de Galicia"
    assert cercano["tecnologia"] == "Oracle"
    assert cercano["cpv"] == "72260000"
    assert cercano["importe_adjudicado"] == 250_000.5
    assert cercano["fecha_fin_efectiva"] == _primero_de_mes(4).isoformat()
    assert cercano["fecha_fin_origen"] == "duracion"
    assert cercano["meses_restantes"] == 4
    # Seis y tres meses antes del fin: la relicitación se espera en ese tramo.
    assert cercano["relicitacion_desde"] == _primero_de_mes(-2).isoformat()
    assert cercano["relicitacion_hasta"] == _primero_de_mes(1).isoformat()

    assert por_id[_EMPATE]["fecha_fin_origen"] == "prorroga"
    assert por_id[_EMPATE]["prorrogas_aplicadas"] == 1
    assert por_id[_LEJANO]["meses_restantes"] == 12


def test_meses_restantes_cuenta_meses_de_calendario_no_dias(
    client: TestClient, sesion: _Sesion, escenario: _Escenario
) -> None:
    """Del 10 de marzo al 28 de julio son cuatro meses de calendario, no cinco.

    Los dos ``meses_restantes`` del test anterior tienen el fin en día 1, y en
    ellos restar meses de calendario y redondear días entre 30,44 dan lo mismo.
    Un fin en día 28 separa las dos cuentas: son 140 días, que redondeados a
    meses de 30,44 días salen 5, y la diferencia de meses de calendario es 4.
    """
    fin = _primero_de_mes(4).replace(day=28)
    # La fecha elegida tiene que seguir separando las dos cuentas.
    assert (fin - _HOY).days == 140
    assert round((fin - _HOY).days / 30.44) == 5
    _licitacion(_MITAD_DE_MES, organo="Concello de Lugo", tecnologia="SAP", cpv="72000000")
    _contrato(
        escenario.owner,
        escenario.organizacion,
        _MITAD_DE_MES,
        fin=fin,
        origen="publicada",
        importe=10_000.0,
    )
    sesion.user_id = escenario.owner

    contrato = next(
        c for c in _cartera(client, escenario.organizacion) if c["licitacion_id"] == _MITAD_DE_MES
    )

    assert contrato["meses_restantes"] == 4


def test_un_contrato_sin_fecha_entra_sin_ventana_inventada(
    client: TestClient, sesion: _Sesion, escenario: _Escenario
) -> None:
    """Existe y se ejecuta, pero no hay de dónde sacar cuándo se relicita."""
    sesion.user_id = escenario.owner

    sin_fecha = next(
        c for c in _cartera(client, escenario.organizacion) if c["licitacion_id"] == _SIN_FECHA
    )

    assert sin_fecha["fecha_fin_efectiva"] is None
    assert sin_fecha["fecha_fin_origen"] is None
    assert sin_fecha["meses_restantes"] is None
    assert sin_fecha["relicitacion_desde"] is None
    assert sin_fecha["relicitacion_hasta"] is None


# ── A quién ───────────────────────────────────────────────────────────────


def test_la_cartera_de_otra_organizacion_no_aparece(
    client: TestClient, sesion: _Sesion, escenario: _Escenario
) -> None:
    """Cada organización ve lo suyo, también quien pertenece a las dos.

    El caso de la persona en ambas es el que importa: tiene acceso legítimo a
    los dos contratos, así que lo único que separa una cartera de la otra es
    el filtro de la consulta, no el control de membresía.
    """
    sesion.user_id = escenario.owner
    propios = {c["licitacion_id"] for c in _cartera(client, escenario.organizacion)}
    assert _AJENO not in propios

    sesion.user_id = escenario.owner_ajeno
    ajenos = _cartera(client, escenario.organizacion_ajena)
    assert [c["licitacion_id"] for c in ajenos] == [_AJENO]

    OrganizationRepository().add_membership(escenario.organizacion_ajena, escenario.owner, "member")
    sesion.user_id = escenario.owner
    assert {c["licitacion_id"] for c in _cartera(client, escenario.organizacion)} == propios
    assert [c["licitacion_id"] for c in _cartera(client, escenario.organizacion_ajena)] == [_AJENO]


def test_sin_organization_id_se_lee_la_cartera_personal(
    client: TestClient, sesion: _Sesion, escenario: _Escenario
) -> None:
    """Omitir el parámetro no es «todas mis organizaciones»: es la personal.

    Es lo que manda un cliente que no lo rellena, y el fallo histórico de
    tenencia que cuenta ``api/tenancy.py`` fue ese: sin ``organization_id`` la
    resolución se saltaba y la consulta se quedaba sin filtro.
    """
    sesion.user_id = escenario.owner

    assert _cartera(client, None) == []


def _rechazo_por_membresia(respuesta: httpx.Response) -> None:
    """403 con el problem+json de no pertenecer, no un 403 por otro motivo."""
    assert respuesta.status_code == 403, respuesta.text
    assert respuesta.headers["content-type"].startswith("application/problem+json")
    cuerpo = respuesta.json()
    assert (cuerpo["status"], cuerpo["detail"]) == (403, _NO_MIEMBRO)


def test_quien_no_es_miembro_recibe_403_por_membresia(
    client: TestClient, sesion: _Sesion, escenario: _Escenario
) -> None:
    """El motivo es no pertenecer: otro 403 (un scope, un guard) no vale igual."""
    sesion.user_id = escenario.owner_ajeno

    respuesta = client.get(_RUTA, params={"organization_id": escenario.organizacion})

    _rechazo_por_membresia(respuesta)


@pytest.mark.parametrize("rol", ["admin", "member", "viewer"])
def test_cualquier_miembro_activo_lee_la_misma_cartera_que_el_owner(
    client: TestClient, sesion: _Sesion, escenario: _Escenario, rol: str
) -> None:
    """Es lectura: un ``viewer`` tiene que poder ver qué vence y cuándo."""
    miembro = _user(f"{rol}-cartera@example.test")
    OrganizationRepository().add_membership(escenario.organizacion, miembro, rol)

    sesion.user_id = escenario.owner
    del_owner = _cartera(client, escenario.organizacion)
    sesion.user_id = miembro

    assert _cartera(client, escenario.organizacion) == del_owner


def test_una_membresia_revocada_pierde_la_cartera(
    client: TestClient, sesion: _Sesion, escenario: _Escenario
) -> None:
    """La fila de membresía sigue existiendo; lo que cuenta es que esté activa."""
    antiguo = _user("revocado-cartera@example.test")
    repo = OrganizationRepository()
    repo.add_membership(escenario.organizacion, antiguo, "member")
    repo.add_membership(escenario.organizacion, antiguo, "member", status="revoked")
    sesion.user_id = antiguo

    respuesta = client.get(_RUTA, params={"organization_id": escenario.organizacion})

    _rechazo_por_membresia(respuesta)


# ── Resumen: los agregados de la misma cartera ────────────────────────────


def _resumen(client: TestClient, organization_id: int | None) -> dict[str, Any]:
    params = {} if organization_id is None else {"organization_id": organization_id}
    respuesta = client.get(_RUTA_RESUMEN, params=params)
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert isinstance(cuerpo, dict)
    return cuerpo


def test_el_resumen_cuenta_la_misma_cartera_que_la_lista(
    client: TestClient, sesion: _Sesion, escenario: _Escenario
) -> None:
    """Dos rutas, un solo universo: si divergen, la cifra de arriba desmiente
    la tabla de abajo en la misma pantalla.

    Los cuatro contratos están vivos con el reloj congelado en ``_HOY``
    (ninguno ha vencido), y sólo ``_CERCANO`` —a cuatro meses— cae dentro del
    horizonte de seis.
    """
    sesion.user_id = escenario.owner

    resumen = _resumen(client, escenario.organizacion)
    lista = _cartera(client, escenario.organizacion)

    assert resumen["organization_id"] == escenario.organizacion
    assert resumen["contratos_vivos"] == len(lista) == 4
    assert resumen["importe_en_ejecucion_eur"] == 1_380_000.5
    assert resumen["vencen_6_meses"] == 1
    assert resumen["vencen_6_meses_importe_eur"] == 250_000.5
    assert resumen["sin_renovacion_preparada"] == 1


def test_el_resumen_no_mezcla_organizaciones(
    client: TestClient, sesion: _Sesion, escenario: _Escenario
) -> None:
    """El contrato ajeno es el más caro de los dos escenarios: si el filtro se
    perdiera, el importe en ejecución de la propia lo delataría."""
    sesion.user_id = escenario.owner_ajeno

    ajeno = _resumen(client, escenario.organizacion_ajena)

    assert ajeno["contratos_vivos"] == 1
    assert ajeno["importe_en_ejecucion_eur"] == 777_000.0


def test_sin_organization_id_el_resumen_es_el_de_la_cartera_personal(
    client: TestClient, sesion: _Sesion, escenario: _Escenario
) -> None:
    """Igual que la lista: omitir el parámetro es la personal, no «todas»."""
    sesion.user_id = escenario.owner

    assert _resumen(client, None)["contratos_vivos"] == 0


def test_el_resumen_de_una_organizacion_ajena_es_403_por_membresia(
    client: TestClient, sesion: _Sesion, escenario: _Escenario
) -> None:
    sesion.user_id = escenario.owner_ajeno

    respuesta = client.get(_RUTA_RESUMEN, params={"organization_id": escenario.organizacion})

    _rechazo_por_membresia(respuesta)


# ── Eventos del contrato vigente ──────────────────────────────────────────


def _eventos(licitacion_id: str) -> None:
    """Lo que ``services/contract_events.py`` deja en la tabla, desordenado.

    Se insertan en orden inverso al cronológico a propósito: el orden que se
    comprueba tiene que salir del ``ORDER BY fecha, id`` de la consulta y no
    del orden de inserción.
    """
    from db.database import connect

    with connect() as conn:
        conn.execute(
            "INSERT INTO contrato_eventos (licitacion_id, tipo, fecha, campo, valor_antes, "
            "valor_despues, importe_delta, detalle) "
            "VALUES (%s, 'modificacion', '2024-09-30', 'importe', '100000', '125000', "
            "25000, 'Modificación al alza del 25%%')",
            (licitacion_id,),
        )
        conn.execute(
            "INSERT INTO contrato_eventos (licitacion_id, tipo, fecha, campo, valor_antes, "
            "valor_despues) VALUES (%s, 'prorroga', '2024-02-01', 'fecha_fin', "
            "'2025-01-31', '2026-01-31')",
            (licitacion_id,),
        )


def _cartera_id(client: TestClient, organization_id: int, licitacion_id: str) -> int:
    contrato = next(
        c for c in _cartera(client, organization_id) if c["licitacion_id"] == licitacion_id
    )
    return int(contrato["id"])


def test_los_eventos_salen_del_mas_antiguo_al_mas_nuevo(
    client: TestClient, sesion: _Sesion, escenario: _Escenario
) -> None:
    """Es el historial del contrato: leerlo al revés cuenta otra historia."""
    sesion.user_id = escenario.owner
    _eventos(_CERCANO)
    cartera_id = _cartera_id(client, escenario.organizacion, _CERCANO)

    respuesta = client.get(
        f"{_RUTA}/{cartera_id}/eventos", params={"organization_id": escenario.organizacion}
    )

    assert respuesta.status_code == 200, respuesta.text
    eventos = respuesta.json()
    assert [e["fecha"] for e in eventos] == ["2024-02-01", "2024-09-30"]
    assert [e["tipo"] for e in eventos] == ["prorroga", "modificacion"]
    # El delta sólo viene en las modificaciones de importe.
    assert eventos[0]["importe_delta_eur"] is None
    assert eventos[1]["importe_delta_eur"] == 25_000.0


def test_sin_detalle_el_evento_se_describe_con_el_cambio(
    client: TestClient, sesion: _Sesion, escenario: _Escenario
) -> None:
    """Las filas antiguas no traen ``detalle``; la fila no puede quedar muda."""
    sesion.user_id = escenario.owner
    _eventos(_CERCANO)
    cartera_id = _cartera_id(client, escenario.organizacion, _CERCANO)

    eventos = client.get(
        f"{_RUTA}/{cartera_id}/eventos", params={"organization_id": escenario.organizacion}
    ).json()

    assert eventos[0]["descripcion"] == "prorroga · fecha_fin: 2025-01-31 → 2026-01-31"
    assert eventos[1]["descripcion"] == "Modificación al alza del 25%"


def test_un_contrato_sin_eventos_devuelve_una_lista_vacia(
    client: TestClient, sesion: _Sesion, escenario: _Escenario
) -> None:
    """Vacío no es 404: el contrato existe, sólo que no le ha pasado nada."""
    sesion.user_id = escenario.owner
    cartera_id = _cartera_id(client, escenario.organizacion, _LEJANO)

    respuesta = client.get(
        f"{_RUTA}/{cartera_id}/eventos", params={"organization_id": escenario.organizacion}
    )

    assert respuesta.status_code == 200
    assert respuesta.json() == []


def test_los_eventos_de_un_contrato_ajeno_son_404(
    client: TestClient, sesion: _Sesion, escenario: _Escenario
) -> None:
    """Y 404, no 403: la existencia de una entrada de otra organización no se
    confirma ni siquiera a quien pertenece a las dos."""
    sesion.user_id = escenario.owner_ajeno
    _eventos(_AJENO)
    ajeno_id = _cartera_id(client, escenario.organizacion_ajena, _AJENO)
    OrganizationRepository().add_membership(escenario.organizacion, escenario.owner_ajeno, "member")

    respuesta = client.get(
        f"{_RUTA}/{ajeno_id}/eventos", params={"organization_id": escenario.organizacion}
    )

    assert respuesta.status_code == 404, respuesta.text


def test_los_eventos_de_una_organizacion_ajena_son_403_por_membresia(
    client: TestClient, sesion: _Sesion, escenario: _Escenario
) -> None:
    sesion.user_id = escenario.owner_ajeno
    cartera_id = _cartera_id(client, escenario.organizacion_ajena, _AJENO)

    respuesta = client.get(
        f"{_RUTA}/{cartera_id}/eventos", params={"organization_id": escenario.organizacion}
    )

    _rechazo_por_membresia(respuesta)

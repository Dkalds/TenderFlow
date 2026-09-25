"""Cuentas de varios órganos (v145), su ficha, su resumen y el buscador del alta.

Hermano de ``test_cuentas_objetivo_etiquetas.py``, que fija el contrato de
siempre —seguir un órgano, aislamiento, etiquetas, roles— y sigue pasando sin
cambios: una cuenta de un solo órgano es exactamente lo que era antes de v145.
Aquí va lo nuevo:

- Una cuenta es un **cliente** con nombre propio y uno o varios órganos. Un
  órgano es de una sola cuenta por organización, y el nombre de la cuenta es
  único en la organización. Las altas de varios órganos son todo o nada.
- La ficha y el resumen cuentan sobre el universo analítico (sin las fuentes
  regionales de censo completo), sin duplicados confirmados, y cada bloque
  declara su universo y su ventana.
- El buscador del alta devuelve órganos reales con su número de expedientes y
  dice de qué cuenta es ya cada uno.

La autenticación se sustituye con ``dependency_overrides``; servicio,
repositorios y Postgres corren de verdad. Lo que se rechaza antes de llegar al
servicio (401, 422) y la traducción a 409/404 están en
``test_cuentas_objetivo_rechazos.py``, sin base.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.routes.dual_auth import require_any_auth
from db.database import connect
from db.repositories.organizations import OrganizationRepository

Como = Callable[[int], TestClient]

_CUENTAS = "/api/v1/cuentas"

_ECONOMIA = "Área de Gobierno de Economía del Ayuntamiento de Madrid"
_INFORMATICA = "Organismo Autónomo Informática del Ayuntamiento de Madrid"
_MADRIDEJOS = "Alcaldía del Ayuntamiento de Madridejos"


def _user(email: str) -> int:
    from db.users import create_user

    return create_user(
        email=email,
        password_hash="test-hash",  # pragma: allowlist secret
        display_name=email.split("@")[0],
    )


@pytest.fixture
def como(client: TestClient) -> Iterator[Como]:
    """Cambia quién llama sin reconstruir el cliente (ver el fichero hermano)."""
    from api.app import app

    ctx: dict[str, Any] = {}
    app.dependency_overrides[require_any_auth] = lambda: ctx

    def _como(user_id: int) -> TestClient:
        ctx.clear()
        ctx.update({"user_id": user_id, "auth_method": "session", "user_key": f"cuentas-{user_id}"})
        return client

    try:
        yield _como
    finally:
        app.dependency_overrides.pop(require_any_auth, None)


@dataclass(frozen=True)
class Equipo:
    owner: int
    viewer: int
    org: int
    owner_b: int
    org_b: int


def _equipo() -> Equipo:
    organizaciones = OrganizationRepository()
    owner = _user("organos-owner@example.test")
    viewer = _user("organos-viewer@example.test")
    owner_b = _user("organos-owner-b@example.test")
    org = int(organizaciones.create_organization("Equipo de cuentas", owner)["id"])
    org_b = int(organizaciones.create_organization("Otro equipo", owner_b)["id"])
    organizaciones.add_membership(org, viewer, "viewer")
    return Equipo(owner, viewer, org, owner_b, org_b)


def _p(organization_id: int) -> dict[str, int]:
    return {"organization_id": organization_id}


def _crear(
    http: TestClient,
    organization_id: int,
    organos: list[str],
    nombre: str | None = None,
    nota: str | None = None,
) -> dict[str, Any]:
    cuerpo: dict[str, Any] = {"organos": organos}
    if nombre is not None:
        cuerpo["nombre"] = nombre
    if nota is not None:
        cuerpo["nota"] = nota
    resp = http.post(_CUENTAS, params=_p(organization_id), json=cuerpo)
    assert resp.status_code == 201, resp.text
    return dict(resp.json())


def _nombres(cuenta: dict[str, Any]) -> list[str]:
    return [o["organo_nombre"] for o in cuenta["organos"]]


def _lista(http: TestClient, organization_id: int) -> list[dict[str, Any]]:
    resp = http.get(_CUENTAS, params=_p(organization_id))
    assert resp.status_code == 200, resp.text
    return list(resp.json())


# ── Siembra del corpus ──────────────────────────────────────────────────────


def _hace(dias: int) -> str:
    return (datetime.now(UTC) - timedelta(days=dias)).isoformat()


def _dentro_de(dias: int) -> str:
    return (date.today() + timedelta(days=dias)).isoformat()


def _lic(
    id_externo: str,
    organo: str,
    *,
    estado: str = "PUB",
    fecha_limite: str | None = None,
    primera_extraccion: str | None = None,
    fecha_fin: str | None = None,
    universo: str | None = None,
    importe: float | None = None,
) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, estado, organo_contratacion, fecha_publicacion, "
            " fecha_extraccion, primera_extraccion, fecha_limite, fecha_fin, "
            " analysis_universe, importe) "
            "VALUES (%s, %s, %s, %s, '2026-09-01', '2026-09-01', %s, %s, %s, %s, %s)",
            (
                id_externo,
                f"Expediente {id_externo}",
                estado,
                organo,
                primera_extraccion or _hace(1),
                fecha_limite,
                fecha_fin,
                universo,
                importe,
            ),
        )


def _adjudicar(id_externo: str, empresa: str, importe: float) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO adjudicaciones "
            "(licitacion_id, nombre, importe_adjudicado, fecha_adjudicacion, fecha_extraccion) "
            "VALUES (%s, %s, %s, '2025-01-01', '2026-09-01')",
            (id_externo, empresa, importe),
        )


def _oportunidad(
    organization_id: int,
    id_externo: str,
    status: str,
    *,
    responsable: int | None = None,
    proxima: str | None = None,
    vence: str | None = None,
) -> int:
    with connect() as c:
        fila = c.execute(
            "INSERT INTO pursuits (organization_id, licitacion_id, status, created_at, "
            " updated_at, responsible_user_id, next_action, next_action_due) "
            "VALUES (%s, %s, %s, '2026-09-01', '2026-09-01', %s, %s, %s) RETURNING id",
            (organization_id, id_externo, status, responsable, proxima, vence),
        ).fetchone()
    assert fila is not None
    return int(fila[0])


# ── Una cuenta, varios órganos ──────────────────────────────────────────────


def test_una_cuenta_agrupa_varios_organos_con_nombre_propio(como: Como) -> None:
    """El cliente que no publica con su nombre: seis órganos, ninguno se llama
    «Ayuntamiento de Madrid». La cuenta los junta bajo ese nombre."""
    e = _equipo()

    cuenta = _crear(
        como(e.owner), e.org, [_ECONOMIA, _INFORMATICA], nombre="Ayuntamiento de Madrid"
    )

    assert cuenta["nombre"] == "Ayuntamiento de Madrid"
    assert _nombres(cuenta) == [_ECONOMIA, _INFORMATICA]
    # El contrato anterior a v145 dice el primer órgano.
    assert cuenta["organo_nombre"] == _ECONOMIA
    assert cuenta["organo_norm"] == cuenta["organos"][0]["organo_norm"]
    assert [c["id"] for c in _lista(como(e.viewer), e.org)] == [cuenta["id"]]


def test_sin_nombre_la_cuenta_se_llama_como_su_primer_organo(como: Como) -> None:
    e = _equipo()

    cuenta = _crear(como(e.owner), e.org, [_INFORMATICA, _ECONOMIA])

    assert cuenta["nombre"] == _INFORMATICA


def test_dos_grafias_del_mismo_organo_en_una_seleccion_son_uno(como: Como) -> None:
    """Chocarían entre sí en la unicidad y parecería que otra cuenta lo tiene."""
    e = _equipo()

    cuenta = _crear(como(e.owner), e.org, [_ECONOMIA, _ECONOMIA.upper(), f"  {_ECONOMIA} "])

    assert _nombres(cuenta) == [_ECONOMIA]


def test_un_organo_solo_puede_estar_en_una_cuenta_y_el_alta_es_todo_o_nada(
    como: Como,
) -> None:
    """Si pudiera estar en dos, cada publicación suya avisaría dos veces. El
    409 nombra la cuenta que ya lo tiene, y no se crea nada a medias."""
    e = _equipo()
    http = como(e.owner)
    madrid = _crear(http, e.org, [_ECONOMIA], nombre="Ayuntamiento de Madrid")

    resp = http.post(
        _CUENTAS,
        params=_p(e.org),
        json={"nombre": "Otra cuenta", "organos": [_INFORMATICA, _ECONOMIA.upper()]},
    )

    assert resp.status_code == 409, resp.text
    assert "Ayuntamiento de Madrid" in resp.json()["detail"]
    assert [c["id"] for c in _lista(http, e.org)] == [madrid["id"]]
    # El órgano libre de la selección tampoco entró en ningún sitio.
    libre = http.post(_CUENTAS, params=_p(e.org), json={"organos": [_INFORMATICA]})
    assert libre.status_code == 201, libre.text


def test_otra_organizacion_puede_tener_el_mismo_organo_y_el_mismo_nombre(como: Como) -> None:
    e = _equipo()
    _crear(como(e.owner), e.org, [_ECONOMIA], nombre="Ayuntamiento de Madrid")

    ajena = _crear(como(e.owner_b), e.org_b, [_ECONOMIA], nombre="Ayuntamiento de Madrid")

    assert ajena["organization_id"] == e.org_b


def test_el_nombre_de_una_cuenta_es_unico_en_la_organizacion(como: Como) -> None:
    """Plegado: «AYUNTAMIENTO DE MADRID» es el mismo nombre escrito otra vez."""
    e = _equipo()
    http = como(e.owner)
    _crear(http, e.org, [_ECONOMIA], nombre="Ayuntamiento de Madrid")
    otra = _crear(http, e.org, [_INFORMATICA], nombre="Informática municipal")

    alta = http.post(
        _CUENTAS,
        params=_p(e.org),
        json={"nombre": "AYUNTAMIENTO  DE MADRID", "organos": [_MADRIDEJOS]},
    )
    renombre = http.patch(
        f"{_CUENTAS}/{otra['id']}", params=_p(e.org), json={"nombre": "ayuntamiento de madrid"}
    )

    assert alta.status_code == 409, alta.text
    assert renombre.status_code == 409, renombre.text
    assert len(_lista(http, e.org)) == 2


def test_seguir_un_organo_que_ya_es_de_una_cuenta_devuelve_esa_cuenta(como: Como) -> None:
    """El clic de Mercado sobre un órgano de una cuenta de varios: la cuenta
    que lo tiene, no una nueva de un solo órgano."""
    e = _equipo()
    http = como(e.owner)
    madrid = _crear(http, e.org, [_ECONOMIA, _INFORMATICA], nombre="Ayuntamiento de Madrid")

    resp = http.post(_CUENTAS, params=_p(e.org), json={"organo": _INFORMATICA.upper()})

    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] == madrid["id"]
    assert len(_lista(http, e.org)) == 1


def test_seguir_un_organo_que_se_llama_como_una_cuenta_lo_anade_a_ella(como: Como) -> None:
    """La cuenta «Ayuntamiento de Getafe» ya existe con su Alcaldía; el órgano
    que se llama exactamente así es de esa misma cuenta, no de una homónima."""
    e = _equipo()
    http = como(e.owner)
    getafe = _crear(
        http, e.org, ["Alcaldía del Ayuntamiento de Getafe"], nombre="Ayuntamiento de Getafe"
    )

    resp = http.post(_CUENTAS, params=_p(e.org), json={"organo": "Ayuntamiento de Getafe"})

    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] == getafe["id"]
    assert _nombres(resp.json()) == [
        "Alcaldía del Ayuntamiento de Getafe",
        "Ayuntamiento de Getafe",
    ]


# ── Editar una cuenta ───────────────────────────────────────────────────────


def test_anadir_y_quitar_organos(como: Como) -> None:
    e = _equipo()
    http = como(e.owner)
    cuenta = _crear(http, e.org, [_ECONOMIA], nombre="Ayuntamiento de Madrid")
    ruta = f"{_CUENTAS}/{cuenta['id']}/organos"

    # Idempotente con el que ya estaba; el nuevo entra.
    anadida = http.post(ruta, params=_p(e.org), json={"organos": [_ECONOMIA, _INFORMATICA]})
    assert anadida.status_code == 200, anadida.text
    assert _nombres(anadida.json()) == [_ECONOMIA, _INFORMATICA]

    economia = anadida.json()["organos"][0]["id"]
    quitada = http.delete(f"{ruta}/{economia}", params=_p(e.org))
    assert quitada.status_code == 200, quitada.text
    assert _nombres(quitada.json()) == [_INFORMATICA]

    # El último no se quita: una cuenta sin órganos no avisaría de nada.
    ultimo = quitada.json()["organos"][0]["id"]
    resp = http.delete(f"{ruta}/{ultimo}", params=_p(e.org))
    assert resp.status_code == 409, resp.text
    assert http.delete(f"{ruta}/{economia}", params=_p(e.org)).status_code == 404


def test_anadir_un_organo_de_otra_cuenta_es_409_y_no_anade_ninguno(como: Como) -> None:
    e = _equipo()
    http = como(e.owner)
    madrid = _crear(http, e.org, [_ECONOMIA], nombre="Ayuntamiento de Madrid")
    otra = _crear(http, e.org, [_MADRIDEJOS], nombre="Madridejos")

    resp = http.post(
        f"{_CUENTAS}/{otra['id']}/organos",
        params=_p(e.org),
        json={"organos": [_INFORMATICA, _ECONOMIA]},
    )

    assert resp.status_code == 409, resp.text
    assert "Ayuntamiento de Madrid" in resp.json()["detail"]
    cuentas = {c["id"]: _nombres(c) for c in _lista(http, e.org)}
    assert cuentas == {madrid["id"]: [_ECONOMIA], otra["id"]: [_MADRIDEJOS]}


def test_un_organo_de_otra_cuenta_no_se_quita_desde_esta(como: Como) -> None:
    e = _equipo()
    http = como(e.owner)
    madrid = _crear(http, e.org, [_ECONOMIA, _INFORMATICA], nombre="Ayuntamiento de Madrid")
    otra = _crear(http, e.org, [_MADRIDEJOS], nombre="Madridejos")
    ajeno = madrid["organos"][0]["id"]

    resp = http.delete(f"{_CUENTAS}/{otra['id']}/organos/{ajeno}", params=_p(e.org))

    assert resp.status_code == 404, resp.text
    assert _nombres(_lista(http, e.org)[0]) == [_ECONOMIA, _INFORMATICA]


def test_editar_renombra_y_cambia_o_borra_la_nota(como: Como) -> None:
    e = _equipo()
    http = como(e.owner)
    cuenta = _crear(http, e.org, [_ECONOMIA], nota="Renueva en Q1")
    ruta = f"{_CUENTAS}/{cuenta['id']}"

    renombrada = http.patch(ruta, params=_p(e.org), json={"nombre": "Ayuntamiento de Madrid"})
    assert renombrada.status_code == 200, renombrada.text
    assert renombrada.json()["nombre"] == "Ayuntamiento de Madrid"
    # Renombrar no toca la nota ni los órganos.
    assert renombrada.json()["nota"] == "Renueva en Q1"
    assert renombrada.json()["organo_nombre"] == _ECONOMIA

    cambiada = http.patch(ruta, params=_p(e.org), json={"nota": "Renueva en Q2"})
    assert cambiada.json()["nota"] == "Renueva en Q2"
    borrada = http.patch(ruta, params=_p(e.org), json={"nota": None})
    assert borrada.json()["nota"] is None
    repuesta = http.patch(ruta, params=_p(e.org), json={"nota": "Algo"})
    assert repuesta.json()["nota"] == "Algo"
    # Una nota en blanco es no tener nota.
    assert http.patch(ruta, params=_p(e.org), json={"nota": "   "}).json()["nota"] is None


def test_editar_una_cuenta_de_otra_organizacion_es_404(como: Como) -> None:
    e = _equipo()
    ajena = _crear(como(e.owner_b), e.org_b, [_ECONOMIA])

    resp = como(e.owner).patch(f"{_CUENTAS}/{ajena['id']}", params=_p(e.org), json={"nota": "x"})

    assert resp.status_code == 404, resp.text
    assert _lista(como(e.owner_b), e.org_b)[0]["nota"] is None


def test_dejar_de_seguir_libera_sus_organos(como: Como) -> None:
    """Los órganos se van en cascada: otra cuenta puede quedárselos después."""
    e = _equipo()
    http = como(e.owner)
    cuenta = _crear(http, e.org, [_ECONOMIA, _INFORMATICA], nombre="Ayuntamiento de Madrid")

    assert http.delete(f"{_CUENTAS}/{cuenta['id']}", params=_p(e.org)).status_code == 204

    otra = _crear(http, e.org, [_INFORMATICA], nombre="Informática municipal")
    assert _nombres(otra) == [_INFORMATICA]


def test_quitar_la_estrella_de_un_organo_lo_saca_de_su_cuenta(como: Como) -> None:
    """La inversa del clic de Mercado. En una cuenta de varios órganos se va
    sólo ése; si era el único, la cuenta entera. Con la grafía del expediente."""
    e = _equipo()
    http = como(e.owner)
    madrid = _crear(http, e.org, [_ECONOMIA, _INFORMATICA], nombre="Ayuntamiento de Madrid")
    sola = _crear(http, e.org, [_MADRIDEJOS])
    ruta = f"{_CUENTAS}/por-organo"

    quitado = http.delete(ruta, params={**_p(e.org), "organo": _INFORMATICA.upper()})
    borrada = http.delete(ruta, params={**_p(e.org), "organo": _MADRIDEJOS})
    repetida = http.delete(ruta, params={**_p(e.org), "organo": _MADRIDEJOS})

    assert quitado.status_code == 204, quitado.text
    assert borrada.status_code == 204, borrada.text
    assert repetida.status_code == 404, repetida.text
    cuentas = {c["id"]: _nombres(c) for c in _lista(http, e.org)}
    assert cuentas == {madrid["id"]: [_ECONOMIA]}
    assert sola["id"] not in cuentas


def test_el_viewer_no_puede_quitar_la_estrella(como: Como) -> None:
    e = _equipo()
    _crear(como(e.owner), e.org, [_ECONOMIA])

    resp = como(e.viewer).delete(
        f"{_CUENTAS}/por-organo", params={**_p(e.org), "organo": _ECONOMIA}
    )

    assert resp.status_code == 403, resp.text
    assert _nombres(_lista(como(e.owner), e.org)[0]) == [_ECONOMIA]


# ── Ficha y resumen ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Corpus:
    equipo: Equipo
    cuenta_id: int
    activa: int
    perdida: int


def _sembrar_corpus(como: Como) -> Corpus:
    """Una cuenta de dos órganos con un expediente de cada caso que la ficha
    tiene que contar o dejar fuera."""
    e = _equipo()
    cuenta = _crear(
        como(e.owner), e.org, [_ECONOMIA, _INFORMATICA], nombre="Ayuntamiento de Madrid"
    )
    # Cuentan.
    _lic("MAD-ABIERTA", _ECONOMIA, fecha_limite=_dentro_de(10), importe=120000.0)
    _lic("MAD-CERRADA", _INFORMATICA.upper(), estado="ADJ", fecha_limite=_dentro_de(10))
    _lic("MAD-PLAZO-PASADO", _INFORMATICA, fecha_limite=_dentro_de(-3))
    _lic("MAD-VENCE", _ECONOMIA, fecha_fin=_dentro_de(90), primera_extraccion=_hace(400))
    _adjudicar("MAD-VENCE", "Incumbente SA", 50000.0)
    _adjudicar("MAD-VENCE", "Socia de la UTE SL", 50000.0)
    # No cuentan.
    _lic("MAD-VIEJA", _ECONOMIA, primera_extraccion=_hace(200), fecha_limite=_dentro_de(10))
    _lic("MAD-LEJOS", _INFORMATICA, fecha_fin=_dentro_de(900), primera_extraccion=_hace(400))
    _adjudicar("MAD-LEJOS", "Incumbente lejano SA", 1000.0)
    _lic("MAD-PSCP", _ECONOMIA, fecha_limite=_dentro_de(10), universo="pscp_observed")
    _lic("MADRIDEJOS-1", _MADRIDEJOS, fecha_limite=_dentro_de(10))
    activa = _oportunidad(
        e.org,
        "MAD-ABIERTA",
        "qualifying",
        responsable=e.owner,
        proxima="Llamar al jefe de servicio",
        vence=_dentro_de(2),
    )
    perdida = _oportunidad(e.org, "MAD-CERRADA", "lost")
    # De otra organización: no es del equipo.
    _oportunidad(e.org_b, "MAD-ABIERTA", "qualifying")
    return Corpus(e, int(cuenta["id"]), activa, perdida)


def test_la_ficha_cuenta_lo_de_sus_organos_en_su_universo_y_su_ventana(como: Como) -> None:
    corpus = _sembrar_corpus(como)
    e = corpus.equipo

    resp = como(e.viewer).get(f"{_CUENTAS}/{corpus.cuenta_id}", params=_p(e.org))

    assert resp.status_code == 200, resp.text
    ficha = resp.json()
    assert ficha["cuenta"]["nombre"] == "Ayuntamiento de Madrid"

    publicaciones = ficha["publicaciones"]
    # Las tres de los últimos 90 días de sus dos órganos; ni la vieja, ni la de
    # la fuente regional de censo completo, ni la de Madridejos.
    ids = {p["id_externo"]: p for p in publicaciones["items"]}
    assert publicaciones["total"] == 3
    assert set(ids) == {"MAD-ABIERTA", "MAD-CERRADA", "MAD-PLAZO-PASADO"}
    assert ids["MAD-ABIERTA"]["abierta"] is True
    assert ids["MAD-CERRADA"]["abierta"] is False
    assert ids["MAD-PLAZO-PASADO"]["abierta"] is False
    assert publicaciones["ambito"]["universo"]
    assert "90" in publicaciones["ambito"]["ventana"]

    vencimientos = ficha["vencimientos"]
    # Un contrato con dos adjudicatarios: un contrato, dos filas.
    assert vencimientos["total"] == 1
    assert {v["empresa"] for v in vencimientos["items"]} == {"Incumbente SA", "Socia de la UTE SL"}
    assert {v["fecha_fin_origen"] for v in vencimientos["items"]} == {"real"}
    assert vencimientos["items"][0]["fecha_fin"] == _dentro_de(90)

    oportunidades = ficha["oportunidades"]
    assert oportunidades["activas"] == 1
    # La activa primero; la de la otra organización no aparece.
    assert [o["id"] for o in oportunidades["items"]] == [corpus.activa, corpus.perdida]
    primera = oportunidades["items"][0]
    assert primera["next_action"] == "Llamar al jefe de servicio"
    assert primera["responsable"] == "organos-owner"
    assert primera["activa"] is True


def test_el_resumen_trae_una_fila_por_cuenta_tambien_a_cero(como: Como) -> None:
    corpus = _sembrar_corpus(como)
    e = corpus.equipo
    vacia = _crear(como(e.owner), e.org, ["Diputación sin expedientes"])

    resp = como(e.viewer).get(f"{_CUENTAS}/resumen", params=_p(e.org))

    assert resp.status_code == 200, resp.text
    resumen = resp.json()
    filas = {f["cuenta_id"]: f for f in resumen["filas"]}
    assert set(filas) == {corpus.cuenta_id, vacia["id"]}
    madrid = filas[corpus.cuenta_id]
    # Abiertas hoy, dos: la abierta y la vieja, porque «abierta» no tiene
    # ventana de publicación. Ni la adjudicada ni la de plazo pasado.
    assert madrid["abiertas"] == 2
    assert madrid["vencen"] == 1
    assert madrid["oportunidades_activas"] == 1
    assert madrid["ultima_publicacion"] is not None
    assert filas[vacia["id"]] == {
        "cuenta_id": vacia["id"],
        "abiertas": 0,
        "ultima_publicacion": None,
        "vencen": 0,
        "oportunidades_activas": 0,
    }
    for campo in ("ambito_abiertas", "ambito_vencen", "ambito_oportunidades"):
        assert resumen[campo]["universo"] and resumen[campo]["ventana"]


def test_la_ficha_de_una_cuenta_ajena(como: Como) -> None:
    """Nombrando la organización ajena es 403; desde la propia, la cuenta no
    existe: 404. En ningún caso sale la ficha."""
    corpus = _sembrar_corpus(como)
    e = corpus.equipo
    intruso = como(e.owner_b)
    ruta = f"{_CUENTAS}/{corpus.cuenta_id}"

    assert intruso.get(ruta, params=_p(e.org)).status_code == 403
    propia = intruso.get(ruta, params=_p(e.org_b))
    assert propia.status_code == 404
    assert "Ayuntamiento de Madrid" not in propia.text


# ── Buscador del alta ───────────────────────────────────────────────────────


def test_el_buscador_trae_organos_reales_y_dice_de_que_cuenta_son(como: Como) -> None:
    """Es lo que evita la cuenta que no casa con nada: se elige un órgano que
    existe, con sus expedientes, en vez de escribir un nombre a ciegas."""
    e = _equipo()
    for n in range(3):
        _lic(f"ECO-{n}", _ECONOMIA)
    _lic("INF-0", _INFORMATICA)
    _lic("MJ-0", _MADRIDEJOS)
    madrid = _crear(como(e.owner), e.org, [_ECONOMIA], nombre="Ayuntamiento de Madrid")
    http = como(e.viewer)

    resp = http.get(
        f"{_CUENTAS}/buscar-organos", params={**_p(e.org), "q": "ayuntamiento de MADRID"}
    )

    assert resp.status_code == 200, resp.text
    candidatos = {c["organo_nombre"]: c for c in resp.json()}
    # Por subcadena, así que Madridejos también sale: por eso se elige de una
    # lista con nombres completos y no se casa por subcadena al avisar.
    assert set(candidatos) == {_ECONOMIA, _INFORMATICA, _MADRIDEJOS}
    assert candidatos[_ECONOMIA]["expedientes"] == 3
    assert candidatos[_ECONOMIA]["cuenta_id"] == madrid["id"]
    assert candidatos[_ECONOMIA]["cuenta_nombre"] == "Ayuntamiento de Madrid"
    assert candidatos[_INFORMATICA]["cuenta_id"] is None
    # El más usado primero: es el que el usuario buscaba casi siempre.
    assert resp.json()[0]["organo_nombre"] == _ECONOMIA

    corto = http.get(f"{_CUENTAS}/buscar-organos", params={**_p(e.org), "q": "ma"})
    assert corto.status_code == 200
    assert corto.json() == []


def test_el_buscador_no_marca_cuentas_de_otra_organizacion(como: Como) -> None:
    e = _equipo()
    _lic("ECO-0", _ECONOMIA)
    _crear(como(e.owner_b), e.org_b, [_ECONOMIA], nombre="De la B")

    resp = como(e.owner).get(f"{_CUENTAS}/buscar-organos", params={**_p(e.org), "q": "economia"})

    assert resp.status_code == 200, resp.text
    assert [(c["organo_nombre"], c["cuenta_id"]) for c in resp.json()] == [(_ECONOMIA, None)]

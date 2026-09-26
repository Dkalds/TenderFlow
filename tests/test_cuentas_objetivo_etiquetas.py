"""Cuentas objetivo (F1.5) y etiquetas de organización (F1.6), por HTTP.

**Por qué existe este fichero.** Las nueve rutas de ``api/routes/cuentas.py``
no tenían ni un test: lo único que tocaba el área era ``test_competitive``, que
usa ``CuentasRepository.follow`` como siembra de otro caso. La migración v105
dice que el tope de treinta etiquetas «lo aplica el servicio, y el test lo
fija», y ese test no existía.

Lo que más importa fijar es el **aislamiento**. Cuentas y etiquetas son de la
organización, no del usuario, y el control vive en dos puertas que cierran
caminos distintos:

- ``resolve_organization``: ¿el llamante es miembro activo de la organización
  que pide? Cierra el camino de **nombrar** la organización ajena en
  ``organization_id``.
- el filtro por ``organization_id`` de ``db/repositories/cuentas.py``, en el
  ``WHERE`` o en la clave del ``ON CONFLICT``: cierra el camino de alcanzar,
  desde la organización **propia** —donde la membresía es correcta—, un
  recurso ajeno por su id o por su nombre.

Ninguna cubre a la otra: basta con que falle una sola para que haya fuga por
su camino, y por eso las dos tienen que aguantar por separado. Los cinco
tests ``test_otra_organizacion_*`` prueban los dos caminos. Los demás de
aislamiento apuntan a uno: los de unicidad por organización y el de
``por-objeto`` sobre el mismo objeto, al repositorio; los de membresía ausente
o revocada, a ``resolve_organization``. Los que intentan borrar o escribir sin
permiso comprueban después, desde el dueño, que nada cambió: un 404 que en
realidad borró algo es el peor fallo posible de estas rutas, porque la
respuesta dice que no pasó nada. La excepción son los tests del 403 del
viewer, que sólo miran el código de estado; que el viewer no escribió nada lo
fija ``test_un_viewer_no_puede_escribir_nada_en_la_cartera``.

La autenticación se sustituye con ``dependency_overrides``; el resto —servicio,
repositorios y Postgres— corre de verdad. Las dos excepciones son los tests de
la carrera de ``crear_etiqueta``, que con ``monkeypatch`` hacen que la búsqueda
por nombre no vea una etiqueta que sí está en la base: es el orden de lecturas
que produce la concurrencia real, sin hilos. Lo que se rechaza antes de llegar
al servicio (401 y 422) está en ``test_cuentas_objetivo_rechazos.py``, sin
base; aquí queda el byte NUL, que se fija contra Postgres porque hasta
2026-09-25 llegaba a él.

Este fichero tuvo tres ``xfail`` estrictos, arreglados los tres el 2026-09-25:
el 500 del viewer que escribe, las etiquetas huérfanas al dejar de seguir una
cuenta y el byte NUL que salía como 500. Los tests que los fijaban siguen aquí,
ya sin marca. Siembran por repositorio y comprueban sus precondiciones con
``pytest.fail``, no con ``assert``: un fallo preparando los datos tiene que
salir como fallo y no confundirse con el que el test vigila.

Las cuentas de varios órganos (v145), su ficha y el buscador del alta están en
``test_cuentas_organos.py``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

import pytest
from fastapi.testclient import TestClient

from api.routes.dual_auth import require_any_auth
from db.repositories.cuentas import CuentasRepository, EtiquetasRepository
from db.repositories.organizations import OrganizationRepository
from db.sql_fragments import plegar_organo

Como = Callable[[int], TestClient]

_CUENTAS = "/api/v1/cuentas"
_ETIQUETAS = "/api/v1/etiquetas"


class Respuesta(Protocol):
    """Lo que estos tests leen de una respuesta del ``TestClient``.

    No se anota con ``httpx.Response``: Starlette usa ``httpx2`` si está
    instalado y ``httpx`` si no, y para mypy son dos tipos distintos.
    """

    @property
    def status_code(self) -> int: ...

    @property
    def text(self) -> str: ...

    # `Any`: el cuerpo JSON es arbitrario; cada test comprueba su forma.
    def json(self) -> Any: ...


def _user(email: str) -> int:
    from db.users import create_user

    return create_user(email=email, password_hash="test-hash")  # pragma: allowlist secret


def _ctx_sesion(user_id: int) -> dict[str, Any]:
    """Lo mínimo que ``require_any_auth`` entrega y estas rutas leen."""
    return {
        "user_id": user_id,
        "auth_method": "session",
        "user_key": f"cuentas-objetivo-{user_id}",
    }


@pytest.fixture
def como(client: TestClient) -> Iterator[Como]:
    """Cambia quién llama sin reconstruir el cliente.

    Los tests de aislamiento necesitan que dos personas actúen en el mismo
    test sobre la misma base: el override devuelve un dict mutable y cada
    ``como(user_id)`` lo rellena con el llamante de la siguiente petición.
    """
    from api.app import app

    ctx: dict[str, Any] = {}
    app.dependency_overrides[require_any_auth] = lambda: ctx

    def _como(user_id: int) -> TestClient:
        ctx.clear()
        ctx.update(_ctx_sesion(user_id))
        return client

    try:
        yield _como
    finally:
        app.dependency_overrides.pop(require_any_auth, None)


@pytest.fixture
def sin_relanzar(como: Como) -> TestClient:
    """Cliente que devuelve la respuesta del servidor en vez de relanzar.

    Comparte con ``como`` el override de autenticación, que es de la app y no
    del cliente. Hace falta donde hoy hay una excepción no traducida: con
    ``raise_server_exceptions=True`` el test no vería el 500, sólo la traza.
    """
    from api.app import app

    return TestClient(app, raise_server_exceptions=False)


@dataclass(frozen=True)
class Equipos:
    """Dos organizaciones compartidas.

    La A tiene los tres roles que importan —owner, member y viewer—; ``owner_b``
    es el de fuera: dueño de la B y sin membresía en la A.
    """

    owner_a: int
    miembro_a: int
    viewer_a: int
    owner_b: int
    org_a: int
    org_b: int


def _equipos() -> Equipos:
    organizations = OrganizationRepository()
    owner_a = _user("cuentas-owner-a@example.test")
    miembro_a = _user("cuentas-miembro-a@example.test")
    viewer_a = _user("cuentas-viewer-a@example.test")
    owner_b = _user("cuentas-owner-b@example.test")
    org_a = int(organizations.create_organization("Equipo A", owner_a)["id"])
    org_b = int(organizations.create_organization("Equipo B", owner_b)["id"])
    organizations.add_membership(org_a, miembro_a, "member")
    organizations.add_membership(org_a, viewer_a, "viewer")
    return Equipos(owner_a, miembro_a, viewer_a, owner_b, org_a, org_b)


def _org(organization_id: int | None) -> dict[str, int]:
    return {} if organization_id is None else {"organization_id": organization_id}


def _seguir(
    http: TestClient, organization_id: int | None, organo: str, nota: str | None = None
) -> dict[str, Any]:
    cuerpo: dict[str, Any] = {"organo": organo}
    if nota is not None:
        cuerpo["nota"] = nota
    resp = http.post(_CUENTAS, params=_org(organization_id), json=cuerpo)
    assert resp.status_code == 201, resp.text
    return dict(resp.json())


def _cuentas(http: TestClient, organization_id: int | None) -> list[dict[str, Any]]:
    resp = http.get(_CUENTAS, params=_org(organization_id))
    assert resp.status_code == 200, resp.text
    return list(resp.json())


def _crear_etiqueta(
    http: TestClient, organization_id: int | None, nombre: str, color: str = "#336699"
) -> dict[str, Any]:
    resp = http.post(
        _ETIQUETAS, params=_org(organization_id), json={"nombre": nombre, "color": color}
    )
    assert resp.status_code == 201, resp.text
    return dict(resp.json())


def _etiquetas(http: TestClient, organization_id: int | None) -> list[dict[str, Any]]:
    resp = http.get(_ETIQUETAS, params=_org(organization_id))
    assert resp.status_code == 200, resp.text
    return list(resp.json())


def _aplicacion(etiqueta_id: int, objeto_id: str, tipo: str = "oportunidad") -> dict[str, Any]:
    return {"etiqueta_id": etiqueta_id, "objeto_tipo": tipo, "objeto_id": objeto_id}


def _aplicar(
    http: TestClient, organization_id: int | None, etiqueta_id: int, objeto_id: str, **kw: str
) -> Respuesta:
    return http.post(
        f"{_ETIQUETAS}/aplicar",
        params=_org(organization_id),
        json=_aplicacion(etiqueta_id, objeto_id, **kw),
    )


def _quitar(
    http: TestClient, organization_id: int | None, etiqueta_id: int, objeto_id: str, **kw: str
) -> Respuesta:
    return http.post(
        f"{_ETIQUETAS}/quitar",
        params=_org(organization_id),
        json=_aplicacion(etiqueta_id, objeto_id, **kw),
    )


def _por_objeto(
    http: TestClient,
    organization_id: int | None,
    objeto_ids: list[str],
    tipo: str = "oportunidad",
) -> dict[str, Any]:
    resp = http.post(
        f"{_ETIQUETAS}/por-objeto",
        params=_org(organization_id),
        json={"objeto_tipo": tipo, "objeto_ids": objeto_ids},
    )
    assert resp.status_code == 200, resp.text
    return dict(resp.json()["por_objeto"])


# ── Siembra sin HTTP ────────────────────────────────────────────────────────


def _etiqueta_en_bd(organization_id: int, nombre: str, autor: int) -> int:
    fila = EtiquetasRepository().create(
        organization_id=organization_id, nombre=nombre, color="#336699", user_id=autor
    )
    if fila is None:
        pytest.fail(f"siembra: la etiqueta {nombre!r} ya existía en una base recién creada")
    return int(fila["id"])


def _sembrar_cartera(e: Equipos) -> tuple[int, int]:
    """Una cuenta y la etiqueta «Q4» aplicada a la oportunidad «17», en la A."""
    cuenta = CuentasRepository().follow(
        organization_id=e.org_a, organo_nombre="Ayuntamiento de Segovia", user_id=e.owner_a
    )
    etiqueta_id = _etiqueta_en_bd(e.org_a, "Q4", e.owner_a)
    if not EtiquetasRepository().aplicar(
        organization_id=e.org_a,
        etiqueta_id=etiqueta_id,
        objeto_tipo="oportunidad",
        objeto_id="17",
        user_id=e.owner_a,
    ):
        pytest.fail("siembra: la etiqueta no se aplicó a la oportunidad 17")
    return int(cuenta["id"]), etiqueta_id


def _primer_organo(organization_id: int, cuenta_id: int) -> int:
    """Id en ``cuenta_organos`` del primer órgano de una cuenta sembrada."""
    cuenta = CuentasRepository().get(organization_id, cuenta_id)
    if cuenta is None or not cuenta["organos"]:
        pytest.fail(f"siembra: la cuenta {cuenta_id} no tiene órganos")
    return int(cuenta["organos"][0]["id"])


# ── Cuentas objetivo: camino feliz ──────────────────────────────────────────


def test_seguir_un_organo_lo_deja_en_la_cartera_del_equipo(como: Como) -> None:
    """La cuenta es del equipo: la sigue el owner y la ve un miembro."""
    e = _equipos()

    cuenta = _seguir(como(e.owner_a), e.org_a, "  Ayuntamiento de Alcalá ", "Renueva en Q1")

    assert cuenta["organization_id"] == e.org_a
    assert cuenta["organo_nombre"] == "Ayuntamiento de Alcalá"
    # El plegado tiene que ser el de los agregados de Mercado: si divergiera,
    # el mismo órgano seguido desde dos pantallas serían dos cuentas.
    assert cuenta["organo_norm"] == plegar_organo("Ayuntamiento de Alcalá")
    assert cuenta["created_by_user_id"] == e.owner_a
    assert cuenta["nota"] == "Renueva en Q1"
    assert cuenta["organo_id"] is None

    vistas_por_miembro = _cuentas(como(e.miembro_a), e.org_a)
    assert [c["id"] for c in vistas_por_miembro] == [cuenta["id"]]


def test_seguir_dos_veces_el_mismo_organo_no_duplica_y_la_nota_se_edita(como: Como) -> None:
    """Idempotente por nombre plegado, y 201 las dos veces.

    Volver a seguir con otra nota es una edición; volver a seguir **sin** nota
    no puede borrar la que había, que es lo que haría un ``DO UPDATE`` ingenuo.
    """
    e = _equipos()
    http = como(e.owner_a)

    primera = _seguir(http, e.org_a, "Ayuntamiento de Alcalá", "Primera nota")
    segunda = _seguir(http, e.org_a, "AYUNTAMIENTO DE ALCALA", "Nota corregida")
    tercera = _seguir(como(e.miembro_a), e.org_a, "ayuntamiento de alcalá")

    assert primera["id"] == segunda["id"] == tercera["id"]
    # El nombre visible es el de quien lo siguió primero, no el último escrito.
    assert tercera["organo_nombre"] == "Ayuntamiento de Alcalá"
    assert segunda["nota"] == "Nota corregida"
    assert tercera["nota"] == "Nota corregida"
    assert len(_cuentas(http, e.org_a)) == 1


def test_las_cuentas_se_listan_por_nombre(como: Como) -> None:
    e = _equipos()
    http = como(e.owner_a)
    for organo in ("Diputación de Zamora", "Ayuntamiento de Burgos", "Consejería de Hacienda"):
        _seguir(http, e.org_a, organo)

    assert [c["organo_nombre"] for c in _cuentas(http, e.org_a)] == [
        "Ayuntamiento de Burgos",
        "Consejería de Hacienda",
        "Diputación de Zamora",
    ]


def test_filtrar_por_organo_encuentra_la_cuenta_escrita_de_otra_forma(como: Como) -> None:
    """La pregunta del botón «Seguir» de Mercado: ¿este órgano ya es cuenta?

    El panel pregunta con la grafía del expediente, y la cuenta pudo crearse
    tecleando otra en /cuentas: tiene que casar el nombre plegado, que es la
    clave de la cuenta. Y sólo en la organización pedida: que la B siga un
    órgano no hace que la A lo siga. Pregunta el viewer porque es una lectura;
    el botón también le tiene que decir en qué estado está.
    """
    e = _equipos()
    cuenta = _seguir(como(e.owner_a), e.org_a, "Ayuntamiento de Alcalá")
    _seguir(como(e.owner_a), e.org_a, "Ayuntamiento de Burgos")
    _seguir(como(e.owner_b), e.org_b, "Ayuntamiento de Getafe")
    http = como(e.viewer_a)

    def _de_organo(organo: str) -> list[dict[str, Any]]:
        resp = http.get(_CUENTAS, params={**_org(e.org_a), "organo": organo})
        assert resp.status_code == 200, resp.text
        return list(resp.json())

    assert [c["id"] for c in _de_organo("  AYUNTAMIENTO DE ALCALA ")] == [cuenta["id"]]
    assert _de_organo("Ayuntamiento de Getafe") == []
    assert _de_organo("Ayuntamiento de Soria") == []


def test_dejar_de_seguir_borra_la_cuenta_y_repetirlo_es_404(como: Como) -> None:
    e = _equipos()
    cuenta = _seguir(como(e.owner_a), e.org_a, "Ayuntamiento de Getafe")
    otra = _seguir(como(e.owner_a), e.org_a, "Ayuntamiento de Leganés")

    # Un miembro puede dejar de seguir lo que siguió el owner: la cartera es
    # del equipo, no de quien la creó.
    http = como(e.miembro_a)
    borrada = http.delete(f"{_CUENTAS}/{cuenta['id']}", params=_org(e.org_a))
    assert borrada.status_code == 204, borrada.text
    assert [c["id"] for c in _cuentas(http, e.org_a)] == [otra["id"]]

    otra_vez = http.delete(f"{_CUENTAS}/{cuenta['id']}", params=_org(e.org_a))
    assert otra_vez.status_code == 404


def test_dejar_de_seguir_una_cuenta_se_lleva_sus_etiquetas(como: Como) -> None:
    """Etiquetar una cuenta usa su id como ``objeto_id``, sin FK que limpie.

    ``shared/dto.py`` lo avisa junto a ``ObjetoEtiquetable``: añadir un tipo
    exige decidir cómo se limpia al borrar el objeto. Para ``cuenta`` no se
    hizo hasta 2026-09-25, y ``objetos_con_etiqueta`` —el filtro «por
    etiqueta» del repositorio— seguía devolviendo el id de la cuenta borrada.
    Ahora ``CuentasRepository.unfollow`` las borra en la misma transacción.

    También fija el alcance del arreglo. La misma etiqueta va aplicada a otra
    cuenta y a una oportunidad con el mismo ``objeto_id`` que la borrada: un
    borrado que no filtre por ``objeto_tipo`` o por ``objeto_id`` se las
    llevaría.
    """
    e = _equipos()
    etiquetas = EtiquetasRepository()
    cuentas = CuentasRepository()
    cuenta = cuentas.follow(
        organization_id=e.org_a, organo_nombre="Ayuntamiento de Getafe", user_id=e.owner_a
    )
    otra = cuentas.follow(
        organization_id=e.org_a, organo_nombre="Ayuntamiento de Leganés", user_id=e.owner_a
    )
    borrada_id, otra_id = str(cuenta["id"]), str(otra["id"])
    etiqueta_id = _etiqueta_en_bd(e.org_a, "Q4", e.owner_a)
    for tipo, objeto_id in (
        ("cuenta", borrada_id),
        ("cuenta", otra_id),
        ("oportunidad", borrada_id),
    ):
        if not etiquetas.aplicar(
            organization_id=e.org_a,
            etiqueta_id=etiqueta_id,
            objeto_tipo=tipo,
            objeto_id=objeto_id,
            user_id=e.owner_a,
        ):
            pytest.fail(f"siembra: la etiqueta no se aplicó a {tipo} {objeto_id}")

    borrada = como(e.owner_a).delete(f"{_CUENTAS}/{cuenta['id']}", params=_org(e.org_a))
    if borrada.status_code != 204:
        pytest.fail(f"precondición: dejar de seguir devolvió {borrada.status_code}")

    oportunidades = etiquetas.objetos_con_etiqueta(e.org_a, etiqueta_id, "oportunidad")
    if oportunidades != [borrada_id]:
        pytest.fail(f"se borró la etiqueta de la oportunidad con el mismo id: {oportunidades}")
    cuentas_etiquetadas = set(etiquetas.objetos_con_etiqueta(e.org_a, etiqueta_id, "cuenta"))
    assert cuentas_etiquetadas == {otra_id}


def test_sin_organization_id_la_cuenta_va_a_la_organizacion_personal(como: Como) -> None:
    """Omitir el parámetro no puede caer a «sin filtro»: resuelve a la personal."""
    e = _equipos()
    personal = int(OrganizationRepository().ensure_personal_organization(e.owner_a)["id"])
    http = como(e.owner_a)

    cuenta = _seguir(http, None, "Ayuntamiento de Móstoles")

    assert cuenta["organization_id"] == personal
    assert [c["id"] for c in _cuentas(http, None)] == [cuenta["id"]]
    assert _cuentas(http, e.org_a) == []


def test_borrar_una_cuenta_que_no_existe_es_404(como: Como) -> None:
    e = _equipos()

    resp = como(e.owner_a).delete(f"{_CUENTAS}/999999", params=_org(e.org_a))

    assert resp.status_code == 404


# ── Etiquetas: camino feliz ─────────────────────────────────────────────────


def test_crear_etiqueta_limpia_el_nombre_normaliza_el_color_y_la_lista(como: Como) -> None:
    e = _equipos()
    http = como(e.miembro_a)

    etiqueta = _crear_etiqueta(http, e.org_a, "  Prioridad Q4 ", "#AABBCC")

    assert etiqueta["organization_id"] == e.org_a
    assert etiqueta["nombre"] == "Prioridad Q4"
    assert etiqueta["nombre_norm"] == "prioridad q4"
    assert etiqueta["color"] == "#aabbcc"
    assert etiqueta["created_by_user_id"] == e.miembro_a
    assert [x["id"] for x in _etiquetas(como(e.owner_a), e.org_a)] == [etiqueta["id"]]


def test_crear_una_etiqueta_que_ya_existe_devuelve_la_misma_sin_cambiarle_el_color(
    como: Como,
) -> None:
    """Dos personas pidiendo «Q4» quieren la misma etiqueta, no un 409.

    Y la segunda no puede repintar la del equipo. En este camino —sin carrera—
    lo impide la búsqueda por ``nombre_norm`` que ``crear_etiqueta`` hace antes
    de insertar: devuelve la existente y el ``INSERT`` no llega a ejecutarse.
    El ``DO NOTHING`` del repositorio sólo decide cuando esa búsqueda llega
    tarde, y eso lo fija ``test_perder_la_carrera_al_crear_una_etiqueta_...``.
    """
    e = _equipos()
    primera = _crear_etiqueta(como(e.owner_a), e.org_a, "Q4", "#112233")

    segunda = _crear_etiqueta(como(e.miembro_a), e.org_a, "  q4 ", "#ffffff")

    assert segunda["id"] == primera["id"]
    assert segunda["color"] == "#112233"
    assert segunda["nombre"] == "Q4"
    assert len(_etiquetas(como(e.owner_a), e.org_a)) == 1


@dataclass
class Carrera:
    """Lo que devolvió cada llamada al repositorio durante la carrera simulada."""

    busquedas: list[dict[str, Any] | None] = field(default_factory=list)
    altas: list[dict[str, Any] | None] = field(default_factory=list)


def _simular_carrera(monkeypatch: pytest.MonkeyPatch, *, busquedas_ciegas: set[int]) -> Carrera:
    """Fuerza la rama de ``crear_etiqueta`` en la que otra petición insertó primero.

    Sin hilos: la búsqueda número ``n`` (desde 0) devuelve ``None`` si ``n``
    está en ``busquedas_ciegas``, aunque la etiqueta ya esté en la base. Es lo
    que ve una petición cuya búsqueda corrió justo antes del ``INSERT`` de otra.
    El alta no se toca: su ``ON CONFLICT`` es el de Postgres.

    Se sustituye el objeto entero, ``services.cuentas._etiquetas``, por una
    subclase que delega en el repositorio real, y ``monkeypatch`` repone el
    original al terminar. No se parchean los métodos de la instancia: para una
    instancia, ``monkeypatch`` guarda el método ligado y al deshacer lo vuelve a
    asignar como atributo propio, que queda para el resto de la sesión y tapa
    cualquier parche posterior sobre ``EtiquetasRepository``.
    """
    import services.cuentas as svc

    carrera = Carrera()

    class EnCarrera(EtiquetasRepository):
        def get_by_nombre(self, organization_id: int, nombre: str) -> dict[str, Any] | None:
            ciega = len(carrera.busquedas) in busquedas_ciegas
            fila = None if ciega else super().get_by_nombre(organization_id, nombre)
            carrera.busquedas.append(fila)
            return fila

        def create(
            self, *, organization_id: int, nombre: str, color: str, user_id: int | None
        ) -> dict[str, Any] | None:
            fila = super().create(
                organization_id=organization_id, nombre=nombre, color=color, user_id=user_id
            )
            carrera.altas.append(fila)
            return fila

    monkeypatch.setattr(svc, "_etiquetas", EnCarrera())
    return carrera


def test_perder_la_carrera_al_crear_una_etiqueta_devuelve_la_ganadora_sin_repintarla(
    como: Como, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La búsqueda previa no vio «Q4», el ``INSERT`` chocó y se recupera la otra.

    Aquí sí es el ``DO NOTHING`` del repositorio lo que protege el color: con
    un ``DO UPDATE`` el alta devolvería la fila repintada con el color de quien
    perdió. Y perder la carrera no es un 409: la etiqueta existe y es la que se
    pedía.
    """
    e = _equipos()
    ganadora = _crear_etiqueta(como(e.owner_a), e.org_a, "Q4", "#112233")
    carrera = _simular_carrera(monkeypatch, busquedas_ciegas={0})

    resp = como(e.miembro_a).post(
        _ETIQUETAS, params=_org(e.org_a), json={"nombre": " q4 ", "color": "#ffffff"}
    )

    assert resp.status_code == 201, resp.text
    assert resp.json() == ganadora
    # Se recorrió la rama: búsqueda ciega, alta que chocó y segunda búsqueda.
    assert carrera.altas == [None]
    assert [None if b is None else b["id"] for b in carrera.busquedas] == [None, ganadora["id"]]
    assert _etiquetas(como(e.owner_a), e.org_a) == [ganadora]


def test_si_tras_perder_la_carrera_la_etiqueta_no_aparece_es_409_sin_crear_nada(
    como: Como, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El ``EtiquetaLimiteError`` de la rama de carrera, que no es el del tope.

    El ``INSERT`` chocó, así que alguien tenía la etiqueta, pero la segunda
    búsqueda tampoco la encuentra: en producción, otra persona la creó justo
    antes y la borró antes de esa búsqueda. La ruta lo traduce a 409 como el
    tope; lo que se fija es que no se inventa nada —ni otra etiqueta ni otro
    color en la que había— y que el detalle es, literal, el de esta rama y no
    el del cupo.
    """
    e = _equipos()
    existente = _crear_etiqueta(como(e.owner_a), e.org_a, "Q4", "#112233")
    carrera = _simular_carrera(monkeypatch, busquedas_ciegas={0, 1})

    resp = como(e.miembro_a).post(
        _ETIQUETAS, params=_org(e.org_a), json={"nombre": "Q4", "color": "#ffffff"}
    )

    assert resp.status_code == 409, resp.text
    # La organización tiene una etiqueta: culpar al cupo —con el número o sin
    # él— sería falso. Se fija el texto entero para no depender de palabras sueltas.
    assert resp.json()["detail"] == "No se pudo crear ni recuperar la etiqueta."
    assert carrera.altas == [None]
    assert carrera.busquedas == [None, None]
    assert _etiquetas(como(e.owner_a), e.org_a) == [existente]


def test_color_por_defecto_si_no_se_manda(como: Como) -> None:
    e = _equipos()
    http = como(e.owner_a)

    resp = http.post(_ETIQUETAS, params=_org(e.org_a), json={"nombre": "Sin color"})

    assert resp.status_code == 201, resp.text
    assert resp.json()["color"] == "#64748b"


def test_aplicar_y_quitar_son_idempotentes_y_por_objeto_lo_refleja(como: Como) -> None:
    """``cambiado`` distingue «lo hice» de «ya estaba así».

    La segunda aplicación choca con la unique de ``etiquetas_aplicadas`` y no
    duplica la fila: si la duplicara, el chip saldría dos veces en la tarjeta.
    """
    e = _equipos()
    http = como(e.owner_a)
    etiqueta = _crear_etiqueta(http, e.org_a, "Q4", "#112233")

    assert _aplicar(http, e.org_a, etiqueta["id"], "17").json() == {"cambiado": True}
    assert _aplicar(como(e.miembro_a), e.org_a, etiqueta["id"], "17").json() == {"cambiado": False}
    assert _por_objeto(http, e.org_a, ["17"]) == {
        "17": [{"id": etiqueta["id"], "nombre": "Q4", "color": "#112233"}]
    }

    assert _quitar(http, e.org_a, etiqueta["id"], "17").json() == {"cambiado": True}
    assert _quitar(http, e.org_a, etiqueta["id"], "17").json() == {"cambiado": False}
    assert _por_objeto(http, e.org_a, ["17"]) == {}


def test_por_objeto_solo_trae_objetos_con_etiquetas_del_tipo_pedido(como: Como) -> None:
    """Los tres tipos comparten tabla y el ``objeto_id`` puede coincidir.

    Un favorito ``EXP-1`` y una cuenta ``EXP-1`` son objetos distintos: si el
    filtro de tipo se perdiera, la etiqueta de uno aparecería en el otro.
    """
    e = _equipos()
    http = como(e.owner_a)
    alfa = _crear_etiqueta(http, e.org_a, "Alfa", "#aa0000")
    beta = _crear_etiqueta(http, e.org_a, "Beta", "#00bb00")
    assert _aplicar(http, e.org_a, beta["id"], "EXP-1", tipo="favorito").status_code == 200
    assert _aplicar(http, e.org_a, alfa["id"], "EXP-1", tipo="favorito").status_code == 200
    assert _aplicar(http, e.org_a, alfa["id"], "EXP-1", tipo="cuenta").status_code == 200

    favoritos = _por_objeto(http, e.org_a, ["EXP-1", "EXP-2"], tipo="favorito")

    assert favoritos == {
        "EXP-1": [
            {"id": alfa["id"], "nombre": "Alfa", "color": "#aa0000"},
            {"id": beta["id"], "nombre": "Beta", "color": "#00bb00"},
        ]
    }
    assert _por_objeto(http, e.org_a, ["EXP-1"], tipo="cuenta") == {
        "EXP-1": [{"id": alfa["id"], "nombre": "Alfa", "color": "#aa0000"}]
    }
    assert _por_objeto(http, e.org_a, [], tipo="oportunidad") == {}


def test_borrar_una_etiqueta_se_lleva_sus_aplicaciones(como: Como) -> None:
    e = _equipos()
    http = como(e.owner_a)
    etiqueta = _crear_etiqueta(http, e.org_a, "Descartar")
    otra = _crear_etiqueta(http, e.org_a, "Seguir")
    _aplicar(http, e.org_a, etiqueta["id"], "42")
    _aplicar(http, e.org_a, otra["id"], "42")

    borrada = como(e.miembro_a).delete(f"{_ETIQUETAS}/{etiqueta['id']}", params=_org(e.org_a))

    assert borrada.status_code == 204, borrada.text
    assert [x["id"] for x in _etiquetas(http, e.org_a)] == [otra["id"]]
    assert _por_objeto(http, e.org_a, ["42"]) == {
        "42": [{"id": otra["id"], "nombre": "Seguir", "color": "#336699"}]
    }
    repetida = http.delete(f"{_ETIQUETAS}/{etiqueta['id']}", params=_org(e.org_a))
    assert repetida.status_code == 404


def test_aplicar_una_etiqueta_que_no_existe_no_cambia_nada(como: Como) -> None:
    e = _equipos()
    http = como(e.owner_a)

    resp = _aplicar(http, e.org_a, 999999, "17")

    assert resp.status_code == 200
    assert resp.json() == {"cambiado": False}
    assert _por_objeto(http, e.org_a, ["17"]) == {}


_NUL = "EXP" + chr(0) + "1"


@pytest.mark.parametrize(
    ("ruta", "cuerpo"),
    [
        pytest.param(_CUENTAS, {"organo": _NUL}, id="organo"),
        pytest.param(_CUENTAS, {"organo": "Ayuntamiento de Soria", "nota": _NUL}, id="nota"),
        pytest.param(_CUENTAS, {"organos": ["Ayuntamiento de Soria", _NUL]}, id="organos"),
        pytest.param(_ETIQUETAS, {"nombre": _NUL}, id="nombre"),
        pytest.param(
            f"{_ETIQUETAS}/aplicar",
            {"objeto_tipo": "oportunidad", "objeto_id": _NUL},
            id="aplicar-objeto_id",
        ),
        pytest.param(
            f"{_ETIQUETAS}/quitar",
            {"objeto_tipo": "oportunidad", "objeto_id": _NUL},
            id="quitar-objeto_id",
        ),
    ],
)
def test_un_byte_nul_en_un_texto_del_cuerpo_es_422(
    como: Como, sin_relanzar: TestClient, ruta: str, cuerpo: dict[str, Any]
) -> None:
    """Lo mismo que ``por-objeto`` ya resolvía con ``SafeStr``, campo a campo.

    Hasta 2026-09-25 estos campos eran ``str`` y el NUL llegaba a psycopg y
    salía como 500 (``DataError``). Aplicar y quitar usan una etiqueta que
    existe, para que el NUL sea lo único anómalo de la petición.
    """
    e = _equipos()
    if "objeto_id" in cuerpo:
        cuerpo = {**cuerpo, "etiqueta_id": _etiqueta_en_bd(e.org_a, "Q4", e.owner_a)}
    como(e.owner_a)

    resp = sin_relanzar.post(ruta, params=_org(e.org_a), json=cuerpo)

    assert resp.status_code == 422, resp.text


# ── Tope de etiquetas (D38) ─────────────────────────────────────────────────


def _llenar_cupo(http: TestClient, organization_id: int) -> list[dict[str, Any]]:
    from services.cuentas import MAX_ETIQUETAS

    return [
        _crear_etiqueta(http, organization_id, f"Etiqueta {n:02d}") for n in range(MAX_ETIQUETAS)
    ]


def test_la_etiqueta_que_supera_el_tope_es_409_y_no_se_crea(como: Como) -> None:
    """El número es la decisión D38, no un detalle: por eso se fija literal."""
    from services.cuentas import MAX_ETIQUETAS, EtiquetaLimiteError, crear_etiqueta

    assert MAX_ETIQUETAS == 30
    e = _equipos()
    http = como(e.owner_a)
    _llenar_cupo(http, e.org_a)

    resp = http.post(_ETIQUETAS, params=_org(e.org_a), json={"nombre": "La treinta y uno"})

    assert resp.status_code == 409, resp.text
    assert "30" in resp.json()["detail"]
    assert len(_etiquetas(http, e.org_a)) == 30
    # La ruta traduce la excepción de dominio; el servicio es quien la lanza.
    with pytest.raises(EtiquetaLimiteError):
        crear_etiqueta(e.miembro_a, nombre="Otra más", color="#000000", organization_id=e.org_a)


def test_con_el_cupo_lleno_pedir_una_etiqueta_que_ya_existe_no_es_409(como: Como) -> None:
    """El tope gobierna altas, no búsquedas.

    Contar antes de buscar —que es como estuvo— devolvía «llegaste al máximo»
    a quien pedía una etiqueta que su organización ya tenía.
    """
    e = _equipos()
    http = como(e.owner_a)
    existentes = _llenar_cupo(http, e.org_a)

    resp = http.post(_ETIQUETAS, params=_org(e.org_a), json={"nombre": "ETIQUETA 07"})

    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] == existentes[7]["id"]


def test_el_tope_es_por_organizacion_y_borrar_libera_hueco(como: Como) -> None:
    e = _equipos()
    llenas = _llenar_cupo(como(e.owner_a), e.org_a)

    # Otra organización no hereda el cupo consumido de la A.
    _crear_etiqueta(como(e.owner_b), e.org_b, "Propia de B")

    http = como(e.owner_a)
    borrada = http.delete(f"{_ETIQUETAS}/{llenas[0]['id']}", params=_org(e.org_a))
    assert borrada.status_code == 204
    _crear_etiqueta(http, e.org_a, "Cabe otra vez")
    assert len(_etiquetas(http, e.org_a)) == 30


# ── Aislamiento entre organizaciones ────────────────────────────────────────


def test_otra_organizacion_no_ve_las_cuentas_ajenas(como: Como) -> None:
    e = _equipos()
    ajena = _seguir(como(e.owner_a), e.org_a, "Ayuntamiento de Toledo")
    propia = _seguir(como(e.owner_b), e.org_b, "Diputación de Cuenca")

    intruso = como(e.owner_b)
    assert [c["id"] for c in _cuentas(intruso, e.org_b)] == [propia["id"]]
    assert _cuentas(intruso, None) == []

    pedida = intruso.get(_CUENTAS, params=_org(e.org_a))
    assert pedida.status_code == 403
    assert "Ayuntamiento de Toledo" not in pedida.text
    assert [c["id"] for c in _cuentas(como(e.owner_a), e.org_a)] == [ajena["id"]]


def test_otra_organizacion_no_puede_dejar_de_seguir_una_cuenta_ajena(como: Como) -> None:
    e = _equipos()
    ajena = _seguir(como(e.owner_a), e.org_a, "Ayuntamiento de Toledo")
    ruta = f"{_CUENTAS}/{ajena['id']}"

    intruso = como(e.owner_b)
    # Desde su organización: la consulta no encuentra la fila, así que no existe.
    assert intruso.delete(ruta, params=_org(e.org_b)).status_code == 404
    assert intruso.delete(ruta).status_code == 404
    # Nombrando la ajena: ni siquiera llega al repositorio.
    assert intruso.delete(ruta, params=_org(e.org_a)).status_code == 403

    assert [c["id"] for c in _cuentas(como(e.owner_a), e.org_a)] == [ajena["id"]]


def test_el_mismo_organo_seguido_por_dos_organizaciones_son_dos_cuentas(como: Como) -> None:
    """La unicidad es ``(organization_id, organo_norm)``, no el órgano a secas.

    Si fuera global, el segundo equipo en seguir un órgano recibiría la cuenta
    del primero —con su nota— como respuesta a su propio POST.
    """
    e = _equipos()
    de_a = _seguir(como(e.owner_a), e.org_a, "Ayuntamiento de Toledo", "Nota interna de A")

    de_b = _seguir(como(e.owner_b), e.org_b, "Ayuntamiento de Toledo")

    assert de_b["id"] != de_a["id"]
    assert de_b["organization_id"] == e.org_b
    assert de_b["nota"] is None
    assert [c["nota"] for c in _cuentas(como(e.owner_a), e.org_a)] == ["Nota interna de A"]


def test_otra_organizacion_no_ve_ni_borra_etiquetas_ajenas(como: Como) -> None:
    e = _equipos()
    ajena = _crear_etiqueta(como(e.owner_a), e.org_a, "Confidencial A")
    propia = _crear_etiqueta(como(e.owner_b), e.org_b, "Propia B")
    ruta = f"{_ETIQUETAS}/{ajena['id']}"

    intruso = como(e.owner_b)
    assert [x["id"] for x in _etiquetas(intruso, e.org_b)] == [propia["id"]]
    assert _etiquetas(intruso, None) == []
    assert intruso.get(_ETIQUETAS, params=_org(e.org_a)).status_code == 403

    assert intruso.delete(ruta, params=_org(e.org_b)).status_code == 404
    assert intruso.delete(ruta).status_code == 404
    assert intruso.delete(ruta, params=_org(e.org_a)).status_code == 403

    assert [x["id"] for x in _etiquetas(como(e.owner_a), e.org_a)] == [ajena["id"]]


def test_el_mismo_nombre_de_etiqueta_en_dos_organizaciones_son_dos_etiquetas(
    como: Como,
) -> None:
    e = _equipos()
    de_a = _crear_etiqueta(como(e.owner_a), e.org_a, "Q4", "#111111")

    de_b = _crear_etiqueta(como(e.owner_b), e.org_b, "q4", "#222222")

    assert de_b["id"] != de_a["id"]
    assert de_b["organization_id"] == e.org_b
    assert de_b["color"] == "#222222"


def test_otra_organizacion_no_puede_aplicar_una_etiqueta_ajena(como: Como) -> None:
    """Aplicar con la etiqueta de otro no puede colarla en ninguna de las dos.

    El control va en el ``WHERE`` del ``INSERT ... SELECT``: la respuesta es
    ``cambiado: false``, que por diseño no distingue «no es tuya» de «ya
    estaba», y lo que se comprueba es que no quedó fila en ningún lado.
    """
    e = _equipos()
    ajena = _crear_etiqueta(como(e.owner_a), e.org_a, "Confidencial A")

    intruso = como(e.owner_b)
    desde_la_suya = _aplicar(intruso, e.org_b, ajena["id"], "17")
    assert desde_la_suya.status_code == 200
    assert desde_la_suya.json() == {"cambiado": False}
    assert _aplicar(intruso, e.org_a, ajena["id"], "17").status_code == 403

    assert _por_objeto(intruso, e.org_b, ["17"]) == {}
    assert _por_objeto(como(e.owner_a), e.org_a, ["17"]) == {}


def test_otra_organizacion_no_puede_quitar_ni_leer_aplicaciones_ajenas(como: Como) -> None:
    e = _equipos()
    ajena = _crear_etiqueta(como(e.owner_a), e.org_a, "Confidencial A")
    assert _aplicar(como(e.owner_a), e.org_a, ajena["id"], "17").json() == {"cambiado": True}

    intruso = como(e.owner_b)
    assert _quitar(intruso, e.org_b, ajena["id"], "17").json() == {"cambiado": False}
    assert _quitar(intruso, None, ajena["id"], "17").json() == {"cambiado": False}
    assert _quitar(intruso, e.org_a, ajena["id"], "17").status_code == 403
    assert _por_objeto(intruso, e.org_b, ["17"]) == {}
    leida = intruso.post(
        f"{_ETIQUETAS}/por-objeto",
        params=_org(e.org_a),
        json={"objeto_tipo": "oportunidad", "objeto_ids": ["17"]},
    )
    assert leida.status_code == 403
    assert "Confidencial" not in leida.text

    assert _por_objeto(como(e.owner_a), e.org_a, ["17"]) == {
        "17": [{"id": ajena["id"], "nombre": "Confidencial A", "color": "#336699"}]
    }


def test_por_objeto_no_mezcla_etiquetas_de_dos_organizaciones_sobre_el_mismo_objeto(
    como: Como,
) -> None:
    """Dos equipos pueden etiquetar el mismo favorito: cada uno ve sólo lo suyo."""
    e = _equipos()
    de_a = _crear_etiqueta(como(e.owner_a), e.org_a, "Etiqueta de A")
    de_b = _crear_etiqueta(como(e.owner_b), e.org_b, "Etiqueta de B")
    _aplicar(como(e.owner_a), e.org_a, de_a["id"], "EXP-9", tipo="favorito")
    _aplicar(como(e.owner_b), e.org_b, de_b["id"], "EXP-9", tipo="favorito")

    vistas_por_a = _por_objeto(como(e.owner_a), e.org_a, ["EXP-9"], tipo="favorito")
    vistas_por_b = _por_objeto(como(e.owner_b), e.org_b, ["EXP-9"], tipo="favorito")

    assert [x["id"] for x in vistas_por_a["EXP-9"]] == [de_a["id"]]
    assert [x["id"] for x in vistas_por_b["EXP-9"]] == [de_b["id"]]


def test_sin_membresia_no_se_escribe_en_la_organizacion_ajena(como: Como) -> None:
    e = _equipos()
    etiqueta_a = _crear_etiqueta(como(e.owner_a), e.org_a, "Q4")

    intruso = como(e.owner_b)
    assert (
        intruso.post(_CUENTAS, params=_org(e.org_a), json={"organo": "Colado"}).status_code == 403
    )
    assert (
        intruso.post(_ETIQUETAS, params=_org(e.org_a), json={"nombre": "Colada"}).status_code == 403
    )

    owner = como(e.owner_a)
    assert _cuentas(owner, e.org_a) == []
    assert [x["id"] for x in _etiquetas(owner, e.org_a)] == [etiqueta_a["id"]]


def test_quien_deja_el_equipo_pierde_el_acceso_a_su_cartera(como: Como) -> None:
    """La membresía se comprueba en cada petición, no al crear el recurso.

    Es la razón de que la cartera sea de la organización: el comercial que se
    va no se lleva las cuentas, ni puede seguir leyéndolas ni borrándolas.
    """
    e = _equipos()
    cuenta = _seguir(como(e.miembro_a), e.org_a, "Ayuntamiento de Ávila")
    etiqueta = _crear_etiqueta(como(e.miembro_a), e.org_a, "Mía")
    OrganizationRepository().add_membership(e.org_a, e.miembro_a, "member", status="revoked")

    ex_miembro = como(e.miembro_a)
    assert ex_miembro.get(_CUENTAS, params=_org(e.org_a)).status_code == 403
    assert ex_miembro.get(_ETIQUETAS, params=_org(e.org_a)).status_code == 403
    assert ex_miembro.delete(f"{_CUENTAS}/{cuenta['id']}", params=_org(e.org_a)).status_code == 403
    assert (
        ex_miembro.delete(f"{_ETIQUETAS}/{etiqueta['id']}", params=_org(e.org_a)).status_code == 403
    )

    owner = como(e.owner_a)
    assert [c["id"] for c in _cuentas(owner, e.org_a)] == [cuenta["id"]]
    assert [x["id"] for x in _etiquetas(owner, e.org_a)] == [etiqueta["id"]]


# ── Roles ───────────────────────────────────────────────────────────────────


def test_un_viewer_lee_la_cartera_del_equipo(como: Como) -> None:
    e = _equipos()
    cuenta = _seguir(como(e.owner_a), e.org_a, "Ayuntamiento de Segovia")
    etiqueta = _crear_etiqueta(como(e.owner_a), e.org_a, "Q4")
    _aplicar(como(e.owner_a), e.org_a, etiqueta["id"], "17")

    viewer = como(e.viewer_a)

    assert [c["id"] for c in _cuentas(viewer, e.org_a)] == [cuenta["id"]]
    assert [x["id"] for x in _etiquetas(viewer, e.org_a)] == [etiqueta["id"]]
    assert list(_por_objeto(viewer, e.org_a, ["17"])) == ["17"]


#: Las nueve escrituras de la cartera, por nombre para poder parametrizarlas
#: antes de que existan los ids de la cuenta, su órgano y la etiqueta.
_ESCRITURAS = (
    "POST-cuentas",
    "POST-cuenta-varios-organos",
    "PATCH-cuenta",
    "POST-organos",
    "DELETE-organo",
    "DELETE-cuenta",
    "POST-etiquetas",
    "DELETE-etiqueta",
    "POST-aplicar",
    "POST-quitar",
)


def _escrituras_del_viewer(
    cuenta_id: int, etiqueta_id: int, organo_id: int
) -> dict[str, tuple[str, str, dict[str, Any] | None]]:
    cuenta = f"{_CUENTAS}/{cuenta_id}"
    return {
        "POST-cuentas": ("post", _CUENTAS, {"organo": "Ayuntamiento de Viewer"}),
        "POST-cuenta-varios-organos": (
            "post",
            _CUENTAS,
            {"nombre": "Cliente del viewer", "organos": ["Órgano del viewer"]},
        ),
        "PATCH-cuenta": ("patch", cuenta, {"nota": "Del viewer"}),
        "POST-organos": ("post", f"{cuenta}/organos", {"organos": ["Otro órgano"]}),
        "DELETE-organo": ("delete", f"{cuenta}/organos/{organo_id}", None),
        "DELETE-cuenta": ("delete", cuenta, None),
        "POST-etiquetas": ("post", _ETIQUETAS, {"nombre": "Del viewer"}),
        "DELETE-etiqueta": ("delete", f"{_ETIQUETAS}/{etiqueta_id}", None),
        "POST-aplicar": ("post", f"{_ETIQUETAS}/aplicar", _aplicacion(etiqueta_id, "99")),
        "POST-quitar": ("post", f"{_ETIQUETAS}/quitar", _aplicacion(etiqueta_id, "17")),
    }


def test_un_viewer_no_puede_escribir_nada_en_la_cartera(
    como: Como, sin_relanzar: TestClient
) -> None:
    """Lo que no puede pasar, se traduzca el rechazo como se traduzca.

    El servicio resuelve con ``write=True`` en todas las escrituras; si alguna
    se quedara en lectura, un viewer podría borrar la cartera del equipo.
    """
    e = _equipos()
    cuenta_id, etiqueta_id = _sembrar_cartera(e)
    organo_id = _primer_organo(e.org_a, cuenta_id)
    antes = _cuentas(como(e.owner_a), e.org_a)

    como(e.viewer_a)
    escrituras = _escrituras_del_viewer(cuenta_id, etiqueta_id, organo_id)
    for nombre, (metodo, ruta, cuerpo) in escrituras.items():
        resp = sin_relanzar.request(metodo.upper(), ruta, params=_org(e.org_a), json=cuerpo)
        assert not resp.is_success, f"{nombre} -> {resp.status_code}"
        # Un 404 o un `cambiado: false` también serían «no hice nada», pero
        # dirían algo falso sobre el recurso: tiene que ser un rechazo.
        assert resp.status_code not in (404, 422), nombre

    owner = como(e.owner_a)
    # La cuenta entera —nombre, nota y órganos—, no sólo que siga existiendo.
    assert _cuentas(owner, e.org_a) == antes
    assert [x["id"] for x in _etiquetas(owner, e.org_a)] == [etiqueta_id]
    assert list(_por_objeto(owner, e.org_a, ["17", "99"])) == ["17"]


@pytest.mark.parametrize("escritura", _ESCRITURAS)
def test_un_viewer_que_intenta_escribir_recibe_403(
    como: Como, sin_relanzar: TestClient, escritura: str
) -> None:
    """Un caso por ruta, contra Postgres y con la membresía de verdad.

    Hasta 2026-09-25 las seis salían como 500 (eran ``xfail`` estrictos): las
    rutas sólo capturaban ``OrganizationAccessError`` y el viewer lanza su
    hermano ``OrganizationPermissionError``. Importa más desde que el botón
    «Seguir» del panel de órgano de Mercado escribe en /cuentas: el viewer que
    lo pulse tiene que leer que su rol es de sólo lectura, no un error del
    servidor. La traducción, ruta a ruta y sin base, está en
    ``test_cuentas_objetivo_rechazos.py``.
    """
    e = _equipos()
    cuenta_id, etiqueta_id = _sembrar_cartera(e)
    organo_id = _primer_organo(e.org_a, cuenta_id)
    metodo, ruta, cuerpo = _escrituras_del_viewer(cuenta_id, etiqueta_id, organo_id)[escritura]
    como(e.viewer_a)

    resp = sin_relanzar.request(metodo.upper(), ruta, params=_org(e.org_a), json=cuerpo)

    assert resp.status_code == 403, resp.text

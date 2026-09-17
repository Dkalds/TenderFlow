"""F5.4 — «qué cambió desde tu última visita», contra Postgres real.

``services/novedades.py`` fusiona cuatro fuentes —historial de lo seguido,
documentos nuevos, recursos resueltos y el ledger del equipo— acotadas por una
marca temporal. Estos tests fijan lo que el usuario no puede comprobar por sí
mismo: que el corte es el de **su** última visita, que sólo entra lo que **él**
sigue (y lo de **su** equipo, si lo pide), y que un cambio llega con nombre en
vez de como «algo cambió».

Las marcas se generan relativas a ahora y no como literales: el servicio recorta
la ventana a ``DIAS_MAXIMOS`` contra el reloj real, así que una fecha fija
envejecería hasta salirse de la ventana y el test pasaría a afirmar otra cosa
sin que nadie lo notara.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

from db.database import connect
from db.repositories.novedades import NovedadesRepository
from services.novedades import DIAS_MAXIMOS, NovedadesDesdeUltimaVisita, desde_ultima_visita

_UK_ANA = "uk-novedades-ana"
_UK_BEA = "uk-novedades-bea"

#: Estado vigente de las licitaciones sembradas. Un snapshot con estos mismos
#: valores no tiene nada que nombrar y cae al aviso genérico.
_VIGENTE = {"estado": "PUB", "fecha_limite": "2026-12-01", "importe": 100_000.0}


# ---------------------------------------------------------------------------
# Siembra
# ---------------------------------------------------------------------------


def _hace(**delta: float) -> datetime:
    return datetime.now(UTC) - timedelta(**delta)


def _iso(**delta: float) -> str:
    return _hace(**delta).isoformat()


def _texto_de_now(momento: datetime) -> str:
    """Lo que deja ``now()`` en una columna ``text`` como ``documentos.created_at``.

    La ingesta no escribe esa columna: la rellena el ``DEFAULT now()``, y el
    cast a texto usa espacio y no ``T``. Sembrar el formato de producción es lo
    que hace que estos tests midan la comparación que corre de verdad.
    """
    return momento.strftime("%Y-%m-%d %H:%M:%S.%f+00")


def _licitacion(
    id_externo: str,
    *,
    estado: str = "PUB",
    fecha_limite: str = "2026-12-01",
    importe: float = 100_000.0,
) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, estado, fecha_limite, importe, fecha_extraccion) "
            "VALUES (%s, %s, %s, %s, %s, '2026-09-01')",
            (id_externo, f"Expediente {id_externo}", estado, fecha_limite, importe),
        )


def _seguir(user_key: str, id_externo: str) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO watchlist_items (user_key, id_externo, created_at) "
            "VALUES (%s, %s, '2026-09-01')",
            (user_key, id_externo),
        )


def _historial(
    id_externo: str,
    *,
    cuando: str,
    snapshot: dict[str, object] | str = _VIGENTE,
    cambiados: str = "estado",
) -> None:
    crudo = snapshot if isinstance(snapshot, str) else json.dumps(snapshot)
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones_history "
            "(id_externo, captured_at, snapshot_json, changed_fields) VALUES (%s, %s, %s, %s)",
            (id_externo, cuando, crudo, cambiados),
        )


def _documento(licitacion_id: str, *, uri: str, creado: datetime, tipo: str = "technical") -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO documentos (licitacion_id, tipo, uri, filename, created_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (licitacion_id, tipo, uri, uri.rsplit("/", 1)[-1], _texto_de_now(creado)),
        )


def _recurso(licitacion_id: str, *, numero: str, fecha: str, sentido: str = "estimado") -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO resoluciones_recurso "
            "(numero_resolucion, fecha, sentido, licitacion_id, fecha_extraccion) "
            "VALUES (%s, %s, %s, %s, %s)",
            (numero, fecha, sentido, licitacion_id, _iso()),
        )


def _usuario_con_equipo(email: str, nombre_equipo: str) -> tuple[int, int]:
    """``(user_id, organization_id)`` reales: el ledger tiene FK a ambos."""
    from db.repositories.organizations import OrganizationRepository
    from db.users import create_user

    user_id = create_user(
        email=email,
        password_hash="test-hash",  # pragma: allowlist secret
        display_name=nombre_equipo,
    )
    organizacion = OrganizationRepository().create_organization(nombre_equipo, user_id)
    return user_id, int(organizacion["id"])


def _abrir_oportunidad(user_id: int, organization_id: int, licitacion_id: str) -> int:
    """Por el servicio, que es quien escribe el evento del ledger."""
    from services.pursuits import create_pursuit
    from shared.dto import PursuitCreate

    pursuit, _ = create_pursuit(
        user_id, PursuitCreate(licitacion_id=licitacion_id, organization_id=organization_id)
    )
    return pursuit.id


def _evento_fechado(user_id: int, organization_id: int, licitacion_id: str, *, cuando: str) -> None:
    """Una oportunidad cuyo único movimiento lleva la fecha ``cuando``.

    ``pursuit_events`` es append-only (hay trigger), así que un evento con otra
    fecha no se consigue moviendo uno escrito por el servicio: se escribe ya
    con la suya.
    """
    with connect() as c:
        pursuit_id = c.execute(
            "INSERT INTO pursuits (organization_id, licitacion_id, responsible_user_id, status) "
            "VALUES (%s, %s, %s, 'qualifying') RETURNING id",
            (organization_id, licitacion_id, user_id),
        ).fetchone()[0]
        c.execute(
            "INSERT INTO pursuit_events "
            "(pursuit_id, organization_id, event_type, actor_user_id, created_at) "
            "VALUES (%s, %s, 'pursuit.updated', %s, %s)",
            (pursuit_id, organization_id, user_id, cuando),
        )


def _por_expediente(resultado: NovedadesDesdeUltimaVisita) -> set[str | None]:
    return {n.licitacion_id for n in resultado.items}


class _SintomaDelBug(Exception):
    """El valor exacto que produce un bug abierto, y sólo ése.

    Los xfail de este módulo declaran ``raises=_SintomaDelBug`` y no
    ``AssertionError``. Así, cualquier otra excepción —un ``assert`` que falle
    en la siembra, un fixture roto, un error dentro del servicio o la
    comprobación de control del propio test— sale en rojo (FAILED, o ERROR si
    rompe el fixture) en vez de absorberse como XFAIL. No hereda de
    ``AssertionError`` para que no quepa la duda.

    Se distingue por el valor, no por la causa: otra regresión que dé
    exactamente el mismo resultado que el bug también sale XFAIL. Por ejemplo,
    el xfail del pliego de hoy frente al cambio de hoy da el mismo valor con un
    diff ordenado sólo por fecha; ese caso lo fija, sin xfail,
    ``test_dentro_del_mismo_dia_el_orden_tambien_es_por_hora``.
    """


def _sintoma_del_bug(obtenido: object, *, correcto: object, con_el_bug: object) -> None:
    """La aserción final de un xfail, con sus tres salidas separadas.

    * ``obtenido == correcto``: vuelve sin más. El test pasa y, como el xfail
      es estricto, sale XPASS y obliga a quitar el marcador.
    * ``obtenido == con_el_bug``: lanza ``_SintomaDelBug``, lo único que el
      xfail acepta.
    * Cualquier otro valor es una regresión distinta de la documentada y falla
      con ``AssertionError``: no se deja esconder detrás del bug conocido.
    """
    if obtenido == correcto:
        return
    assert obtenido == con_el_bug, (
        f"ni el resultado correcto ({correcto!r}) ni el del bug ({con_el_bug!r}): {obtenido!r}"
    )
    raise _SintomaDelBug(f"{obtenido!r} en vez de {correcto!r}")


# ---------------------------------------------------------------------------
# Qué cuenta como novedad
# ---------------------------------------------------------------------------


def test_las_cuatro_fuentes_llegan_fusionadas_y_con_nombre(tmp_db):
    """Un expediente seguido con un cambio, un pliego, un recurso y una
    oportunidad movida: cuatro líneas del diff, cada una con su subtipo."""
    user_id, org_id = _usuario_con_equipo("novedades-fusion@example.test", "Equipo fusión")
    _licitacion("NOV-1", fecha_limite="2026-12-10")
    _seguir(_UK_ANA, "NOV-1")
    _historial("NOV-1", cuando=_iso(hours=20), snapshot={"fecha_limite": "2026-12-01"})
    _documento("NOV-1", uri="https://placsp.test/NOV-1/pliego.pdf", creado=_hace(days=1))
    _recurso("NOV-1", numero="R-1/2026", fecha=_hace(days=1).date().isoformat())
    _abrir_oportunidad(user_id, org_id, "NOV-1")

    resultado = desde_ultima_visita(_UK_ANA, last_seen=_iso(days=2), organization_id=org_id)

    assert resultado.por_subtipo == {
        "plazo_ampliado": 1,
        "documento_nuevo": 1,
        "recurso": 1,
        "pursuit": 1,
    }
    assert _por_expediente(resultado) == {"NOV-1"}
    titulos = {n.subtipo: n.titulo for n in resultado.items}
    assert titulos["plazo_ampliado"] == "Plazo ampliado al 10/12/2026"
    # El tipo de adjunto y el sentido van en el titular: deciden si hay que
    # dejarlo todo, y sin ellos las dos líneas dirían lo mismo.
    assert titulos["documento_nuevo"] == "Documento nuevo: technical"
    assert titulos["recurso"] == "Recurso estimado"
    assert titulos["pursuit"] == "Tu equipo movió «Expediente NOV-1»"
    pursuit = next(n for n in resultado.items if n.subtipo == "pursuit")
    assert pursuit.detalle == "Ahora está en identified."


def test_lo_que_no_se_sigue_no_es_novedad(tmp_db):
    """El corpus cambia miles de filas al día; el diff personal sólo mira lo
    que el usuario sigue."""
    _licitacion("NOV-SEGUIDO")
    _licitacion("NOV-AJENO")
    _seguir(_UK_ANA, "NOV-SEGUIDO")
    _historial("NOV-AJENO", cuando=_iso(hours=3))
    _documento("NOV-AJENO", uri="https://placsp.test/ajeno.pdf", creado=_hace(days=1))
    _recurso("NOV-AJENO", numero="R-AJENO", fecha=_hace(days=1).date().isoformat())

    resultado = desde_ultima_visita(_UK_ANA, last_seen=_iso(days=2))

    assert resultado.items == []


def test_sin_novedades_la_banda_llega_igual_con_su_corte(tmp_db):
    """Cero ítems no es una respuesta vacía: la UI necesita ``desde`` para
    decir «sin novedades desde el jueves» en vez de parecer rota."""
    marca = _iso(days=3)

    resultado = desde_ultima_visita(_UK_ANA, last_seen=marca)

    assert resultado.items == []
    assert resultado.por_subtipo == {}
    assert resultado.desde == marca
    assert resultado.ventana_recortada is False


def test_la_rotacion_del_token_de_placsp_no_se_anuncia_como_documento_nuevo(tmp_db):
    """El mismo pliego con otra URL no es un pliego nuevo.

    PLACSP re-emite el token de sus enlaces; la ingesta lo reconoce por
    ``source_hash`` y refresca la fila en vez de insertar otra. Si el diff lo
    tomara por nuevo, el aviso de F5.1 sería ruido diario.
    """
    from db.repositories.documentos import DocumentosRepository
    from db.upsert import DocumentoReferencia

    _licitacion("NOV-TOKEN")
    _seguir(_UK_ANA, "NOV-TOKEN")
    repo = DocumentosRepository()
    repo.upsert_meta(
        "NOV-TOKEN",
        [DocumentoReferencia(tipo="legal", uri="https://placsp.test/doc?t=AAA", source_hash="H1")],
    )
    with connect() as c:
        c.execute(
            "UPDATE documentos SET created_at = %s WHERE licitacion_id = 'NOV-TOKEN'",
            (_texto_de_now(_hace(days=5)),),
        )

    repo.upsert_meta(
        "NOV-TOKEN",
        [DocumentoReferencia(tipo="legal", uri="https://placsp.test/doc?t=BBB", source_hash="H1")],
    )

    assert desde_ultima_visita(_UK_ANA, last_seen=_iso(days=2)).items == []


@pytest.mark.parametrize(
    ("metodo", "subtipo_perdido"),
    [
        ("cambios_en_seguidos", "cambio"),
        ("documentos_nuevos_en_seguidos", "documento_nuevo"),
        ("recursos_en_seguidos", "recurso"),
        ("pursuits_movidos", "pursuit"),
    ],
    ids=["historial", "documentos", "recursos", "ledger"],
)
def test_una_fuente_caida_no_esconde_las_demas(tmp_db, monkeypatch, metodo, subtipo_perdido):
    """Cada fuente va en su propio ``try``: que una tabla falle no puede dejar
    al usuario sin enterarse de lo que traen las otras tres.

    Se rompe una fuente cada vez porque el aislamiento es por bloque: que
    aguante la caída del historial no dice nada de la de los documentos.
    """
    user_id, org_id = _usuario_con_equipo("novedades-caida@example.test", "Equipo caída")
    _licitacion("NOV-CAIDA")
    _seguir(_UK_ANA, "NOV-CAIDA")
    _historial("NOV-CAIDA", cuando=_iso(hours=5))
    _documento("NOV-CAIDA", uri="https://placsp.test/caida.pdf", creado=_hace(days=1))
    _recurso("NOV-CAIDA", numero="R-CAIDA", fecha=_hace(days=1).date().isoformat())
    _abrir_oportunidad(user_id, org_id, "NOV-CAIDA")

    def _fuente_caida(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise RuntimeError(f"{metodo} no responde")

    monkeypatch.setattr(NovedadesRepository, metodo, _fuente_caida)

    resultado = desde_ultima_visita(_UK_ANA, last_seen=_iso(days=2), organization_id=org_id)

    esperado = {"cambio": 1, "documento_nuevo": 1, "recurso": 1, "pursuit": 1}
    del esperado[subtipo_perdido]
    assert resultado.por_subtipo == esperado


# ---------------------------------------------------------------------------
# Snapshot y campos cambiados
# ---------------------------------------------------------------------------


def test_el_cambio_que_escribe_la_ingesta_llega_con_nombre(tmp_db):
    """Extremo a extremo: el historial lo escribe ``upsert_licitaciones_with_history``
    con su formato real (snapshot JSON del estado anterior, campos en CSV) y
    el diff tiene que poder nombrarlo."""
    from db.upsert import Licitacion, upsert_licitaciones_with_history

    def _version(fecha_limite: str) -> Licitacion:
        return Licitacion(
            id_externo="NOV-INGESTA",
            titulo="Soporte SAP S/4HANA",
            estado="PUB",
            fecha_limite=fecha_limite,
            importe=250_000.0,
        )

    upsert_licitaciones_with_history([_version("2026-11-15T21:59:00+00:00")], source="pub")
    _seguir(_UK_ANA, "NOV-INGESTA")
    upsert_licitaciones_with_history([_version("2026-11-30T21:59:00+00:00")], source="atom_live")

    resultado = desde_ultima_visita(_UK_ANA, last_seen=_iso(hours=1))

    assert len(resultado.items) == 1
    novedad = resultado.items[0]
    assert novedad.subtipo == "plazo_ampliado"
    assert novedad.titulo == "Plazo ampliado al 30/11/2026"
    assert novedad.detalle == "Antes cerraba el 15/11/2026."
    assert novedad.licitacion_id == "NOV-INGESTA"
    assert novedad.cuando >= resultado.desde


@pytest.mark.parametrize(
    ("vigente", "snapshot", "cambiados", "subtipo", "titulo", "detalle"),
    [
        (
            {"estado": "ANUL"},
            {"estado": "PUB", "fecha_limite": "2026-11-01"},
            "estado,fecha_limite",
            "anulado",
            "Expediente anulado",
            "Ya no se puede presentar oferta.",
        ),
        (
            {"fecha_limite": "2026-11-20"},
            {"fecha_limite": "2026-12-01"},
            "fecha_limite",
            "plazo_acortado",
            "Plazo acortado al 20/11/2026",
            "Antes cerraba el 01/12/2026.",
        ),
        (
            {"importe": 120_000.0},
            {"importe": 100_000.0},
            "importe",
            "importe_corregido",
            "Importe corregido a 120.000 €",
            "Antes era 100.000 €.",
        ),
    ],
    ids=["anulacion_gana_al_plazo", "plazo_acortado", "importe_corregido"],
)
def test_el_snapshot_anterior_contra_la_fila_vigente_decide_el_nombre(
    tmp_db, vigente, snapshot, cambiados, subtipo, titulo, detalle
):
    """El «antes» sale del snapshot guardado y el «después» de la licitación
    vigente: el diff no vuelve a consultar para ponerle nombre al cambio.

    La clasificación en sí ya la fija ``test_avisos_y_novedades.py`` con
    diccionarios en memoria. Lo que se mira aquí es el cableado: que cada lado
    salga de su tabla. Si se cruzaran, el plazo acortado se anunciaría como
    ampliado y la anulación no se vería."""
    _licitacion("NOV-SNAP", **vigente)
    _seguir(_UK_ANA, "NOV-SNAP")
    _historial("NOV-SNAP", cuando=_iso(hours=2), snapshot=snapshot, cambiados=cambiados)

    [novedad] = desde_ultima_visita(_UK_ANA, last_seen=_iso(days=1)).items

    assert (novedad.subtipo, novedad.titulo, novedad.detalle) == (subtipo, titulo, detalle)


def test_un_snapshot_ilegible_cae_al_generico_con_los_campos(tmp_db):
    """Un historial corrupto no puede tragarse el aviso: perderlo por no saber
    nombrarlo sería peor que avisar sin nombre."""
    _licitacion("NOV-CORRUPTO")
    _seguir(_UK_ANA, "NOV-CORRUPTO")
    _historial(
        "NOV-CORRUPTO",
        cuando=_iso(hours=2),
        snapshot="{no es json",
        cambiados="url,organo_contratacion",
    )

    [novedad] = desde_ultima_visita(_UK_ANA, last_seen=_iso(days=1)).items

    assert novedad.subtipo == "cambio"
    assert novedad.titulo == "Cambio en el expediente"
    assert novedad.detalle == "organo_contratacion, url"


@pytest.mark.parametrize(
    "cambiados",
    ["url, organo_contratacion", '["url", "organo_contratacion"]'],
    ids=["csv", "json"],
)
def test_changed_fields_en_csv_o_en_json_dicen_lo_mismo(tmp_db, cambiados):
    """``changed_fields`` llegó en dos formatos según la época; el aviso
    genérico tiene que nombrar los mismos campos con cualquiera de los dos."""
    _licitacion("NOV-CAMPOS")
    _seguir(_UK_ANA, "NOV-CAMPOS")
    _historial("NOV-CAMPOS", cuando=_iso(hours=2), cambiados=cambiados)

    [novedad] = desde_ultima_visita(_UK_ANA, last_seen=_iso(days=1)).items

    assert (novedad.subtipo, novedad.detalle) == ("cambio", "organo_contratacion, url")


# ---------------------------------------------------------------------------
# Corte por la última visita
# ---------------------------------------------------------------------------


def test_solo_entra_lo_posterior_a_la_ultima_visita(tmp_db):
    """Lo anterior a la marca ya se vio; repetirlo convierte el diff en catálogo."""
    user_id, org_id = _usuario_con_equipo("novedades-corte@example.test", "Equipo corte")
    for id_externo in ("NOV-CORTE", "NOV-CORTE-VIEJO"):
        _licitacion(id_externo)
        _seguir(_UK_ANA, id_externo)
    _historial("NOV-CORTE", cuando=_iso(days=3), cambiados="url")
    _historial("NOV-CORTE", cuando=_iso(days=1), cambiados="organo_contratacion")
    _documento("NOV-CORTE", uri="https://placsp.test/viejo.pdf", creado=_hace(days=3))
    _documento("NOV-CORTE", uri="https://placsp.test/nuevo.pdf", creado=_hace(days=1))
    _recurso("NOV-CORTE", numero="R-VIEJO", fecha=_hace(days=3).date().isoformat())
    _recurso("NOV-CORTE", numero="R-NUEVO", fecha=_hace(days=1).date().isoformat())
    _evento_fechado(user_id, org_id, "NOV-CORTE-VIEJO", cuando=_iso(days=3))
    _abrir_oportunidad(user_id, org_id, "NOV-CORTE")

    marca = _iso(days=2)
    resultado = desde_ultima_visita(_UK_ANA, last_seen=marca, organization_id=org_id)

    assert resultado.desde == marca
    assert resultado.por_subtipo == {"cambio": 1, "documento_nuevo": 1, "recurso": 1, "pursuit": 1}
    cambio = next(n for n in resultado.items if n.subtipo == "cambio")
    assert cambio.detalle == "organo_contratacion"
    assert _por_expediente(resultado) == {"NOV-CORTE"}


def test_sin_ultima_visita_se_usa_la_ventana_maxima(tmp_db):
    """Primera visita o navegador nuevo: se enseña lo de la ventana entera en
    vez de decir «nada», que sería falso."""
    _licitacion("NOV-PRIMERA")
    _seguir(_UK_ANA, "NOV-PRIMERA")
    _historial("NOV-PRIMERA", cuando=_iso(days=DIAS_MAXIMOS - 4), cambiados="url")
    _historial("NOV-PRIMERA", cuando=_iso(days=DIAS_MAXIMOS + 6), cambiados="titulo")

    resultado = desde_ultima_visita(_UK_ANA, last_seen=None)

    assert [n.detalle for n in resultado.items] == ["url"]
    assert resultado.ventana_recortada is False
    desde = datetime.fromisoformat(resultado.desde)
    assert abs(desde - _hace(days=DIAS_MAXIMOS)) < timedelta(minutes=1)


def test_una_visita_mas_antigua_que_la_ventana_se_recorta_y_lo_dice(tmp_db):
    """Quien vuelve tras un mes no recibe un mes de cambios; y la UI tiene que
    poder decir que hubo más, en vez de dar a entender que no pasó nada."""
    _licitacion("NOV-RECORTE")
    _seguir(_UK_ANA, "NOV-RECORTE")
    _historial("NOV-RECORTE", cuando=_iso(days=DIAS_MAXIMOS - 4), cambiados="url")
    _historial("NOV-RECORTE", cuando=_iso(days=DIAS_MAXIMOS + 6), cambiados="titulo")

    resultado = desde_ultima_visita(_UK_ANA, last_seen=_iso(days=DIAS_MAXIMOS + 16))

    assert [n.detalle for n in resultado.items] == ["url"]
    assert resultado.ventana_recortada is True


@pytest.mark.parametrize(
    "formato",
    [
        lambda m: m.isoformat(),
        lambda m: m.strftime("%Y-%m-%dT%H:%M:%SZ"),
        lambda m: m.replace(tzinfo=None).isoformat(),
    ],
    ids=["utc_con_offset", "utc_con_z", "sin_zona"],
)
def test_z_y_la_marca_sin_zona_cortan_igual_que_utc(tmp_db, formato):
    """``Z`` y la marca sin zona se leen como UTC: las tres grafías de la
    misma marca dan el mismo corte y el mismo ``desde``. Sólo cubre marcas
    UTC; con otro offset el corte se desplaza (ver el xfail de abajo)."""
    marca = _hace(days=2).replace(microsecond=0)
    _licitacion("NOV-ZONA")
    _seguir(_UK_ANA, "NOV-ZONA")
    _historial("NOV-ZONA", cuando=_iso(days=3), cambiados="titulo")
    _historial("NOV-ZONA", cuando=_iso(days=1), cambiados="url")

    resultado = desde_ultima_visita(_UK_ANA, last_seen=formato(marca))

    assert resultado.desde == marca.isoformat()
    assert [n.detalle for n in resultado.items] == ["url"]


@pytest.mark.xfail(
    strict=True,
    raises=_SintomaDelBug,
    reason=(
        "Bug latente: desde_ultima_visita no pasa a UTC una marca con otro offset "
        "(no hay astimezone) y el corte llega al SQL como '...T19:00:00+02:00'. "
        "Comparado como texto contra columnas en UTC, todo lo ocurrido en las dos "
        "horas siguientes a la marca queda fuera. Hoy la ruta sólo le pasa read_at "
        "de now_utc_iso(), así que no se ve desde la API. Al corregirlo, quitar el "
        "xfail."
    ),
)
def test_una_marca_con_otro_offset_corta_en_el_mismo_instante(tmp_db):
    """La firma acepta cualquier ISO con zona; el instante es lo que manda, no
    la hora de pared de la zona en que se escribió."""
    marca = _hace(days=2).replace(microsecond=0)
    _licitacion("NOV-OFFSET")
    _seguir(_UK_ANA, "NOV-OFFSET")
    # Una hora antes y una después de la marca: en `+02:00` la hora de pared de
    # la marca va dos por delante de la de ambas filas, así que el fallo no
    # depende de la hora ni del día en que corra la suite.
    _historial("NOV-OFFSET", cuando=(marca - timedelta(hours=1)).isoformat(), cambiados="titulo")
    _historial("NOV-OFFSET", cuando=(marca + timedelta(hours=1)).isoformat(), cambiados="url")

    madrid_verano = timezone(timedelta(hours=2))

    en_utc = desde_ultima_visita(_UK_ANA, last_seen=marca.isoformat())
    en_madrid = desde_ultima_visita(_UK_ANA, last_seen=marca.astimezone(madrid_verano).isoformat())

    # Control: con la misma marca escrita en UTC sale justo la fila posterior.
    # Si falla, lo roto no es el offset, y el test cae en rojo en vez de XFAIL.
    assert [n.detalle for n in en_utc.items] == ["url"]
    # Con el bug, el corte de pared en `+02:00` deja fuera también la fila
    # posterior: ninguna de las dos llega.
    _sintoma_del_bug([n.detalle for n in en_madrid.items], correcto=["url"], con_el_bug=[])


def test_una_marca_ilegible_no_rompe_el_resumen(tmp_db):
    """Una marca corrupta se trata como primera visita: tumbar la banda por un
    valor que el usuario no controla sería el peor de los dos fallos."""
    _licitacion("NOV-ILEGIBLE")
    _seguir(_UK_ANA, "NOV-ILEGIBLE")
    _historial("NOV-ILEGIBLE", cuando=_iso(days=5), cambiados="url")

    resultado = desde_ultima_visita(_UK_ANA, last_seen="el jueves por la tarde")

    assert [n.detalle for n in resultado.items] == ["url"]
    assert resultado.ventana_recortada is False


def test_el_diff_va_del_mas_reciente_al_mas_antiguo_y_respeta_el_limite(tmp_db):
    """El usuario piensa en «qué ha pasado», no en «qué ha pasado en cada
    tabla»: el orden es cronológico entre fuentes y el límite corta lo viejo.

    El pliego y el recurso van **entre** los dos cambios. Así, el orden en que
    el servicio concatena las fuentes (primero todo el historial) no coincide
    con el esperado, y un límite aplicado antes de ordenar dejaría fuera el
    pliego y no el cambio viejo. Cada ítem cae en un día natural distinto (se
    separan más de 24 h) para no depender de cómo compara el texto una fecha
    con espacio, una con ``T`` y una sin hora; ese caso tiene su propio xfail.
    """
    _licitacion("NOV-ORDEN")
    _seguir(_UK_ANA, "NOV-ORDEN")
    _historial("NOV-ORDEN", cuando=_iso(minutes=5), cambiados="reciente")
    _documento("NOV-ORDEN", uri="https://placsp.test/orden.pdf", creado=_hace(hours=25))
    _recurso("NOV-ORDEN", numero="R-ORDEN", fecha=_hace(days=3).date().isoformat())
    _historial("NOV-ORDEN", cuando=_iso(days=5), cambiados="viejo")
    marca = _iso(days=6)

    def _lineas(resultado: NovedadesDesdeUltimaVisita) -> list[str | None]:
        return [n.detalle if n.subtipo == "cambio" else n.subtipo for n in resultado.items]

    completo = desde_ultima_visita(_UK_ANA, last_seen=marca)
    recortado = desde_ultima_visita(_UK_ANA, last_seen=marca, limit=2)

    assert _lineas(completo) == ["reciente", "documento_nuevo", "recurso", "viejo"]
    assert _lineas(recortado) == ["reciente", "documento_nuevo"]
    assert recortado.por_subtipo == {"cambio": 1, "documento_nuevo": 1}


def test_dentro_del_mismo_dia_el_orden_tambien_es_por_hora(tmp_db):
    """Dos fuentes el mismo día natural: manda la hora, no el orden en que el
    servicio las concatena.

    El test de arriba separa cada ítem en un día distinto, así que no distingue
    un orden por instante de uno sólo por fecha. Aquí el cambio del historial
    (que se concatena primero) es de las 08:00 y el movimiento del ledger (que
    se concatena el último) de las 20:00 del mismo día UTC. Ambas columnas
    guardan el ISO con ``T`` tal como se siembra, así que el resultado no
    depende del bug del espacio en ``documentos.created_at``. Un orden sólo
    por fecha dejaría el cambio delante, y con ``limit=1`` sobreviviría él.
    """
    user_id, org_id = _usuario_con_equipo("novedades-mismo-dia@example.test", "Equipo mismo día")
    _licitacion("NOV-HORA")
    _seguir(_UK_ANA, "NOV-HORA")
    # Medianoche UTC de hace dos días: las 20:00 de ese día ya han pasado sea
    # cual sea la hora a la que corra la suite.
    dia = _hace(days=2).replace(hour=0, minute=0, second=0, microsecond=0)
    _historial("NOV-HORA", cuando=(dia + timedelta(hours=8)).isoformat(), cambiados="url")
    _evento_fechado(user_id, org_id, "NOV-HORA", cuando=(dia + timedelta(hours=20)).isoformat())
    visita = (dia - timedelta(days=1)).isoformat()

    completo = desde_ultima_visita(_UK_ANA, last_seen=visita, organization_id=org_id)
    recortado = desde_ultima_visita(_UK_ANA, last_seen=visita, organization_id=org_id, limit=1)

    assert [n.subtipo for n in completo.items] == ["pursuit", "cambio"]
    assert [n.subtipo for n in recortado.items] == ["pursuit"]


@pytest.mark.xfail(
    strict=True,
    raises=_SintomaDelBug,
    reason=(
        "Bug abierto: documentos.created_at lo rellena DEFAULT now() y el cast a "
        "texto usa espacio ('2026-09-16 15:00:00+00'), mientras el corte es ISO con "
        "'T'. Como ' ' < 'T', todo pliego publicado el mismo día de la última "
        "visita queda fuera del diff aunque sea posterior. Al corregirlo, quitar "
        "el xfail."
    ),
)
def test_un_pliego_publicado_el_dia_de_la_visita_pero_despues_es_novedad(tmp_db):
    """El caso habitual: miro el Resumen por la mañana, el órgano publica el
    pliego por la tarde y vuelvo al día siguiente."""
    from db.repositories.documentos import DocumentosRepository
    from db.upsert import DocumentoReferencia

    _licitacion("NOV-MISMO-DIA")
    _seguir(_UK_ANA, "NOV-MISMO-DIA")
    DocumentosRepository().upsert_meta(
        "NOV-MISMO-DIA",
        [DocumentoReferencia(tipo="technical", uri="https://placsp.test/ppt.pdf")],
    )
    with connect() as c:
        creado = str(
            c.execute(
                "SELECT created_at FROM documentos WHERE licitacion_id = 'NOV-MISMO-DIA'"
            ).fetchone()[0]
        )
    # Medianoche UTC del mismo día en que se creó: anterior al pliego y en su
    # misma fecha sea cual sea la hora a la que corra el test.
    visita = f"{creado[:10]}T00:00:00+00:00"
    visita_del_dia_anterior = (datetime.fromisoformat(visita) - timedelta(days=1)).isoformat()

    del_dia_anterior = desde_ultima_visita(_UK_ANA, last_seen=visita_del_dia_anterior)
    del_mismo_dia = desde_ultima_visita(_UK_ANA, last_seen=visita)

    # Control: con la visita un día antes el pliego sí sale, así que la siembra
    # y el cruce con lo seguido funcionan y lo único que cambia es la fecha.
    assert del_dia_anterior.por_subtipo == {"documento_nuevo": 1}
    _sintoma_del_bug(del_mismo_dia.por_subtipo, correcto={"documento_nuevo": 1}, con_el_bug={})


@pytest.mark.xfail(
    strict=True,
    raises=_SintomaDelBug,
    reason=(
        "Bug abierto, misma causa que el anterior y otro síntoma: el diff se ordena "
        "por `cuando` como texto, y el `cuando` de un pliego es MIN(created_at) con "
        "espacio ('2026-09-16 16:09:04+00') mientras el de un cambio lleva 'T'. Un "
        "pliego de hoy queda por debajo de cualquier cambio de hoy aunque sea "
        "posterior, y `limit` lo deja fuera. Arreglar sólo el filtro de "
        "documentos no lo corrige: hay que normalizar también `publicado_en`. Al "
        "corregirlo, quitar el xfail."
    ),
)
def test_un_pliego_de_hoy_va_por_delante_de_un_cambio_de_hoy_anterior(tmp_db):
    """La visita fue otro día, así que el filtro deja pasar el pliego; lo que
    falla es dónde cae en el diff y, con límite, si llega a salir."""
    from db.repositories.documentos import DocumentosRepository
    from db.upsert import DocumentoReferencia

    _licitacion("NOV-ORDEN-HOY")
    _seguir(_UK_ANA, "NOV-ORDEN-HOY")
    DocumentosRepository().upsert_meta(
        "NOV-ORDEN-HOY",
        [DocumentoReferencia(tipo="technical", uri="https://placsp.test/hoy.pdf")],
    )
    with connect() as c:
        creado = str(
            c.execute(
                "SELECT created_at FROM documentos WHERE licitacion_id = 'NOV-ORDEN-HOY'"
            ).fetchone()[0]
        )
    dia = datetime.fromisoformat(f"{creado[:10]}T00:00:00+00:00")
    # El cambio, a medianoche UTC del día del pliego: anterior a él y en su misma
    # fecha, sea cual sea la hora a la que corra la suite. Con `_iso(minutes=5)`
    # el test daría XPASS en los cinco primeros minutos de cada día.
    _historial("NOV-ORDEN-HOY", cuando=dia.isoformat(), cambiados="url")
    visita = (dia - timedelta(days=2)).isoformat()

    completo = desde_ultima_visita(_UK_ANA, last_seen=visita)
    recortado = desde_ultima_visita(_UK_ANA, last_seen=visita, limit=1)

    # Control: llegan los dos ítems y el límite deja uno. El bug sólo cambia el
    # orden y, con él, cuál sobrevive al recorte; si falta un ítem, es otra cosa.
    assert sorted(n.subtipo for n in completo.items) == ["cambio", "documento_nuevo"]
    assert len(recortado.items) == 1
    _sintoma_del_bug(
        ([n.subtipo for n in completo.items], [n.subtipo for n in recortado.items]),
        correcto=(["documento_nuevo", "cambio"], ["documento_nuevo"]),
        con_el_bug=(["cambio", "documento_nuevo"], ["cambio"]),
    )


# ---------------------------------------------------------------------------
# Aislamiento entre usuarios y organizaciones
# ---------------------------------------------------------------------------


def test_cada_usuario_ve_solo_lo_que_el_sigue(tmp_db):
    """Las tres consultas personales filtran por ``user_key``; sin ese filtro,
    el diff de Ana enseñaría los pliegos y recursos de lo que sigue Bea."""
    for id_externo, user_key in (("NOV-DE-ANA", _UK_ANA), ("NOV-DE-BEA", _UK_BEA)):
        _licitacion(id_externo)
        _seguir(user_key, id_externo)
        _historial(id_externo, cuando=_iso(hours=4), cambiados="url")
        _documento(id_externo, uri=f"https://placsp.test/{id_externo}.pdf", creado=_hace(days=1))
        _recurso(id_externo, numero=f"R-{id_externo}", fecha=_hace(days=1).date().isoformat())

    de_ana = desde_ultima_visita(_UK_ANA, last_seen=_iso(days=2))
    de_bea = desde_ultima_visita(_UK_BEA, last_seen=_iso(days=2))

    assert _por_expediente(de_ana) == {"NOV-DE-ANA"}
    assert _por_expediente(de_bea) == {"NOV-DE-BEA"}
    assert (
        de_ana.por_subtipo
        == de_bea.por_subtipo
        == {"cambio": 1, "documento_nuevo": 1, "recurso": 1}
    )


def test_un_expediente_seguido_por_dos_no_duplica_la_novedad(tmp_db):
    """Que Bea siga lo mismo no puede multiplicar las líneas de Ana: la unión
    con ``watchlist_items`` sólo es correcta si se acota al usuario."""
    _licitacion("NOV-COMPARTIDO")
    _seguir(_UK_ANA, "NOV-COMPARTIDO")
    _seguir(_UK_BEA, "NOV-COMPARTIDO")
    _historial("NOV-COMPARTIDO", cuando=_iso(hours=4), cambiados="url")

    resultado = desde_ultima_visita(_UK_ANA, last_seen=_iso(days=1))

    assert [n.licitacion_id for n in resultado.items] == ["NOV-COMPARTIDO"]


def test_sin_organizacion_no_se_lee_ningun_ledger(tmp_db):
    """``organization_id=None`` es «sin banda del equipo», no «el ledger de
    todas las organizaciones».

    El servicio sólo recibe una ``user_key`` y no resuelve organizaciones: qué
    organización se pide lo decide la ruta, y que no elija una por defecto lo
    fija ``test_novedades_ruta_ultima_visita.py``. Lo que puede romperse aquí
    es el filtro: si ``pursuits_movidos`` aceptara ``None`` como «cualquier
    organización» (el habitual ``%s IS NULL OR organization_id = %s``) y el
    servicio dejara de descartar ese caso, el diff enseñaría el pipeline de
    todos los equipos. El control con la organización explícita demuestra que
    la oportunidad sembrada sí saldría; sin él, la banda vacía no probaría
    nada.
    """
    user_id, org_id = _usuario_con_equipo("novedades-sin-org@example.test", "Equipo cualquiera")
    _licitacion("NOV-EQUIPO")
    _abrir_oportunidad(user_id, org_id, "NOV-EQUIPO")

    sin_organizacion = desde_ultima_visita(_UK_ANA, last_seen=_iso(days=1))
    con_organizacion = desde_ultima_visita(_UK_ANA, last_seen=_iso(days=1), organization_id=org_id)

    assert sin_organizacion.items == []
    assert con_organizacion.por_subtipo == {"pursuit": 1}


def test_la_banda_del_equipo_es_solo_la_de_esa_organizacion(tmp_db):
    """El ledger se lee con ``WHERE organization_id``: el pipeline de otro
    equipo no puede asomar en el diff aunque toque el mismo expediente."""
    ana_id, org_ana = _usuario_con_equipo("novedades-org-ana@example.test", "Equipo Ana")
    bea_id, org_bea = _usuario_con_equipo("novedades-org-bea@example.test", "Equipo Bea")
    _licitacion("NOV-ORG-ANA")
    _licitacion("NOV-ORG-BEA")
    _abrir_oportunidad(ana_id, org_ana, "NOV-ORG-ANA")
    _abrir_oportunidad(bea_id, org_bea, "NOV-ORG-BEA")
    _abrir_oportunidad(bea_id, org_bea, "NOV-ORG-ANA")

    resultado = desde_ultima_visita(_UK_ANA, last_seen=_iso(days=1), organization_id=org_ana)

    assert resultado.por_subtipo == {"pursuit": 1}
    assert _por_expediente(resultado) == {"NOV-ORG-ANA"}

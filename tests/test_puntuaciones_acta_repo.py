"""Repositorio de puntuaciones del acta (v170) y eventos de fila confirmada.

Todo contra Postgres (``tmp_db``): lo que se prueba es SQL —el reemplazo
transaccional del expediente, la cola de expedientes pendientes, el cruce de
nombres de la organización— y un test sin base solo comprobaría que el SQL es
una cadena.
"""

from __future__ import annotations

from typing import Any, cast

import psycopg
import pytest

from db.repositories.puntuaciones_acta import (
    ActaStatus,
    PuntuacionesActaRepository,
    PuntuacionNueva,
)

_VERSION = "acta-puntuaciones-v1"
_LIC = "placsp:10000141020261:ACTA/2026"
_AHORA = "2026-11-01T10:00:00+00:00"

_SERVLET_PLACSP = "https://contrataciondelestado.es/FileSystem/servlet/GetDocumentByIdServlet"

NIF_PROPIO = "B12345678"  # pragma: allowlist secret
NIF_AJENO = "A87654321"  # pragma: allowlist secret


# ── Siembra ─────────────────────────────────────────────────────────────────


def _licitacion(c: Any, id_externo: str, *, fuente: str = "placsp") -> None:
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion, fuente) "
        "VALUES (%s, %s, %s, %s) ON CONFLICT (id_externo) DO NOTHING",
        (id_externo, "Servicio de soporte y mantenimiento", _AHORA, fuente),
    )


def _usuario_y_organizacion(correo: str, *, nombre: str | None = None) -> tuple[int, int]:
    from db.repositories.organizations import OrganizationRepository
    from db.users import create_user

    user_id = create_user(
        email=correo,
        password_hash="x",  # pragma: allowlist secret
        display_name=nombre,
    )
    org_id = int(OrganizationRepository().ensure_personal_organization(user_id)["id"])
    return user_id, org_id


def _pursuit(c: Any, org_id: int, user_id: int, licitacion_id: str) -> int:
    fila = c.execute(
        "INSERT INTO pursuits (licitacion_id, organization_id, responsible_user_id, "
        " identified_at, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (licitacion_id, org_id, user_id, _AHORA, _AHORA, _AHORA),
    ).fetchone()
    return int(fila[0])


def _adjudicacion(
    c: Any,
    licitacion_id: str,
    nombre: str,
    nif: str | None,
    *,
    importe: float = 1000.0,
    lote_id: int | None = None,
    empresa_id: int | None = None,
) -> None:
    c.execute(
        "INSERT INTO adjudicaciones "
        "(licitacion_id, nombre, nif, importe_adjudicado, lote_id, empresa_id, fecha_extraccion) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (licitacion_id, nombre, nif, importe, lote_id, empresa_id, _AHORA),
    )


def _lote(c: Any, licitacion_id: str, numero: str) -> int:
    fila = c.execute(
        "INSERT INTO lotes (licitacion_id, numero, fecha_extraccion) VALUES (%s, %s, %s) "
        "RETURNING id",
        (licitacion_id, numero, _AHORA),
    ).fetchone()
    return int(fila[0])


def _acta(c: Any, licitacion_id: str, uri: str = "https://placsp.example/acta-mesa.pdf") -> int:
    fila = c.execute(
        "INSERT INTO documentos (licitacion_id, tipo, uri) VALUES (%s, 'acta', %s) RETURNING id",
        (licitacion_id, uri),
    ).fetchone()
    return int(fila[0])


def _acta_con_estado(c: Any, licitacion_id: str, uri: str, status: str) -> int:
    """Un acta más del expediente (el ``uri`` es único por expediente) en el estado dado."""
    documento = _acta(c, licitacion_id, uri)
    c.execute("UPDATE documentos SET status = %s WHERE id = %s", (status, documento))
    return documento


def _fila(documento_id: int, **cambios: Any) -> PuntuacionNueva:
    base: PuntuacionNueva = {
        "lote_numero": None,
        "licitador_nombre": "ACME SERVICIOS S.L.",
        "licitador_normalizado": "acme servicios",
        "criterio": "Oferta económica",
        "puntos": 45.0,
        "puntos_max": 60.0,
        "es_precio": True,
        "excluida": False,
        "documento_id": documento_id,
        "pagina": 3,
        "cita": "ACME SERVICIOS S.L.  45,00",
    }
    return cast("PuntuacionNueva", {**base, **cambios})


def _guardar(
    licitacion_id: str,
    filas: list[PuntuacionNueva],
    *,
    status: ActaStatus = "ok",
    version: str = _VERSION,
    error_detail: str | None = None,
) -> None:
    PuntuacionesActaRepository().guardar(
        licitacion_id,
        status=status,
        extraction_version=version,
        model="modelo-de-prueba",
        documentos_leidos=1,
        error_detail=error_detail,
        filas=filas,
    )


def _expediente_seguido(licitacion_id: str, correo: str, *, fuente: str = "placsp") -> None:
    """Un expediente con una oportunidad de la organización de ``correo`` y su adjudicación."""
    from db.database import connect

    user_id, org_id = _usuario_y_organizacion(correo)
    with connect() as c:
        _licitacion(c, licitacion_id, fuente=fuente)
        _pursuit(c, org_id, user_id, licitacion_id)
        _adjudicacion(c, licitacion_id, "ACME SERVICIOS S.L.", NIF_PROPIO)


def _pendientes(limit: int = 200) -> dict[str, bool]:
    filas = PuntuacionesActaRepository().expedientes_pendientes(
        extraction_version=_VERSION, limit=limit
    )
    return {fila["licitacion_id"]: fila["tiene_acta"] for fila in filas}


# ── guardar / leer ──────────────────────────────────────────────────────────


def test_guardar_reemplaza_el_expediente_entero(tmp_db: Any) -> None:
    from db.database import connect

    with connect() as c:
        _licitacion(c, _LIC)
        documento = _acta(c, _LIC)
    repo = PuntuacionesActaRepository()

    _guardar(
        _LIC,
        [
            _fila(documento, criterio="Oferta económica"),
            _fila(documento, criterio="Memoria técnica", es_precio=False, puntos=30.0),
            _fila(documento, criterio=None, puntos=75.0, puntos_max=100.0, es_precio=None),
        ],
    )
    assert len(repo.list_puntuaciones(_LIC)) == 3

    _guardar(_LIC, [_fila(documento, licitador_normalizado="otra", criterio="Mejoras")])

    filas = repo.list_puntuaciones(_LIC)
    assert len(filas) == 1
    assert filas[0]["licitador_normalizado"] == "otra"
    assert filas[0]["criterio"] == "Mejoras"


def test_guardar_dos_veces_igual_no_duplica(tmp_db: Any) -> None:
    from db.database import connect

    with connect() as c:
        _licitacion(c, _LIC)
        documento = _acta(c, _LIC)
    nuevas = [
        _fila(documento, criterio="Oferta económica"),
        _fila(documento, criterio=None, puntos=75.0, puntos_max=100.0, es_precio=None),
    ]

    _guardar(_LIC, nuevas)
    _guardar(_LIC, nuevas)

    repo = PuntuacionesActaRepository()
    leidas = repo.list_puntuaciones(_LIC)
    assert [f["criterio"] for f in leidas] == ["Oferta económica", None]
    with connect() as c:
        assert c.execute("SELECT count(*) FROM acta_extracciones").fetchone()[0] == 1


def test_list_puntuaciones_devuelve_lo_escrito_en_el_orden_del_acta(tmp_db: Any) -> None:
    from db.database import connect

    with connect() as c:
        _licitacion(c, _LIC)
        documento = _acta(c, _LIC)
    escritas = [
        _fila(documento, lote_numero="1", criterio="Oferta económica", pagina=2),
        _fila(documento, lote_numero="1", criterio="Memoria técnica", es_precio=False, pagina=2),
        _fila(
            documento,
            lote_numero="2",
            licitador_nombre="BETA SOLUCIONES SA",
            licitador_normalizado="beta soluciones",
            excluida=True,
            puntos=None,
            puntos_max=None,
            es_precio=None,
            criterio=None,
            pagina=4,
            cita="BETA SOLUCIONES SA  excluida",
        ),
    ]
    _guardar(_LIC, escritas)

    leidas = PuntuacionesActaRepository().list_puntuaciones(_LIC)

    assert [{k: v for k, v in f.items() if k != "id"} for f in leidas] == escritas
    assert all(isinstance(f["id"], int) for f in leidas)


def test_guardar_sin_filas_deja_la_extraccion_y_borra_las_puntuaciones(tmp_db: Any) -> None:
    from db.database import connect

    with connect() as c:
        _licitacion(c, _LIC)
        documento = _acta(c, _LIC)
    repo = PuntuacionesActaRepository()
    _guardar(_LIC, [_fila(documento)])
    assert repo.list_puntuaciones(_LIC)

    _guardar(_LIC, [], status="sin_tabla")

    assert repo.list_puntuaciones(_LIC) == []
    extraccion = repo.get_extraccion(_LIC)
    assert extraccion is not None
    assert extraccion["status"] == "sin_tabla"
    assert extraccion["extraction_version"] == _VERSION
    assert extraccion["model"] == "modelo-de-prueba"
    assert extraccion["documentos_leidos"] == 1
    assert extraccion["extracted_at"] is not None


def test_get_extraccion_sin_fila_es_none(tmp_db: Any) -> None:
    assert PuntuacionesActaRepository().get_extraccion("no-existe") is None


def test_extracted_at_solo_marca_las_lecturas_que_llegaron_a_una_conclusion(tmp_db: Any) -> None:
    """Un ``error`` posterior deja ``extracted_at`` en ``NULL`` y sin puntuaciones.

    ``guardar`` siempre reemplaza el expediente: tras el ``error`` no queda dato
    leído que una fecha de lectura pueda respaldar.
    """
    from db.database import connect

    with connect() as c:
        _licitacion(c, _LIC)
        documento = _acta(c, _LIC)
    repo = PuntuacionesActaRepository()

    _guardar(_LIC, [], status="error", error_detail="tiempo agotado")
    primera = repo.get_extraccion(_LIC)
    assert primera is not None
    assert primera["status"] == "error"
    assert primera["error_detail"] == "tiempo agotado"
    assert primera["extracted_at"] is None

    _guardar(_LIC, [_fila(documento)], status="ok")
    leida = repo.get_extraccion(_LIC)
    assert leida is not None
    assert leida["extracted_at"] is not None
    assert leida["error_detail"] is None
    assert len(repo.list_puntuaciones(_LIC)) == 1

    _guardar(_LIC, [], status="error", error_detail="otra vez")
    despues = repo.get_extraccion(_LIC)
    assert despues is not None
    assert despues["status"] == "error"
    assert despues["extracted_at"] is None
    assert repo.list_puntuaciones(_LIC) == []

    _guardar(_LIC, [], status="sin_acta")
    sin_acta = repo.get_extraccion(_LIC)
    assert sin_acta is not None
    assert sin_acta["extracted_at"] is None


def test_guardar_con_filas_repetidas_se_deshace_y_deja_el_estado_anterior(tmp_db: Any) -> None:
    """Dos filas con la misma clave chocan con el índice único: nada se escribe."""
    from db.database import connect

    with connect() as c:
        _licitacion(c, _LIC)
        documento = _acta(c, _LIC)
    repo = PuntuacionesActaRepository()
    _guardar(_LIC, [_fila(documento, licitador_normalizado="primera", criterio="Mejoras")])
    antes = repo.list_puntuaciones(_LIC)
    extraccion_antes = repo.get_extraccion(_LIC)
    assert len(antes) == 1
    assert extraccion_antes is not None

    repetida = _fila(documento, licitador_normalizado="otra", criterio="Mejoras")
    with pytest.raises(psycopg.errors.UniqueViolation):
        _guardar(
            _LIC,
            [repetida, repetida],
            status="sin_tabla",
            version="acta-puntuaciones-v2",
        )

    # Ni las puntuaciones ni el estado de la extracción cambiaron: el DELETE y
    # el UPSERT previos al INSERT que falló se deshicieron con él.
    assert repo.list_puntuaciones(_LIC) == antes
    assert repo.get_extraccion(_LIC) == extraccion_antes


def test_tiene_actas_solo_cuenta_documentos_tipo_acta(tmp_db: Any) -> None:
    from db.database import connect

    with connect() as c:
        _licitacion(c, _LIC)
        c.execute(
            "INSERT INTO documentos (licitacion_id, tipo, uri) VALUES (%s, 'legal', %s)",
            (_LIC, "https://placsp.example/pcap.pdf"),
        )
    repo = PuntuacionesActaRepository()
    assert repo.tiene_actas(_LIC) is False

    with connect() as c:
        _acta(c, _LIC)
    assert repo.tiene_actas(_LIC) is True
    assert repo.tiene_actas("no-existe") is False


# ── expedientes_pendientes ──────────────────────────────────────────────────


def test_expedientes_pendientes_solo_con_oportunidad_y_adjudicacion(tmp_db: Any) -> None:
    from db.database import connect

    # A: oportunidad + adjudicación + acta.
    _expediente_seguido("LIC-A", "a@example.test")
    # B: oportunidad + adjudicación, sin acta.
    _expediente_seguido("LIC-B", "b@example.test")
    # D: oportunidad + acta, todavía sin adjudicación.
    user_d, org_d = _usuario_y_organizacion("d@example.test")
    with connect() as c:
        _acta(c, "LIC-A")
        # C: adjudicación + acta, nadie lo sigue.
        _licitacion(c, "LIC-C")
        _adjudicacion(c, "LIC-C", "ACME SERVICIOS S.L.", NIF_PROPIO)
        _acta(c, "LIC-C")
        _licitacion(c, "LIC-D")
        _pursuit(c, org_d, user_d, "LIC-D")
        _acta(c, "LIC-D")

    assert _pendientes() == {"LIC-A": True, "LIC-B": False}


def test_expedientes_pendientes_excluye_la_version_vigente_salvo_error(tmp_db: Any) -> None:
    from db.database import connect

    for i, lic in enumerate(("OK1", "OK0", "ERR1", "SIN1", "SIN1-ACTA")):
        _expediente_seguido(lic, f"v{i}@example.test")
    _guardar("OK1", [], status="ok", version=_VERSION)
    _guardar("OK0", [], status="ok", version="acta-puntuaciones-v0")
    _guardar("ERR1", [], status="error", version=_VERSION, error_detail="tiempo agotado")
    _guardar("SIN1", [], status="sin_acta", version=_VERSION)
    _guardar("SIN1-ACTA", [], status="sin_acta", version=_VERSION)
    with connect() as c:
        # El acta llegó después de la lectura que dijo «sin acta».
        _acta(c, "SIN1-ACTA")

    assert _pendientes() == {"OK0": False, "ERR1": False, "SIN1-ACTA": True}


def test_expedientes_pendientes_no_repite_sin_tabla_de_la_version_vigente(tmp_db: Any) -> None:
    from db.database import connect

    _expediente_seguido("LIC-A", "a@example.test")
    with connect() as c:
        _acta(c, "LIC-A")
    _guardar("LIC-A", [], status="sin_tabla")

    assert _pendientes() == {}


def test_expedientes_pendientes_solo_de_fuentes_que_ingieren_actas(tmp_db: Any) -> None:
    """Un pursuit de PSCP o TED con adjudicación no es de la cola: PLACSP no lo lleva.

    Si lo fuera, ``encolar_pendientes`` le escribiría ``sin_acta`` y la ficha
    diría «PLACSP no publicó acta de mesa» de un expediente que no es de PLACSP.
    """
    from db.database import connect

    propias = {
        "placsp": "LIC-PLACSP",
        "placsp_agregadas": "LIC-AGREGADAS",
        "bulk_202610": "LIC-BULK",
    }
    # ``bulkX…`` ni es el carril ``bulk_YYYYMM``: el ``_`` no es comodín.
    ajenas = {
        "pscp": "LIC-PSCP",
        "ted": "LIC-TED",
        "galicia_rss": "LIC-RSS",
        "placsp_menores": "LIC-MENORES",
        "placsp_watched_company_awards": "LIC-VIGILADA",
        "bulkX202610": "LIC-BULKX",
    }
    for i, (fuente, lic) in enumerate({**propias, **ajenas}.items()):
        _expediente_seguido(lic, f"fuente{i}@example.test", fuente=fuente)
    with connect() as c:
        for lic in ajenas.values():
            _acta(c, lic)  # ni con un documento acta de por medio
        _acta(c, "LIC-BULK")

    assert _pendientes() == {
        "LIC-PLACSP": False,
        "LIC-AGREGADAS": False,
        "LIC-BULK": True,
    }


def test_expedientes_pendientes_reencola_sin_tabla_con_un_acta_publicable_pendiente(
    tmp_db: Any,
) -> None:
    """La lectura baja 3 actas por pasada: si no hubo tabla y quedan más, vuelve a la cola."""
    from db.database import connect

    for i, lic in enumerate(("SIN-PENDIENTE", "SIN-LEIDAS", "SIN-ESCANEADA", "SIN-SIN-PUBLICAR")):
        _expediente_seguido(lic, f"t{i}@example.test")
    _expediente_seguido("SIN-OK", "t-ok@example.test")
    with connect() as c:
        # Ya hay un acta leída y otra por descargar: la tabla puede estar en la segunda.
        _acta_con_estado(c, "SIN-PENDIENTE", "https://placsp.example/a1.pdf", "extracted")
        _acta_con_estado(c, "SIN-PENDIENTE", "https://placsp.example/a2.pdf", "pending")
        # Todas leídas, o escaneadas (terminal): repetir la lectura daría lo mismo.
        _acta_con_estado(c, "SIN-LEIDAS", "https://placsp.example/a1.pdf", "extracted")
        _acta_con_estado(c, "SIN-ESCANEADA", "https://placsp.example/a1.pdf", "sin_texto")
        # Anunciada y no servida todavía (expediente abierto con DOC_CN y sin DOC_CD).
        c.execute(
            "UPDATE licitaciones SET estado = 'PUB', tipos_anuncio = 'DOC_CN' "
            "WHERE id_externo = 'SIN-SIN-PUBLICAR'"
        )
        _acta_con_estado(c, "SIN-SIN-PUBLICAR", f"{_SERVLET_PLACSP}?DocumentIdParam=T", "pending")
        # ``ok`` con un acta pendiente: ya hay tabla, no se vuelve a leer.
        _acta_con_estado(c, "SIN-OK", "https://placsp.example/a1.pdf", "extracted")
        _acta_con_estado(c, "SIN-OK", "https://placsp.example/a2.pdf", "pending")
    for lic in ("SIN-PENDIENTE", "SIN-LEIDAS", "SIN-ESCANEADA", "SIN-SIN-PUBLICAR"):
        _guardar(lic, [], status="sin_tabla")
    _guardar("SIN-OK", [], status="ok")

    assert _pendientes() == {"SIN-PENDIENTE": True}


def test_expedientes_pendientes_un_expediente_con_dos_pursuits_sale_una_vez(tmp_db: Any) -> None:
    from db.database import connect

    _expediente_seguido("LIC-A", "a@example.test")
    otro_usuario, otra_org = _usuario_y_organizacion("otra@example.test")
    with connect() as c:
        _pursuit(c, otra_org, otro_usuario, "LIC-A")
        # Dos adjudicatarios no multiplican las filas de la cola.
        _adjudicacion(c, "LIC-A", "BETA SOLUCIONES SA", NIF_AJENO, importe=2000.0)

    filas = PuntuacionesActaRepository().expedientes_pendientes(extraction_version=_VERSION)

    assert filas == [{"licitacion_id": "LIC-A", "tiene_acta": False}]


def test_expedientes_pendientes_respeta_el_limite_y_prioriza_lo_no_intentado(
    tmp_db: Any,
) -> None:
    for i, lic in enumerate(("A-ERR", "B-NUEVO")):
        _expediente_seguido(lic, f"l{i}@example.test")
    _guardar("A-ERR", [], status="error", error_detail="tiempo agotado")

    assert list(_pendientes(limit=1)) == ["B-NUEVO"]


# ── adjudicatarios_por_lote ─────────────────────────────────────────────────


def test_adjudicatarios_por_lote_trae_el_numero_del_lote(tmp_db: Any) -> None:
    from db.database import connect

    with connect() as c:
        _licitacion(c, _LIC)
        lote_1 = _lote(c, _LIC, "1")
        lote_2 = _lote(c, _LIC, "2")
        _adjudicacion(c, _LIC, "ACME SERVICIOS S.L.", NIF_PROPIO, importe=1000.0, lote_id=lote_1)
        _adjudicacion(c, _LIC, "BETA SOLUCIONES SA", NIF_AJENO, importe=2000.0, lote_id=lote_2)
        # Sin lote resuelto: el número es None, no se inventa.
        _adjudicacion(c, _LIC, "GAMMA SL", None, importe=3000.0)
        _licitacion(c, "OTRO")
        _adjudicacion(c, "OTRO", "NO ES DE ESTE EXPEDIENTE", NIF_AJENO)

    adjudicatarios = PuntuacionesActaRepository().adjudicatarios_por_lote(_LIC)

    assert adjudicatarios == [
        {"lote_numero": "1", "nombre": "ACME SERVICIOS S.L.", "nif": NIF_PROPIO},
        {"lote_numero": "2", "nombre": "BETA SOLUCIONES SA", "nif": NIF_AJENO},
        {"lote_numero": None, "nombre": "GAMMA SL", "nif": None},
    ]


# ── nombres_de_organizacion ─────────────────────────────────────────────────


def test_nombres_de_organizacion(tmp_db: Any) -> None:
    from db.database import connect
    from db.repositories.organization_nifs import OrganizationNifRepository

    _, org_id = _usuario_y_organizacion("propia@example.test", nombre="Acme Holding")
    _, otra_org = _usuario_y_organizacion("ajena@example.test", nombre="Ajena Holding")
    OrganizationNifRepository().replace_all(
        org_id,
        nifs=[
            {"nif": NIF_PROPIO, "principal": True, "razon_social": "ACME SERVICIOS DIGITALES SL"},
            # Sin razón social declarada: no aporta nombre (ni uno vacío).
            {"nif": "C11111111", "principal": False},  # pragma: allowlist secret
        ],
    )
    OrganizationNifRepository().replace_all(
        otra_org,
        nifs=[{"nif": NIF_AJENO, "principal": True, "razon_social": "BETA SOLUCIONES SL"}],
    )
    with connect() as c:
        # El maestro de empresas: nombre canónico y alias del mismo NIF.
        empresa_id = int(
            c.execute(
                "INSERT INTO empresas (nombre_canonico, nif_canonico) VALUES (%s, %s) "
                "RETURNING empresa_id",
                ("ACME SERVICIOS SOCIEDAD LIMITADA", NIF_PROPIO),
            ).fetchone()[0]
        )
        c.execute(
            "INSERT INTO empresa_aliases (empresa_id, alias_normalizado, fuente, confianza, "
            " created_at) VALUES (%s, %s, 'test', 1.0, %s)",
            (empresa_id, "acme servicios", _AHORA),
        )
        empresa_ajena = int(
            c.execute(
                "INSERT INTO empresas (nombre_canonico, nif_canonico) VALUES (%s, %s) "
                "RETURNING empresa_id",
                ("BETA SOLUCIONES SOCIEDAD ANONIMA", NIF_AJENO),
            ).fetchone()[0]
        )
        _licitacion(c, _LIC)
        # Cómo la adjudicó la Plataforma al NIF declarado.
        _adjudicacion(c, _LIC, "ACME SERVICIOS S.L.", NIF_PROPIO)
        # Una adjudicación con el NIF publicado de otra forma, que el maestro
        # ya resolvió a la empresa de la organización.
        _adjudicacion(
            c,
            _LIC,
            "ACME SERVICIOS Y COMPAÑIA SL",
            "B-12345678",
            importe=1500.0,
            empresa_id=empresa_id,
        )
        # Las de otra organización no cuentan, resuelvan por NIF o por empresa.
        _adjudicacion(c, _LIC, "BETA SOLUCIONES SA", NIF_AJENO, importe=2000.0)
        _adjudicacion(
            c,
            _LIC,
            "BETA SOLUCIONES Y CIA",
            "A-87654321",
            importe=2500.0,
            empresa_id=empresa_ajena,
        )

    nombres = PuntuacionesActaRepository().nombres_de_organizacion(org_id)

    assert sorted(nombres) == sorted(
        [
            "ACME SERVICIOS S.L.",  # adjudicaciones.nombre del NIF declarado
            "ACME SERVICIOS Y COMPAÑIA SL",  # adjudicaciones.nombre por empresa_id
            "ACME SERVICIOS SOCIEDAD LIMITADA",  # empresas.nombre_canonico
            "acme servicios",  # empresa_aliases.alias_normalizado
            "ACME SERVICIOS DIGITALES SL",  # organization_nifs.razon_social (la de otra org no)
            "Acme Holding",  # organizations.name
        ]
    )


def test_nombres_de_organizacion_sin_nifs_declarados_solo_trae_su_nombre(tmp_db: Any) -> None:
    _, org_id = _usuario_y_organizacion("sin-nif@example.test", nombre="Sin NIF SL")

    assert PuntuacionesActaRepository().nombres_de_organizacion(org_id) == ["Sin NIF SL"]


# ── eventos de fila confirmada ──────────────────────────────────────────────


def test_fila_acta_events_en_orden(tmp_db: Any) -> None:
    import json

    from db.database import connect
    from db.repositories.pursuits import PursuitRepository

    user_id, org_id = _usuario_y_organizacion("eventos@example.test")
    otro_usuario, otra_org = _usuario_y_organizacion("otro-equipo@example.test")
    with connect() as c:
        _licitacion(c, _LIC)
        pursuit_id = _pursuit(c, org_id, user_id, _LIC)
        otra_pursuit = _pursuit(c, otra_org, otro_usuario, _LIC)
    repo = PursuitRepository()
    assert repo.fila_acta_events(org_id, pursuit_id) == []

    primero = {"lote_numero": None, "licitador_normalizado": "acme servicios"}
    segundo = {"lote_numero": "2", "licitador_normalizado": "beta soluciones"}
    repo.append_fila_acta_event(
        organization_id=org_id, pursuit_id=pursuit_id, actor_user_id=user_id, payload=primero
    )
    # Otro tipo de evento del mismo ledger, y el de otra organización: ninguno cuenta.
    repo.append_kit_event(
        organization_id=org_id,
        pursuit_id=pursuit_id,
        actor_user_id=user_id,
        payload={"item": "dnie", "marcado": True},
    )
    repo.append_fila_acta_event(
        organization_id=otra_org,
        pursuit_id=otra_pursuit,
        actor_user_id=otro_usuario,
        payload={"lote_numero": None, "licitador_normalizado": "ajena"},
    )
    repo.append_fila_acta_event(
        organization_id=org_id, pursuit_id=pursuit_id, actor_user_id=user_id, payload=segundo
    )

    eventos = repo.fila_acta_events(org_id, pursuit_id)

    assert [json.loads(e["payload_json"]) for e in eventos] == [primero, segundo]
    assert {e["actor_user_id"] for e in eventos} == {user_id}
    assert all(e["created_at"] for e in eventos)
    assert PursuitRepository.FILA_ACTA_EVENT_TYPE == "fila_acta_confirmada"

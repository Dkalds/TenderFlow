"""v164: las licitaciones de PLACSP pasan a ``placsp:<órgano>:<expediente>``.

Dos niveles, como ``tests/test_v153_rekey_pscp_id_externo_migration.py``. Sin
base, la forma de lo que emite la migración (encadenamiento, orden de las
guardas, el borrado detrás del conteo, la lista de referencias del RFC). Con
base (``tmp_db``), que reaplicar sus sentencias sobre filas sembradas con la
clave vieja lleva cada fila y todo lo que cuelga de ella a la clave que los
escritores construyen, que deja alias para los ids viejos, y que aborta sin
tocar nada ante cada una de sus guardas.
"""

from __future__ import annotations

import importlib.util
import os
import secrets
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import psycopg
import pytest

_RUTA = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "alembic"
    / "versions"
    / "v164_identidad_placsp_rekey.py"
)

_ORG_A = "31055010149261"
_ORG_B = "11778670221627"
_EXP = "2026/LIC/0049"


def _cargar() -> Any:
    spec = importlib.util.spec_from_file_location("v164_identidad_placsp_rekey", _RUTA)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _sql_emitido(funcion: str, *, dialecto: str = "postgresql") -> list[str]:
    modulo = _cargar()
    emitido: list[str] = []
    with patch.object(modulo, "op") as op_falso:
        op_falso.get_bind.return_value.dialect.name = dialecto
        op_falso.execute.side_effect = emitido.append
        getattr(modulo, funcion)()
    return emitido


# ---------------------------------------------------------------------------
# Forma, sin base
# ---------------------------------------------------------------------------


def test_encadena_con_la_fase_a() -> None:
    modulo = _cargar()
    assert modulo.revision == "v164_identidad_placsp_rekey"
    assert modulo.down_revision == "v163_identidad_placsp_fase_a"


def test_fuera_de_postgres_no_emite_nada() -> None:
    assert _sql_emitido("upgrade", dialecto="sqlite") == []
    assert _sql_emitido("downgrade", dialecto="sqlite") == []


def test_downgrade_no_emite_nada_en_postgres() -> None:
    """Irreversible a propósito (como v153): la inversa vuelve a juntar órganos."""
    assert _sql_emitido("downgrade") == []


def test_empieza_con_los_limites_de_la_transaccion() -> None:
    emitido = _sql_emitido("upgrade")
    assert emitido[:3] == [
        "SET LOCAL statement_timeout = 0",
        "SET LOCAL lock_timeout = '30s'",
        "SET LOCAL row_security = off",
    ]


def test_las_guardas_van_antes_de_la_primera_escritura() -> None:
    emitido = _sql_emitido("upgrade")
    guardas = next(i for i, s in enumerate(emitido) if "sin organo_ref_fuente" in s)
    # Lo primero que toca una tabla real es apagar el trigger; antes solo se
    # crea y se llena el mapa temporal.
    primera_escritura = next(i for i, s in enumerate(emitido) if "DISABLE TRIGGER" in s)
    assert guardas < primera_escritura
    assert all("_rekey_placsp_organo" in s for s in emitido[3:guardas])
    texto = emitido[guardas]
    for aviso in (
        "sin organo_ref_fuente",
        "forma vieja",
        "claves nuevas repetidas",
        "ya existen con la clave nueva",
        "FK a licitaciones sin repuntar",
        "trabajos pendientes",
    ):
        assert aviso in texto, aviso
    assert texto.count("RAISE EXCEPTION") == 6


def test_no_borra_nada_antes_de_comprobar_que_no_quedan_referencias() -> None:
    """El borrado arrastra en cascada lo que no se repuntó: va detrás del conteo."""
    emitido = _sql_emitido("upgrade")
    borrado = next(i for i, s in enumerate(emitido) if s.startswith("DELETE FROM licitaciones"))
    conteo = next(i for i, s in enumerate(emitido) if "referencias sin repuntar" in s)
    ultimo_repunte = max(i for i, s in enumerate(emitido) if s.startswith("UPDATE "))
    alias = next(i for i, s in enumerate(emitido) if "INSERT INTO licitaciones_id_anterior" in s)
    assert alias < ultimo_repunte < conteo < borrado


def test_el_trigger_de_tecnologia_se_reactiva() -> None:
    emitido = _sql_emitido("upgrade")
    apagar = emitido.index(
        "ALTER TABLE licitacion_tecnologia_score DISABLE TRIGGER trg_lts_derivar_ml"
    )
    encender = emitido.index(
        "ALTER TABLE licitacion_tecnologia_score ENABLE TRIGGER trg_lts_derivar_ml"
    )
    assert apagar < encender


def test_la_lista_de_referencias_es_la_del_rfc_mas_las_que_v153_no_cubrio() -> None:
    """RFC §4 y §«Decisiones de la fase A» 7: las 27 de v153, más
    ``domain_events.aggregate_id`` (que v153 olvidó), ``licitaciones_id_anterior``
    y las dos sin FK que el RFC añade (``ml_feedback``, ``organization_references``)."""
    v153 = importlib.util.spec_from_file_location(
        "v153", _RUTA.parent / "v153_rekey_pscp_id_externo.py"
    )
    assert v153 is not None and v153.loader is not None
    modulo_v153 = importlib.util.module_from_spec(v153)
    v153.loader.exec_module(modulo_v153)

    nuevas = {(t, c) for t, c, _ in _cargar()._REFERENCIAS}
    viejas = {(t, c) for t, c, _ in modulo_v153._REFERENCIAS}
    assert viejas <= nuevas
    assert nuevas - viejas == {
        ("domain_events", "aggregate_id"),
        ("licitaciones_id_anterior", "id_externo"),
        ("ml_feedback", "expediente"),
        ("organization_references", "expediente_id"),
    }
    filtros = {(t, c): f for t, c, f in _cargar()._REFERENCIAS}
    assert filtros[("domain_events", "aggregate_id")] == "aggregate_type = 'licitacion'"


def test_el_payload_solo_se_reescribe_en_los_eventos_no_despachados() -> None:
    emitido = _sql_emitido("upgrade")
    payload = [s for s in emitido if "jsonb_set" in s]
    assert len(payload) == 2
    assert all("dispatched_at IS NULL" in s for s in payload)


def test_las_colisiones_del_repositorio_usan_el_mapa_de_la_migracion() -> None:
    """``db.repositories.identidad`` copia las expresiones del mapa (una migración
    no se importa): si la revisión cambia una, la consulta de colisiones también."""
    from db.repositories import identidad

    modulo = _cargar()

    def sin_parentesis(sql: str) -> str:
        return sql.replace("(", "").replace(")", "")

    assert sin_parentesis(identidad._FAMILIA_REKEY_SQL) == sin_parentesis(modulo._FAMILIA)
    assert identidad._CABEZA_NUEVA_SQL == modulo._CABEZA_NUEVA
    assert identidad._EXPEDIENTE_VIEJO_SQL == modulo._EXPEDIENTE
    assert identidad._FORMA_VIEJA_SQL == modulo._FORMA_VIEJA


def test_la_codificacion_del_organo_es_la_de_shared() -> None:
    """``%`` primero y luego ``:``, como ``codificar_organo``."""
    assert _cargar()._ORGANO == ("replace(replace(l.organo_ref_fuente, '%', '%25'), ':', '%3A')")


# ---------------------------------------------------------------------------
# Con base
# ---------------------------------------------------------------------------


def _uno(c: Any, sql: str, params: tuple[Any, ...] = ()) -> Any:
    fila = c.execute(sql, params).fetchone()
    return fila[0] if fila else None


def _licitacion(
    c: Any,
    id_externo: str,
    *,
    fuente: str = "placsp",
    organo: str | None = _ORG_A,
    organo_nombre: str = "Órgano",
) -> None:
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, fuente, url, "
        " organo_ref_fuente, fecha_extraccion, primera_extraccion, fecha_publicacion, "
        " ml_tecnologias) "
        "VALUES (%s, %s, %s, %s, %s, %s, '2026-09-27T02:31:41+00:00', "
        " '2026-08-01T02:10:28+00:00', '2026-07-13', 'SAP')",
        (
            id_externo,
            f"Contrato {id_externo}",
            organo_nombre,
            fuente,
            "https://contrataciondelestado.es/wps/poc?uri=deeplink:detalle_licitacion&idEvl=x",
            organo,
        ),
    )


def _sembrar(c: Any) -> int:
    """Lo de producción en pequeño: una fila de cada forma y algo de todo colgando.

    En su propia transacción: el trigger diferido de ``licitacion_tecnologia_score``
    deja eventos pendientes hasta el commit y con ellos no se deja desactivar.
    """
    _licitacion(c, _EXP)
    _licitacion(c, "OTRO/2026", fuente="bulk_202610", organo=_ORG_B)
    _licitacion(c, "RSC: 2019-00078")
    _licitacion(c, "placsp_watched_company_awards:W-1", fuente="placsp_watched_company_awards")
    _licitacion(c, "placsp_agregadas:AG-1", fuente="placsp_agregadas", organo="A:B%")
    # Fuera de la familia: no se tocan.
    _licitacion(c, f"placsp_menores:{_ORG_A}:1/2026", fuente="placsp_menores")
    _licitacion(c, "ted:533989-2026", fuente="ted", organo=None)

    org = c.execute("INSERT INTO organizations (name) VALUES ('Org') RETURNING id").fetchone()[0]
    c.execute(
        "INSERT INTO adjudicaciones (licitacion_id, nombre, fecha_extraccion) "
        "VALUES (%s, 'Seidor', '2026-09-27')",
        (_EXP,),
    )
    c.execute(
        "INSERT INTO licitacion_tecnologia_score "
        " (licitacion_id, tecnologia, probabilidad, threshold_aplicado) "
        "VALUES (%s, 'SAP', 0.82, 0.5)",
        (_EXP,),
    )
    c.execute(
        "INSERT INTO licitaciones_history (id_externo, captured_at, snapshot_json, changed_fields) "
        "VALUES ('OTRO/2026', '2026-09-27', '{}', 'titulo')"
    )
    c.execute("INSERT INTO pursuits (organization_id, licitacion_id) VALUES (%s, %s)", (org, _EXP))
    c.execute(
        "INSERT INTO follows (organization_id, user_key, target_type, target_id) "
        "VALUES (%s, 'u1', 'licitacion', %s), (%s, 'u1', 'empresa', %s)",
        (org, _EXP, org, _EXP),
    )
    c.execute(
        "INSERT INTO user_notifications (organization_id, user_key, type, licitacion_id) "
        "VALUES (%s, 'u1', 'nueva', 'RSC: 2019-00078')",
        (org,),
    )
    c.execute(
        "INSERT INTO licitaciones_duplicados (licitacion_id, canonical_id) "
        "VALUES ('ted:533989-2026', %s)",
        (_EXP,),
    )
    c.execute(
        "INSERT INTO ml_feedback (expediente, relevante, created_at) VALUES (%s, 1, '2026-09-27')",
        (_EXP,),
    )
    c.execute(
        "INSERT INTO domain_events (event_type, aggregate_id, aggregate_type, payload_json, "
        " created_at, dispatched_at) VALUES "
        "('licitacion.nueva', %s, 'licitacion', %s, '2026-09-27', NULL), "
        "('licitacion.nueva', %s, 'licitacion', %s, '2026-09-26', '2026-09-26'), "
        "('empresa.x', %s, 'empresa', '{}', '2026-09-26', NULL)",
        (
            _EXP,
            '{"id_externo": "2026/LIC/0049", "otro": 1}',
            _EXP,
            '{"licitacion_id": "2026/LIC/0049"}',
            _EXP,
        ),
    )
    return int(org)


def _aplicar(c: Any) -> None:
    for sentencia in _cargar().sentencias_upgrade():
        c.execute(sentencia)


def _nuevo(organo: str, expediente: str, prefijo: str = "placsp") -> str:
    from shared.identidad_placsp import clave_placsp

    return clave_placsp(prefijo, organo, expediente)


def test_lleva_cada_fila_y_lo_que_cuelga_de_ella_a_la_clave_nueva(tmp_db: Any) -> None:
    from db.database import connect
    from db.repositories.identidad import ids_anteriores_de, resolver_id_licitacion

    exp_a = _nuevo(_ORG_A, _EXP)
    with connect() as c:
        _sembrar(c)
    with connect() as c:
        _aplicar(c)

        ids = {r[0] for r in c.execute("SELECT id_externo FROM licitaciones").fetchall()}
        assert ids == {
            exp_a,
            _nuevo(_ORG_B, "OTRO/2026"),
            # El expediente con ':' va tal cual, y su expediente natural se recupera.
            _nuevo(_ORG_A, "RSC: 2019-00078"),
            _nuevo(_ORG_A, "W-1", "placsp_watched_company_awards"),
            # El órgano se codifica: «A:B%» → «A%3AB%25».
            "placsp_agregadas:A%3AB%25:AG-1",
            f"placsp_menores:{_ORG_A}:1/2026",
            "ted:533989-2026",
        }

        titulo, primera, ml, vector = c.execute(
            "SELECT titulo, primera_extraccion, ml_tecnologias, search_vector IS NOT NULL "
            "FROM licitaciones WHERE id_externo = %s",
            (exp_a,),
        ).fetchone()
        assert (titulo, primera, ml, vector) == (
            f"Contrato {_EXP}",
            "2026-08-01T02:10:28+00:00",
            "SAP",
            True,
        )

        assert _uno(c, "SELECT licitacion_id FROM adjudicaciones") == exp_a
        assert _uno(c, "SELECT licitacion_id FROM licitacion_tecnologia_score") == exp_a
        assert _uno(c, "SELECT id_externo FROM licitaciones_history") == _nuevo(_ORG_B, "OTRO/2026")
        assert _uno(c, "SELECT licitacion_id FROM pursuits") == exp_a
        assert _uno(c, "SELECT licitacion_id FROM user_notifications") == _nuevo(
            _ORG_A, "RSC: 2019-00078"
        )
        assert c.execute(
            "SELECT licitacion_id, canonical_id FROM licitaciones_duplicados"
        ).fetchone() == ("ted:533989-2026", exp_a)
        assert _uno(c, "SELECT expediente FROM ml_feedback") == exp_a
        follows = dict(c.execute("SELECT target_type, target_id FROM follows").fetchall())
        assert follows == {"licitacion": exp_a, "empresa": _EXP}

        # Outbox: el agregado se repunta siempre; el payload, solo si no salió aún.
        eventos = c.execute(
            "SELECT aggregate_type, aggregate_id, payload_json, dispatched_at "
            "FROM domain_events ORDER BY id"
        ).fetchall()
        pendiente, despachado, ajeno = eventos
        assert pendiente[1] == exp_a and despachado[1] == exp_a
        import json

        assert json.loads(pendiente[2]) == {"id_externo": exp_a, "otro": 1}
        assert json.loads(despachado[2]) == {"licitacion_id": _EXP}
        assert ajeno[1] == _EXP  # aggregate_type = 'empresa': no es una licitación

        habilitado = _uno(c, "SELECT tgenabled FROM pg_trigger WHERE tgname = 'trg_lts_derivar_ml'")
        assert habilitado == "O"
        motivo = _uno(c, "SELECT DISTINCT motivo FROM licitaciones_id_anterior")
        assert motivo == "rekey_placsp_organo"
        assert _uno(c, "SELECT count(*) FROM licitaciones_id_anterior") == 5

    # Un alias por fila re-escrita: la API y la ficha pública resuelven el viejo.
    assert resolver_id_licitacion(_EXP) == (exp_a, True)
    assert resolver_id_licitacion(exp_a) == (exp_a, False)
    assert ids_anteriores_de(exp_a) == [_EXP]


def test_la_clave_es_la_misma_que_escribe_el_conector(tmp_db: Any) -> None:
    """Si el mapa y el escritor divergieran, la siguiente ingesta duplicaría la fila."""
    from lxml import etree

    from db.database import connect
    from scraper.connectors.placsp import _PlacspParseCore

    fixture = Path(__file__).parent / "fixtures" / "placsp" / "03_sin_fecha_limite.xml"
    entry = etree.fromstring(fixture.read_bytes())
    with patch("scraper.pipeline._ml_classify_entry", return_value=None):
        parsed = _PlacspParseCore().parse_entry_elem(entry, fuente="placsp")
    assert parsed is not None
    nueva = parsed.licitacion.id_externo
    organo = parsed.licitacion.organo_ref_fuente
    assert organo is not None
    expediente = nueva.split(":", 2)[2]

    with connect() as c:
        _licitacion(c, expediente, organo=organo)
    with connect() as c:
        _aplicar(c)
        ids = [r[0] for r in c.execute("SELECT id_externo FROM licitaciones").fetchall()]
    assert ids == [nueva]


def test_tras_la_rekey_dos_organos_con_el_mismo_expediente_conviven(tmp_db: Any) -> None:
    """Lo que la fase B arregla: el segundo órgano ya no pisa al primero."""
    from db.database import connect, connect_read
    from db.upsert import Licitacion, upsert_licitaciones

    with connect() as c:
        _licitacion(c, _EXP, organo=_ORG_A, organo_nombre="Mutua Intercomarcal")
    with connect() as c:
        _aplicar(c)

    nuevas, _ = upsert_licitaciones(
        [
            Licitacion(
                id_externo=_nuevo(_ORG_B, _EXP),
                titulo="Hosting",
                organo_contratacion="EGARSAT",
                organo_ref_fuente=_ORG_B,
                fuente="placsp",
            )
        ]
    )
    assert nuevas == 1
    with connect_read() as c:
        filas = dict(
            c.execute("SELECT id_externo, organo_contratacion FROM licitaciones").fetchall()
        )
    assert filas == {
        _nuevo(_ORG_A, _EXP): "Mutua Intercomarcal",
        _nuevo(_ORG_B, _EXP): "EGARSAT",
    }


@pytest.mark.parametrize(
    ("preparar", "aviso"),
    [
        (
            lambda c: _licitacion(c, "SIN-ORGANO/1", organo=None),
            "sin organo_ref_fuente",
        ),
        (
            lambda c: _licitacion(c, "SIN-PREFIJO", fuente="placsp_watched_company_awards"),
            "forma vieja",
        ),
        (
            # Un escritor nuevo ya escribió la clave de `_EXP` (la ingesta no paró).
            lambda c: _licitacion(c, _nuevo(_ORG_A, _EXP), organo=_ORG_A),
            "ya existen con la clave nueva",
        ),
        (
            lambda c: c.execute(
                "INSERT INTO jobs (tipo, payload_json, estado) VALUES ('x', %s, 'pending')",
                ('{"licitacion_id": "2026/LIC/0049"}',),
            ),
            "trabajos pendientes",
        ),
    ],
    ids=["sin_organo", "forma_rara", "clave_ya_existe", "cola_pendiente"],
)
def test_cada_guarda_aborta_sin_tocar_nada(tmp_db: Any, preparar: Any, aviso: str) -> None:
    from db.database import connect

    with connect() as c:
        _sembrar(c)
        preparar(c)

    with connect() as c:
        with pytest.raises(psycopg.errors.RaiseException, match=aviso):
            _aplicar(c)

    with connect() as c:
        assert _uno(c, "SELECT count(*) FROM licitaciones WHERE id_externo = %s", (_EXP,)) == 1
        assert _uno(c, "SELECT licitacion_id FROM pursuits") == _EXP
        assert _uno(c, "SELECT count(*) FROM licitaciones_id_anterior") == 0


def test_dos_filas_que_irian_a_la_misma_clave_abortan(tmp_db: Any) -> None:
    """Solo puede pasar si dos filas viejas comparten órgano y expediente con
    fuentes distintas de la misma familia: ``placsp`` y un ``bulk`` no (son la
    misma fila), pero dos carriles de empresas vigiladas sí."""
    from db.database import connect

    with connect() as c:
        _licitacion(c, "placsp_watched_company_awards:W-1", fuente="placsp_watched_company_awards")
        _licitacion(
            c,
            "placsp_watched_company_awards_bulk_202607:W-1",
            fuente="placsp_watched_company_awards_bulk_202607",
        )
    with connect() as c:
        with pytest.raises(psycopg.errors.RaiseException, match="claves nuevas repetidas"):
            _aplicar(c)


def _colision(c: Any, clave: str, organo: str, fuente: str = "placsp") -> None:
    """Lo que dejó el incidente #577: la misma licitación, escrita ya con la clave nueva."""
    _licitacion(c, clave, fuente=fuente, organo=organo)
    c.execute(
        "INSERT INTO licitaciones_history (id_externo, captured_at, snapshot_json, changed_fields) "
        "VALUES (%s, '2026-10-28', '{}', 'titulo')",
        (clave,),
    )


def test_las_colisiones_son_las_que_la_guarda_encontraria(tmp_db: Any) -> None:
    """``colisiones_del_rekey_placsp`` reproduce el mapa de v164: solo el destino de
    una fila vieja con órgano cuenta, y marca las que tienen datos de usuario."""
    from db.database import connect
    from db.repositories.identidad import colisiones_del_rekey_placsp

    watched = _nuevo(_ORG_A, "W-1", "placsp_watched_company_awards")
    with connect() as c:
        org = _sembrar(c)
        _colision(c, _nuevo(_ORG_A, _EXP), _ORG_A)
        _colision(c, watched, _ORG_A, fuente="placsp_watched_company_awards")
        # Sin gemela vieja: una licitación nueva de verdad, no choca.
        _colision(c, _nuevo(_ORG_A, "SOLO-NUEVA/1"), _ORG_A)
        # La gemela vieja apunta a otro órgano: su destino es otra clave.
        _colision(c, _nuevo(_ORG_A, "OTRO/2026"), _ORG_A, fuente="bulk_202610")
        c.execute(
            "INSERT INTO follows (organization_id, user_key, target_type, target_id) "
            "VALUES (%s, 'u1', 'licitacion', %s)",
            (org, watched),
        )

    colisiones = {c["id_externo"]: c for c in colisiones_del_rekey_placsp()}
    assert set(colisiones) == {_nuevo(_ORG_A, _EXP), watched}
    assert colisiones[_nuevo(_ORG_A, _EXP)]["id_viejo"] == _EXP
    assert not colisiones[_nuevo(_ORG_A, _EXP)]["datos_de_usuario"]
    assert colisiones[watched]["datos_de_usuario"]


def test_borrar_las_colisiones_despeja_la_guarda_y_respeta_los_datos_de_usuario(
    tmp_db: Any,
) -> None:
    from db.database import connect
    from db.repositories.identidad import (
        borrar_licitaciones_en_colision,
        colisiones_del_rekey_placsp,
    )

    exp_a = _nuevo(_ORG_A, _EXP)
    con_usuario = _nuevo(_ORG_A, "CON-USUARIO/1")
    with connect() as c:
        org = _sembrar(c)
        _colision(c, exp_a, _ORG_A)
        c.execute(
            "INSERT INTO licitacion_tecnologia_score "
            " (licitacion_id, tecnologia, probabilidad, threshold_aplicado) "
            "VALUES (%s, 'SAP', 0.9, 0.5)",
            (exp_a,),
        )
        # Una con pursuit: la lista la incluye, el borrado no la toca.
        _licitacion(c, con_usuario, organo=_ORG_A)
        c.execute(
            "INSERT INTO pursuits (organization_id, licitacion_id) VALUES (%s, %s)",
            (org, con_usuario),
        )

    borradas = borrar_licitaciones_en_colision([exp_a, con_usuario])

    assert borradas == 1
    assert colisiones_del_rekey_placsp() == []
    with connect() as c:
        assert _uno(c, "SELECT count(*) FROM licitaciones WHERE id_externo = %s", (exp_a,)) == 0
        assert (
            _uno(c, "SELECT count(*) FROM licitaciones_history WHERE id_externo = %s", (exp_a,))
            == 0
        )
        assert (
            _uno(c, "SELECT count(*) FROM licitaciones WHERE id_externo = %s", (con_usuario,)) == 1
        )
        assert _uno(c, "SELECT count(*) FROM licitaciones WHERE id_externo = %s", (_EXP,)) == 1
    # Y la guarda de v164 ya no encuentra la clave ocupada.
    with connect() as c:
        _aplicar(c)
        assert (
            _uno(c, "SELECT licitacion_id FROM pursuits WHERE licitacion_id = %s", (exp_a,))
            == exp_a
        )


def test_cubre_todas_las_fk_a_licitaciones(tmp_db: Any) -> None:
    """La guarda de FK, comprobada aparte: toda FK a `licitaciones` del esquema
    actual está en `_REFERENCIAS`. Una tabla nueva con FK tiene que entrar en la
    lista de la próxima re-key (y este test lo dirá)."""
    from db.database import connect

    cubiertas = {f"{t}.{c}" for t, c, _ in _cargar()._REFERENCIAS}
    with connect() as c:
        fks = {
            f"{tabla}.{columna}"
            for tabla, columna in c.execute(
                "SELECT r.relname, a.attname FROM pg_constraint k "
                "JOIN pg_class r ON r.oid = k.conrelid "
                "JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = ANY (k.conkey) "
                "WHERE k.contype = 'f' AND k.confrelid = 'licitaciones'::regclass"
            ).fetchall()
        }
    assert fks <= cubiertas, fks - cubiertas


def _rol_miembro_del_dueno(atributos: str) -> Iterator[str]:
    """Un rol no superusuario, miembro del dueño (ver el test de v153)."""
    from db.database import connect

    rol = f"tf_v164_{os.getpid()}_{secrets.token_hex(4)}"
    with connect() as c:
        dueno = str(_uno(c, "SELECT current_user"))
        c.execute(f'CREATE ROLE "{rol}" NOLOGIN NOSUPERUSER {atributos}')
        c.execute(f'GRANT "{dueno}" TO "{rol}"')
    try:
        yield rol
    finally:
        with connect() as c:
            c.execute(f'DROP OWNED BY "{rol}"')
            c.execute(f'DROP ROLE "{rol}"')


@pytest.fixture()
def rol_sin_bypass(tmp_db: Any) -> Iterator[str]:
    yield from _rol_miembro_del_dueno("NOBYPASSRLS")


def test_bajo_un_rol_sujeto_a_rls_aborta_en_vez_de_saltarse_filas(rol_sin_bypass: str) -> None:
    from db.database import connect

    with connect() as c:
        org = _sembrar(c)
    with connect() as c:
        c.execute(f'SET ROLE "{rol_sin_bypass}"')
        c.execute("SELECT set_config('app.organization_id', %s, false)", (str(org + 1),))
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="row-level security"):
            _aplicar(c)

    with connect() as c:
        assert _uno(c, "SELECT licitacion_id FROM pursuits") == _EXP

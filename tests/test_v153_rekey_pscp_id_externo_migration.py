"""v153: las licitaciones PSCP pasan a ``pscp:{uuid de la ficha}:{codi_expedient}``.

Dos niveles, como v151. Sin base, la forma de lo que emite la migración. Con
base (``tmp_db``), que reaplicar sus sentencias sobre filas sembradas con la
clave vieja lleva cada fila y todo lo que cuelga de ella a la nueva —datos de
usuario incluidos, aunque la sesión arrastre otra organización— y que, si el
conector nuevo ya escribió la clave, aborta sin tocar nada.
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

from db.database import connect
from scraper.connectors.base import RawNotice
from scraper.connectors.pscp import PscpConnector, _natural_id

_RUTA = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "alembic"
    / "versions"
    / "v153_rekey_pscp_id_externo.py"
)

_CLINIC = "38d06b2c-6449-44f1-b47f-60ef10cc0ff6"
_UB = "0b5e3f8a-1c2d-4e5f-8a9b-0c1d2e3f4a5b"


def _cargar() -> Any:
    spec = importlib.util.spec_from_file_location("v153_rekey_pscp_id_externo", _RUTA)
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


def _ficha(uuid: str, publicacion: str = "300017093") -> str:
    return f"https://contractaciopublica.cat/ca/detall-publicacio/{uuid}/{publicacion}"


# ---------------------------------------------------------------------------
# Forma, sin base
# ---------------------------------------------------------------------------


def test_encadena_con_v152() -> None:
    modulo = _cargar()
    assert modulo.revision == "v153_rekey_pscp_id_externo"
    assert modulo.down_revision == "v152_fechas_sin_zona_utc"


def test_fuera_de_postgres_no_emite_nada() -> None:
    assert _sql_emitido("upgrade", dialecto="sqlite") == []
    assert _sql_emitido("downgrade", dialecto="sqlite") == []


def test_no_borra_nada_antes_de_comprobar_que_no_quedan_referencias() -> None:
    """El borrado arrastra en cascada lo que no se repuntó: va detrás del conteo."""
    emitido = _sql_emitido("upgrade")
    borrado = next(i for i, s in enumerate(emitido) if s.startswith("DELETE FROM licitaciones"))
    conteo = next(i for i, s in enumerate(emitido) if "referencias sin repuntar" in s)
    ultimo_repunte = max(i for i, s in enumerate(emitido) if s.startswith("UPDATE "))
    assert ultimo_repunte < conteo < borrado


def test_el_trigger_de_tecnologia_se_reactiva() -> None:
    emitido = _sql_emitido("upgrade")
    apagar = emitido.index(
        "ALTER TABLE licitacion_tecnologia_score DISABLE TRIGGER trg_lts_derivar_ml"
    )
    encender = emitido.index(
        "ALTER TABLE licitacion_tecnologia_score ENABLE TRIGGER trg_lts_derivar_ml"
    )
    assert apagar < encender


def test_la_clave_es_la_misma_que_escribe_el_conector(tmp_db) -> None:
    """El mapa de la migración y `_natural_id` tienen que dar el mismo id: si
    divergieran, la siguiente ingesta duplicaría lo que la migración re-keyó."""
    registro = {
        "codi_expedient": "Obert",
        "objecte_contracte": "Implantació SAP SuccessFactors",
        "codi_cpv": "72263000-6",
        "enllac_publicacio": {"url": _ficha(_CLINIC.upper())},
    }
    natural = _natural_id(registro)
    assert natural is not None
    parsed = PscpConnector(dataset_id="t-t").parse(RawNotice(natural, registro))
    assert parsed is not None

    with connect() as c:
        _licitacion(c, "pscp:Obert", url=_ficha(_CLINIC.upper()))
        for sentencia in _cargar().sentencias_upgrade():
            c.execute(sentencia)
        ids = [r[0] for r in c.execute("SELECT id_externo FROM licitaciones").fetchall()]
    assert ids == [parsed.licitacion.id_externo]


# ---------------------------------------------------------------------------
# Con base
# ---------------------------------------------------------------------------


def _licitacion(c: Any, id_externo: str, *, url: str | None, fuente: str = "pscp") -> None:
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, fuente, url, "
        " fecha_extraccion, primera_extraccion, fecha_publicacion, ml_tecnologias) "
        "VALUES (%s, %s, 'Organo', %s, %s, '2026-09-27T02:31:41+00:00', "
        " '2026-08-01T02:10:28+00:00', '2026-07-13', 'SAP')",
        (id_externo, f"Contrato {id_externo}", fuente, url),
    )


def _sembrar(c: Any) -> int:
    """Lo de prod en pequeño: una fila PSCP de cada caso y algo de todo colgando.

    Se siembra en su propia transacción: el trigger diferido de
    ``licitacion_tecnologia_score`` deja eventos pendientes hasta el commit, y
    con ellos Postgres no deja desactivarlo (en prod la migración abre una
    transacción limpia).
    """
    _licitacion(c, "pscp:Obert", url=_ficha(_CLINIC))
    _licitacion(c, "pscp:2026/18", url=_ficha(_UB, "300000001"))
    _licitacion(c, f"pscp:{_UB}:YA-NUEVA", url=_ficha(_UB, "300000002"))
    _licitacion(c, "pscp:SIN-FICHA", url="https://contractaciopublica.cat/ca/detall/1")
    _licitacion(c, "pscp:SIN-URL", url=None)
    _licitacion(c, "2026/18", url=None, fuente="placsp")

    org = c.execute("INSERT INTO organizations (name) VALUES ('Org') RETURNING id").fetchone()[0]
    c.execute(
        "INSERT INTO adjudicaciones (licitacion_id, nombre, fecha_extraccion) "
        "VALUES ('pscp:Obert', 'Seidor', '2026-09-27')"
    )
    c.execute(
        "INSERT INTO licitacion_tecnologia_score "
        " (licitacion_id, tecnologia, probabilidad, threshold_aplicado) "
        "VALUES ('pscp:Obert', 'SAP', 0.82, 0.5)"
    )
    c.execute(
        "INSERT INTO licitaciones_history (id_externo, captured_at, snapshot_json, changed_fields) "
        "VALUES ('pscp:2026/18', '2026-09-27', '{}', 'titulo')"
    )
    c.execute(
        "INSERT INTO pursuits (organization_id, licitacion_id) VALUES (%s, 'pscp:Obert')", (org,)
    )
    c.execute(
        "INSERT INTO follows (organization_id, user_key, target_type, target_id) "
        "VALUES (%s, 'u1', 'licitacion', 'pscp:Obert'), (%s, 'u1', 'empresa', 'pscp:Obert')",
        (org, org),
    )
    c.execute(
        "INSERT INTO user_notifications (organization_id, user_key, type, licitacion_id) "
        "VALUES (%s, 'u1', 'nueva', 'pscp:2026/18')",
        (org,),
    )
    c.execute(
        "INSERT INTO licitaciones_duplicados (licitacion_id, canonical_id) "
        "VALUES ('pscp:2026/18', '2026/18')"
    )
    return org


def _uno(c: Any, sql: str) -> Any:
    fila = c.execute(sql).fetchone()
    return fila[0] if fila else None


def test_lleva_cada_fila_y_lo_que_cuelga_de_ella_a_la_clave_nueva(tmp_db) -> None:
    obert, ub = f"pscp:{_CLINIC}:Obert", f"pscp:{_UB}:2026/18"
    with connect() as c:
        _sembrar(c)
    with connect() as c:
        for sentencia in _cargar().sentencias_upgrade():
            c.execute(sentencia)

        ids = {r[0] for r in c.execute("SELECT id_externo FROM licitaciones").fetchall()}
        assert ids == {
            obert,
            ub,
            f"pscp:{_UB}:YA-NUEVA",
            "pscp:SIN-FICHA",
            "pscp:SIN-URL",
            "2026/18",
        }

        # La fila conserva lo suyo, y lo generado se recalcula.
        titulo, primera, ml, vector = c.execute(
            "SELECT titulo, primera_extraccion, ml_tecnologias, search_vector IS NOT NULL "
            "FROM licitaciones WHERE id_externo = %s",
            (obert,),
        ).fetchone()
        assert (titulo, primera, ml, vector) == (
            "Contrato pscp:Obert",
            "2026-08-01T02:10:28+00:00",
            "SAP",
            True,
        )

        assert _uno(c, "SELECT licitacion_id FROM adjudicaciones") == obert
        assert _uno(c, "SELECT licitacion_id FROM licitacion_tecnologia_score") == obert
        assert _uno(c, "SELECT id_externo FROM licitaciones_history") == ub
        assert _uno(c, "SELECT licitacion_id FROM pursuits") == obert
        assert _uno(c, "SELECT licitacion_id FROM user_notifications") == ub
        assert c.execute(
            "SELECT licitacion_id, canonical_id FROM licitaciones_duplicados"
        ).fetchone() == (ub, "2026/18")
        # De las polimórficas solo se toca lo que es licitación.
        follows = dict(c.execute("SELECT target_type, target_id FROM follows").fetchall())
        assert follows == {"licitacion": obert, "empresa": "pscp:Obert"}

        habilitado = _uno(c, "SELECT tgenabled FROM pg_trigger WHERE tgname = 'trg_lts_derivar_ml'")
        assert habilitado == "O"


def _rol_miembro_del_dueno(atributos: str) -> Iterator[str]:
    """Un rol no superusuario con los ``atributos`` dados, miembro del dueño.

    El de la suite es superusuario, y los superusuarios se saltan la RLS aunque
    la tabla tenga ``FORCE`` (ver ``tests/test_rls_tenant_scope_integration.py``):
    con él, lo que la RLS le haría a la migración no se vería. Este es miembro
    del dueño —la migración desactiva un trigger, y eso es cosa del dueño—, pero
    ``SUPERUSER`` y ``BYPASSRLS`` no se heredan nunca: solo tiene los suyos.
    Nombre único: los roles son globales al clúster y la suite corre en paralelo.
    """
    rol = f"tf_v153_{os.getpid()}_{secrets.token_hex(4)}"
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


@pytest.fixture()
def rol_como_produccion(tmp_db: Any) -> Iterator[str]:
    """El ``postgres`` de Supabase con que migra ``migrate.yml``: dueño, no
    superusuario, con ``BYPASSRLS`` (medido en prod el 2026-10-17)."""
    yield from _rol_miembro_del_dueno("BYPASSRLS")


def test_con_el_rol_de_produccion_repunta_aunque_haya_organizacion(
    rol_como_produccion: str,
) -> None:
    with connect() as c:
        org = _sembrar(c)
    with connect() as c:
        c.execute(f'SET ROLE "{rol_como_produccion}"')
        c.execute("SELECT set_config('app.organization_id', %s, false)", (str(org + 1),))
        for sentencia in _cargar().sentencias_upgrade():
            c.execute(sentencia)
        c.execute("RESET ROLE")
        assert _uno(c, "SELECT licitacion_id FROM pursuits") == f"pscp:{_CLINIC}:Obert"
        assert _uno(c, "SELECT licitacion_id FROM user_notifications") == f"pscp:{_UB}:2026/18"


def test_bajo_un_rol_sujeto_a_rls_aborta_en_vez_de_saltarse_filas(rol_sin_bypass: str) -> None:
    """Con ``app.organization_id`` puesto, las políticas FORCE RLS esconderían
    las filas de las demás organizaciones al ``UPDATE`` y al conteo previo al
    borrado: las tablas sin FK (``user_notifications``, ``follows``…) quedarían
    huérfanas sin error. ``row_security = off`` lo convierte en un fallo."""
    with connect() as c:
        org = _sembrar(c)
    with connect() as c:
        c.execute(f'SET ROLE "{rol_sin_bypass}"')
        c.execute("SELECT set_config('app.organization_id', %s, false)", (str(org + 1),))
        # El rol ve lo que la política deja ver: el pursuit de `org` no.
        assert _uno(c, "SELECT count(*) FROM pursuits") == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="row-level security"):
            for sentencia in _cargar().sentencias_upgrade():
                c.execute(sentencia)

    with connect() as c:
        assert _uno(c, "SELECT licitacion_id FROM pursuits") == "pscp:Obert"
        assert _uno(c, "SELECT licitacion_id FROM user_notifications") == "pscp:2026/18"


def test_si_el_conector_nuevo_ya_escribio_la_clave_aborta_sin_tocar_nada(tmp_db) -> None:
    with connect() as c:
        _sembrar(c)
        _licitacion(c, f"pscp:{_CLINIC}:Obert", url=_ficha(_CLINIC))

    with connect() as c:
        with pytest.raises(psycopg.errors.RaiseException, match="ya existen con la clave nueva"):
            for sentencia in _cargar().sentencias_upgrade():
                c.execute(sentencia)

    with connect() as c:
        assert _uno(c, "SELECT count(*) FROM licitaciones WHERE id_externo = 'pscp:Obert'") == 1
        assert _uno(c, "SELECT licitacion_id FROM pursuits") == "pscp:Obert"


def test_cubre_todas_las_fk_a_licitaciones(tmp_db) -> None:
    """La guarda de la migración, comprobada aparte: si una FK nueva no
    estuviera en `_REFERENCIAS`, la migración abortaría en prod."""
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

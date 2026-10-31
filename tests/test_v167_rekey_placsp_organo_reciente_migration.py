"""v167: las filas re-keyed con un órgano antiguo pasan a la clave del órgano actual.

Mismos dos niveles que ``tests/test_v164_identidad_placsp_rekey_migration.py``.
Sin base: la forma de lo que emite (encadenamiento, guardas antes de escribir,
trigger apagado antes del borrado en cascada, borrado detrás del conteo) y que
el mapa embebido es coherente con ``shared.identidad_placsp``. Con base: que
mueve la fila y lo que cuelga de ella, borra el duplicado que la ingesta ya
escribió con la clave correcta, encadena los alias de ``v164`` y no hace nada
sobre una base sin esas filas.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import patch

import psycopg
import pytest

_VERSIONES = Path(__file__).resolve().parents[1] / "db" / "alembic" / "versions"
_RUTA = _VERSIONES / "v167_rekey_placsp_organo_reciente.py"

_NIF = "Q2891006E"
_ORG = "10000140020261"
_EXP = "039/21-SP"
_VIEJA = f"placsp:{_NIF}:{_EXP}"
_NUEVA = f"placsp:{_ORG}:{_EXP}"


def _cargar(ruta: Path = _RUTA) -> Any:
    spec = importlib.util.spec_from_file_location(ruta.stem, ruta)
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


def test_encadena_con_v166() -> None:
    modulo = _cargar()
    assert modulo.revision == "v167_rekey_placsp_organo_reciente"
    assert modulo.down_revision == "v166_source_health_status_disabled"


def test_fuera_de_postgres_y_en_downgrade_no_emite_nada() -> None:
    assert _sql_emitido("upgrade", dialecto="sqlite") == []
    assert _sql_emitido("downgrade") == []


def test_las_guardas_van_antes_de_la_primera_escritura() -> None:
    emitido = _sql_emitido("upgrade")
    guardas = next(i for i, s in enumerate(emitido) if "decídalos a mano" in s)
    primera_escritura = next(i for i, s in enumerate(emitido) if "DISABLE TRIGGER" in s)
    assert guardas < primera_escritura
    texto = emitido[guardas]
    for aviso in ("repetidas", "datos de usuario", "FK a licitaciones", "trabajos pendientes"):
        assert aviso in texto, aviso
    assert texto.count("RAISE EXCEPTION") == 4


def test_el_trigger_se_apaga_antes_del_borrado_en_cascada_y_se_reactiva() -> None:
    """El borrado de los duplicados toca ``licitacion_tecnologia_score``: con el
    trigger diferido encendido dejaría eventos pendientes y no se podría apagar."""
    emitido = _sql_emitido("upgrade")
    apagar = emitido.index(
        "ALTER TABLE licitacion_tecnologia_score DISABLE TRIGGER trg_lts_derivar_ml"
    )
    encender = emitido.index(
        "ALTER TABLE licitacion_tecnologia_score ENABLE TRIGGER trg_lts_derivar_ml"
    )
    primer_borrado = next(i for i, s in enumerate(emitido) if s.startswith("DELETE FROM "))
    assert apagar < primer_borrado < encender


def test_la_clave_antigua_se_borra_detras_del_conteo_de_referencias() -> None:
    emitido = _sql_emitido("upgrade")
    conteo = next(i for i, s in enumerate(emitido) if "referencias sin repuntar" in s)
    ultimo_repunte = max(i for i, s in enumerate(emitido) if s.startswith("UPDATE "))
    borrado_viejas = next(
        i for i, s in enumerate(emitido) if s.startswith("DELETE FROM licitaciones l USING")
    )
    assert ultimo_repunte < conteo < borrado_viejas


def test_las_referencias_son_las_de_v164() -> None:
    v164 = _cargar(_VERSIONES / "v164_identidad_placsp_rekey.py")
    assert _cargar()._REFERENCIAS == v164._REFERENCIAS


def test_el_mapa_es_coherente_con_la_clave_que_escribe_el_conector() -> None:
    from shared.identidad_placsp import clave_placsp, descomponer_clave_placsp

    mapa = _cargar()._MAPA_DATOS
    assert len(mapa) == 452
    assert len({nuevo for _, nuevo, _ in mapa}) == len(mapa)
    for viejo, nuevo, organo in mapa:
        partes = descomponer_clave_placsp(viejo)
        assert partes is not None, viejo
        assert nuevo == clave_placsp(partes.prefijo, organo, partes.expediente)
        assert nuevo != viejo


# ---------------------------------------------------------------------------
# Con base
# ---------------------------------------------------------------------------


def _uno(c: Any, sql: str, params: tuple[Any, ...] = ()) -> Any:
    fila = c.execute(sql, params).fetchone()
    return fila[0] if fila else None


def _licitacion(c: Any, id_externo: str, organo: str, titulo: str) -> None:
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, fuente, url, "
        " organo_ref_fuente, fecha_extraccion, primera_extraccion, fecha_publicacion) "
        "VALUES (%s, %s, 'Órgano', 'placsp', %s, %s, '2026-10-31T10:00:00+00:00', "
        " '2018-10-01T00:00:00+00:00', '2018-10-01')",
        (
            id_externo,
            titulo,
            "https://contrataciondelestado.es/wps/poc?uri=deeplink:detalle_licitacion&idEvl=x",
            organo,
        ),
    )


def _adjudicacion(c: Any, licitacion: str, nombre: str) -> None:
    c.execute(
        "INSERT INTO adjudicaciones (licitacion_id, nombre, fecha_extraccion) "
        "VALUES (%s, %s, '2026-10-31')",
        (licitacion, nombre),
    )


def _aplicar(c: Any, mapa: tuple[tuple[str, str, str], ...]) -> None:
    modulo = _cargar()
    modulo._MAPA_DATOS = mapa
    for sentencia in modulo.sentencias_upgrade():
        c.execute(sentencia)


def test_mueve_la_fila_y_borra_el_duplicado_con_la_clave_correcta(tmp_db: Any) -> None:
    from db.database import connect
    from db.repositories.identidad import resolver_id_licitacion

    with connect() as c:
        _licitacion(c, _VIEJA, _NIF, "Re-keyed con el NIF")
        _adjudicacion(c, _VIEJA, "De la fila re-keyed")
        org = c.execute("INSERT INTO organizations (name) VALUES ('Org') RETURNING id").fetchone()[
            0
        ]
        c.execute(
            "INSERT INTO pursuits (organization_id, licitacion_id) VALUES (%s, %s)", (org, _VIEJA)
        )
        # El alias de v164: el expediente pelado apuntaba a la clave con el NIF.
        c.execute(
            "INSERT INTO licitaciones_id_anterior (id_anterior, id_externo, motivo, creado_en) "
            "VALUES (%s, %s, 'rekey_placsp_organo', '2026-10-31T00:00:00+00:00')",
            (_EXP, _VIEJA),
        )
        # El duplicado que la ingesta escribió ya con la clave correcta.
        _licitacion(c, _NUEVA, _ORG, "Copia reciente de la ingesta")
        _adjudicacion(c, _NUEVA, "Del duplicado")
    with connect() as c:
        _aplicar(c, ((_VIEJA, _NUEVA, _ORG),))

        filas = c.execute(
            "SELECT id_externo, titulo, organo_ref_fuente FROM licitaciones"
        ).fetchall()
        assert [tuple(f) for f in filas] == [(_NUEVA, "Re-keyed con el NIF", _ORG)]
        adjudicaciones = c.execute("SELECT licitacion_id, nombre FROM adjudicaciones").fetchall()
        assert [tuple(a) for a in adjudicaciones] == [(_NUEVA, "De la fila re-keyed")]
        assert _uno(c, "SELECT licitacion_id FROM pursuits") == _NUEVA
        alias = dict(
            c.execute("SELECT id_anterior, motivo FROM licitaciones_id_anterior").fetchall()
        )
        assert alias == {_EXP: "rekey_placsp_organo", _VIEJA: "rekey_placsp_organo_reciente"}
        assert (
            _uno(c, "SELECT tgenabled FROM pg_trigger WHERE tgname = 'trg_lts_derivar_ml'") == "O"
        )

    # Las dos claves anteriores resuelven a la correcta.
    assert resolver_id_licitacion(_EXP) == (_NUEVA, True)
    assert resolver_id_licitacion(_VIEJA) == (_NUEVA, True)


def test_un_destino_ocupado_con_datos_de_usuario_aborta_sin_tocar_nada(tmp_db: Any) -> None:
    from db.database import connect

    with connect() as c:
        _licitacion(c, _VIEJA, _NIF, "Re-keyed")
        _licitacion(c, _NUEVA, _ORG, "Duplicado con usuario")
        org = c.execute("INSERT INTO organizations (name) VALUES ('Org') RETURNING id").fetchone()[
            0
        ]
        c.execute(
            "INSERT INTO pursuits (organization_id, licitacion_id) VALUES (%s, %s)", (org, _NUEVA)
        )

    with connect() as c:
        with pytest.raises(psycopg.errors.RaiseException, match="datos de usuario"):
            _aplicar(c, ((_VIEJA, _NUEVA, _ORG),))

    with connect() as c:
        ids = {r[0] for r in c.execute("SELECT id_externo FROM licitaciones").fetchall()}
        assert ids == {_VIEJA, _NUEVA}
        assert _uno(c, "SELECT count(*) FROM licitaciones_id_anterior") == 0


def test_sin_las_filas_del_mapa_no_hace_nada(tmp_db: Any) -> None:
    """Sobre una base que no tiene las 452 (CI, desarrollo) la revisión es inocua."""
    from db.database import connect

    with connect() as c:
        _licitacion(c, "placsp:31055010149261:OTRA/2026", "31055010149261", "Ajena")
    with connect() as c:
        _aplicar(c, _cargar()._MAPA_DATOS)
        ids = [r[0] for r in c.execute("SELECT id_externo FROM licitaciones").fetchall()]
        assert ids == ["placsp:31055010149261:OTRA/2026"]
        assert _uno(c, "SELECT count(*) FROM licitaciones_id_anterior") == 0

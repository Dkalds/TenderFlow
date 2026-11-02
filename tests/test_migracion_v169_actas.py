"""v169: ``documentos.tipo`` admite ``'acta'`` y nacen las tablas de puntuaciones del acta.

Dos niveles, como ``tests/test_v167_rekey_placsp_organo_reciente_migration.py``.
Sin base: la forma de lo que emite la revisión (encadenado, orden del CHECK,
downgrade que no deja filas que el CHECK viejo rechazaría). Con base: que la
base migrada a ``head`` hace lo que la revisión dice —acepta el tipo, rechaza
los demás, protege la unicidad aunque ``lote_numero`` y ``criterio`` sean
``NULL`` y borra en cascada—.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import patch

import psycopg
import pytest

_VERSIONES = Path(__file__).resolve().parents[1] / "db" / "alembic" / "versions"
_NOMBRE = "v169_actas_puntuaciones"

_LIC = "placsp:10000140020261:ACTA/2026"


def _cargar() -> Any:
    spec = importlib.util.spec_from_file_location(_NOMBRE, _VERSIONES / f"{_NOMBRE}.py")
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _emitido(funcion: str, *, dialecto: str = "postgresql") -> tuple[list[str], Any]:
    """SQL que emite ``funcion`` por ``op.execute`` y el ``op`` falso que lo recibió."""
    modulo = _cargar()
    emitido: list[str] = []
    with patch.object(modulo, "op") as op_falso:
        op_falso.get_bind.return_value.dialect.name = dialecto
        op_falso.execute.side_effect = emitido.append
        getattr(modulo, funcion)()
    return emitido, op_falso


# ---------------------------------------------------------------------------
# Forma, sin base
# ---------------------------------------------------------------------------


def test_encadena_con_v168() -> None:
    modulo = _cargar()
    assert modulo.revision == _NOMBRE
    assert modulo.down_revision == "v168_mv_canonicas_universo_producto"


def test_fuera_de_postgres_no_emite_nada() -> None:
    for funcion in ("upgrade", "downgrade"):
        emitido, op_falso = _emitido(funcion, dialecto="sqlite")
        assert emitido == []
        op_falso.create_table.assert_not_called()


def test_upgrade_tira_el_check_viejo_antes_de_crear_el_nuevo() -> None:
    emitido, _ = _emitido("upgrade")
    tirar = next(i for i, s in enumerate(emitido) if "DROP CONSTRAINT" in s)
    crear = next(i for i, s in enumerate(emitido) if "ADD CONSTRAINT ck_documentos_tipo" in s)
    assert tirar < crear
    # El nombre del CHECK de v56 es inline y sin nombre: se busca, no se supone.
    assert "pg_constraint" in emitido[tirar]
    assert "CHECK (tipo IN ('legal', 'technical', 'additional', 'acta'))" in emitido[crear]


def test_upgrade_crea_las_dos_tablas_y_la_unicidad_que_no_ignora_los_nulos() -> None:
    _, op_falso = _emitido("upgrade")
    tablas = [llamada.args[0] for llamada in op_falso.create_table.call_args_list]
    assert tablas == ["acta_extracciones", "acta_puntuaciones"]
    sql = "\n".join(str(llamada.args[0]) for llamada in op_falso.execute.call_args_list)
    assert "uq_acta_puntuaciones_fila" in sql
    assert "COALESCE(lote_numero, '')" in sql
    assert "COALESCE(criterio, '')" in sql


def test_downgrade_borra_las_actas_antes_de_estrechar_el_check() -> None:
    """Con filas ``acta`` el ``ADD CONSTRAINT`` del vocabulario viejo fallaría."""
    emitido, op_falso = _emitido("downgrade")
    borrar = emitido.index("DELETE FROM documentos WHERE tipo = 'acta'")
    estrechar = next(i for i, s in enumerate(emitido) if "ADD CONSTRAINT" in s)
    assert borrar < estrechar
    assert "CHECK (tipo IN ('legal', 'technical', 'additional'))" in emitido[estrechar]
    quitadas = [llamada.args[0] for llamada in op_falso.drop_table.call_args_list]
    assert quitadas == ["acta_puntuaciones", "acta_extracciones"]


# ---------------------------------------------------------------------------
# Con base
# ---------------------------------------------------------------------------


def _sembrar_acta(c: Any) -> int:
    """Una licitación con su acta; devuelve el ``documentos.id`` del acta."""
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion) VALUES (%s, %s, %s)",
        (_LIC, "Servicio de soporte y mantenimiento de sistemas", "2026-11-01"),
    )
    fila = c.execute(
        "INSERT INTO documentos (licitacion_id, tipo, uri) VALUES (%s, 'acta', %s) RETURNING id",
        (_LIC, "https://contrataciondelestado.es/acta-mesa.pdf"),
    ).fetchone()
    return int(fila[0])


def _puntuacion(
    c: Any,
    documento_id: int,
    *,
    lote: str | None = None,
    licitador: str = "acme",
    criterio: str | None = None,
) -> None:
    c.execute(
        "INSERT INTO acta_puntuaciones (licitacion_id, lote_numero, licitador_nombre, "
        " licitador_normalizado, criterio, puntos, documento_id, pagina, cita) "
        "VALUES (%s, %s, 'ACME S.L.', %s, %s, 42.5, %s, 3, 'ACME S.L.  42,5')",
        (_LIC, lote, licitador, criterio, documento_id),
    )


def _cuenta(c: Any, tabla: str) -> int:
    return int(c.execute(f"SELECT count(*) FROM {tabla}").fetchone()[0])  # noqa: S608 -- tabla fijada por el test


def test_documentos_admite_tipo_acta(tmp_db: Any) -> None:
    from db.database import connect

    with connect() as c:
        _sembrar_acta(c)
    with connect() as c:
        assert c.execute("SELECT tipo FROM documentos").fetchone()[0] == "acta"


def test_documentos_sigue_rechazando_tipos_desconocidos(tmp_db: Any) -> None:
    from db.database import connect

    with connect() as c:
        _sembrar_acta(c)
    with pytest.raises(psycopg.errors.CheckViolation), connect() as c:
        c.execute(
            "INSERT INTO documentos (licitacion_id, tipo, uri) VALUES (%s, 'otro', 'https://x/y')",
            (_LIC,),
        )


def test_acta_puntuaciones_unicidad_con_lote_y_criterio_nulos(tmp_db: Any) -> None:
    """``NULL <> NULL`` dejaría repetir justo la fila del total del expediente."""
    from db.database import connect

    with connect() as c:
        documento = _sembrar_acta(c)
        _puntuacion(c, documento)
    with pytest.raises(psycopg.errors.UniqueViolation), connect() as c:
        _puntuacion(c, documento)
    # Lo que difiere en lote, licitador o criterio es otra fila.
    with connect() as c:
        _puntuacion(c, documento, lote="2")
        _puntuacion(c, documento, licitador="otra")
        _puntuacion(c, documento, criterio="Oferta económica")
        assert _cuenta(c, "acta_puntuaciones") == 4


def test_acta_extracciones_status_cerrado(tmp_db: Any) -> None:
    from db.database import connect

    with connect() as c:
        _sembrar_acta(c)
        c.execute(
            "INSERT INTO acta_extracciones (licitacion_id, status, extraction_version, "
            " documentos_leidos) VALUES (%s, 'ok', 'acta-puntuaciones-v1', 1)",
            (_LIC,),
        )
        for status in ("sin_tabla", "sin_acta", "error"):
            c.execute("UPDATE acta_extracciones SET status = %s", (status,))
    with pytest.raises(psycopg.errors.CheckViolation), connect() as c:
        c.execute("UPDATE acta_extracciones SET status = 'raro'")


def test_borrar_documento_borra_sus_puntuaciones(tmp_db: Any) -> None:
    from db.database import connect

    with connect() as c:
        documento = _sembrar_acta(c)
        _puntuacion(c, documento)
        _puntuacion(c, documento, criterio="Oferta económica")
    with connect() as c:
        c.execute("DELETE FROM documentos WHERE id = %s", (documento,))
        assert _cuenta(c, "acta_puntuaciones") == 0
        # La licitación y su estado de extracción no dependen del documento.
        assert _cuenta(c, "licitaciones") == 1

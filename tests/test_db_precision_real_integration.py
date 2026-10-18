"""Los ``real`` llegan con todas sus cifras aunque el servidor diga ``extra_float_digits = 0``.

Supabase fija ``extra_float_digits = 0`` en su fichero de configuración. Con
ese valor Postgres manda los ``real`` (float4) en texto con 6 cifras
significativas y psycopg, que lee en texto, recibe ``1.17822e+07`` por
``11782155``: los importes adjudicados de la API, el worker y el MCP salían
redondeados a la centena de miles. Aquí el valor de producción se simula
pidiéndolo al abrir la conexión (``-c extra_float_digits=0``), que es lo que
haría el fichero de configuración, y se comprueba que el ``configure`` del
pool lo deja en 3.
"""

from __future__ import annotations

import psycopg
import pytest

from db.connection import _make_pg_configure
from tests.conftest import _pg_test_url

pytestmark = pytest.mark.integration

#: Un importe adjudicado real de producción (AsturCon XXI, lote 1).
IMPORTE = 11782155


def _conexion_como_supabase(*, autocommit: bool) -> psycopg.Connection[tuple[object, ...]]:
    conn = psycopg.connect(_pg_test_url(), options="-c extra_float_digits=0", autocommit=autocommit)
    fila = conn.execute("SHOW extra_float_digits").fetchone()
    assert fila is not None and fila[0] == "0", "la simulación de Supabase no se aplicó"
    return conn


def test_sin_configurar_el_real_llega_redondeado() -> None:
    """El síntoma: con ``extra_float_digits = 0`` el ``real`` pierde cifras."""
    with _conexion_como_supabase(autocommit=True) as conn:
        fila = conn.execute(f"SELECT {IMPORTE}::real").fetchone()
    assert fila is not None
    assert fila[0] == 11782200


@pytest.mark.parametrize("read_only", [False, True])
def test_configure_del_pool_devuelve_el_real_exacto(read_only: bool) -> None:
    # El pool de lectura va en autocommit y el de escritura no
    # (`_pg_connect_kwargs`); el `configure` tiene que valer en los dos.
    with _conexion_como_supabase(autocommit=read_only) as conn:
        _make_pg_configure(read_only=read_only)(conn)
        fila = conn.execute(f"SELECT {IMPORTE}::real").fetchone()
    assert fila is not None
    assert fila[0] == IMPORTE

"""El pase de ``db/importe_tipo.py`` solo declara ``sin_iva`` lo adjudicado de PSCP.

Integración (``tmp_db``): se siembran por el camino de escritura real las filas
que dejó el parser antiguo y las que el pase no debe tocar.
"""

from __future__ import annotations

from typing import Any

from db.connection import connect_read
from db.importe_tipo import aplicar_lote, contar_candidatas
from db.upsert import Adjudicacion, Licitacion, replace_adjudicaciones_batch, upsert_licitaciones

_AGR = "pscp:93b05970-c56b-42d0-82b8-78d21a231f37:2302/081"


def _lic(id_externo: str, **over: Any) -> Licitacion:
    base: dict[str, Any] = {
        "id_externo": id_externo,
        "titulo": "Compra de llicències Office",
        "importe": 769.5,
        "importe_tipo": "desconocido",
        "estado": "AGR",
        "fuente": "pscp",
    }
    base.update(over)
    return Licitacion(**base)


def _sembrar() -> None:
    upsert_licitaciones(
        [
            _lic(_AGR),
            # Importe distinto de lo adjudicado: no se sabe de dónde salió.
            _lic("pscp:otro:1", importe=1000.0),
            # Sin adjudicación guardada.
            _lic("pscp:otro:2"),
            # Otra fuente con el mismo patrón: fuera del pase.
            _lic("ted:1-2026", fuente="ted"),
        ]
    )
    replace_adjudicaciones_batch(
        {
            i: [
                Adjudicacion(
                    licitacion_id=i, nombre="SEIDOR SOLUTIONS S.L.", importe_adjudicado=769.5
                )
            ]
            for i in (_AGR, "pscp:otro:1", "ted:1-2026")
        }
    )


def _tipos() -> dict[str, str]:
    with connect_read() as c:
        return dict(c.execute("SELECT id_externo, importe_tipo FROM licitaciones").fetchall())


def test_el_pase_corrige_solo_lo_adjudicado_de_pscp_y_es_idempotente(tmp_db):
    _sembrar()
    assert contar_candidatas() == {"AGR": 1}

    assert aplicar_lote(100) == 1
    assert aplicar_lote(100) == 0

    assert _tipos() == {
        _AGR: "sin_iva",
        "pscp:otro:1": "desconocido",
        "pscp:otro:2": "desconocido",
        "ted:1-2026": "desconocido",
    }
    assert contar_candidatas() == {}

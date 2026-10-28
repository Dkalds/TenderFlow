"""La reingesta normal corrige los cuatro defectos que mide el verificador.

Integración (``tmp_db``). Se siembra una fila PLACSP con el estado que dejó el
parser antiguo —``importe_tipo`` desconocido, ``provincia`` «España», fecha con
hora, adjudicación y garantía a 0, solvencia económica sin umbral— y se
reingiere **por el camino de escritura real** (``upsert_licitaciones_with_history``
+ ``replace_adjudicaciones_batch``, lo que hace ``run_connector``) con lo que
el parser de hoy produce para el mismo expediente. Es la comprobación de que
ningún COALESCE del upsert deja el valor viejo
(``docs/runbooks/reingesta-unica-placsp.md`` §«Qué pisa una reingesta»).
"""

from __future__ import annotations

from typing import Any

from db.repositories.verificacion_reingesta import (
    ceros_en_hijas,
    licitaciones_placsp,
    solvencia_economica,
)
from db.upsert import (
    Adjudicacion,
    CondicionesCodice,
    GarantiaExigida,
    Licitacion,
    RequisitoSolvencia,
    replace_adjudicaciones_batch,
    upsert_licitaciones_with_history,
)


def _lic(**over: Any) -> Licitacion:
    base: dict[str, Any] = {
        "id_externo": "REING-1",
        "titulo": "Servicio de soporte SAP",
        "organo_contratacion": "Ayuntamiento de Ejemplo",
        "importe": 100000.0,
        "estado": "ADJ",
        "fuente": "bulk_202503",
    }
    base.update(over)
    return Licitacion(**base)


def _sembrar_estado_antiguo() -> None:
    upsert_licitaciones_with_history(
        [
            _lic(
                importe_tipo="desconocido",
                provincia="España",
                fecha_publicacion="2025-03-04T10:11:12.155+01:00",
                condiciones=CondicionesCodice(
                    garantias=[GarantiaExigida(orden=1, porcentaje=0.0)],
                    solvencia=[RequisitoSolvencia(orden=1, clase="economica")],
                ),
            ),
            # Otra fuente: no cuenta en ninguna cifra PLACSP.
            _lic(id_externo="ted:1", fuente="ted", provincia="España"),
        ],
        source="bulk_202503",
    )
    replace_adjudicaciones_batch(
        {
            "REING-1": [
                Adjudicacion(licitacion_id="REING-1", nombre="Empresa", importe_adjudicado=0.0)
            ]
        }
    )


def _reingerir_con_el_parser_de_hoy() -> None:
    upsert_licitaciones_with_history(
        [
            _lic(
                importe_tipo="sin_iva",
                importe_base_sin_iva=100000.0,
                importe_con_iva=121000.0,
                provincia=None,
                fecha_publicacion="2025-04-01",
                fuente="bulk_202504",
                condiciones=CondicionesCodice(
                    garantias=[GarantiaExigida(orden=1, porcentaje=None)],
                    solvencia=[
                        RequisitoSolvencia(orden=1, clase="economica", umbral_importe=150000.0)
                    ],
                ),
            )
        ],
        source="bulk_202504",
    )
    replace_adjudicaciones_batch(
        {
            "REING-1": [
                Adjudicacion(licitacion_id="REING-1", nombre="Empresa", importe_adjudicado=None)
            ]
        }
    )


def test_el_verificador_ve_los_defectos_del_estado_antiguo(tmp_db):
    _sembrar_estado_antiguo()

    lic = licitaciones_placsp()
    assert lic["filas"] == 1
    assert lic["importe_tipo_desconocido"] == 1
    assert lic["provincia_espana"] == 1
    assert lic["fecha_publicacion_con_hora"] == 1
    sol = solvencia_economica()
    assert (sol["requisitos"], sol["con_umbral"]) == (1, 0)
    (feed,) = ceros_en_hijas()
    assert feed["grupo"] == "placsp"
    assert (feed["adjudicaciones_con_cero"], feed["garantias_con_cero"]) == (1, 1)


def test_la_reingesta_normal_corrige_los_cuatro(tmp_db):
    _sembrar_estado_antiguo()
    _reingerir_con_el_parser_de_hoy()

    lic = licitaciones_placsp()
    assert lic["importe_tipo_desconocido"] == 0
    assert lic["importe_sin_iva"] == 1
    assert lic["con_base_sin_iva"] == 1
    assert lic["provincia_espana"] == 0
    assert lic["fecha_publicacion_con_hora"] == 0
    sol = solvencia_economica()
    assert (sol["con_umbral"], sol["licitaciones_con_umbral"]) == (1, 1)
    (feed,) = ceros_en_hijas()
    assert (feed["adjudicaciones_con_cero"], feed["garantias_con_cero"]) == (0, 0)


def test_desde_separa_lo_que_la_reingesta_no_toco(tmp_db):
    _sembrar_estado_antiguo()

    assert licitaciones_placsp(desde="2999-01-01")["filas"] == 0
    assert licitaciones_placsp(desde="2000-01-01")["filas"] == 1
    assert ceros_en_hijas(desde="2999-01-01") == []

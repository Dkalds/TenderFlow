"""Backfill de ``es_precio``/``peso_precio_pct`` con la regla nueva del precio.

Lo que se fija:

- **Paridad con el parser.** Recalcular desde las filas guardadas da las mismas
  marcas y el mismo peso que ``parse_condiciones``/``parse_peso_precio`` sobre
  el XML del que salieron. Si divergieran, el backfill y la siguiente
  re-ingesta se pisarían el uno al otro.
- **Qué se escribe.** ``--verificar`` no toca nada; un pase real corrige las
  marcas y el peso; el segundo pase no encuentra nada (idempotente).
- **Qué no se escribe.** Un ``peso_precio_pct`` que no es el que derivaban las
  marcas guardadas no salió de esas filas: se queda como está.
"""

from __future__ import annotations

from typing import Any

import pytest

from db.criterios_precio import CriterioGuardado, CriteriosDeLicitacion, recalcular_lote
from db.upsert import CondicionesCodice, CriterioAdjudicacion, Licitacion, upsert_licitaciones
from scraper.codice_parser import parse_condiciones, parse_peso_precio
from scripts.backfill_criterio_precio import main, recalcular
from tests.test_codice_parser_condiciones import (
    _FORMULAS,
    _FORMULAS_SIN_PRECIO,
    _criterio,
    _criterios,
    _entry,
    _lote,
    _terminos,
)

# ─── La regla sobre filas guardadas ──────────────────────────────────────────


def _guardado(
    id_: int,
    descripcion: str,
    peso: float | None,
    *,
    tipo: str | None = None,
    subtipo: str | None = None,
    es_precio: bool = False,
    lote: str | None = None,
    padre: int | None = None,
) -> CriterioGuardado:
    return CriterioGuardado(
        id=id_,
        lote_numero=lote,
        padre_orden=padre,
        peso=peso,
        es_precio=es_precio,
        tipo_codigo=tipo,
        subtipo_codigo=subtipo,
        descripcion=descripcion,
    )


def _fogasa_guardado() -> tuple[CriterioGuardado, ...]:
    """Las filas de 20/2026 tal como las dejó la regla vieja."""
    return (
        _guardado(1, "Memoria técnica", 40, tipo="SUBJ", subtipo="99"),
        _guardado(2, _FORMULAS_SIN_PRECIO, 18, tipo="OBJ", subtipo="2", es_precio=True),
        _guardado(3, _FORMULAS, 42, tipo="OBJ", subtipo="1"),
    )


def test_recalcula_las_marcas_y_el_peso_de_fogasa() -> None:
    lic = CriteriosDeLicitacion("20/2026", 18.0, _fogasa_guardado())

    recalculo = recalcular(lic)

    assert recalculo.es_precio == {1: False, 2: False, 3: True}
    assert (recalculo.peso_antes, recalculo.peso_despues) == (18.0, 42.0)


def test_cada_lote_es_su_ambito_y_el_peso_sale_solo_del_expediente() -> None:
    """El lote 1 usa ``OBJ``/``1``; el expediente no, y ahí manda el texto."""
    lic = CriteriosDeLicitacion(
        "L-1",
        None,
        (
            _guardado(1, "Oferta económica", 70, tipo="OBJ", subtipo="2"),
            _guardado(2, "Plazo de entrega", 30, tipo="OBJ", subtipo="2"),
            _guardado(3, "Precio", 60, tipo="OBJ", subtipo="1", lote="1"),
            _guardado(4, "Precio hora", 40, tipo="OBJ", subtipo="2", lote="1"),
            _guardado(5, "Precio unitario", 100, tipo="OBJ", subtipo="2", padre=1),
        ),
    )

    recalculo = recalcular(lic)

    assert recalculo.es_precio == {1: True, 2: False, 3: True, 4: False, 5: True}
    # El subcriterio (padre 1) no entra en la suma: 70 + 30.
    assert recalculo.peso_despues == 70.0


@pytest.mark.parametrize(
    "terminos",
    [
        pytest.param(
            _terminos(
                _criterios(
                    _criterio("Memoria técnica", "40", tipo="SUBJ", subtipo="99"),
                    _criterio(_FORMULAS_SIN_PRECIO, "18", tipo="OBJ", subtipo="2"),
                    _criterio(_FORMULAS, "42", tipo="OBJ", subtipo="1"),
                )
            ),
            id="fogasa",
        ),
        pytest.param(
            _terminos(
                _criterios(
                    _criterio("Oferta económica", "0.85", tipo="OBJ", subtipo="2"),
                    _criterio("Formación sin coste", "0.15", tipo="OBJ", subtipo="2"),
                )
            ),
            id="todo-obj-2-en-fracciones",
        ),
        pytest.param(
            _terminos(
                _criterios(
                    _criterio(
                        "Oferta económica",
                        "55",
                        hijos=_criterio("Precio hora", "100", tag="SubordinateAwardingCriteria"),
                    ),
                    _criterio("Criterios distintos del precio", "45"),
                )
            ),
            id="sin-codigos-con-subcriterio",
        ),
    ],
)
def test_paridad_con_el_parser(terminos: str) -> None:
    entry = _entry(
        terminos=terminos,
        lotes=_lote("1", _terminos(_criterios(_criterio("Precio", "100", tipo="OBJ")))),
    )
    parseados = parse_condiciones(entry).criterios
    # Las filas, como las guarda el upsert, pero con todas las marcas a False:
    # el recálculo no puede apoyarse en lo que traen.
    guardados = tuple(
        _guardado(
            i,
            c.descripcion or "",
            c.peso,
            tipo=c.tipo_codigo,
            subtipo=c.subtipo_codigo,
            lote=c.lote_numero,
            padre=c.padre_orden,
        )
        for i, c in enumerate(parseados)
    )

    recalculo = recalcular(CriteriosDeLicitacion("P-1", None, guardados))

    assert [recalculo.es_precio[i] for i in range(len(parseados))] == [
        c.es_precio for c in parseados
    ]
    assert recalculo.peso_despues == parse_peso_precio(entry)


# ─── Contra Postgres ─────────────────────────────────────────────────────────


@pytest.fixture()
def db(tmp_db: Any) -> Any:
    db_mod, _ = tmp_db
    return db_mod


def _guardar(id_externo: str, peso_precio_pct: float | None) -> None:
    """La licitación de FOGASA con las marcas viejas (el 18 como precio)."""
    criterios = [
        CriterioAdjudicacion(
            orden=1,
            descripcion="Memoria técnica",
            peso=40.0,
            tipo_codigo="SUBJ",
            subtipo_codigo="99",
        ),
        CriterioAdjudicacion(
            orden=2,
            descripcion=_FORMULAS_SIN_PRECIO,
            peso=18.0,
            es_precio=True,
            tipo_codigo="OBJ",
            subtipo_codigo="2",
        ),
        CriterioAdjudicacion(
            orden=3, descripcion=_FORMULAS, peso=42.0, tipo_codigo="OBJ", subtipo_codigo="1"
        ),
    ]
    upsert_licitaciones(
        [
            Licitacion(
                id_externo=id_externo,
                titulo="Servicio de Oficina de Ciberseguridad",
                organo_contratacion="FOGASA",
                estado="PUB",
                peso_precio_pct=peso_precio_pct,
                condiciones=CondicionesCodice(criterios=criterios),
            )
        ]
    )


def _estado(id_externo: str) -> tuple[float | None, list[bool]]:
    from db.database import connect

    with connect() as c:
        peso = c.execute(
            "SELECT peso_precio_pct FROM licitaciones WHERE id_externo = %s", (id_externo,)
        ).fetchone()[0]
        marcas = [
            bool(fila[0])
            for fila in c.execute(
                "SELECT es_precio FROM licitacion_criterios_adjudicacion "
                "WHERE licitacion_id = %s ORDER BY orden",
                (id_externo,),
            ).fetchall()
        ]
    return peso, marcas


def test_verificar_no_escribe_y_cuenta_lo_que_cambiaria(db: Any) -> None:
    _guardar("20/2026", 18.0)

    lote = recalcular_lote("", 100, recalcular, escribir=False)

    assert (lote.licitaciones, lote.criterios_reescritos, lote.pesos_reescritos) == (1, 2, 1)
    assert _estado("20/2026") == (18.0, [False, True, False])


def test_un_pase_corrige_y_el_segundo_no_encuentra_nada(db: Any) -> None:
    _guardar("20/2026", 18.0)

    assert main(["--pausa", "0"]) == 0
    assert _estado("20/2026") == (42.0, [False, False, True])

    segundo = recalcular_lote("", 100, recalcular, escribir=True)
    assert (segundo.criterios_reescritos, segundo.pesos_reescritos, segundo.cambios) == (0, 0, ())
    assert main(["--verificar", "--pausa", "0"]) == 0


def test_verificar_sale_con_1_si_queda_trabajo(db: Any) -> None:
    _guardar("20/2026", 18.0)

    assert main(["--verificar", "--pausa", "0"]) == 1


def test_un_peso_que_no_salio_de_las_filas_no_se_pisa(db: Any) -> None:
    """La columna dice 50, y las marcas guardadas derivaban 18: no hay base."""
    _guardar("20/2026", 50.0)

    lote = recalcular_lote("", 100, recalcular, escribir=True)

    assert (lote.pesos_reescritos, lote.desalineadas) == (0, 1)
    assert lote.cambios[0].peso == "desalineada"
    assert _estado("20/2026") == (50.0, [False, False, True])


def test_recorre_por_lotes_y_reanuda_desde_la_ultima_clave(db: Any) -> None:
    for id_externo in ("A-1", "B-1", "C-1"):
        _guardar(id_externo, 18.0)

    primero = recalcular_lote("", 2, recalcular, escribir=True)
    segundo = recalcular_lote(primero.hasta or "", 2, recalcular, escribir=True)
    fin = recalcular_lote(segundo.hasta or "", 2, recalcular, escribir=True)

    assert (primero.hasta, primero.licitaciones) == ("B-1", 2)
    assert (segundo.hasta, segundo.licitaciones) == ("C-1", 1)
    assert fin.hasta is None
    assert all(_estado(i)[0] == 42.0 for i in ("A-1", "B-1", "C-1"))

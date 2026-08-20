"""El score de oportunidad ordena en el servidor y coincide con el del cliente.

La tabla de `/renovaciones` pedía 1000 filas ordenadas por `fecha_fin_efectiva`
y las reordenaba en el navegador por score de oportunidad. Con más contratos
que ese tope en la ventana, el "top de oportunidades" que veía el usuario era
el top de las 1000 primeras **por fecha de fin**, no el del dataset: un
contrato enorme y muy arriesgado que vence al final del horizonte se caía de la
lista sin que nada lo indicara. `test_top_por_score_no_es_el_top_por_fecha`
reproduce exactamente eso.

Ahora ordena el SQL (``order_by="score"``). Como la fórmula sigue existiendo
también en TypeScript —el cliente pinta con ella la columna "Oportunidad"—,
hay dos encarnaciones que se pueden separar en silencio. Aquí se fijan las
tres cosas que impiden esa deriva:

1. El port Python (:func:`score_oportunidad`) devuelve lo que devuelve el
   módulo TS caso por caso.
2. El TS sigue diciendo lo mismo (guarda textual sobre el fichero).
3. El SQL que sale de ``order_by="score"`` ordena descendente y liga sus
   parámetros en el orden correcto.

**Lo que estos tests NO comprueban:** la paridad contra datos reales. Eso
exige ejecutar la query contra Postgres y comparar el orden servido con el
orden que produciría el cliente sobre el mismo dataset; no hay Postgres en el
entorno donde se escribieron. Lo que aquí se verifica es la fórmula y la forma
de la sentencia, no su resultado sobre el corpus.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from db.repositories.renovaciones import (
    DIAS_POR_MES,
    proximas_renovaciones,
    score_oportunidad,
    urgencia_oportunidad,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TS_MODULE = _REPO_ROOT / "web" / "src" / "lib" / "opportunity-score.ts"

HORIZONTE = 6 * DIAS_POR_MES  # 180 días, el horizonte por defecto de la vista


# ── 1. Paridad de la fórmula: Python vs TypeScript ────────────────────────
# Cada caso trae el valor que devuelve `opportunityScore()` en
# `web/src/lib/opportunity-score.ts`, calculado a mano desde ese fuente:
#
#     urgency  = clamp(1 - dias / horizonte, 0, 1)
#     score    = riesgo * importe * urgency,  y 0 si falta riesgo o importe.

_CASOS_PARIDAD: list[tuple[str, dict[str, Any], float]] = [
    # Sin riesgo del modelo no se prioriza: 0, por grande que sea el contrato.
    ("sin_riesgo", {"riesgo_cambio": None, "importe": 1_000_000.0, "dias_restantes": 10}, 0.0),
    # Sin importe tampoco.
    ("sin_importe", {"riesgo_cambio": 0.9, "importe": None, "dias_restantes": 10}, 0.0),
    ("importe_cero", {"riesgo_cambio": 0.9, "importe": 0.0, "dias_restantes": 10}, 0.0),
    ("importe_negativo", {"riesgo_cambio": 0.9, "importe": -5.0, "dias_restantes": 10}, 0.0),
    # Sin días no hay urgencia y el producto se anula.
    ("sin_dias", {"riesgo_cambio": 0.9, "importe": 1_000_000.0, "dias_restantes": None}, 0.0),
    # Vence hoy → urgencia 1 → el score es riesgo x importe.
    ("vence_hoy", {"riesgo_cambio": 0.5, "importe": 200_000.0, "dias_restantes": 0}, 100_000.0),
    # Mitad del horizonte → urgencia 0.5.
    ("mitad", {"riesgo_cambio": 0.5, "importe": 200_000.0, "dias_restantes": 90}, 50_000.0),
    # Justo al final del horizonte → urgencia 0.
    ("fin_horizonte", {"riesgo_cambio": 0.5, "importe": 200_000.0, "dias_restantes": 180}, 0.0),
    # Ya vencido: la urgencia satura en 1, no crece por encima.
    ("ya_vencido", {"riesgo_cambio": 0.5, "importe": 200_000.0, "dias_restantes": -10}, 100_000.0),
    # Más allá del horizonte: satura en 0, no se vuelve negativo (invertiría
    # el orden y pondría los contratos lejanos por delante).
    ("mas_alla", {"riesgo_cambio": 0.5, "importe": 200_000.0, "dias_restantes": 400}, 0.0),
    # Riesgo alto y contrato pequeño que vence ya gana a uno enorme y seguro
    # que vence al final: es la razón de ser del score.
    (
        "caliente_pequeno",
        {"riesgo_cambio": 0.9, "importe": 100_000.0, "dias_restantes": 5},
        87_500.0,
    ),
]


@pytest.mark.parametrize(("nombre", "kwargs", "esperado"), _CASOS_PARIDAD, ids=lambda v: v)
def test_score_python_coincide_con_el_de_typescript(
    nombre: str, kwargs: dict[str, Any], esperado: float
) -> None:
    assert score_oportunidad(horizonte_dias=HORIZONTE, **kwargs) == pytest.approx(esperado), nombre


def test_urgencia_con_horizonte_no_positivo() -> None:
    """Rama degenerada del TS: sin horizonte solo urge lo ya vencido.

    El SQL no la traduce porque `months_ahead` está acotado a >= 1, pero el
    port la conserva para que la comparación caso a caso sea completa.
    """
    assert urgencia_oportunidad(0, 0) == 1.0
    assert urgencia_oportunidad(-3, 0) == 1.0
    assert urgencia_oportunidad(5, 0) == 0.0


def test_el_modulo_typescript_sigue_diciendo_lo_mismo() -> None:
    """Guarda textual: si el TS cambia de fórmula, este test lo para.

    La lista de casos de arriba es un espejo escrito a mano de ese fichero.
    Sin esta guarda, editar el TS dejaría la tabla verde y el orden servido
    dejaría de corresponderse con el número pintado.
    """
    fuente = _TS_MODULE.read_text(encoding="utf-8")
    assert "const u = 1 - diasRestantes / horizonteDias;" in fuente
    assert "return Math.min(1, Math.max(0, u));" in fuente
    assert "if (riesgoCambio == null || importe == null || importe <= 0) return 0;" in fuente
    assert (
        "return riesgoCambio * importe * urgency(input.diasRestantes, input.horizonteDias);"
        in fuente
    )


# ── 2. El top por score no es el top por fecha ────────────────────────────

# Cuatro contratos en una ventana de 6 meses. Ordenados por fecha de fin, los
# dos primeros son los dos que menos valen; el contrato que de verdad importa
# (grande, arriesgado) vence el último.
_DATASET = [
    {"id": "PEQUENO-YA", "dias": 5, "importe": 50_000.0, "riesgo": 0.9},
    {"id": "SEGURO-PRONTO", "dias": 20, "importe": 900_000.0, "riesgo": 0.05},
    {"id": "MEDIO", "dias": 100, "importe": 300_000.0, "riesgo": 0.5},
    {"id": "GRANDE-ARRIESGADO", "dias": 150, "importe": 4_000_000.0, "riesgo": 0.8},
]


def _ordenado_por_score(filas: list[dict[str, Any]]) -> list[str]:
    return [
        f["id"]
        for f in sorted(
            filas,
            key=lambda f: (
                -score_oportunidad(
                    riesgo_cambio=f["riesgo"],
                    importe=f["importe"],
                    dias_restantes=f["dias"],
                    horizonte_dias=HORIZONTE,
                ),
                f["dias"],
            ),
        )
    ]


def test_top_por_score_no_es_el_top_por_fecha() -> None:
    por_fecha = [f["id"] for f in sorted(_DATASET, key=lambda f: f["dias"])]
    por_score = _ordenado_por_score(_DATASET)

    assert por_fecha[:2] == ["PEQUENO-YA", "SEGURO-PRONTO"]
    # 4M x 0.8 x urgencia(150/180) = 533.333 domina a todo lo demás aunque sea
    # el último en vencer: truncar por fecha lo dejaba fuera.
    assert por_score[0] == "GRANDE-ARRIESGADO"
    assert por_score[:2] != por_fecha[:2]


# ── 3. Forma de la sentencia que emite `order_by="score"` ─────────────────


class _FakeCursor:
    description = (("licitacion_id",),)

    def fetchall(self) -> list[tuple[Any, ...]]:
        return []


class _FakeConn:
    def __init__(self, sink: list[tuple[str, list[Any]]]) -> None:
        self._sink = sink

    def execute(self, sql: str, params: Any) -> _FakeCursor:
        self._sink.append((sql, list(params)))
        return _FakeCursor()


@pytest.fixture
def sql_capturado(monkeypatch):
    """Captura (sql, params) sin tocar Postgres."""
    sink: list[tuple[str, list[Any]]] = []

    @contextmanager
    def _fake_connect_read():
        yield _FakeConn(sink)

    monkeypatch.setattr(
        "db.repositories.renovaciones.connect_read", _fake_connect_read, raising=True
    )
    return sink


def test_order_by_score_ordena_descendente_en_sql(sql_capturado) -> None:
    proximas_renovaciones(months_ahead=6, order_by="score", limit=200)

    sql, params = sql_capturado[0]
    orden = sql[sql.index("ORDER BY") :]
    assert "pr.riesgo_cambio * a.importe_adjudicado" in orden
    assert ") DESC," in orden
    assert "fecha_fin_efectiva ASC" in orden
    # El horizonte va como parámetro entre los filtros y el LIMIT/OFFSET.
    assert params[-3:] == [6 * DIAS_POR_MES, 200, 0]
    # Alineación placeholder↔parámetro: un `%s` de más o de menos aquí es un
    # error de bind que solo aparecería en producción.
    assert sql.count("%s") == len(params)


def test_order_by_fecha_es_el_orden_por_defecto(sql_capturado) -> None:
    proximas_renovaciones(months_ahead=6)

    sql, params = sql_capturado[0]
    assert sql.rstrip().endswith("ORDER BY fecha_fin_efectiva ASC LIMIT %s OFFSET %s")
    assert "riesgo_cambio * a.importe_adjudicado" not in sql
    assert params == [6, 200, 0]
    assert sql.count("%s") == len(params)


def test_los_filtros_no_desalinean_el_parametro_del_horizonte(sql_capturado) -> None:
    """Con todos los filtros puestos el horizonte sigue ligado donde toca."""
    proximas_renovaciones(
        months_ahead=12,
        empresa_id=7,
        ccaa="Madrid",
        tecnologias=["SAP", "Cloud"],
        min_importe=1000.0,
        order_by="score",
        limit=50,
        offset=100,
    )

    sql, params = sql_capturado[0]
    assert params == [12, 7, "Madrid", "SAP", "Cloud", 1000.0, 12 * DIAS_POR_MES, 50, 100]
    assert sql.count("%s") == len(params)


def test_el_horizonte_del_score_usa_los_meses_ya_acotados(sql_capturado) -> None:
    """`months_ahead` se acota a [1, 60] ANTES de derivar el horizonte.

    Si el clamp se aplicara después, un `months=999` produciría una urgencia
    calculada sobre 29.970 días —todo el mundo con urgencia ~1— mientras el
    `BETWEEN` solo miraría 60 meses.
    """
    proximas_renovaciones(months_ahead=999, order_by="score")

    _, params = sql_capturado[0]
    assert params[0] == 60
    assert params[-3] == 60 * DIAS_POR_MES

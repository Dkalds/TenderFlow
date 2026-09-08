"""Los fixtures del frontend cuadran con el contrato de la API (C8.3).

`tests/test_pursuits_api_contract.py` y `tests/test_contract_dto.py` fijan el
contrato **del lado del backend**. Lo que no había era nada que comprobara que
lo que el frontend *cree* recibir coincide: los tests de `web/src/hooks`
construyen el JSON del `fetch` doblado a mano, y un campo de más —o de menos—
pasa en verde y revienta en producción.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.check_contract_fixtures import (
    operaciones_consumidas_por_hooks,
    operaciones_del_openapi,
    validar,
)

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "web" / "src" / "test" / "fixtures"
MANIFIESTO = FIXTURES / "manifest.json"

#: Piso de cobertura. Es el mismo que aplica CI y **solo sube**: bajarlo es
#: declarar que se acepta más superficie sin verificar.
COBERTURA_MINIMA = 80.0


@pytest.fixture(scope="module")
def openapi() -> dict[str, Any]:
    from api.app import app

    return dict(app.openapi())


@pytest.fixture(scope="module")
def entradas() -> list[dict[str, Any]]:
    datos = json.loads(MANIFIESTO.read_text(encoding="utf-8"))
    return list(datos.get("fixtures", []))


def _esquema(doc: dict[str, Any], entrada: dict[str, Any]) -> dict[str, Any] | None:
    op = (doc.get("paths") or {}).get(entrada["path"], {}).get(entrada["method"].lower())
    if not isinstance(op, dict):
        return None
    estado = str(entrada.get("status", "200"))
    contenido = (op.get("responses") or {}).get(estado, {}).get("content", {})
    json_ = contenido.get("application/json")
    return json_["schema"] if isinstance(json_, dict) and "schema" in json_ else None


def test_manifiesto_existe_y_no_esta_vacio(entradas: list[dict[str, Any]]) -> None:
    assert entradas, "el manifiesto de fixtures no declara ninguna operación"


def test_cada_fixture_declarada_existe(entradas: list[dict[str, Any]]) -> None:
    faltan = [e["fixture"] for e in entradas if not (FIXTURES / e["fixture"]).exists()]
    assert not faltan, f"el manifiesto declara fixtures que no existen: {faltan}"


def test_cada_fixture_cuadra_con_su_operacion(
    entradas: list[dict[str, Any]], openapi: dict[str, Any]
) -> None:
    problemas: list[str] = []
    for entrada in entradas:
        esquema = _esquema(openapi, entrada)
        if esquema is None:
            problemas.append(
                f"{entrada['fixture']}: {entrada['method']} {entrada['path']} "
                f"no existe en el OpenAPI"
            )
            continue
        valor = json.loads((FIXTURES / entrada["fixture"]).read_text(encoding="utf-8"))
        for fallo in validar(valor, esquema, openapi):
            problemas.append(f"{entrada['fixture']}: {fallo}")
    assert not problemas, "fixtures que no cuadran con el contrato:\n" + "\n".join(problemas)


def test_un_campo_inventado_falla(entradas: list[dict[str, Any]], openapi: dict[str, Any]) -> None:
    """El control tiene que rechazar lo que vino a rechazar.

    Sin este test, un validador que devolviera siempre `[]` pasaría todos los
    demás y no protegería nada.
    """
    entrada = next(e for e in entradas if e["fixture"] == "organizations.json")
    esquema = _esquema(openapi, entrada)
    assert esquema is not None

    valor = json.loads((FIXTURES / entrada["fixture"]).read_text(encoding="utf-8"))
    assert isinstance(valor, list) and valor, "la fixture de organizaciones está vacía"
    corrupta = [{**valor[0], "campo_que_la_api_no_manda": "x"}]

    fallos = validar(corrupta, esquema, openapi)
    assert any("campo_que_la_api_no_manda" in f for f in fallos), (
        "el validador acepta un campo que el contrato no declara"
    )


def test_un_campo_requerido_ausente_falla(
    entradas: list[dict[str, Any]], openapi: dict[str, Any]
) -> None:
    entrada = next(e for e in entradas if e["fixture"] == "organizations.json")
    esquema = _esquema(openapi, entrada)
    assert esquema is not None
    valor = json.loads((FIXTURES / entrada["fixture"]).read_text(encoding="utf-8"))
    sin_id = [{k: v for k, v in valor[0].items() if k != "id"}]
    fallos = validar(sin_id, esquema, openapi)
    assert any("id" in f and "requerido" in f for f in fallos), (
        f"el validador no detecta un requerido ausente: {fallos}"
    )


def test_cobertura_de_operaciones_de_hooks(
    entradas: list[dict[str, Any]], openapi: dict[str, Any]
) -> None:
    from scripts.check_contract_fixtures import _normaliza_ruta

    cubiertas = {_normaliza_ruta(e["path"]) for e in entradas}
    consumidas = operaciones_consumidas_por_hooks() & operaciones_del_openapi(openapi)
    assert consumidas, "no se detectó ninguna operación consumida por web/src/hooks"

    cobertura = 100.0 * len(cubiertas & consumidas) / len(consumidas)
    sin_cubrir = sorted(consumidas - cubiertas)
    assert cobertura >= COBERTURA_MINIMA, (
        f"cobertura {cobertura:.0f} % < {COBERTURA_MINIMA:.0f} %. "
        f"Operaciones sin fixture: {sin_cubrir}"
    )

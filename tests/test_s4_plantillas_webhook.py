"""Plantillas de webhook por formato, validadas contra su esquema (S4.3, D13).

Los esquemas viven en ``tests/fixtures/`` porque son el contrato con dos
plataformas externas: si Microsoft cambia la forma de la Adaptive Card o Slack
la de Block Kit, lo que hay que actualizar es el fichero, y el test dice
exactamente qué payload dejó de encajar.

**Por qué un validador propio y no ``jsonschema``.** La librería no está en el
lockfile y añadir una dependencia de producción para dos ficheros de test no
compensa (el lockfile se compila con ``uv --generate-hashes``, así que tocarlo
tiene coste). El validador de aquí abajo cubre exactamente los constructos que
usan los dos esquemas —``type``, ``const``, ``enum``, ``required``,
``properties``, ``items``, ``minItems``/``maxItems``, ``minLength``/
``maxLength`` y ``$ref`` local— y falla ruidosamente ante cualquier otro, así
que no puede dar por bueno un esquema que no entiende.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from shared.events import renderizar

_FIXTURES = Path(__file__).parent / "fixtures"
_TIMESTAMP = "2026-09-06T08:00:00+00:00"

_PAYLOAD = {
    "pursuit_id": 42,
    "licitacion_id": "PLACSP:2026/000123",
    "titulo": "Servicios de mantenimiento SAP",
    "organization_id": 7,
    "responsible_user_id": 3,
    "actor_user_id": 1,
}

_TIPOS_JSON = {
    "string": str,
    "boolean": bool,
    "object": dict,
    "array": list,
    "null": type(None),
}

_CLAVES_SOPORTADAS = {
    "$schema",
    "$ref",
    "title",
    "description",
    "definitions",
    "type",
    "const",
    "enum",
    "required",
    "properties",
    "items",
    "minItems",
    "maxItems",
    "minLength",
    "maxLength",
}


def _tipo_ok(valor: Any, esperado: Any) -> bool:
    nombres = esperado if isinstance(esperado, list) else [esperado]
    for nombre in nombres:
        python = _TIPOS_JSON.get(nombre)
        if python is None:
            raise AssertionError(f"tipo JSON no soportado por este validador: {nombre}")
        # `bool` es subclase de `int` en Python; aquí no hay enteros, pero un
        # `isinstance(True, str)` falso positivo sería peor que este guardia.
        if isinstance(valor, python):
            return True
    return False


def _validar(instancia: Any, esquema: dict[str, Any], raiz: dict[str, Any], ruta: str) -> None:
    desconocidas = set(esquema) - _CLAVES_SOPORTADAS
    assert not desconocidas, f"{ruta}: el validador no entiende {sorted(desconocidas)}"

    if "$ref" in esquema:
        referencia = esquema["$ref"]
        assert referencia.startswith("#/definitions/"), f"{ruta}: $ref externo no soportado"
        destino = raiz["definitions"][referencia.split("/")[-1]]
        _validar(instancia, destino, raiz, ruta)
        return

    if "const" in esquema:
        assert instancia == esquema["const"], f"{ruta}: {instancia!r} != {esquema['const']!r}"
    if "enum" in esquema:
        assert instancia in esquema["enum"], f"{ruta}: {instancia!r} fuera de {esquema['enum']}"
    if "type" in esquema:
        assert _tipo_ok(instancia, esquema["type"]), f"{ruta}: no es {esquema['type']}"
    if isinstance(instancia, str):
        if "minLength" in esquema:
            assert len(instancia) >= esquema["minLength"], f"{ruta}: demasiado corto"
        if "maxLength" in esquema:
            assert len(instancia) <= esquema["maxLength"], f"{ruta}: demasiado largo"
    if isinstance(instancia, dict):
        for obligatoria in esquema.get("required", []):
            assert obligatoria in instancia, f"{ruta}: falta {obligatoria!r}"
        for clave, subesquema in esquema.get("properties", {}).items():
            if clave in instancia:
                _validar(instancia[clave], subesquema, raiz, f"{ruta}.{clave}")
    if isinstance(instancia, list):
        if "minItems" in esquema:
            assert len(instancia) >= esquema["minItems"], f"{ruta}: pocos elementos"
        if "maxItems" in esquema:
            assert len(instancia) <= esquema["maxItems"], f"{ruta}: demasiados elementos"
        if "items" in esquema:
            for i, elemento in enumerate(instancia):
                _validar(elemento, esquema["items"], raiz, f"{ruta}[{i}]")


def _esquema(nombre: str) -> dict[str, Any]:
    datos: dict[str, Any] = json.loads((_FIXTURES / nombre).read_text(encoding="utf-8"))
    return datos


def test_plantilla_teams_valida_contra_adaptive_cards_15():
    esquema = _esquema("adaptive_cards_schema.json")
    cuerpo = renderizar(
        "pursuit.assigned", _PAYLOAD, formato="teams_adaptive_card", timestamp=_TIMESTAMP
    )
    _validar(cuerpo, esquema, esquema, "$")
    tarjeta = cuerpo["attachments"][0]["content"]
    assert tarjeta["version"] == "1.5"


def test_plantilla_slack_valida_contra_block_kit():
    esquema = _esquema("block_kit_schema.json")
    cuerpo = renderizar("pursuit.assigned", _PAYLOAD, formato="slack_blocks", timestamp=_TIMESTAMP)
    _validar(cuerpo, esquema, esquema, "$")


def test_el_header_de_slack_respeta_el_tope_de_150_de_plain_text():
    """Slack rechaza el mensaje si el ``plain_text`` de un header lo supera."""
    payload = {**_PAYLOAD, "titulo": "T" * 400}
    cuerpo = renderizar("pursuit.assigned", payload, formato="slack_blocks", timestamp=_TIMESTAMP)
    cabecera = cuerpo["blocks"][0]
    assert cabecera["type"] == "header"
    assert len(cabecera["text"]["text"]) <= 150


def test_slack_trocea_los_campos_en_secciones_de_diez():
    """Block Kit admite como mucho 10 ``fields`` por ``section``."""
    payload = {f"campo_{i:02d}": f"valor {i}" for i in range(30)}
    cuerpo = renderizar("pursuit.assigned", payload, formato="slack_blocks", timestamp=_TIMESTAMP)
    for bloque in cuerpo["blocks"]:
        assert len(bloque.get("fields", [])) <= 10


@pytest.mark.parametrize("formato", ["json", None, "", "formato_que_no_existe"])
def test_un_evento_sin_plantilla_especifica_cae_a_json(formato):
    """Criterio de S4.3, y además la degradación correcta: un receptor que
    espera el JSON firmado de siempre lo sigue recibiendo."""
    cuerpo = renderizar("pursuit.created", _PAYLOAD, formato=formato, timestamp=_TIMESTAMP)
    assert cuerpo == {"event": "pursuit.created", "data": _PAYLOAD, "timestamp": _TIMESTAMP}


def test_el_formato_json_no_cambia_de_forma():
    """El cuerpo histórico ``{event, data, timestamp}`` es contrato con
    receptores en producción: cambiarlo los rompe sin aviso."""
    cuerpo = renderizar("licitacion.cambiada", {"id_externo": "X"}, formato="json", timestamp="T")
    assert set(cuerpo) == {"event", "data", "timestamp"}


def test_las_plantillas_no_pierden_el_expediente():
    """Un aviso de Slack o Teams sin el expediente no sirve para nada."""
    slack = renderizar("pursuit.assigned", _PAYLOAD, formato="slack_blocks", timestamp=_TIMESTAMP)
    teams = renderizar(
        "pursuit.assigned", _PAYLOAD, formato="teams_adaptive_card", timestamp=_TIMESTAMP
    )
    assert _PAYLOAD["titulo"] in slack["text"]
    assert _PAYLOAD["titulo"] in teams["attachments"][0]["content"]["body"][0]["text"]

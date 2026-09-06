"""O0.6f del plan 2026-09 v2: los modelos NIM de razonamiento reciben `chat_template_kwargs`.

Hecho 22 del plan: los NIM de razonamiento generan una traza ANTES de la
respuesta y esa traza consume el presupuesto de ``max_tokens``. Si se lo come
entero, el stream llega vacío y ``/ask`` degrada con el mismo síntoma que un
proveedor caído. ``chat_template_kwargs`` es lo que suprime la traza, y el
cliente no lo enviaba.

Criterio de aceptación del plan: se envía a los modelos NIM marcados como de
razonamiento **y a ningún otro**. Los tests miran el cuerpo real de la petición
interceptando el SDK, no la intención del código.
"""

from __future__ import annotations

import sys
import types
from typing import Any, ClassVar

import pytest

from llm import client as llm_client
from llm.providers import openai_provider


class _ChunkVacio:
    """Chunk sin choices: el stream termina sin emitir texto.

    Basta para el propósito de estos tests, que miran el CUERPO de la petición
    y no lo que el modelo responde.
    """

    choices: ClassVar[list[Any]] = []
    usage: ClassVar[None] = None


class _CompletionsEspia:
    """Sustituto de ``client.chat.completions`` que guarda los kwargs recibidos."""

    def __init__(self, registro: dict[str, Any]) -> None:
        self._registro = registro

    def create(self, **kwargs: Any) -> list[_ChunkVacio]:
        self._registro.clear()
        self._registro.update(kwargs)
        return [_ChunkVacio()]


class _ClienteEspia:
    def __init__(self, registro: dict[str, Any], **_: Any) -> None:
        self.chat = type("_Chat", (), {"completions": _CompletionsEspia(registro)})()


@pytest.fixture
def cuerpo(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Captura los kwargs con los que se llama a ``chat.completions.create``.

    El SDK de ``openai`` es una dependencia OPCIONAL (extra ``[llm]`` de
    pyproject) y no está instalada en el entorno de tests: el proveedor la
    importa dentro de la función y degrada a NoOp si falta. Por eso aquí se
    inyecta un módulo doble en ``sys.modules`` en vez de parchear el real —
    así el test corre en el bucle rápido con o sin el extra instalado, y sigue
    ejerciendo el código de verdad del proveedor.
    """
    registro: dict[str, Any] = {}

    class _OpenAIFalso:
        def __init__(self, **kwargs: Any) -> None:
            self.chat = _ClienteEspia(registro).chat

    modulo = types.ModuleType("openai")
    modulo.OpenAI = _OpenAIFalso  # type: ignore[attr-defined]  # doble de test
    monkeypatch.setitem(sys.modules, "openai", modulo)
    return registro


def _consumir(model: str, **kwargs: Any) -> None:
    list(
        openai_provider.stream(
            "system",
            [{"role": "user", "content": "hola"}],
            model,
            "clave-de-prueba",
            **kwargs,
        )
    )


@pytest.mark.parametrize("model", sorted(llm_client.REASONING_TEMPLATE_KWARGS))
def test_los_nim_de_razonamiento_envian_chat_template_kwargs(
    cuerpo: dict[str, Any], model: str
) -> None:
    _consumir(model, chat_template_kwargs=llm_client.chat_template_kwargs_for(model))
    assert cuerpo["extra_body"] == {
        "chat_template_kwargs": llm_client.REASONING_TEMPLATE_KWARGS[model]
    }


@pytest.mark.parametrize("model", sorted(llm_client.NON_REASONING_MODELS))
def test_ningun_otro_modelo_lo_envia(cuerpo: dict[str, Any], model: str) -> None:
    """Mandarlo a OpenAI o Anthropic es un 400: la lista tiene que ser estricta."""
    assert llm_client.chat_template_kwargs_for(model) is None
    _consumir(model, chat_template_kwargs=llm_client.chat_template_kwargs_for(model))
    assert "extra_body" not in cuerpo


def test_el_catalogo_no_tiene_modelos_sin_clasificar() -> None:
    """Un modelo nuevo en AVAILABLE_MODELS obliga a decidir si razona o no.

    Sin este test, añadir un NIM de razonamiento al catálogo lo dejaría fuera
    del registro por omisión y el fallo sería un stream vacío intermitente —
    justo el modo de fallo que O0.6f cierra.
    """
    clasificados = set(llm_client.REASONING_TEMPLATE_KWARGS) | set(llm_client.NON_REASONING_MODELS)
    sin_clasificar = set(llm_client.AVAILABLE_MODELS) - clasificados
    assert not sin_clasificar, (
        f"Modelos sin decidir si son de razonamiento: {sorted(sin_clasificar)}. "
        "Añadilos a REASONING_TEMPLATE_KWARGS o a NON_REASONING_MODELS en llm/client.py."
    )


def test_los_dos_conjuntos_no_se_solapan() -> None:
    assert not (set(llm_client.REASONING_TEMPLATE_KWARGS) & llm_client.NON_REASONING_MODELS)


def test_chat_template_kwargs_for_devuelve_una_copia() -> None:
    """Mutar la respuesta no puede contaminar el registro compartido del módulo."""
    model = next(iter(llm_client.REASONING_TEMPLATE_KWARGS))
    devuelto = llm_client.chat_template_kwargs_for(model)
    assert devuelto is not None
    devuelto["thinking"] = "contaminado"
    assert llm_client.REASONING_TEMPLATE_KWARGS[model]["thinking"] is False


def test_modelo_desconocido_no_recibe_nada() -> None:
    assert llm_client.chat_template_kwargs_for("proveedor/modelo-que-no-existe") is None

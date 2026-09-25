"""``scripts/eval_rag_generation.py`` (``make eval-llm``) no toca ninguna base de datos.

El script sembraba el golden set con ``upsert_licitaciones`` en lo que dijera
``DATABASE_URL``. Lanzado desde el checkout principal, cuyo ``.env`` apunta a
producción, escribía allí las licitaciones falsas ``EVAL-0xx``. Ahora emula la
recuperación sobre el propio golden set y arranca con ``DATABASE_URL`` vacía.
Estos tests fijan las dos cosas sin LLM real ni red, y también el recuento de
expedientes citados que el eval hace de cada respuesta.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from typing import Any

import pytest
from pydantic import SecretStr

import scripts.eval_rag_generation as eval_rag

# Sin credenciales: basta una URL no vacía que no resuelva a ningún host.
_URL_PRODUCCION = "postgresql://prod.invalid:5432/tenderflow?sslmode=verify-full"


def test_no_abre_conexiones_aunque_el_entorno_apunte_a_produccion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psycopg

    import db.connection as conexion
    import llm.client
    from config import settings

    # Lo que ve el script lanzado desde el checkout principal: la URL real en
    # el entorno y en `settings`, que la carga del `.env`.
    monkeypatch.setenv("DATABASE_URL", _URL_PRODUCCION)
    monkeypatch.setattr(settings, "DATABASE_URL", SecretStr(_URL_PRODUCCION))
    # `main()` añade la raíz del repo a `sys.path`; que no se quede puesta.
    monkeypatch.setattr(sys, "path", [*sys.path])

    intentos: list[str] = []

    def _conexion_prohibida(*_args: Any, **_kwargs: Any) -> Any:
        intentos.append("conexión")
        raise AssertionError("el eval intentó abrir una conexión a la BD")

    # `_get_conn` es el embudo de `connect()` y `connect_read()`, y por tanto
    # de `upsert_licitaciones`; `psycopg.connect`, el de una conexión cruda.
    monkeypatch.setattr(conexion, "_get_conn", _conexion_prohibida)
    monkeypatch.setattr(psycopg, "connect", _conexion_prohibida)

    llamadas: list[tuple[list[str], str]] = []

    def _llm_falso(
        question: str, docs: list[dict[str, Any]], model: str, keywords: list[str], **_: Any
    ) -> Iterator[str]:
        llamadas.append(([d["id_externo"] for d in docs], conexion._database_url()))
        yield "respuesta simulada"

    monkeypatch.setattr(llm.client, "stream_llm_response", _llm_falso)

    golden = eval_rag._load_golden_set()
    assert eval_rag.main(["--limit", str(len(golden))]) == 0

    assert intentos == []
    assert len(llamadas) == len(golden)
    # La URL de producción ya no llega a ninguna pregunta: el script vació el
    # entorno y `settings` antes de la primera.
    assert {url for _, url in llamadas} == {""}


def test_la_recuperacion_emulada_mete_la_licitacion_esperada_en_el_contexto() -> None:
    """Sin la licitación correcta en el contexto, la respuesta no mide al modelo."""
    golden = eval_rag._load_golden_set()
    corpus = eval_rag._corpus(golden)

    for entry in golden:
        docs = eval_rag._recuperar(entry["question"], corpus, eval_rag._TOP_K)
        ids = [d["id_externo"] for d in docs]
        assert len(ids) <= eval_rag._TOP_K
        assert set(entry["expected_ids"]) & set(ids), f"{entry['question']!r} -> {ids}"


def test_citas_de_expediente_separa_las_del_contexto_de_las_ajenas() -> None:
    docs = [{"id_externo": "EVAL-001"}, {"id_externo": "EVAL-008"}]
    texto = (
        "El Ayuntamiento licita [EVAL-001] ([doc:3 p.2]). EVAL-008 va sin corchetes, "
        "y [EXP-2024-001] y [EVAL-020] no estaban en el contexto. [Nota] y [1] no son ids."
    )

    citados, ajenos = eval_rag._citas_de_expediente(texto, docs)

    # Sin corchetes no hay cita; el marcador de pliego, `[Nota]` y `[1]` no son ids.
    assert citados == {"EVAL-001"}
    assert ajenos == ["EVAL-020", "EXP-2024-001"]


def test_el_resumen_cuenta_el_expediente_esperado_los_ajenos_vacias_y_errores(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import llm.client

    # `main()` vacía `DATABASE_URL` y añade la raíz a `sys.path`: que no salga del test.
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setattr(sys, "path", [*sys.path])

    # Una respuesta por pregunta del golden set, en orden: EVAL-001, 002, 003 y 004.
    respuestas: Iterator[str | Exception] = iter(
        [
            "El proyecto Fénix es [EVAL-001], del Ayuntamiento de Zaragoza.",
            "",
            "Puede ser [EVAL-020] o [EXP-2024-001].",
            RuntimeError("503 Service temporarily overloaded"),
        ]
    )

    def _llm_falso(
        question: str, docs: list[dict[str, Any]], model: str, keywords: list[str], **_: Any
    ) -> Iterator[str]:
        respuesta = next(respuestas)
        if isinstance(respuesta, Exception):
            raise respuesta
        if respuesta:
            yield respuesta

    monkeypatch.setattr(llm.client, "stream_llm_response", _llm_falso)

    assert eval_rag.main(["--limit", "4"]) == 0

    assert (
        "Expedientes: el esperado se cita en 1/4 preguntas; 2 id/s ajeno/s al contexto; "
        "1 respuesta/s vacía/s; 1 pregunta/s con error."
    ) in capsys.readouterr().out

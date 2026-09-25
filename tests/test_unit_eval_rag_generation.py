"""``scripts/eval_rag_generation.py`` (``make eval-llm``) no toca ninguna base de datos.

El script sembraba el golden set con ``upsert_licitaciones`` en lo que dijera
``DATABASE_URL``. Lanzado desde el checkout principal, cuyo ``.env`` apunta a
producción, escribía allí las licitaciones falsas ``EVAL-0xx``. Ahora emula la
recuperación sobre el propio golden set y arranca con ``DATABASE_URL`` vacía.
Estos tests fijan las dos cosas sin LLM real ni red.
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

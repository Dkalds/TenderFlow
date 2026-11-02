"""El handler de embeddings por expediente no trocea ni embebe las actas.

Spec de las puntuaciones del acta, §3.3: el acta de la mesa no es pliego y no
entra en chunks ni embeddings. Sin BD: el repositorio y el motor de embeddings
van parchados.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from db.repositories.documentos import TIPO_ACTA
from scheduler.worker import ejecutar_embeddings_expediente


def _ejecutar(filas: list[dict[str, Any]]) -> tuple[dict[str, object], MagicMock]:
    repo = MagicMock()
    repo.list_by_licitacion.return_value = filas
    repo.count_chunks.return_value = 0
    repo.get.side_effect = lambda documento_id: {"texto": f"texto {documento_id}"}
    repo.replace_chunks.side_effect = lambda _documento_id, trozos, _embeddings: len(trozos)
    job = MagicMock()
    job.payload = {"licitacion_id": "EXP-1"}
    with (
        patch("db.repositories.documentos.DocumentosRepository", return_value=repo),
        patch("services.embeddings.embeddings_masivos_disponibles", return_value=True),
        patch("services.embeddings.encode_texts", return_value=[[0.1]]),
        patch("services.rag.chunking.chunk_text", return_value=["trozo"]),
    ):
        resultado = ejecutar_embeddings_expediente(job)
    return dict(resultado), repo


def test_el_handler_de_embeddings_no_trocea_actas():
    resultado, repo = _ejecutar(
        [
            {"id": 1, "tipo": "legal", "status": "extracted"},
            {"id": 2, "tipo": TIPO_ACTA, "status": "extracted"},
            {"id": 3, "tipo": "technical", "status": "extracted"},
        ]
    )

    assert [llamada.args[0] for llamada in repo.replace_chunks.call_args_list] == [1, 3]
    assert resultado == {"licitacion_id": "EXP-1", "documentos": 2, "chunks": 2}


def test_el_handler_de_embeddings_con_solo_actas_no_hace_nada():
    resultado, repo = _ejecutar([{"id": 2, "tipo": TIPO_ACTA, "status": "extracted"}])

    repo.replace_chunks.assert_not_called()
    assert resultado == {"licitacion_id": "EXP-1", "documentos": 0, "chunks": 0}

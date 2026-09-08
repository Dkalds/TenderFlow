"""El informe de embeddings y el mapa de páginas, en sus ramas degradadas (C5.7).

Las dos existen por el mismo motivo —que una migración a medias no tumbe lo que
ya funciona— y las dos son invisibles mientras todo va bien:

- sin `v120` aplicada, `chunks_por_version` no existe y el informe **no** puede
  caerse: el reparto por versión es informativo;
- un fallo leyendo las páginas de un documento no puede tumbar su embedding: sin
  páginas los chunks se guardan igual y la cita apunta al documento en vez de a
  la página, que es peor pero no es perder el documento.
"""

from __future__ import annotations

from typing import Any

import pytest


class _RepoDoble:
    def __init__(
        self,
        *,
        paginas: Any = None,
        por_version: Any = None,
    ) -> None:
        self._paginas = paginas if paginas is not None else []
        self._por_version = por_version if por_version is not None else []

    def list_pages(self, documento_id: int) -> Any:
        if isinstance(self._paginas, Exception):
            raise self._paginas
        return self._paginas

    def chunks_por_version(self) -> Any:
        if isinstance(self._por_version, Exception):
            raise self._por_version
        return self._por_version

    def status_counts(self) -> dict[str, int]:
        return {"total": 0}

    def formato_counts(self) -> list[dict[str, Any]]:
        return []


class TestMapaDePaginas:
    def test_las_paginas_se_ordenan_como_offsets(self) -> None:
        from scheduler.jobs.documentos_embeddings import _paginas_del_documento

        repo = _RepoDoble(
            paginas=[
                {"start_offset": 0, "page_number": 1},
                {"start_offset": 1800, "page_number": 2},
            ]
        )
        assert _paginas_del_documento(repo, 7) == [(0, 1), (1800, 2)]

    def test_un_offset_ausente_cuenta_como_cero(self) -> None:
        """Un documento de una sola página no tiene por qué declararlo."""
        from scheduler.jobs.documentos_embeddings import _paginas_del_documento

        repo = _RepoDoble(paginas=[{"start_offset": None, "page_number": 1}])
        assert _paginas_del_documento(repo, 7) == [(0, 1)]

    def test_un_fallo_leyendo_paginas_no_tumba_el_embedding(self) -> None:
        """Sin páginas la cita apunta al documento; sin chunks no hay cita."""
        from scheduler.jobs.documentos_embeddings import _paginas_del_documento

        repo = _RepoDoble(paginas=RuntimeError("columna page_number no existe"))
        assert _paginas_del_documento(repo, 7) == []


class TestInformeDeVersiones:
    def _montar(self, monkeypatch: pytest.MonkeyPatch, repo: _RepoDoble) -> None:
        import db.repositories.documentos as repo_mod
        import shared.object_store as store

        monkeypatch.setattr(repo_mod, "DocumentosRepository", lambda: repo)
        monkeypatch.setattr(store, "store_stats", lambda: None)

    def test_sin_la_columna_de_version_el_informe_no_se_cae(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`v120` sin aplicar es un entorno legítimo, no un error del informe."""
        from scheduler.jobs.documentos_embeddings import report_cli

        self._montar(
            monkeypatch,
            _RepoDoble(por_version=RuntimeError('column "version" does not exist')),
        )
        assert report_cli() == 0

    def test_los_pendientes_son_los_que_no_están_en_la_versión_vigente(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Durante una migración de modelo es la única forma de saber cuánto
        queda: sin ella el re-embedding es un job sin progreso observable."""
        from config.settings import settings
        from scheduler.jobs.documentos_embeddings import report_cli

        vigente = settings.EMBEDDING_VERSION
        registrado: list[dict[str, Any]] = []

        self._montar(
            monkeypatch,
            _RepoDoble(
                por_version=[
                    {"version": vigente, "n": 900},
                    {"version": "modelo-anterior", "n": 100},
                ]
            ),
        )

        import scheduler.jobs.documentos_embeddings as mod

        monkeypatch.setattr(
            mod.log, "info", lambda evento, **kw: registrado.append({"evento": evento, **kw})
        )

        assert report_cli() == 0
        reparto = next(r for r in registrado if r["evento"] == "documentos_chunks_por_version")
        assert reparto["pendientes"] == 100
        assert reparto["vigente"] == vigente

"""``scripts/backfill_documentos_pscp``: cuenta sin pedir nada y barre el atraso sin ventana."""

from __future__ import annotations

from typing import Any

import pytest

import scripts.backfill_documentos_pscp as backfill
from scraper.documentos_plataforma import ResumenDocumentos


class _Repo:
    def __init__(self) -> None:
        self.ventanas: list[int | None] = []

    def pscp_para_documentos(
        self, limit: int = 200, *, dias_cambio: int | None = 7
    ) -> list[dict[str, Any]]:
        self.ventanas.append(dias_cambio)
        return [{"id_externo": "pscp:a", "url": None}, {"id_externo": "pscp:b", "url": None}]


@pytest.fixture()
def repo(monkeypatch) -> _Repo:
    falso = _Repo()
    monkeypatch.setattr(backfill, "DocumentosRepository", lambda: falso)
    return falso


def test_sin_aplicar_solo_cuenta(repo, monkeypatch, capsys):
    def completar(**kw: Any) -> ResumenDocumentos:
        raise AssertionError("sin --aplicar no se pide ninguna ficha")

    monkeypatch.setattr(backfill, "completar_documentos_pscp", completar)

    assert backfill.main([]) == 0
    assert "cuya ficha toca leer: 2" in capsys.readouterr().out
    assert repo.ventanas == [None]


def test_aplicar_barre_el_atraso_entero_sin_ventana(repo, monkeypatch):
    recibido: dict[str, Any] = {}

    def completar(**kw: Any) -> ResumenDocumentos:
        recibido.update(kw)
        return ResumenDocumentos()

    monkeypatch.setattr(backfill, "completar_documentos_pscp", completar)

    assert backfill.main(["--aplicar", "--presupuesto", "60"]) == 0
    assert recibido["dias_cambio"] is None
    assert recibido["presupuesto_s"] == 60
    assert recibido["limite"] > 19_291  # el atraso medido el 2026-11-09 cabe en una lista

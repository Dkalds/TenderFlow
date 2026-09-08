"""Predecesor y similares: la búsqueda, ejecutada (C1.3).

`test_similares.py` cubre las piezas puras —`_cpv4`, `_baja`, `_solape`— y deja
sin ejecutar `buscar()`, `_ordenar()` y `_a_candidato()`, que son las que
deciden lo que ve el usuario. Es la parte que el propio módulo señala como la
que no se puede equivocar: decirle a alguien que el incumbente es X cuando no lo
es le hace preparar la oferta contra un competidor imaginario.

Lo que se fija aquí es el listón —un predecesor por debajo del umbral **no** se
propone—, que el método viaje siempre en la respuesta, y que un fallo del modelo
degrade a términos en vez de vaciar la ficha.
"""

from __future__ import annotations

from typing import Any

import pytest

_OBJETIVO = {
    "id_externo": "EXP-2026-100",
    "titulo": "Servicio de mantenimiento de sistemas informáticos municipales",
    "descripcion": "Mantenimiento evolutivo y correctivo",
    "cpv": "72500000",
    "organo_id": 5,
    "organo_contratacion": "Ayuntamiento de León",
    "fecha_publicacion": "2026-01-15",
}


class _RepoDoble:
    def __init__(
        self,
        *,
        objetivo: dict[str, Any] | None = None,
        previos: list[dict[str, Any]] | None = None,
        otros: list[dict[str, Any]] | None = None,
    ) -> None:
        self._objetivo = objetivo
        self._previos = previos or []
        self._otros = otros or []
        self.pedidos: list[dict[str, Any]] = []

    def objetivo(self, id_externo: str) -> dict[str, Any] | None:
        return self._objetivo

    def candidatos_a_predecesor(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.pedidos.append({"tipo": "predecesor", **kwargs})
        return self._previos

    def candidatos_a_similar(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.pedidos.append({"tipo": "similar", **kwargs})
        return self._otros


def _fila(id_externo: str, titulo: str, **extra: Any) -> dict[str, Any]:
    return {"id_externo": id_externo, "titulo": titulo, **extra}


@pytest.fixture
def mod(monkeypatch: pytest.MonkeyPatch):
    """El módulo con los embeddings apagados: el camino por defecto en CI."""
    import services.similares as modulo

    monkeypatch.setattr(modulo, "embeddings_available", lambda: False)
    return modulo


class TestSinExpediente:
    def test_un_expediente_que_no_existe_devuelve_nada(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(mod, "repo", _RepoDoble(objetivo=None))

        assert mod.buscar("NO-EXISTE") is None


class TestMetodoDeclarado:
    def test_sin_embeddings_el_metodo_es_fts(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Una lista ordenada por un criterio que el consumidor no conoce no se
        puede interpretar: por eso el método viaja siempre."""
        monkeypatch.setattr(mod, "repo", _RepoDoble(objetivo=_OBJETIVO))

        assert mod.buscar("EXP-2026-100").metodo == "fts"

    def test_con_embeddings_el_metodo_es_embedding(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.similares as mod

        monkeypatch.setattr(mod, "embeddings_available", lambda: True)
        monkeypatch.setattr(mod, "semantic_match", lambda texto, corpus, threshold=0.0: [(0, 0.9)])
        monkeypatch.setattr(
            mod,
            "repo",
            _RepoDoble(
                objetivo=_OBJETIVO,
                otros=[_fila("EXP-2025-001", "Mantenimiento de sistemas informáticos")],
            ),
        )

        resultado = mod.buscar("EXP-2026-100")
        assert resultado.metodo == "embedding"
        assert [c.id_externo for c in resultado.similares] == ["EXP-2025-001"]

    def test_un_fallo_del_modelo_degrada_a_terminos_y_no_vacia_la_ficha(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sin el fallback, un fallo del modelo dejaría la ficha sin similares."""
        import services.similares as mod

        def _explota(texto: str, corpus: list[str], threshold: float = 0.0) -> Any:
            raise RuntimeError("modelo no cargado")

        monkeypatch.setattr(mod, "embeddings_available", lambda: True)
        monkeypatch.setattr(mod, "semantic_match", _explota)
        monkeypatch.setattr(
            mod,
            "repo",
            _RepoDoble(
                objetivo=_OBJETIVO,
                otros=[_fila("EXP-2025-001", "Mantenimiento de sistemas informáticos")],
            ),
        )

        resultado = mod.buscar("EXP-2026-100")
        assert resultado.metodo == "fts"
        assert len(resultado.similares) == 1

    def test_sin_candidatos_el_metodo_se_declara_igualmente(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(mod, "repo", _RepoDoble(objetivo=_OBJETIVO))

        resultado = mod.buscar("EXP-2026-100")
        assert resultado.similares == []
        assert resultado.metodo == "fts"
        assert resultado.n == 0


class TestPredecesor:
    def test_un_parecido_suficiente_se_propone_con_su_baja(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        previo = _fila(
            "EXP-2022-007",
            "Servicio de mantenimiento de sistemas informáticos municipales",
            importe_base_sin_iva=100_000.0,
            importe_adjudicado=80_000.0,
            adjudicatario="Integradora S.A.",
            fecha_adjudicacion="2022-06-01",
        )
        monkeypatch.setattr(mod, "repo", _RepoDoble(objetivo=_OBJETIVO, previos=[previo]))

        predecesor = mod.buscar("EXP-2026-100").predecesor
        assert predecesor is not None
        assert predecesor.adjudicatario == "Integradora S.A."
        assert predecesor.baja_pct == 20.0

    def test_por_debajo_del_umbral_no_se_afirma_un_incumbente(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Es la afirmación fuerte del módulo: sin evidencia, no se hace."""
        previo = _fila("EXP-2022-007", "Obras de pavimentación del casco antiguo")
        monkeypatch.setattr(mod, "repo", _RepoDoble(objetivo=_OBJETIVO, previos=[previo]))

        assert mod.buscar("EXP-2026-100").predecesor is None

    def test_el_predecesor_se_pide_acotado_al_organo_y_al_cpv4(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _RepoDoble(objetivo=_OBJETIVO)
        monkeypatch.setattr(mod, "repo", repo)

        mod.buscar("EXP-2026-100")
        pedido = next(p for p in repo.pedidos if p["tipo"] == "predecesor")
        assert pedido["organo_id"] == 5
        assert pedido["cpv4"] == "7250"
        assert pedido["antes_de"] == "2026-01-15"

    def test_los_similares_no_se_acotan_al_organo(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """«Qué más se compra parecido» es de cualquier órgano."""
        repo = _RepoDoble(objetivo=_OBJETIVO)
        monkeypatch.setattr(mod, "repo", repo)

        mod.buscar("EXP-2026-100")
        pedido = next(p for p in repo.pedidos if p["tipo"] == "similar")
        assert "organo_id" not in pedido


class TestFormaDeSalida:
    def test_el_tope_de_similares_se_respeta_y_n_cuenta_todo_lo_mirado(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        otros = [
            _fila(f"EXP-2025-{i:03d}", "Mantenimiento de sistemas informáticos municipales")
            for i in range(5)
        ]
        monkeypatch.setattr(
            mod, "repo", _RepoDoble(objetivo=_OBJETIVO, previos=otros[:2], otros=otros)
        )

        resultado = mod.buscar("EXP-2026-100", max_similares=2)
        assert len(resultado.similares) == 2
        assert resultado.n == 7

    def test_el_similar_no_lleva_datos_de_adjudicacion(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Solo el predecesor afirma quién ganó; un similar no."""
        fila = _fila(
            "EXP-2025-001",
            "Servicio de mantenimiento de sistemas informáticos municipales",
            importe_base_sin_iva=50_000.0,
            importe_adjudicado=40_000.0,
            adjudicatario="Otra S.L.",
            fecha_adjudicacion="2025-02-02",
        )
        monkeypatch.setattr(mod, "repo", _RepoDoble(objetivo=_OBJETIVO, otros=[fila]))

        similar = mod.buscar("EXP-2026-100").similares[0]
        assert similar.adjudicatario is None
        assert similar.importe_adjudicado is None
        assert similar.baja_pct is None
        assert similar.importe == 50_000.0

    def test_sin_base_declarada_cae_al_importe_historico(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fila = _fila(
            "EXP-2025-001",
            "Servicio de mantenimiento de sistemas informáticos municipales",
            importe=30_000.0,
        )
        monkeypatch.setattr(mod, "repo", _RepoDoble(objetivo=_OBJETIVO, otros=[fila]))

        assert mod.buscar("EXP-2026-100").similares[0].importe == 30_000.0

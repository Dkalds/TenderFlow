"""Pre-generación nocturna del resumen IA (P3 «Pre-generar el resumen IA»).

Tres cosas que tienen que ser verdad para que la fase sirva de algo:

1. Escribe **la misma clave** que la ruta leerá: si divergieran, el job pagaría
   resúmenes que nadie encuentra.
2. No paga lo que ya está: entrada vigente → cero llamadas al LLM.
3. Respeta el presupuesto y la credencial: el BudgetGuard corta el lote, un 401
   también, y sin caché compartida no se gasta nada.

Todo con dobles: sin BD, sin proveedor y sin Redis.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from config import settings
from scheduler.jobs import documentos_embeddings as job
from services.rag import resumen as svc


class _CacheFalsa:
    def __init__(self, inicial: dict[str, Any] | None = None) -> None:
        self.datos: dict[str, Any] = dict(inicial or {})
        self.ttls: dict[str, float] = {}

    def get(self, key: str) -> Any | None:
        return self.datos.get(key)

    def set(self, key: str, value: Any, ttl: float = 60.0) -> None:
        self.datos[key] = value
        self.ttls[key] = ttl


_DOC = {"id_externo": "EXP-1", "titulo": "SAP S/4", "importe": 100.0, "chunks": []}
_DOCUMENTOS = [{"id": 7, "status": "extracted", "created_at": "2026-09-01"}]


def _contexto() -> tuple[dict[str, Any], dict[str, Any], str | None]:
    ctx = {"documentos": _DOCUMENTOS, "has_pliego_text": True, "truncated": False}
    return ctx, dict(_DOC), "2026-09-10T00:00:00"


@pytest.fixture()
def cache(monkeypatch: pytest.MonkeyPatch) -> _CacheFalsa:
    falsa = _CacheFalsa()
    monkeypatch.setattr("shared.cache.get_cache", lambda _ns="default": falsa)
    return falsa


@pytest.fixture()
def llamadas_llm(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    llamadas: list[dict[str, Any]] = []

    def _stream(**kwargs: Any) -> Iterator[str]:
        llamadas.append(kwargs)
        yield "Resumen "
        yield "generado"

    monkeypatch.setattr("llm.client.stream_llm_response", _stream)
    return llamadas


def _clave_de_la_ruta() -> str:
    """La clave exacta que calcula `POST /licitaciones/{id}/resumen`."""
    ctx, doc, ficha_at = _contexto()
    return svc.resumen_cache_key("EXP-1", "modelo-x", doc, ctx["documentos"], ficha_at)


# ── pregenerar_resumen ─────────────────────────────────────────────────────


class TestPregenerarResumen:
    def test_escribe_la_clave_que_la_ruta_lee(
        self, monkeypatch: pytest.MonkeyPatch, cache: _CacheFalsa, llamadas_llm: list[Any]
    ) -> None:
        monkeypatch.setattr(svc, "cargar_contexto_resumen", lambda _id: _contexto())

        assert svc.pregenerar_resumen("EXP-1", model="modelo-x") == "generado"

        assert cache.datos == {_clave_de_la_ruta(): "Resumen generado"}
        assert cache.ttls[_clave_de_la_ruta()] == svc.RESUMEN_CACHE_TTL_SECONDS
        (llamada,) = llamadas_llm
        assert llamada["mode"] == "resumen"
        assert llamada["question"] == svc.RESUMEN_QUESTION
        assert llamada["max_tokens"] == svc.RESUMEN_MAX_TOKENS
        assert llamada["model"] == "modelo-x"

    def test_entrada_vigente_no_llama_al_llm(
        self, monkeypatch: pytest.MonkeyPatch, cache: _CacheFalsa, llamadas_llm: list[Any]
    ) -> None:
        monkeypatch.setattr(svc, "cargar_contexto_resumen", lambda _id: _contexto())
        cache.datos[_clave_de_la_ruta()] = "ya estaba"

        assert svc.pregenerar_resumen("EXP-1", model="modelo-x") == "vigente"
        assert llamadas_llm == []
        assert cache.datos[_clave_de_la_ruta()] == "ya estaba"

    def test_otro_modelo_es_otra_clave(
        self, monkeypatch: pytest.MonkeyPatch, cache: _CacheFalsa, llamadas_llm: list[Any]
    ) -> None:
        """El modelo es parte de la clave: pre-generar con otro no calienta nada."""
        monkeypatch.setattr(svc, "cargar_contexto_resumen", lambda _id: _contexto())
        cache.datos[_clave_de_la_ruta()] = "del modelo x"

        assert svc.pregenerar_resumen("EXP-1", model="modelo-y") == "generado"
        assert len(llamadas_llm) == 1

    def test_licitacion_inexistente(
        self, monkeypatch: pytest.MonkeyPatch, cache: _CacheFalsa
    ) -> None:
        monkeypatch.setattr(svc, "cargar_contexto_resumen", lambda _id: None)
        assert svc.pregenerar_resumen("NO-EXISTE", model="m") == "no_encontrada"
        assert cache.datos == {}

    def test_respuesta_vacia_no_se_cachea(
        self, monkeypatch: pytest.MonkeyPatch, cache: _CacheFalsa
    ) -> None:
        monkeypatch.setattr(svc, "cargar_contexto_resumen", lambda _id: _contexto())
        monkeypatch.setattr("llm.client.stream_llm_response", lambda **_kw: iter(["  "]))
        assert svc.pregenerar_resumen("EXP-1", model="m") == "vacio"
        assert cache.datos == {}


# ── Fase del job ───────────────────────────────────────────────────────────


class _GuardFalso:
    def __init__(self, agotar_tras: int | None = None) -> None:
        self.checks = 0
        self.agotar_tras = agotar_tras

    def check(self, *_a: Any, **_kw: Any) -> None:
        from llm.budget import LLMBudgetExceeded

        if self.agotar_tras is not None and self.checks >= self.agotar_tras:
            raise LLMBudgetExceeded("daily", spent=5.0, limit=5.0)
        self.checks += 1


@pytest.fixture()
def fase(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Fase habilitada, con caché compartida y candidatas fijas."""
    monkeypatch.setattr(settings, "RESUMEN_PREGEN_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RESUMEN_PREGEN_MODEL", "modelo-x", raising=False)
    monkeypatch.setattr("shared.cache.es_compartida", lambda _b: True)
    monkeypatch.setattr("shared.cache.get_cache", lambda _ns="default": _CacheFalsa())
    monkeypatch.setattr(job, "_candidatas_resumen", lambda _limit: ["A", "B", "C"])
    guard = _GuardFalso()
    monkeypatch.setattr("llm.budget.get_budget_guard", lambda: guard)
    return {"guard": guard}


class TestFaseResumenPregen:
    def test_apagada_por_defecto(self) -> None:
        assert settings.RESUMEN_PREGEN_ENABLED is False
        assert job._run_resumen_pregen_phase()["disabled"] == 1

    def test_sin_cache_compartida_no_gasta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "RESUMEN_PREGEN_ENABLED", True, raising=False)
        monkeypatch.setattr("shared.cache.es_compartida", lambda _b: False)
        llamado = []
        monkeypatch.setattr(
            "services.rag.resumen.pregenerar_resumen", lambda *a, **k: llamado.append(a)
        )

        counts = job._run_resumen_pregen_phase()

        assert counts["sin_cache_compartida"] == 1
        assert llamado == []

    def test_cuenta_cada_resultado(
        self, monkeypatch: pytest.MonkeyPatch, fase: dict[str, Any]
    ) -> None:
        resultados = {"A": "generado", "B": "vigente", "C": "vacio"}
        modelos: list[str] = []

        def _pregenerar(id_externo: str, *, model: str) -> str:
            modelos.append(model)
            return resultados[id_externo]

        monkeypatch.setattr("services.rag.resumen.pregenerar_resumen", _pregenerar)

        counts = job._run_resumen_pregen_phase(limit=3)

        assert (counts["generados"], counts["vigentes"], counts["vacios"]) == (1, 1, 1)
        assert counts["candidatas"] == 3
        assert modelos == ["modelo-x"] * 3
        assert fase["guard"].checks == 3

    def test_presupuesto_agotado_corta_el_lote(
        self, monkeypatch: pytest.MonkeyPatch, fase: dict[str, Any]
    ) -> None:
        fase["guard"].agotar_tras = 1
        hechos: list[str] = []
        monkeypatch.setattr(
            "services.rag.resumen.pregenerar_resumen",
            lambda id_externo, *, model: hechos.append(id_externo) or "generado",
        )

        counts = job._run_resumen_pregen_phase()

        assert hechos == ["A"]
        assert counts["presupuesto_agotado"]

    def test_credencial_rechazada_corta_el_lote(
        self, monkeypatch: pytest.MonkeyPatch, fase: dict[str, Any]
    ) -> None:
        from llm.providers import LLMAuthError

        intentos: list[str] = []

        def _pregenerar(id_externo: str, *, model: str) -> str:
            intentos.append(id_externo)
            raise LLMAuthError(model=model, status_code=401)

        monkeypatch.setattr("services.rag.resumen.pregenerar_resumen", _pregenerar)

        counts = job._run_resumen_pregen_phase()

        assert intentos == ["A"]
        assert counts["error"] == 1
        assert "401" in counts["credencial_rechazada"]

    def test_modelo_retirado_corta_el_lote(
        self, monkeypatch: pytest.MonkeyPatch, fase: dict[str, Any]
    ) -> None:
        from llm.providers import LLMModelUnavailableError

        intentos: list[str] = []

        def _pregenerar(id_externo: str, *, model: str) -> str:
            intentos.append(id_externo)
            raise LLMModelUnavailableError(model=model, status_code=410)

        monkeypatch.setattr("services.rag.resumen.pregenerar_resumen", _pregenerar)

        counts = job._run_resumen_pregen_phase()

        assert intentos == ["A"]
        assert counts["error"] == 1
        assert "410" in counts["modelo_no_disponible"]

    def test_un_fallo_suelto_no_para_el_resto(
        self, monkeypatch: pytest.MonkeyPatch, fase: dict[str, Any]
    ) -> None:
        def _pregenerar(id_externo: str, *, model: str) -> str:
            if id_externo == "A":
                raise RuntimeError("contexto roto")
            return "generado"

        monkeypatch.setattr("services.rag.resumen.pregenerar_resumen", _pregenerar)

        counts = job._run_resumen_pregen_phase()

        assert (counts["error"], counts["generados"]) == (1, 2)


class TestCandidatas:
    def test_orden_de_prioridad_sin_repetidas(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "db.resumen_pregen.licitaciones_seguidas_abiertas", lambda _l: ["S1", "S2"]
        )
        monkeypatch.setattr(job, "_ids_banda_caliente", lambda _l: ["S2", "C1"])
        monkeypatch.setattr(
            "db.resumen_pregen.licitaciones_publicadas_desde", lambda _d, _l: ["H1", "C1"]
        )

        assert job._candidatas_resumen(10) == ["S1", "S2", "C1", "H1"]
        assert job._candidatas_resumen(3) == ["S1", "S2", "C1"]

    def test_una_fuente_caida_no_tumba_las_demas(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _scoring_roto(_l: int) -> list[str]:
            raise RuntimeError("scoring caído")

        monkeypatch.setattr("db.resumen_pregen.licitaciones_seguidas_abiertas", lambda _l: ["S1"])
        monkeypatch.setattr(job, "_ids_banda_caliente", _scoring_roto)
        monkeypatch.setattr(
            "db.resumen_pregen.licitaciones_publicadas_desde", lambda _d, _l: ["H1"]
        )

        assert job._candidatas_resumen(10) == ["S1", "H1"]


def test_los_settings_viven_en_su_modulo_hermano() -> None:
    """P3 módulos-dios: el setting nuevo no suma líneas a `config/settings.py`."""
    from config.settings import Settings
    from config.settings_resumen import ResumenPregenSettings

    assert issubclass(Settings, ResumenPregenSettings)
    for campo in ("RESUMEN_PREGEN_ENABLED", "RESUMEN_PREGEN_BATCH", "RESUMEN_PREGEN_MODEL"):
        assert campo in ResumenPregenSettings.model_fields
        assert campo in Settings.model_fields


def test_el_modelo_por_defecto_es_el_de_la_ui() -> None:
    """Si difieren, la clave de caché no coincide y la fase no calienta nada."""
    from api.routes.ask import ResumenRequest
    from config.settings_resumen import ResumenPregenSettings

    assert (
        ResumenPregenSettings.model_fields["RESUMEN_PREGEN_MODEL"].default
        == ResumenRequest.model_fields["model"].default
    )

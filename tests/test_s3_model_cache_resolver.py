"""S3.2 — activar una versión tiene que cambiar el artefacto que sirve la API.

``POST /api/v1/models/{name}/activate/{version}`` invalida la caché de proceso,
pero eso solo sirve si la recarga resuelve un artefacto **distinto**. Hasta
2026-09 la recarga era ``SAPClassifier.load()`` sin ruta: en Render eso mira
``data/models/sap_classifier.pkl``, un fichero que no existe (sin disco, sin
``data/`` en la imagen y sin nadie que llamara a ``ensure_downloaded()`` fuera
de ``scraper/pipeline.py``). El rollback del runbook no cambiaba lo servido y
``/explain`` degradaba a 503 para siempre.

Estos tests no tocan red ni BD: inyectan el resolvedor
(``api.model_cache._resolve_artifact``), que es la única dependencia externa de
la caché desde que hay **un solo** resolvedor de ``model_versions``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import api.model_cache as cache_mod
from scraper.ml_classifier import DEGRADACION_VERSION_MISMATCH
from scraper.ml_classifier import SAPClassifier as _SAPClassifierReal


class _ClasificadorFalso:
    """Recuerda de qué ruta se cargó, para poder afirmar cuál se está sirviendo."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.serving_degradado: str | None = (
            None if path is not None else DEGRADACION_VERSION_MISMATCH
        )

    @classmethod
    def load(cls, path: Path | None = None) -> _ClasificadorFalso:
        return cls(path)


@pytest.fixture(autouse=True)
def _clasificador_falso(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scraper.ml_classifier.SAPClassifier", _ClasificadorFalso)
    cache_mod.invalidate_classifier_cache()
    yield
    cache_mod.invalidate_classifier_cache()


def _resolver_fijo(destino: dict[str, Path | None]) -> Any:
    def _resolver(_name: str) -> Path | None:
        return destino["path"]

    return _resolver


class TestActivacionCambiaElArtefacto:
    def test_activar_otra_version_cambia_lo_servido(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        v1 = tmp_path / "sap_classifier_v1.pkl"
        v2 = tmp_path / "sap_classifier_v2.pkl"
        destino: dict[str, Path | None] = {"path": v1}
        monkeypatch.setattr(cache_mod, "_resolve_artifact", _resolver_fijo(destino))

        servido = cache_mod.get_classifier()
        assert servido.path == v1

        # Lo que hace la ruta de activación: cambia la versión activa (aquí, lo
        # que devuelve el resolvedor) e invalida la caché.
        destino["path"] = v2
        cache_mod.invalidate_classifier_cache()

        assert cache_mod.get_classifier().path == v2

    def test_sin_invalidar_se_sigue_sirviendo_el_anterior(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """El TTL es lo que cubre a los procesos que no recibieron la petición."""
        destino: dict[str, Path | None] = {"path": tmp_path / "v1.pkl"}
        monkeypatch.setattr(cache_mod, "_resolve_artifact", _resolver_fijo(destino))

        primero = cache_mod.get_classifier()
        destino["path"] = tmp_path / "v2.pkl"

        assert cache_mod.get_classifier() is primero

    def test_el_lock_y_el_ttl_siguen_vigentes(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Una sola carga por ventana de TTL: el contenedor tiene la memoria contada."""
        from config.settings import settings

        monkeypatch.setattr(settings, "API_MODEL_CACHE_TTL_SECONDS", 0.0, raising=False)
        cargas: list[Path | None] = []

        def _resolver(_name: str) -> Path | None:
            cargas.append(tmp_path / "v1.pkl")
            return tmp_path / "v1.pkl"

        monkeypatch.setattr(cache_mod, "_resolve_artifact", _resolver)

        cache_mod.get_classifier()
        cache_mod.get_classifier()

        assert len(cargas) == 1


class TestDegradacion:
    def test_artefacto_resuelto_no_es_degradacion(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            cache_mod, "_resolve_artifact", _resolver_fijo({"path": tmp_path / "v1.pkl"})
        )

        cache_mod.get_classifier()

        assert cache_mod.classifier_degradation() is None

    def test_sin_version_activa_se_publica_el_motivo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """El resolvedor devuelve None → se sirve el local y se dice por qué."""
        monkeypatch.setattr(cache_mod, "_resolve_artifact", _resolver_fijo({"path": None}))

        cache_mod.get_classifier()

        # `load()` sin ruta deja su propio motivo, más preciso que el genérico.
        assert cache_mod.classifier_degradation() == DEGRADACION_VERSION_MISMATCH

    def test_resolver_roto_no_tumba_la_api(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _revienta(_name: str) -> Path | None:
            raise RuntimeError("registry ilegible")

        monkeypatch.setattr(cache_mod, "_resolve_artifact", _revienta)

        assert cache_mod.get_classifier() is not None
        assert cache_mod.classifier_degradation() is not None

    def test_mismatch_de_sha256_propaga(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Servir explicaciones de otro modelo es peor que un 500."""
        from shared.model_artifacts import ModelArtifactMismatch

        def _mismatch(_name: str) -> Path | None:
            raise ModelArtifactMismatch("el sha256 no coincide")

        monkeypatch.setattr(cache_mod, "_resolve_artifact", _mismatch)

        with pytest.raises(ModelArtifactMismatch):
            cache_mod.get_classifier()

    def test_la_degradacion_llega_a_la_respuesta_de_explain(self) -> None:
        """No solo al log: el DTO de /explain ya tiene `warning` y por ahí sale.

        Usa la clase REAL (capturada al importar, antes de que la fixture
        sustituya el atributo del módulo por el doble).
        """
        clf = _SAPClassifierReal.__new__(_SAPClassifierReal)
        clf.serving_degradado = DEGRADACION_VERSION_MISMATCH

        payload = clf._con_degradacion({"prediction": True, "confidence": 0.9})

        assert payload["degradado"] == DEGRADACION_VERSION_MISMATCH
        assert "Degradado" in str(payload["warning"])

    def test_sin_degradacion_el_payload_no_se_toca(self) -> None:
        clf = _SAPClassifierReal.__new__(_SAPClassifierReal)
        clf.serving_degradado = None

        payload = clf._con_degradacion({"prediction": True, "confidence": 0.9})

        assert "warning" not in payload
        assert "degradado" not in payload


class TestDirectorioDeDescarga:
    def test_es_escribible(self) -> None:
        """En Render no hay disco propio: el destino tiene que poder crearse."""
        from shared.model_artifacts import artifact_cache_dir

        destino = artifact_cache_dir()

        assert destino.exists()
        sonda = destino / ".escritura_test"
        sonda.write_text("ok", encoding="utf-8")
        sonda.unlink()

    def test_cae_al_temp_si_data_dir_no_se_puede_crear(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import tempfile

        from config.settings import settings
        from shared.model_artifacts import artifact_cache_dir

        # DATA_DIR apuntando a un FICHERO: crear `<fichero>/models` es un
        # OSError en cualquier plataforma. Es el equivalente portable del
        # contenedor de solo lectura.
        fichero = tmp_path / "no-soy-un-directorio"
        fichero.write_text("x", encoding="utf-8")
        monkeypatch.setattr(settings, "DATA_DIR", fichero, raising=False)

        destino = artifact_cache_dir()

        assert str(destino).startswith(tempfile.gettempdir())

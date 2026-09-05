"""Tests de shared/model_artifacts — resolución verificada por sha256.

Cierra el ítem del backlog «db/model_registry.py no verifica el sha256 del
modelo servido contra el registrado»: registrar una versión, mutar el fichero
en disco y confirmar que la discrepancia se detecta.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from shared.model_artifacts import ModelArtifactMismatch, resolve_active_artifact


def _register(name: str, path: Path, sha256: str) -> None:
    from db.model_registry import register_version

    register_version(name=name, path=str(path), sha256=sha256, activate=True)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def cache_dir(tmp_path, monkeypatch) -> Path:
    """Apunta ``artifact_cache_dir()`` a ``tmp_path`` y devuelve ese directorio.

    Hace falta desde S3.2: la descarga ya no va al ``path`` del registro sino a
    la caché escribible, que sale de ``settings.DATA_DIR/models``. Sin este
    redireccionamiento los tests escribirían ``baja_model.pkl`` en el
    ``data/models/`` del checkout — pisando el artefacto real del que
    desarrolla y, peor, dejando un fichero que la pasada siguiente encontraría
    en el camino de «caché ya poblada», con lo que la descarga que se pretende
    verificar no llegaría a intentarse.
    """
    from config.settings import settings

    data_dir = tmp_path / "datadir"
    monkeypatch.setattr(settings, "DATA_DIR", data_dir, raising=False)
    return data_dir / "models"


def _descarga_falsa(contenido: bytes, destinos: list[Path] | None = None):
    """``_download_release_asset`` de mentira que deja ``contenido`` en ``dest``."""

    def _fake_download(_asset_name: str, dest: Path) -> bool:
        if destinos is not None:
            destinos.append(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(contenido)
        return True

    return _fake_download


def test_sin_version_activa_devuelve_none(tmp_db):
    assert resolve_active_artifact("modelo-inexistente") is None


def test_happy_path_artefacto_verificado(tmp_db, tmp_path):
    artefacto = tmp_path / "baja_model.pkl"
    artefacto.write_bytes(b"modelo-serializado")
    _register("baja", artefacto, _sha(b"modelo-serializado"))

    assert resolve_active_artifact("baja") == artefacto


def test_mutacion_del_artefacto_se_detecta(tmp_db, tmp_path):
    """Registrar → mutar el fichero → la resolución falla con mismatch."""
    artefacto = tmp_path / "baja_model.pkl"
    artefacto.write_bytes(b"modelo-original")
    _register("baja", artefacto, _sha(b"modelo-original"))

    artefacto.write_bytes(b"modelo-sustituido")

    with pytest.raises(ModelArtifactMismatch):
        resolve_active_artifact("baja")


def test_fichero_ausente_sin_sha_devuelve_none(tmp_db, tmp_path, cache_dir):
    artefacto = tmp_path / "no-existe.pkl"
    _register("baja", artefacto, "")

    assert resolve_active_artifact("baja") is None


def test_fichero_ausente_con_sha_intenta_descarga(tmp_db, tmp_path, cache_dir):
    """Runner efímero: sin fichero local se intenta el asset de la Release.

    El asset se sigue pidiendo por el basename del path registrado, pero desde
    S3.2 el DESTINO ya no es ese path: es la caché escribible. El ``path`` de
    ``model_versions`` es la ruta de la máquina que ENTRENÓ (un runner de
    Actions), y el contenedor de la API en Render no tiene disco propio, no
    lleva ``data/`` en la imagen y puede ni siquiera poder crear ese
    directorio — descargar ahí era la razón de que ``/explain`` degradase a 503
    de forma permanente.
    """
    registrado = tmp_path / "runner-que-entreno" / "baja_model.pkl"
    contenido = b"modelo-desde-release"
    _register("baja", registrado, _sha(contenido))

    pedidos: list[str] = []
    destinos: list[Path] = []

    def _fake_download(asset_name: str, dest: Path) -> bool:
        pedidos.append(asset_name)
        return _descarga_falsa(contenido, destinos)(asset_name, dest)

    with patch("shared.model_artifacts._download_release_asset", side_effect=_fake_download):
        resolved = resolve_active_artifact("baja")

    assert pedidos == ["baja_model.pkl"]
    assert destinos == [cache_dir / "baja_model.pkl"]
    assert resolved == cache_dir / "baja_model.pkl"
    assert resolved.read_bytes() == contenido
    # La ruta del registro no se toca: en Render puede no ser ni creable.
    assert not registrado.exists()


def test_descarga_deja_el_checksum_colocado(tmp_db, tmp_path, cache_dir):
    """El asset de la Release llega solo, sin su ``.sha256``.

    ``shared.model_integrity.verify_model_integrity`` —el paso previo a
    ``joblib.load``— aborta en ENV=prod si no hay ni pin ni checksum
    co-ubicado, así que sin escribirlo aquí resolver el artefacto cambiaría el
    fallback a baseline por un RuntimeError a mitad del batch. Va junto al
    artefacto, o sea en la caché (S3.2): «co-ubicado» es literal, es donde lo
    busca ``verify_model_integrity``.
    """
    registrado = tmp_path / "runner-que-entreno" / "baja_model.pkl"
    contenido = b"modelo-desde-release"
    _register("baja", registrado, _sha(contenido))

    with patch(
        "shared.model_artifacts._download_release_asset",
        side_effect=_descarga_falsa(contenido),
    ):
        resuelto = resolve_active_artifact("baja")

    sidecar = cache_dir / "baja_model.sha256"
    assert sidecar == resuelto.with_suffix(".sha256")
    assert sidecar.read_text(encoding="utf-8").strip() == _sha(contenido)


def test_activar_otra_version_renueva_el_checksum_de_la_cache(tmp_db, tmp_path, cache_dir):
    """Regresión: la caché reciclaba el ``.sha256`` de la versión anterior.

    Cada versión de ``baja_model``/``retencion_model`` se registra con el MISMO
    basename (``services/ml/baja_model.py::_MODEL_PATH`` es una ruta fija), así
    que la entrada de caché ``baja_model.pkl`` se reutiliza al activar una
    versión nueva. El ``.pkl`` obsoleto sí se borraba; su ``.sha256`` no, y
    ``_ensure_sidecar_checksum`` respetaba el sidecar existente — con lo que
    ``verify_model_integrity`` leía el hash de la versión vieja junto al
    artefacto nuevo y abortaba con «integridad comprometida» en ENV=prod.
    Activar una versión rompía el servicio en vez de cambiarlo, que es
    exactamente el fallo que S3.2 vino a arreglar.
    """
    from shared.model_integrity import verify_model_integrity

    registrado = tmp_path / "runner-que-entreno" / "baja_model.pkl"
    vieja, nueva = b"modelo-v1", b"modelo-v2"

    _register("baja", registrado, _sha(vieja))
    with patch(
        "shared.model_artifacts._download_release_asset", side_effect=_descarga_falsa(vieja)
    ):
        resolve_active_artifact("baja")

    # `POST /models/baja/activate/2`: otra versión activa, mismo basename.
    _register("baja", registrado, _sha(nueva))
    with patch(
        "shared.model_artifacts._download_release_asset", side_effect=_descarga_falsa(nueva)
    ):
        resuelto = resolve_active_artifact("baja")

    assert resuelto.read_bytes() == nueva
    assert (cache_dir / "baja_model.sha256").read_text(encoding="utf-8").strip() == _sha(nueva)
    # El invariante de verdad: el artefacto resuelto se puede cargar en prod.
    verify_model_integrity(
        resuelto,
        pinned_sha256="",
        pin_setting_name="ML_BAJA_SHA256",
        model_label="baja_model",
        env="prod",
    )


def test_un_sidecar_huerfano_en_la_cache_no_bloquea_la_descarga(tmp_db, tmp_path, cache_dir):
    """El ``.sha256`` que sobrevive a su artefacto no manda sobre el nuevo.

    En un checkout ``artifact_cache_dir()`` ES ``data/models/``, donde
    ``services/ml/promotion.py::_escribir_checksum`` deja el checksum del
    artefacto publicado. Si el ``.pkl`` desaparece (``data/models/`` está en
    .gitignore, y en un contenedor el disco es efímero) y el ``.sha256`` no,
    lo que acaba de bajarse —y de cotejarse contra ``model_versions``— es lo
    que vale.
    """
    registrado = tmp_path / "runner-que-entreno" / "baja_model.pkl"
    contenido = b"modelo-desde-release"
    _register("baja", registrado, _sha(contenido))

    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "baja_model.sha256").write_text("hash-de-un-pkl-que-ya-no-esta", encoding="utf-8")

    with patch(
        "shared.model_artifacts._download_release_asset",
        side_effect=_descarga_falsa(contenido),
    ):
        resuelto = resolve_active_artifact("baja")

    assert resuelto.read_bytes() == contenido
    assert (cache_dir / "baja_model.sha256").read_text(encoding="utf-8").strip() == _sha(contenido)


def test_no_pisa_un_checksum_colocado_existente(tmp_db, tmp_path):
    """Si el sidecar ya existe se respeta: detectar una discrepancia entre él y
    el artefacto es justo el trabajo de verify_model_integrity."""
    artefacto = tmp_path / "baja_model.pkl"
    artefacto.write_bytes(b"modelo-serializado")
    sidecar = tmp_path / "baja_model.sha256"
    sidecar.write_text("un-hash-que-no-cuadra", encoding="utf-8")
    _register("baja", artefacto, _sha(b"modelo-serializado"))

    assert resolve_active_artifact("baja") == artefacto
    assert sidecar.read_text(encoding="utf-8") == "un-hash-que-no-cuadra"


def test_descarga_con_sha_incorrecto_falla(tmp_db, tmp_path, cache_dir):
    registrado = tmp_path / "runner-que-entreno" / "baja_model.pkl"
    _register("baja", registrado, _sha(b"lo-esperado"))

    with (
        patch(
            "shared.model_artifacts._download_release_asset",
            side_effect=_descarga_falsa(b"otra-cosa"),
        ),
        pytest.raises(ModelArtifactMismatch),
    ):
        resolve_active_artifact("baja")

    # Un asset que no cuadra no se legitima con un checksum co-ubicado: sin
    # sidecar, `verify_model_integrity` seguiría rechazándolo en prod.
    assert not (cache_dir / "baja_model.sha256").exists()


def test_sap_active_learning_es_paso_canonico():
    from scheduler.pipeline_runs import CANONICAL_STEPS

    assert "sap_active_learning" in CANONICAL_STEPS


def test_sap_active_learning_invoca_maybe_retrain(tmp_db, monkeypatch):
    """El paso ejecuta maybe_retrain_classifier bajo la ventana periódica."""
    import scheduler.pipeline_runs as pr

    called: list[bool] = []

    def _fake_retrain(**_kw):
        called.append(True)
        return {"triggered": False, "feedbacks_new": 0}

    monkeypatch.setattr("scheduler.concept_drift.maybe_retrain_classifier", _fake_retrain)

    assert pr._run_sap_active_learning() == "ok"
    assert called == [True]
    # Segunda pasada dentro de la ventana semanal → skipped (lock retenido).
    assert pr._run_sap_active_learning() == "skipped"
    assert called == [True]


# ---------------------------------------------------------------------------
# resolve_servable_artifact — el canal cableado en scraper/ (2026-09)
# ---------------------------------------------------------------------------
#
# `precompute_ml_proba` y `precompute_ml_tecnologias` decidían si había modelo
# con `is_available()`, un `Path.exists()` sobre `data/models/`, que está en
# .gitignore y viene vacío en el runner: salían en `no_model` por construcción
# en cada pasada de la pipeline diaria, con `sap_classifier.pkl` publicado en
# la Release desde 2026-05-22 y nadie bajándolo.


def test_servable_prefiere_la_version_activa_sobre_el_local(tmp_path):
    from shared.model_artifacts import resolve_servable_artifact

    activo = tmp_path / "del-registro.pkl"
    local = tmp_path / "local.pkl"
    local.write_bytes(b"local")

    with patch("shared.model_artifacts.resolve_active_artifact", return_value=activo):
        assert resolve_servable_artifact("sap_classifier", local) == activo


def test_servable_cae_al_local_sin_version_activa(tmp_path):
    from shared.model_artifacts import resolve_servable_artifact

    local = tmp_path / "local.pkl"
    local.write_bytes(b"local")

    with patch("shared.model_artifacts.resolve_active_artifact", return_value=None):
        assert resolve_servable_artifact("sap_classifier", local) == local


def test_servable_sin_activa_ni_local_devuelve_none(tmp_path):
    """El caso del runner efímero: `data/models/` vacío y sin versión activa."""
    from shared.model_artifacts import resolve_servable_artifact

    with patch("shared.model_artifacts.resolve_active_artifact", return_value=None):
        assert resolve_servable_artifact("sap_classifier", tmp_path / "no-existe.pkl") is None


def test_servable_propaga_el_mismatch_en_vez_de_caer_al_local(tmp_path):
    """Servir el artefacto equivocado es peor que no servir ninguno: si la
    versión activa no cuadra con su sha256, el fallo sube -- no se sirve por
    detrás un local que nadie ha verificado."""
    from shared.model_artifacts import resolve_servable_artifact

    local = tmp_path / "local.pkl"
    local.write_bytes(b"local")

    with patch(
        "shared.model_artifacts.resolve_active_artifact",
        side_effect=ModelArtifactMismatch("sha distinto"),
    ):
        with pytest.raises(ModelArtifactMismatch):
            resolve_servable_artifact("sap_classifier", local)


def test_los_clasificadores_de_scraper_resuelven_por_el_canal():
    """El nombre del registro y la ruta local viajan juntos: si alguien cambia
    uno sin el otro, el artefacto deja de resolverse en silencio."""
    from scraper.ml_classifier import _MODEL_PATH as SAP_PATH
    from scraper.ml_classifier import SAPClassifier
    from scraper.tech_classifier import _MODEL_PATH as TECH_PATH
    from scraper.tech_classifier import TechnologyClassifier

    with patch("shared.model_artifacts.resolve_servable_artifact") as resolver:
        SAPClassifier.resolve_artifact()
        TechnologyClassifier.resolve_artifact()

    assert [c.args for c in resolver.call_args_list] == [
        ("sap_classifier", SAP_PATH),
        ("tech_classifier", TECH_PATH),
    ]


def test_precompute_ml_proba_sirve_el_artefacto_resuelto_no_el_local(tmp_path):
    """La regresión: el paso ya no se rinde por `is_available()` (disco local)
    y carga el artefacto que devuelve el canal."""
    from scraper import ml_training

    artefacto = tmp_path / "resuelto.pkl"
    with (
        patch("scraper.ml_classifier.SAPClassifier.resolve_artifact", return_value=artefacto),
        patch("scraper.ml_classifier.SAPClassifier.is_available") as is_available,
        patch("scraper.ml_classifier.SAPClassifier.load", side_effect=RuntimeError("stop")) as load,
    ):
        resultado = ml_training.precompute_ml_proba()

    load.assert_called_once_with(artefacto)
    is_available.assert_not_called()
    # `load` reventó a propósito: interesa por dónde pasó, no que puntúe.
    assert resultado["skipped_no_model"] is True

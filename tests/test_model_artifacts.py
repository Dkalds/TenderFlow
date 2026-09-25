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

    Las versiones de ``baja_model``/``retencion_model`` registradas antes de los
    nombres por contenido comparten basename (``_MODEL_PATH`` era una ruta
    fija), igual que ``sap_classifier.pkl``, así que la entrada de caché
    ``baja_model.pkl`` se reutiliza al activar otra de ellas. El ``.pkl``
    obsoleto sí se borraba; su ``.sha256`` no, y
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


# ── S8.4: el bucket antes que la Release ───────────────────────────────────
#
# El orden no es cosmético. La Release exige `GITHUB_TOKEN` para no chocar con
# el rate limit anónimo de la API de GitHub, y el contenedor de la API en
# Render no tiene ninguno: el camino de la Release es justo el que falla donde
# más falta hace. El bucket ya está configurado para los binarios de pliegos.


@pytest.fixture
def bucket(tmp_path, monkeypatch):
    """Almacén de objetos sobre disco, apuntando a un directorio del test."""
    from shared.object_store import get_object_store, reset_object_store_cache

    monkeypatch.setenv("DOCUMENT_BLOB_DIR", str(tmp_path / "bucket"))
    monkeypatch.delenv("DOCUMENT_BLOB_BACKEND", raising=False)
    monkeypatch.delenv("DOCUMENT_BLOB_BUCKET", raising=False)
    monkeypatch.delenv("MODEL_BLOB_PREFIX", raising=False)
    reset_object_store_cache()
    yield get_object_store()
    reset_object_store_cache()


def _publicar_en_bucket(path_registrado: Path, contenido: bytes) -> None:
    """Deja el artefacto en el bucket con el nombre por el que se pedirá."""
    from shared.model_artifacts import publish_artifact_to_bucket

    fuente = path_registrado.parent / "publicado" / path_registrado.name
    fuente.parent.mkdir(parents=True, exist_ok=True)
    fuente.write_bytes(contenido)
    assert publish_artifact_to_bucket(fuente) is True


def test_el_bucket_resuelve_sin_token_de_github(tmp_db, tmp_path, cache_dir, bucket, monkeypatch):
    """Criterio de aceptación de S8.4: sin `GITHUB_TOKEN` sigue habiendo modelo."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    registrado = tmp_path / "runner-que-entreno" / "baja_model.pkl"
    contenido = b"modelo-desde-el-bucket"
    _register("baja", registrado, _sha(contenido))
    _publicar_en_bucket(registrado, contenido)

    def _release_prohibida(_asset: str, _dest: Path) -> bool:
        raise AssertionError("la Release no debería intentarse si el bucket resuelve")

    with patch("shared.model_artifacts._download_release_asset", side_effect=_release_prohibida):
        resolved = resolve_active_artifact("baja")

    assert resolved == cache_dir / "baja_model.pkl"
    assert resolved.read_bytes() == contenido


def test_si_el_bucket_no_lo_tiene_se_cae_a_la_release(tmp_db, tmp_path, cache_dir, bucket):
    """El bucket vacío no puede dejar sin modelo a quien lo tiene publicado."""
    registrado = tmp_path / "runner-que-entreno" / "baja_model.pkl"
    contenido = b"modelo-desde-release"
    _register("baja", registrado, _sha(contenido))

    with patch(
        "shared.model_artifacts._download_release_asset",
        side_effect=_descarga_falsa(contenido),
    ) as release:
        resolved = resolve_active_artifact("baja")

    release.assert_called_once()
    assert resolved is not None and resolved.read_bytes() == contenido


def test_el_sha256_se_verifica_igual_viniendo_del_bucket(tmp_db, tmp_path, cache_dir, bucket):
    """Servir el artefacto equivocado es peor que no servir ninguno, venga de donde venga."""
    registrado = tmp_path / "runner-que-entreno" / "baja_model.pkl"
    _register("baja", registrado, _sha(b"el modelo bueno"))
    _publicar_en_bucket(registrado, b"otro modelo distinto")

    with (
        patch("shared.model_artifacts._download_release_asset", return_value=False),
        pytest.raises(ModelArtifactMismatch),
    ):
        resolve_active_artifact("baja")


def test_sin_bucket_configurado_el_camino_es_el_de_siempre(tmp_db, tmp_path, cache_dir):
    """La degradación: sin almacén, S8.4 no cambia nada de lo que ya había."""
    from shared.model_artifacts import _download_bucket_asset

    assert _download_bucket_asset("baja_model.pkl", tmp_path / "destino.pkl") is False


# ── Un solo transporte para la Release (P3 del backlog, 2026-09-18) ─────────


def test_la_descarga_de_la_release_delega_en_release_assets(tmp_path, monkeypatch):
    """``_download_release_asset`` usa el transporte pinned, no ``requests``,
    y localiza el asset empezando por la Release de tag fijo."""
    from shared import model_artifacts
    from shared.release_assets import ML_MODELS_RELEASE_TAG, AssetLocalizado

    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    dest = tmp_path / "baja_model.pkl"
    with (
        patch(
            "shared.release_assets.locate_release_asset",
            return_value=AssetLocalizado({"tag_name": "ml-models"}, 9),
        ) as localizar,
        patch("shared.release_assets.download_asset", return_value=True) as descarga,
    ):
        assert model_artifacts._download_release_asset("baja_model.pkl", dest) is True
    localizar.assert_called_once_with(
        "Dkalds/TenderFlow", "baja_model.pkl", token="tok", tag_fijo=ML_MODELS_RELEASE_TAG
    )
    descarga.assert_called_once_with("Dkalds/TenderFlow", 9, dest, token="tok")


def test_la_release_sin_el_asset_no_intenta_descargar(tmp_path):
    from shared import model_artifacts

    with (
        patch("shared.release_assets.locate_release_asset", return_value=None),
        patch("shared.release_assets.download_asset") as descarga,
    ):
        assert model_artifacts._download_release_asset("baja_model.pkl", tmp_path / "x") is False
    descarga.assert_not_called()


def test_la_release_inaccesible_devuelve_false(tmp_path):
    """Sin red, las tres candidatas fallan y el resultado es False, sin excepción."""
    import requests

    from shared import model_artifacts

    with patch(
        "shared.release_assets.pinned_https_request",
        side_effect=requests.ConnectionError("sin red"),
    ):
        assert model_artifacts._download_release_asset("baja_model.pkl", tmp_path / "x") is False
    assert not (tmp_path / "x").exists()


def test_una_descarga_fallida_devuelve_false(tmp_path):
    from shared import model_artifacts
    from shared.release_assets import AssetLocalizado

    with (
        patch(
            "shared.release_assets.locate_release_asset",
            return_value=AssetLocalizado({"tag_name": "ml-models"}, 9),
        ),
        patch("shared.release_assets.download_asset", return_value=False),
    ):
        assert model_artifacts._download_release_asset("baja_model.pkl", tmp_path / "x") is False


# ── Resolución de punta a punta sin BD (2026-09) ────────────────────────────
#
# El registro se sustituye por `get_active` de mentira y la red por un GitHub
# de mentira que responde por URL: lo que se ejerce es el camino real
# `resolve_active_artifact` → `_download_release_asset` → `locate_release_asset`
# → `download_asset`, con la verificación del sha256 al final.


class _Respuesta:
    """Doble mínimo de ``PinnedHttpsResponse`` (200 con cuerpo, o un status)."""

    def __init__(self, status_code: int = 200, body: bytes = b"") -> None:
        self.status_code = status_code
        self.headers: dict[str, str] = {}
        self._body = body

    def raise_for_status(self) -> None:
        if self.status_code >= 300:
            raise RuntimeError(f"Pinned HTTPS response status {self.status_code}")

    def iter_content(self, chunk_size: int = 8192):
        yield self._body

    def __enter__(self) -> _Respuesta:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


class _GitHubFalso:
    """``pinned_https_request`` que responde por URL; lo no configurado es 404."""

    def __init__(self, rutas: dict[str, object]) -> None:
        self.rutas = rutas
        self.urls: list[str] = []

    def __call__(self, _method: str, url: str, **_kwargs: object) -> _Respuesta:
        import json

        self.urls.append(url)
        respuesta = self.rutas.get(url)
        if respuesta is None:
            return _Respuesta(status_code=404)
        if isinstance(respuesta, bytes):
            return _Respuesta(body=respuesta)
        return _Respuesta(body=json.dumps(respuesta).encode())


_API = "https://api.github.com/repos/Dkalds/TenderFlow/releases"


def _fila_activa(path: Path, contenido: bytes, version: int = 1) -> dict[str, object]:
    return {"version": version, "path": str(path), "sha256": _sha(contenido)}


def test_una_release_de_software_posterior_no_deja_sin_artefacto(tmp_path, cache_dir):
    """El incidente de `release.yml`: *latest* pasa a ser una release sin assets.

    El artefacto está en la Release de tag fijo, así que *latest* no llega ni
    a consultarse.
    """
    registrado = tmp_path / "runner-que-entreno" / "baja_model-3fa9c1d2e4b5.pkl"
    contenido = b"modelo-publicado-en-ml-models"
    github = _GitHubFalso(
        {
            f"{_API}/tags/ml-models": {
                "id": 1,
                "tag_name": "ml-models",
                "assets": [{"name": registrado.name, "id": 9}],
            },
            f"{_API}/latest": {"id": 2, "tag_name": "v2.0.0", "assets": []},
            f"{_API}/assets/9": contenido,
        }
    )
    with (
        patch("db.model_registry.get_active", return_value=_fila_activa(registrado, contenido)),
        patch("shared.model_artifacts._download_bucket_asset", return_value=False),
        patch("shared.release_assets.pinned_https_request", side_effect=github),
    ):
        resuelto = resolve_active_artifact("baja_model")

    assert resuelto == cache_dir / registrado.name
    assert resuelto.read_bytes() == contenido
    assert f"{_API}/latest" not in github.urls


def test_una_fila_con_nombre_fijo_se_sigue_resolviendo(tmp_path, cache_dir):
    """Compatibilidad: las filas anteriores registran ``baja_model.pkl``.

    Su asset se subió a lo que entonces era *latest*; hoy *latest* es otra y
    `ml-models` no lo tiene, así que se encuentra entre las recientes, por
    nombre, y se verifica igual contra el sha256 registrado.
    """
    registrado = tmp_path / "runner-que-entreno" / "baja_model.pkl"
    contenido = b"modelo-v2-con-nombre-fijo"
    software = {"id": 3, "tag_name": "v1.5.0", "assets": []}
    github = _GitHubFalso(
        {
            f"{_API}/latest": software,
            f"{_API}?per_page=30": [
                software,
                {
                    "id": 2,
                    "tag_name": "v0.0.0-model",
                    "assets": [{"name": "baja_model.pkl", "id": 5}],
                },
            ],
            f"{_API}/assets/5": contenido,
        }
    )
    with (
        patch("db.model_registry.get_active", return_value=_fila_activa(registrado, contenido)),
        patch("shared.model_artifacts._download_bucket_asset", return_value=False),
        patch("shared.release_assets.pinned_https_request", side_effect=github),
    ):
        resuelto = resolve_active_artifact("baja_model")

    assert resuelto == cache_dir / "baja_model.pkl"
    assert resuelto.read_bytes() == contenido
    assert (cache_dir / "baja_model.sha256").read_text(encoding="utf-8") == _sha(contenido)


def test_dos_versiones_con_nombre_por_contenido_no_comparten_cache(tmp_path, cache_dir):
    """Activar vN+1 ya no borra ni pisa la entrada de caché de vN.

    Con el basename compartido, cada cambio de versión invalidaba la caché (y
    su sidecar) de la anterior; con el hash en el nombre, cada versión tiene
    la suya y volver atrás no obliga a descargar otra vez.
    """
    v1, v2 = b"modelo-v1", b"modelo-v2"
    ruta_v1 = tmp_path / "runner" / f"baja_model-{_sha(v1)[:12]}.pkl"
    ruta_v2 = tmp_path / "runner" / f"baja_model-{_sha(v2)[:12]}.pkl"

    for ruta, contenido in ((ruta_v1, v1), (ruta_v2, v2)):
        with (
            patch("db.model_registry.get_active", return_value=_fila_activa(ruta, contenido)),
            patch("shared.model_artifacts._download_bucket_asset", return_value=False),
            patch(
                "shared.model_artifacts._download_release_asset",
                side_effect=_descarga_falsa(contenido),
            ),
        ):
            assert resolve_active_artifact("baja_model") == cache_dir / ruta.name

    assert (cache_dir / ruta_v1.name).read_bytes() == v1
    assert (cache_dir / ruta_v2.name).read_bytes() == v2
    assert (cache_dir / ruta_v1.name).with_suffix(".sha256").read_text(encoding="utf-8") == _sha(v1)


def test_model_artifacts_no_usa_requests():
    """El salto sin pinning no puede volver por la puerta de atrás."""
    import ast
    import inspect

    from shared import model_artifacts

    arbol = ast.parse(inspect.getsource(model_artifacts))
    importados = {
        alias.name
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Import)
        for alias in nodo.names
    } | {nodo.module for nodo in ast.walk(arbol) if isinstance(nodo, ast.ImportFrom)}
    assert "requests" not in importados

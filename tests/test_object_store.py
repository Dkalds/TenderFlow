"""Tests de ``shared/object_store.py`` (plan 2026-09 v2, S8.1).

Todo lo de aquí es unitario: el almacén no toca la BD y el backend de sistema
de ficheros existe precisamente para poder ejercitar el contrato entero sin
credenciales ni red. Los tests de ``S3ObjectStore`` usan un cliente boto3 doble
—verifican que se llama a la API correcta, no que AWS funcione—.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from shared.object_store import (
    FilesystemObjectStore,
    NullObjectStore,
    ObjectStoreError,
    S3ObjectStore,
    blob_prefix,
    build_object_store,
    document_blob_key,
    get_object_store,
    load_config,
    model_artifact_key,
    purge_keys,
    reset_object_store_cache,
    store_stats,
)


@pytest.fixture(autouse=True)
def _entorno_limpio(monkeypatch):
    """Ningún test hereda la configuración de otro ni la del ``.env`` real."""
    for var in (
        "DOCUMENT_BLOB_BACKEND",
        "DOCUMENT_BLOB_BUCKET",
        "DOCUMENT_BLOB_ENDPOINT_URL",
        "DOCUMENT_BLOB_REGION",
        "DOCUMENT_BLOB_PREFIX",
        "DOCUMENT_BLOB_DIR",
        "MODEL_BLOB_PREFIX",
    ):
        monkeypatch.delenv(var, raising=False)
    reset_object_store_cache()
    yield
    reset_object_store_cache()


# ── Backend de sistema de ficheros: el contrato completo ───────────────────


class TestFilesystemObjectStore:
    def test_put_get_delete_round_trip(self, tmp_path):
        store = FilesystemObjectStore(tmp_path)
        store.put("documentos/abc123", b"contenido del pliego")

        assert store.get("documentos/abc123") == b"contenido del pliego"
        assert store.delete("documentos/abc123") is True
        assert store.get("documentos/abc123") is None
        assert store.delete("documentos/abc123") is False

    def test_get_de_clave_inexistente_es_none_no_error(self, tmp_path):
        """ "No está" y "el almacén falla" son cosas distintas para el fetcher."""
        assert FilesystemObjectStore(tmp_path).get("documentos/no-existe") is None

    def test_put_sobrescribe(self, tmp_path):
        store = FilesystemObjectStore(tmp_path)
        store.put("documentos/x", b"v1")
        store.put("documentos/x", b"v2")
        assert store.get("documentos/x") == b"v2"

    def test_stats_cuenta_objetos_y_bytes(self, tmp_path):
        store = FilesystemObjectStore(tmp_path)
        store.put("documentos/a", b"12345")
        store.put("documentos/b", b"678")
        store.put("modelos/m", b"9")

        solo_documentos = store.stats(prefix="documentos/")
        assert solo_documentos.objetos == 2
        assert solo_documentos.bytes == 8
        todo = store.stats()
        assert todo.objetos == 3

    @pytest.mark.parametrize(
        "clave",
        ["../fuera", "documentos/../../etc/passwd", "/absoluta", "", "con espacio"],
    )
    def test_claves_que_se_escapan_de_la_raiz_se_rechazan(self, tmp_path, clave):
        """Una clave es una ruta en este backend: el path traversal se corta aquí."""
        with pytest.raises(ObjectStoreError):
            FilesystemObjectStore(tmp_path).put(clave, b"x")

    def test_el_temporal_de_escritura_no_queda_visible(self, tmp_path):
        store = FilesystemObjectStore(tmp_path)
        store.put("documentos/a", b"x")
        assert [p.name for p in (tmp_path / "documentos").iterdir()] == ["a"]


class TestNullObjectStore:
    def test_no_lanza_al_guardar_y_no_devuelve_nada(self):
        """Sin bucket configurado, la ingesta se comporta como antes de S8."""
        store = NullObjectStore()
        assert store.enabled is False
        store.put("documentos/a", b"x")  # no lanza
        assert store.get("documentos/a") is None
        assert store.delete("documentos/a") is False
        assert store.stats().objetos == 0


# ── Resolución del backend desde el entorno ────────────────────────────────


class TestResolucionDeBackend:
    def test_sin_configuracion_queda_deshabilitado(self):
        assert build_object_store().backend == "disabled"
        assert get_object_store().enabled is False

    def test_auto_elige_ficheros_cuando_hay_directorio(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DOCUMENT_BLOB_DIR", str(tmp_path))
        assert build_object_store().backend == "filesystem"

    def test_auto_elige_s3_cuando_hay_bucket(self, monkeypatch):
        monkeypatch.setenv("DOCUMENT_BLOB_BUCKET", "pliegos")
        assert build_object_store().backend == "s3"

    def test_backend_explicito_sin_su_configuracion_falla_ruidosamente(self, monkeypatch):
        monkeypatch.setenv("DOCUMENT_BLOB_BACKEND", "s3")
        with pytest.raises(ObjectStoreError, match="DOCUMENT_BLOB_BUCKET"):
            build_object_store()

    def test_backend_desconocido_falla(self, monkeypatch):
        monkeypatch.setenv("DOCUMENT_BLOB_BACKEND", "dropbox")
        with pytest.raises(ObjectStoreError, match="desconocido"):
            build_object_store()

    def test_la_cache_se_invalida_al_cambiar_el_entorno(self, monkeypatch, tmp_path):
        """El almacén se cachea, pero no puede quedarse pegado a un entorno viejo."""
        assert get_object_store().backend == "disabled"
        monkeypatch.setenv("DOCUMENT_BLOB_DIR", str(tmp_path))
        assert get_object_store().backend == "filesystem"


class TestClaves:
    def test_la_clave_es_documentos_source_hash(self):
        assert document_blob_key("abc123") == "documentos/abc123"

    def test_sin_source_hash_se_usa_el_sha256_del_binario(self):
        assert document_blob_key(None, fallback="deadbeef") == "documentos/deadbeef"

    def test_sin_identidad_no_hay_clave(self):
        """Guardar bajo el id de la fila rompería la deduplicación en silencio."""
        assert document_blob_key(None) is None
        assert document_blob_key("   ") is None

    def test_un_source_hash_con_forma_de_ruta_no_produce_clave(self):
        assert document_blob_key("../../etc/passwd") is None

    def test_prefijo_configurable(self, monkeypatch):
        monkeypatch.setenv("DOCUMENT_BLOB_PREFIX", "pliegos")
        assert blob_prefix() == "pliegos/"
        assert document_blob_key("abc") == "pliegos/abc"

    def test_los_modelos_viven_bajo_otro_prefijo(self):
        """Su ciclo de vida no es el de un pliego: la retención no los toca."""
        assert model_artifact_key("baja_model.pkl") == "modelos/baja_model.pkl"
        assert model_artifact_key("../x") is None


class TestHelpers:
    def test_store_stats_es_none_sin_almacen(self):
        """`None` significa NO MEDIDO; un 0 se leería como «bucket vacío»."""
        assert store_stats() is None

    def test_store_stats_mide_solo_el_prefijo_de_pliegos(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DOCUMENT_BLOB_DIR", str(tmp_path))
        store = get_object_store()
        store.put("documentos/a", b"1234")
        store.put("modelos/m", b"1234567890")

        stats = store_stats()
        assert stats is not None
        assert stats.objetos == 1
        assert stats.bytes == 4

    def test_purge_keys_cuenta_solo_lo_que_existia(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DOCUMENT_BLOB_DIR", str(tmp_path))
        store = get_object_store()
        store.put("documentos/a", b"x")
        store.put("documentos/b", b"y")

        assert purge_keys(["documentos/a", "documentos/b", "documentos/fantasma"]) == 2
        assert store.get("documentos/a") is None

    def test_purge_keys_no_se_detiene_ante_una_clave_invalida(self, monkeypatch, tmp_path):
        """Fail-open por clave: la purga nocturna no puede pararse por una fila."""
        monkeypatch.setenv("DOCUMENT_BLOB_DIR", str(tmp_path))
        get_object_store().put("documentos/b", b"y")
        assert purge_keys(["../rota", "documentos/b"]) == 1

    def test_purge_keys_sin_almacen_no_hace_nada(self):
        assert purge_keys(["documentos/a"]) == 0


# ── S3: se verifica la llamada, no el proveedor ────────────────────────────


class TestS3ObjectStore:
    def _store_con_cliente(self, cliente) -> S3ObjectStore:
        store = S3ObjectStore("pliegos", endpoint_url="https://r2.example")
        store._client = cliente
        return store

    def test_put_usa_put_object_con_la_clave_normalizada(self):
        cliente = MagicMock()
        self._store_con_cliente(cliente).put("documentos/a", b"x", content_type="application/pdf")
        cliente.put_object.assert_called_once_with(
            Bucket="pliegos", Key="documentos/a", Body=b"x", ContentType="application/pdf"
        )

    def test_get_devuelve_none_cuando_la_clave_no_existe(self):
        cliente = MagicMock()
        error = Exception("no such key")
        error.response = {"Error": {"Code": "NoSuchKey"}}
        cliente.get_object.side_effect = error

        assert self._store_con_cliente(cliente).get("documentos/a") is None

    def test_un_fallo_real_del_bucket_no_se_confunde_con_ausencia(self):
        """Si el bucket falla, el fetcher tiene que enterarse: `None` mentiría."""
        cliente = MagicMock()
        error = Exception("acceso denegado")
        error.response = {"Error": {"Code": "AccessDenied"}}
        cliente.get_object.side_effect = error

        with pytest.raises(ObjectStoreError):
            self._store_con_cliente(cliente).get("documentos/a")

    def test_stats_suma_las_paginas_del_listado(self):
        cliente = MagicMock()
        cliente.get_paginator.return_value.paginate.return_value = [
            {"Contents": [{"Size": 10}, {"Size": 5}]},
            {"Contents": [{"Size": 1}]},
        ]
        stats = self._store_con_cliente(cliente).stats(prefix="documentos/")
        assert (stats.objetos, stats.bytes) == (3, 16)

    def test_endpoint_y_region_llegan_al_cliente(self, monkeypatch):
        """Es lo que hace que el mismo código valga para R2, Supabase o MinIO."""
        creado = {}

        class _Boto3Falso:
            @staticmethod
            def client(servicio, **kwargs):
                creado["servicio"] = servicio
                creado.update(kwargs)
                return MagicMock()

        monkeypatch.setitem(__import__("sys").modules, "boto3", _Boto3Falso)
        S3ObjectStore("b", endpoint_url="https://r2.example", region_name="auto")._cliente()

        assert creado["servicio"] == "s3"
        assert creado["endpoint_url"] == "https://r2.example"
        assert creado["region_name"] == "auto"


def test_load_config_normaliza_el_prefijo_sin_barra(monkeypatch):
    monkeypatch.setenv("DOCUMENT_BLOB_PREFIX", "algo")
    assert load_config().prefix == "algo/"

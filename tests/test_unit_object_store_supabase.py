"""Backend de Supabase Storage de ``shared/object_store.py`` y su configuraciÃ³n.

Unitario: ni red ni BD (ADR-029 Â§B). El transporte HTTP se inyecta con un doble
que hace de Supabase Storage en memoria â€”mismos endpoints, mismos cÃ³digos de
Â«no existeÂ»â€”, asÃ­ que lo que se verifica es el contrato del backend: quÃ© URL,
quÃ© cabeceras, cÃ³mo se distingue Â«no estÃ¡Â» de Â«fallaÂ» y que la clave de
servidor no acaba en ningÃºn mensaje de error.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field

import pytest

from config.settings import settings
from shared.object_store import (
    ObjectStoreError,
    SupabaseStorageObjectStore,
    build_object_store,
    get_object_store,
    load_config,
    reset_object_store_cache,
)

BASE = "https://proyecto.supabase.co"
CLAVE = "clave-servidor-de-prueba"
_VARIABLES = (
    "DOCUMENT_BLOB_BACKEND",
    "DOCUMENT_BLOB_BUCKET",
    "DOCUMENT_BLOB_ENDPOINT_URL",
    "DOCUMENT_BLOB_REGION",
    "DOCUMENT_BLOB_PREFIX",
    "DOCUMENT_BLOB_DIR",
    "DOCUMENT_BLOB_SUPABASE_URL",
    "DOCUMENT_BLOB_SUPABASE_KEY",
)


@pytest.fixture(autouse=True)
def _entorno_limpio(monkeypatch):
    """Sin variables en el entorno y con ``settings`` en sus defaults."""
    for var in _VARIABLES:
        monkeypatch.delenv(var, raising=False)
    for var, defecto in (
        ("DOCUMENT_BLOB_BACKEND", "auto"),
        ("DOCUMENT_BLOB_BUCKET", ""),
        ("DOCUMENT_BLOB_DIR", ""),
        ("DOCUMENT_BLOB_PREFIX", "documentos/"),
        ("DOCUMENT_BLOB_SUPABASE_URL", ""),
    ):
        monkeypatch.setattr(settings, var, defecto)
    reset_object_store_cache()
    yield
    reset_object_store_cache()


@dataclass
class _Respuesta:
    status_code: int
    cuerpo: bytes = b""
    cerrada: bool = False

    def iter_content(self, chunk_size: int = 8192) -> Iterator[bytes]:
        for i in range(0, len(self.cuerpo), chunk_size):
            yield self.cuerpo[i : i + chunk_size]

    def close(self) -> None:
        self.cerrada = True


@dataclass
class _SupabaseFalso:
    """Supabase Storage en memoria, con la forma de respuesta real."""

    bucket: str = "pliegos"
    objetos: dict[str, bytes] = field(default_factory=dict)
    peticiones: list[tuple[str, str, dict[str, str]]] = field(default_factory=list)
    respuestas: list[_Respuesta] = field(default_factory=list)
    #: Si se fija, toda peticiÃ³n devuelve este status (simula un fallo).
    forzar_status: int | None = None
    #: Forma del Â«no existeÂ»: 404 a secas o el 400 con cuerpo que tambiÃ©n usa.
    no_encontrado_como_400: bool = False

    def __call__(
        self, metodo: str, url: str, cabeceras: Mapping[str, str], cuerpo: bytes | None
    ) -> _Respuesta:
        self.peticiones.append((metodo, url, dict(cabeceras)))
        respuesta = self._responder(metodo, url, cuerpo)
        self.respuestas.append(respuesta)
        return respuesta

    def _no_encontrado(self) -> _Respuesta:
        if self.no_encontrado_como_400:
            return _Respuesta(400, json.dumps({"statusCode": "404", "error": "not_found"}).encode())
        return _Respuesta(404, b'{"error":"not_found"}')

    def _responder(self, metodo: str, url: str, cuerpo: bytes | None) -> _Respuesta:
        if self.forzar_status is not None:
            return _Respuesta(self.forzar_status, b'{"error":"boom"}')
        ruta = url.removeprefix(f"{BASE}/storage/v1/")
        if metodo == "POST" and ruta == f"object/list/{self.bucket}":
            return self._listar(json.loads(cuerpo or b"{}"))
        if metodo == "POST" and ruta.startswith(f"object/{self.bucket}/"):
            self.objetos[ruta.removeprefix(f"object/{self.bucket}/")] = cuerpo or b""
            return _Respuesta(200, b'{"Key":"ok"}')
        if metodo == "GET" and ruta.startswith(f"object/authenticated/{self.bucket}/"):
            clave = ruta.removeprefix(f"object/authenticated/{self.bucket}/")
            if clave not in self.objetos:
                return self._no_encontrado()
            return _Respuesta(200, self.objetos[clave])
        if metodo == "DELETE" and ruta.startswith(f"object/{self.bucket}/"):
            clave = ruta.removeprefix(f"object/{self.bucket}/")
            if self.objetos.pop(clave, None) is None:
                return self._no_encontrado()
            return _Respuesta(200, b"{}")
        return _Respuesta(405)

    def _listar(self, peticion: dict[str, object]) -> _Respuesta:
        """Listado de un nivel, como la API: carpetas con ``id`` nulo."""
        prefijo = str(peticion.get("prefix") or "")
        base = f"{prefijo}/" if prefijo else ""
        filas: dict[str, dict[str, object]] = {}
        for clave, datos in sorted(self.objetos.items()):
            if not clave.startswith(base):
                continue
            resto = clave.removeprefix(base)
            nombre, _, mas = resto.partition("/")
            if mas:
                filas.setdefault(nombre, {"name": nombre, "id": None, "metadata": None})
            else:
                filas[nombre] = {
                    "name": nombre,
                    "id": f"id-{clave}",
                    "metadata": {"size": len(datos)},
                }
        offset = int(str(peticion.get("offset") or 0))
        limite = int(str(peticion.get("limit") or 100))
        trozo = list(filas.values())[offset : offset + limite]
        return _Respuesta(200, json.dumps(trozo).encode())


def _store(falso: _SupabaseFalso) -> SupabaseStorageObjectStore:
    return SupabaseStorageObjectStore(BASE, falso.bucket, CLAVE, transporte=falso)


class TestContrato:
    def test_put_get_delete_round_trip(self):
        falso = _SupabaseFalso()
        store = _store(falso)

        store.put("documentos/abc123", b"contenido del pliego", content_type="application/pdf")

        assert store.get("documentos/abc123") == b"contenido del pliego"
        assert store.delete("documentos/abc123") is True
        assert store.get("documentos/abc123") is None
        assert store.delete("documentos/abc123") is False

    @pytest.mark.parametrize("como_400", [False, True])
    def test_no_existe_es_none_con_las_dos_formas_de_supabase(self, como_400):
        """Supabase dice Â«no existeÂ» con 404 o con 400 + ``statusCode: 404``."""
        falso = _SupabaseFalso(no_encontrado_como_400=como_400)
        store = _store(falso)
        assert store.get("documentos/no-esta") is None
        assert store.delete("documentos/no-esta") is False

    def test_put_hace_upsert_con_cabeceras_de_servidor(self):
        falso = _SupabaseFalso()
        _store(falso).put("documentos/x", b"v1", content_type="application/pdf")

        metodo, url, cabeceras = falso.peticiones[0]
        assert metodo == "POST"
        assert url == f"{BASE}/storage/v1/object/pliegos/documentos/x"
        assert cabeceras["Authorization"] == f"Bearer {CLAVE}"
        assert cabeceras["apikey"] == CLAVE
        assert cabeceras["x-upsert"] == "true"
        assert cabeceras["Content-Type"] == "application/pdf"

    def test_put_sobrescribe(self):
        falso = _SupabaseFalso()
        store = _store(falso)
        store.put("documentos/x", b"v1")
        store.put("documentos/x", b"v2")
        assert store.get("documentos/x") == b"v2"

    def test_las_respuestas_se_cierran_siempre(self):
        falso = _SupabaseFalso()
        store = _store(falso)
        store.put("documentos/x", b"v1")
        store.get("documentos/x")
        store.get("documentos/otra")
        assert falso.respuestas and all(r.cerrada for r in falso.respuestas)

    def test_stats_recorre_carpetas_y_pagina(self):
        falso = _SupabaseFalso()
        store = _store(falso)
        store.PAGINA_LISTADO = 2  # fuerza a paginar con pocos objetos
        for i in range(3):
            store.put(f"documentos/{i}", b"12345")
        store.put("documentos/sub/profundo", b"123")
        store.put("modelos/m", b"9")

        solo_documentos = store.stats(prefix="documentos/")
        assert solo_documentos.objetos == 4
        assert solo_documentos.bytes == 18

        todo = store.stats()
        assert todo.objetos == 5
        assert todo.bytes == 19


class TestFallos:
    @pytest.mark.parametrize("operacion", ["put", "get", "delete", "stats"])
    def test_un_500_es_error_no_ausencia(self, operacion):
        store = _store(_SupabaseFalso(forzar_status=500))
        with pytest.raises(ObjectStoreError, match=r"HTTP 500|listar"):
            if operacion == "put":
                store.put("documentos/x", b"v")
            elif operacion == "get":
                store.get("documentos/x")
            elif operacion == "delete":
                store.delete("documentos/x")
            else:
                store.stats()

    def test_un_fallo_de_transporte_no_filtra_la_clave(self):
        def transporte_roto(metodo, url, cabeceras, cuerpo):
            raise RuntimeError(f"conexiÃ³n rechazada con {cabeceras['Authorization']}")

        store = SupabaseStorageObjectStore(BASE, "pliegos", CLAVE, transporte=transporte_roto)
        with pytest.raises(ObjectStoreError) as exc:
            store.get("documentos/x")
        assert CLAVE not in str(exc.value)
        assert "RuntimeError" in str(exc.value)

    @pytest.mark.parametrize("clave", ["../fuera", "/absoluta", "documentos/../../x", ""])
    def test_claves_peligrosas_se_rechazan_antes_de_la_red(self, clave):
        falso = _SupabaseFalso()
        with pytest.raises(ObjectStoreError):
            _store(falso).put(clave, b"x")
        assert falso.peticiones == []

    @pytest.mark.parametrize(
        ("url", "bucket", "clave"),
        [
            ("http://proyecto.supabase.co", "pliegos", CLAVE),
            ("no-es-url", "pliegos", CLAVE),
            (BASE, "bucket/con/barras", CLAVE),
            (BASE, "pliegos", ""),
        ],
    )
    def test_configuracion_invalida_falla_al_construir(self, url, bucket, clave):
        with pytest.raises(ObjectStoreError):
            SupabaseStorageObjectStore(url, bucket, clave)

    def test_el_transporte_por_defecto_fija_el_host_del_proyecto(self, monkeypatch):
        """La allowlist del transporte es el host del proyecto y nada mÃ¡s."""
        llamadas: list[dict[str, object]] = []

        def fake_pinned(metodo, url, **kwargs):
            llamadas.append({"metodo": metodo, "url": url, **kwargs})
            return _Respuesta(200, b"datos")

        monkeypatch.setattr("shared.object_store.pinned_https_request", fake_pinned)
        store = SupabaseStorageObjectStore(BASE, "pliegos", CLAVE)
        assert store.get("documentos/x") == b"datos"
        assert llamadas[0]["allowed_hosts"] == frozenset({"proyecto.supabase.co"})
        assert llamadas[0]["timeout_seconds"] == SupabaseStorageObjectStore.TIMEOUT_SECONDS


class TestConfiguracion:
    def test_auto_elige_supabase_con_bucket_y_url(self, monkeypatch):
        monkeypatch.setenv("DOCUMENT_BLOB_BUCKET", "pliegos")
        monkeypatch.setenv("DOCUMENT_BLOB_SUPABASE_URL", BASE)
        monkeypatch.setenv("DOCUMENT_BLOB_SUPABASE_KEY", CLAVE)
        assert get_object_store().backend == "supabase"

    def test_auto_sin_url_de_supabase_sigue_siendo_s3(self, monkeypatch):
        monkeypatch.setenv("DOCUMENT_BLOB_BUCKET", "pliegos")
        assert build_object_store().backend == "s3"

    def test_supabase_explicito_sin_url_falla_ruidosamente(self, monkeypatch):
        monkeypatch.setenv("DOCUMENT_BLOB_BACKEND", "supabase")
        monkeypatch.setenv("DOCUMENT_BLOB_BUCKET", "pliegos")
        with pytest.raises(ObjectStoreError, match="DOCUMENT_BLOB_SUPABASE_URL"):
            build_object_store()

    def test_settings_alimenta_la_configuracion_sin_variable_de_entorno(
        self, monkeypatch, tmp_path
    ):
        """Lo que ``settings`` cargÃ³ del ``.env`` cuenta aunque no estÃ© en ``os.environ``."""
        monkeypatch.setattr(settings, "DOCUMENT_BLOB_DIR", str(tmp_path))
        assert get_object_store().backend == "filesystem"

    def test_el_entorno_gana_a_settings(self, monkeypatch, tmp_path):
        monkeypatch.setattr(settings, "DOCUMENT_BLOB_DIR", str(tmp_path))
        monkeypatch.setenv("DOCUMENT_BLOB_DIR", "")
        assert get_object_store().backend == "disabled"

    def test_la_clave_no_sale_en_el_repr_de_la_configuracion(self, monkeypatch):
        monkeypatch.setenv("DOCUMENT_BLOB_SUPABASE_KEY", CLAVE)
        cfg = load_config()
        assert cfg.supabase_key == CLAVE
        assert CLAVE not in repr(cfg)

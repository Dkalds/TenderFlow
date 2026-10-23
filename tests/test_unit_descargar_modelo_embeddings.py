"""`docker/descargar_modelo_embeddings.py`: revisión fija, sha256 obligatorio, todo o nada.

Sin red: el abridor de URLs se sustituye por uno que sirve bytes en memoria.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

_RUTA = Path(__file__).resolve().parents[1] / "docker" / "descargar_modelo_embeddings.py"
_COMMIT = "a" * 40


def _modulo() -> ModuleType:
    spec = importlib.util.spec_from_file_location("descargar_modelo_embeddings", _RUTA)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo  # dataclasses resuelve anotaciones por el módulo
    spec.loader.exec_module(modulo)
    return modulo


_CONTENIDO = {
    "onnx/model.onnx": b"grafo onnx",
    "tokenizer.json": b'{"model": {}}',
    "sentence_bert_config.json": b'{"max_seq_length": 128}',
}


def _sha(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def _abridor(mod: ModuleType, pedidas: list[str]):
    def abrir(url: str):
        pedidas.append(url)
        ruta = url.split(f"/resolve/{_COMMIT}/", 1)[1]
        return mod._Respuesta(io.BytesIO(_CONTENIDO[ruta]))

    return abrir


def _lista(mod: ModuleType, **cambios: str):
    hashes = {
        "sha256_modelo": _sha(_CONTENIDO["onnx/model.onnx"]),
        "sha256_tokenizador": _sha(_CONTENIDO["tokenizer.json"]),
        "sha256_config": _sha(_CONTENIDO["sentence_bert_config.json"]),
    }
    hashes.update(cambios)
    return mod.ficheros(**hashes)


def test_descarga_verifica_y_deja_origen(tmp_path: Path) -> None:
    mod = _modulo()
    pedidas: list[str] = []
    destino = tmp_path / "embeddings"

    mod.descargar(
        repo=mod.REPO_POR_DEFECTO,
        revision=_COMMIT,
        destino=destino,
        lista=_lista(mod),
        abrir=_abridor(mod, pedidas),
    )

    assert (destino / "model.onnx").read_bytes() == _CONTENIDO["onnx/model.onnx"]
    assert (destino / "tokenizer.json").is_file()
    assert (destino / "sentence_bert_config.json").is_file()
    origen = json.loads((destino / "origen.json").read_text(encoding="utf-8"))
    assert origen["repo"] == mod.REPO_POR_DEFECTO
    assert origen["revision"] == _COMMIT
    assert set(origen["ficheros"]) == {"model.onnx", "tokenizer.json", "sentence_bert_config.json"}
    assert all(
        u.startswith(f"https://huggingface.co/{mod.REPO_POR_DEFECTO}/resolve/") for u in pedidas
    )
    # Sin restos del directorio temporal junto al destino.
    assert [p.name for p in tmp_path.iterdir()] == ["embeddings"]


def test_un_hash_que_no_cuadra_no_deja_nada(tmp_path: Path) -> None:
    mod = _modulo()
    destino = tmp_path / "embeddings"

    with pytest.raises(mod.DescargaInvalida, match=r"tokenizer\.json"):
        mod.descargar(
            repo=mod.REPO_POR_DEFECTO,
            revision=_COMMIT,
            destino=destino,
            lista=_lista(mod, sha256_tokenizador="0" * 64),
            abrir=_abridor(mod, []),
        )

    assert not destino.exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("revision", ["main", "v1.0", "A" * 40, "a" * 39])
def test_revision_tiene_que_ser_un_commit(tmp_path: Path, revision: str) -> None:
    mod = _modulo()
    with pytest.raises(mod.DescargaInvalida, match="commit"):
        mod.descargar(
            repo=mod.REPO_POR_DEFECTO,
            revision=revision,
            destino=tmp_path / "x",
            lista=_lista(mod),
            abrir=_abridor(mod, []),
        )


def test_sin_hash_no_se_descarga(tmp_path: Path) -> None:
    mod = _modulo()
    pedidas: list[str] = []
    with pytest.raises(mod.DescargaInvalida, match="sha256"):
        mod.descargar(
            repo=mod.REPO_POR_DEFECTO,
            revision=_COMMIT,
            destino=tmp_path / "x",
            lista=_lista(mod, sha256_config=""),
            abrir=_abridor(mod, pedidas),
        )
    assert pedidas == []


def test_sin_revision_sale_bien_y_sin_modelo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """El CI construye la imagen sin argumentos: no puede fallar ni bajar nada."""
    mod = _modulo()
    monkeypatch.delenv("EMBEDDINGS_ONNX_REVISION", raising=False)
    destino = tmp_path / "embeddings"

    assert mod.main(["--destino", str(destino)]) == 0

    assert destino.is_dir() and list(destino.iterdir()) == []
    assert "sin EMBEDDINGS_ONNX_REVISION" in capsys.readouterr().out


def test_con_revision_y_sin_hashes_falla(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _modulo()
    for var in ("MODELO", "TOKENIZADOR", "CONFIG"):
        monkeypatch.delenv(f"EMBEDDINGS_ONNX_SHA256_{var}", raising=False)
    assert mod.main(["--destino", str(tmp_path / "e"), "--revision", _COMMIT]) == 1


def test_solo_https(tmp_path: Path) -> None:
    mod = _modulo()
    with pytest.raises(mod.DescargaInvalida, match="HTTPS"):
        mod._abrir_url("http://huggingface.co/x")

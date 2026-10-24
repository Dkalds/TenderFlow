"""Codificador ONNX de la consulta (`services/embeddings_onnx.py`).

Sin el modelo real: una sesión falsa con la misma interfaz que
`onnxruntime.InferenceSession` y un tokenizador `tokenizers` construido en
memoria. Lo que se fija aquí es lo que tiene que reproducir sentence-transformers
—truncado con los tokens especiales dentro, mean pooling que ignora el relleno,
normalización L2— y cómo `services.embeddings` elige el motor. La paridad
numérica con el modelo de verdad es `tests/test_embeddings_onnx_paridad.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace
from tokenizers.processors import TemplateProcessing

from services import embeddings
from services.embeddings_onnx import (
    CodificadorOnnx,
    ModeloOnnxInvalido,
    leer_max_seq_length,
    modelo_onnx_presente,
)

_PALABRAS = ["servicio", "de", "mantenimiento", "sap", "erp", "limpieza"]
_PALABRAS += ["oficinas", "licencias", "software", "red"]
_VOCAB = {"<pad>": 0, "<unk>": 1, "<s>": 2, "</s>": 3} | {
    palabra: i for i, palabra in enumerate(_PALABRAS, start=4)
}

_DIM = 6


def _tokenizer() -> Tokenizer:
    tok = Tokenizer(WordLevel(_VOCAB, unk_token="<unk>"))
    tok.pre_tokenizer = Whitespace()
    tok.post_processor = TemplateProcessing(
        single="<s> $A </s>", special_tokens=[("<s>", 2), ("</s>", 3)]
    )
    return tok


class _Nodo:
    def __init__(self, name: str) -> None:
        self.name = name


class _SesionFalsa:
    """Embedding de token determinista: depende del id y de la posición.

    Que dependa de la posición es lo que hace visible un relleno mal tratado:
    si el pooling contara las posiciones de `<pad>`, el mismo texto daría otro
    vector según con quién comparta lote.
    """

    def __init__(self, entradas: tuple[str, ...] = ("input_ids", "attention_mask")) -> None:
        self._entradas = entradas
        self.llamadas: list[dict[str, np.ndarray]] = []

    def get_inputs(self) -> list[_Nodo]:
        return [_Nodo(n) for n in self._entradas]

    def get_outputs(self) -> list[_Nodo]:
        return [_Nodo("last_hidden_state")]

    def run(self, output_names: list[str] | None, input_feed: dict[str, Any]) -> list[Any]:
        self.llamadas.append(input_feed)
        ids = np.asarray(input_feed["input_ids"], dtype=np.float32)
        lote, largo = ids.shape
        pos = np.broadcast_to(np.arange(largo, dtype=np.float32), (lote, largo))
        base = np.stack(
            [ids, ids * 0.5 + pos, np.sin(ids), np.cos(pos), ids % 3, np.ones_like(ids)], axis=-1
        )
        # El relleno lleva basura grande a propósito: si entra en la media, se nota.
        relleno = np.asarray(input_feed["attention_mask"]) == 0
        base[relleno] = 1000.0
        return [base]


def _pooling_de_referencia(
    sesion: _SesionFalsa, tok: Tokenizer, texto: str, max_len: int
) -> np.ndarray:
    """La cuenta de sentence-transformers, hecha a mano para un solo texto."""
    tok.enable_truncation(max_length=max_len)
    enc = tok.encode(texto)
    ids = np.asarray([enc.ids], dtype=np.int64)
    mask = np.ones_like(ids)
    tokens = sesion.run(None, {"input_ids": ids, "attention_mask": mask})[0][0]
    media = tokens.mean(axis=0)
    return media / np.linalg.norm(media)


def test_mean_pooling_normalizado_e_independiente_del_lote() -> None:
    sesion = _SesionFalsa()
    cod = CodificadorOnnx(sesion, _tokenizer(), max_seq_length=128)

    textos = ["servicio sap", "mantenimiento de licencias software sap erp red", "limpieza"]
    vectores = cod.codificar(textos, batch_size=8)

    assert vectores.shape == (3, _DIM)
    assert vectores.dtype == np.float32
    np.testing.assert_allclose(np.linalg.norm(vectores, axis=1), 1.0, rtol=1e-6)
    # Cada texto, solo, da el mismo vector que dentro del lote con relleno.
    for i, texto in enumerate(textos):
        esperado = _pooling_de_referencia(_SesionFalsa(), _tokenizer(), texto, 128)
        np.testing.assert_allclose(vectores[i], esperado, rtol=1e-5, atol=1e-6)


def test_orden_de_salida_es_el_de_entrada_aunque_se_agrupe_por_longitud() -> None:
    cod = CodificadorOnnx(_SesionFalsa(), _tokenizer(), max_seq_length=128)
    textos = ["sap", "servicio de mantenimiento sap erp", "red", "licencias software"]

    juntos = cod.codificar(textos, batch_size=2)
    sueltos = np.vstack([cod.codificar([t]) for t in textos])

    np.testing.assert_allclose(juntos, sueltos, rtol=1e-5, atol=1e-6)


def test_trunca_con_los_tokens_especiales_dentro() -> None:
    sesion = _SesionFalsa()
    cod = CodificadorOnnx(sesion, _tokenizer(), max_seq_length=4)

    cod.codificar(["servicio de mantenimiento sap erp"])

    ids = sesion.llamadas[0]["input_ids"]
    assert ids.shape == (1, 4)
    assert ids[0, 0] == _VOCAB["<s>"] and ids[0, -1] == _VOCAB["</s>"]


def test_rellena_con_el_id_de_pad_y_mascara_cero() -> None:
    sesion = _SesionFalsa()
    cod = CodificadorOnnx(sesion, _tokenizer(), max_seq_length=128)

    cod.codificar(["sap", "servicio de mantenimiento sap"], batch_size=4)

    feed = sesion.llamadas[0]
    assert feed["input_ids"].dtype == np.int64
    corto = int(np.argmin(feed["attention_mask"].sum(axis=1)))
    assert list(feed["attention_mask"][corto]) == [1, 1, 1, 0, 0, 0]
    assert list(feed["input_ids"][corto][3:]) == [_VOCAB["<pad>"]] * 3


def test_pasa_token_type_ids_si_el_grafo_lo_pide() -> None:
    sesion = _SesionFalsa(entradas=("input_ids", "attention_mask", "token_type_ids"))
    cod = CodificadorOnnx(sesion, _tokenizer(), max_seq_length=128)

    cod.codificar(["sap erp"])

    feed = sesion.llamadas[0]
    assert set(feed) == {"input_ids", "attention_mask", "token_type_ids"}
    assert not feed["token_type_ids"].any()


def test_lista_vacia_no_llama_al_modelo() -> None:
    sesion = _SesionFalsa()
    vectores = CodificadorOnnx(sesion, _tokenizer(), max_seq_length=128).codificar([])
    assert vectores.shape[0] == 0
    assert sesion.llamadas == []


def test_salida_sin_dimension_de_token_se_rechaza() -> None:
    class _SesionPooled(_SesionFalsa):
        def run(self, output_names: list[str] | None, input_feed: dict[str, Any]) -> list[Any]:
            return [np.ones((len(input_feed["input_ids"]), _DIM), dtype=np.float32)]

    with pytest.raises(ModeloOnnxInvalido):
        CodificadorOnnx(_SesionPooled(), _tokenizer(), max_seq_length=128).codificar(["sap"])


# ── Ficheros del directorio ────────────────────────────────────────────────


def _directorio_modelo(tmp_path: Path, *, origen: dict[str, str] | None = None) -> Path:
    (tmp_path / "model.onnx").write_bytes(b"no es un modelo")
    _tokenizer().save(str(tmp_path / "tokenizer.json"))
    if origen is not None:
        (tmp_path / "origen.json").write_text(json.dumps(origen), encoding="utf-8")
    return tmp_path


def test_modelo_presente_exige_modelo_y_tokenizador(tmp_path: Path) -> None:
    assert not modelo_onnx_presente(tmp_path)
    (tmp_path / "model.onnx").write_bytes(b"x")
    assert not modelo_onnx_presente(tmp_path)
    _tokenizer().save(str(tmp_path / "tokenizer.json"))
    assert modelo_onnx_presente(tmp_path)
    assert not modelo_onnx_presente(tmp_path / "no-existe")


def test_max_seq_length_sale_de_sentence_bert_config(tmp_path: Path) -> None:
    assert leer_max_seq_length(tmp_path) == 128
    (tmp_path / "sentence_bert_config.json").write_text(
        json.dumps({"max_seq_length": 64, "do_lower_case": False}), encoding="utf-8"
    )
    assert leer_max_seq_length(tmp_path) == 64


# ── Elección del motor en services.embeddings ─────────────────────────────


@pytest.fixture
def sin_sentence_transformers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embeddings, "_has_sentence_transformers", lambda: False)
    embeddings._reiniciar_onnx()
    yield
    embeddings._reiniciar_onnx()


def test_sin_configurar_no_hay_motor(
    sin_sentence_transformers: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(embeddings.settings, "EMBEDDINGS_ONNX_DIR", "")
    assert embeddings.backend_embeddings() is None
    assert embeddings.embeddings_available() is False
    with pytest.raises(ImportError):
        embeddings.encode_texts(["sap"])


def test_onnx_configurado_codifica_la_consulta(
    sin_sentence_transformers: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    directorio = _directorio_modelo(tmp_path)
    monkeypatch.setattr(embeddings.settings, "EMBEDDINGS_ONNX_DIR", str(directorio))
    sesion = _SesionFalsa()
    monkeypatch.setattr(
        embeddings,
        "_cargar_codificador_onnx",
        lambda d: CodificadorOnnx(sesion, Tokenizer.from_file(str(d / "tokenizer.json")), 128),
    )

    assert embeddings.backend_embeddings() == "onnx"
    assert embeddings.embeddings_available() is True
    vector = embeddings.encode_texts(["mantenimiento sap"])
    assert vector.shape == (1, _DIM)
    assert len(sesion.llamadas) == 1


def test_onnx_no_sirve_para_codificar_corpus_en_la_peticion(
    sin_sentence_transformers: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        embeddings.settings, "EMBEDDINGS_ONNX_DIR", str(_directorio_modelo(tmp_path))
    )
    assert embeddings.embeddings_available() is True
    assert embeddings.embeddings_masivos_disponibles() is False


def test_masivos_sigue_a_embeddings_available_sin_onnx(monkeypatch: pytest.MonkeyPatch) -> None:
    """Los tests que parchean `embeddings_available` siguen gobernando el corpus."""
    monkeypatch.setattr(embeddings.settings, "EMBEDDINGS_ONNX_DIR", "")
    monkeypatch.setattr(embeddings, "embeddings_available", lambda: True)
    assert embeddings.embeddings_masivos_disponibles() is True
    monkeypatch.setattr(embeddings, "embeddings_available", lambda: False)
    assert embeddings.embeddings_masivos_disponibles() is False


def test_directorio_configurado_sin_ficheros_no_activa_onnx(
    sin_sentence_transformers: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(embeddings.settings, "EMBEDDINGS_ONNX_DIR", str(tmp_path / "vacio"))
    assert embeddings.backend_embeddings() is None


def test_origen_de_otro_modelo_no_activa_onnx(
    sin_sentence_transformers: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    directorio = _directorio_modelo(
        tmp_path, origen={"repo": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"}
    )
    monkeypatch.setattr(embeddings.settings, "EMBEDDINGS_ONNX_DIR", str(directorio))
    monkeypatch.setattr(
        embeddings.settings, "EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2"
    )
    assert embeddings.backend_embeddings() is None


def test_origen_ilegible_apaga_onnx_sin_lanzar(
    sin_sentence_transformers: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Un origen.json truncado no puede convertir cada búsqueda en un 500."""
    directorio = _directorio_modelo(tmp_path)
    (directorio / "origen.json").write_text('{"repo": "sentence-trans', encoding="utf-8")
    monkeypatch.setattr(embeddings.settings, "EMBEDDINGS_ONNX_DIR", str(directorio))
    assert embeddings.backend_embeddings() is None
    assert embeddings.embeddings_available() is False


def test_origen_del_mismo_modelo_activa_onnx(
    sin_sentence_transformers: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    directorio = _directorio_modelo(
        tmp_path, origen={"repo": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"}
    )
    monkeypatch.setattr(embeddings.settings, "EMBEDDINGS_ONNX_DIR", str(directorio))
    monkeypatch.setattr(
        embeddings.settings, "EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2"
    )
    assert embeddings.backend_embeddings() == "onnx"


def test_un_fallo_al_cargar_apaga_onnx_hasta_reiniciar(
    sin_sentence_transformers: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Un modelo roto no se reintenta en cada petición: se carga una vez y se apaga."""
    monkeypatch.setattr(
        embeddings.settings, "EMBEDDINGS_ONNX_DIR", str(_directorio_modelo(tmp_path))
    )
    intentos: list[Path] = []

    def _rompe(d: Path) -> CodificadorOnnx:
        intentos.append(d)
        raise RuntimeError("model.onnx corrupto")

    monkeypatch.setattr(embeddings, "_cargar_codificador_onnx", _rompe)

    with pytest.raises(RuntimeError):
        embeddings.encode_texts(["sap"])
    assert embeddings.embeddings_available() is False
    with pytest.raises(ImportError):
        embeddings.encode_texts(["sap"])
    assert len(intentos) == 1


def test_sentence_transformers_tiene_preferencia(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Es el motor con el que se embebió lo guardado: si está, manda él."""
    monkeypatch.setattr(embeddings, "_has_sentence_transformers", lambda: True)
    monkeypatch.setattr(
        embeddings.settings, "EMBEDDINGS_ONNX_DIR", str(_directorio_modelo(tmp_path))
    )
    assert embeddings.backend_embeddings() == "sentence_transformers"
    assert embeddings.embeddings_masivos_disponibles() is True

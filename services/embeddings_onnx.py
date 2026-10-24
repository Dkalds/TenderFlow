"""Codificador de embeddings en ONNX, sin PyTorch, para la consulta de la API.

Por qué existe
--------------
Los fragmentos de pliego de ``documento_chunks`` se embeben en el plano de
ingesta con sentence-transformers (extra ``[ml]``, que arrastra PyTorch, ~2 GB).
La imagen de la API no lo instala a propósito (C3.1), así que hasta 2026-10
``hybrid_search`` devolvía ``[]`` siempre en producción: el índice vectorial
existía y ninguna ruta lo consultaba (backlog P2 «La búsqueda por significado
no corre en producción»).

Codificar UNA consulta no necesita PyTorch: el mismo
``paraphrase-multilingual-MiniLM-L12-v2`` exportado a ONNX, con
``onnxruntime`` y ``tokenizers`` (decenas de MB, no gigas), da el mismo
vector. Lo que hay que reproducir de sentence-transformers es poco y está
fijado en ``tests/test_unit_embeddings_onnx.py``:

1. Tokenizar con el ``tokenizer.json`` del modelo, truncando a
   ``max_seq_length`` (128 en este modelo, de ``sentence_bert_config.json``)
   **con los tokens especiales dentro**, como hace ``transformers``.
2. Media de los embeddings de token pesada por la máscara de atención (el
   módulo ``Pooling`` con ``pooling_mode_mean_tokens``): el relleno no cuenta.
3. Normalización L2, que en este repo pide quien codifica
   (``normalize_embeddings=True`` en ``services.embeddings.encode_texts``), no
   el modelo.

Que el resultado coincide con sentence-transformers lo mide
``tests/test_embeddings_onnx_paridad.py`` (coseno ≥ 0,999 sobre frases fijas),
que solo corre donde están el modelo ONNX y el extra ``[ml]``.

Coste
-----
El ``model.onnx`` en float32 pesa ~470 MB y la sesión los lleva a memoria: es el
grueso de lo que este módulo añade al proceso de la API (plan ``standard``,
2 GB). Por eso se carga perezosamente, una vez, en la primera consulta que lo
necesita (``services.embeddings``), y por eso no se usa la variante cuantizada:
ahorraría memoria a costa de no reproducir los vectores guardados.

Codificar un texto de 128 tokens son unos 5 GFLOP: una consulta es barata, pero
un corpus de miles dentro de una petición no lo es. Ver
``services.embeddings.embeddings_masivos_disponibles``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import numpy as np
import numpy.typing as npt

if TYPE_CHECKING:
    from tokenizers import Tokenizer

#: Ficheros sin los que no hay codificador. ``model.onnx`` es el de la carpeta
#: ``onnx/`` del repo de Hugging Face; ``tokenizer.json``, el de la raíz.
FICHERO_MODELO = "model.onnx"
FICHERO_TOKENIZADOR = "tokenizer.json"
#: Opcionales: el largo máximo de secuencia y de dónde salió el modelo
#: (lo escribe ``scripts/descargar_modelo_embeddings.py``).
FICHERO_CONFIG_ST = "sentence_bert_config.json"
FICHERO_ORIGEN = "origen.json"

#: El ``max_seq_length`` de ``paraphrase-multilingual-MiniLM-L12-v2``. Solo se
#: usa si el directorio no trae ``sentence_bert_config.json``.
MAX_SEQ_LENGTH_POR_DEFECTO = 128

#: Salidas por nombre, en orden de preferencia: la de un export de
#: sentence-transformers (``token_embeddings``) y la de uno de ``optimum`` /
#: ``transformers`` (``last_hidden_state``). Las dos son embeddings de token,
#: antes del pooling.
_SALIDAS_DE_TOKEN = ("token_embeddings", "last_hidden_state")

#: Candidatos al token de relleno: XLM-R (``<pad>``) y BERT (``[PAD]``).
_TOKENS_DE_RELLENO = ("<pad>", "[PAD]")


class ModeloOnnxInvalido(RuntimeError):
    """El grafo no devuelve lo que un codificador de frases necesita."""


class _Nodo(Protocol):
    @property
    def name(self) -> str: ...


class SesionOnnx(Protocol):
    """Lo que se usa de ``onnxruntime.InferenceSession`` (los tests la falsean)."""

    def get_inputs(self) -> Sequence[_Nodo]: ...

    def get_outputs(self) -> Sequence[_Nodo]: ...

    # ``run`` devuelve una lista de ``numpy.ndarray`` sin tipar en onnxruntime
    # (no publica stubs); se convierte con ``np.asarray`` en el único sitio que
    # la llama.
    def run(
        self,
        output_names: list[str] | None,
        input_feed: dict[str, npt.NDArray[np.int64]],
    ) -> Sequence[object]: ...


def modelo_onnx_presente(directorio: Path) -> bool:
    """True si ``directorio`` trae el modelo y el tokenizador."""
    return (directorio / FICHERO_MODELO).is_file() and (directorio / FICHERO_TOKENIZADOR).is_file()


def leer_max_seq_length(directorio: Path) -> int:
    """``max_seq_length`` de ``sentence_bert_config.json``, o el del modelo por defecto."""
    ruta = directorio / FICHERO_CONFIG_ST
    if not ruta.is_file():
        return MAX_SEQ_LENGTH_POR_DEFECTO
    valor = json.loads(ruta.read_text(encoding="utf-8")).get("max_seq_length")
    return int(valor) if isinstance(valor, int) and valor > 0 else MAX_SEQ_LENGTH_POR_DEFECTO


def leer_repo_de_origen(directorio: Path) -> str | None:
    """El repo de Hugging Face del que se descargó el modelo, si consta."""
    ruta = directorio / FICHERO_ORIGEN
    if not ruta.is_file():
        return None
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Un origen.json roto (descarga interrumpida) no puede tumbar cada
        # llamada a embeddings_available(): quien llama lo trata como modelo
        # no utilizable y la búsqueda cae a texto.
        raise OrigenIlegibleError(str(ruta)) from None
    repo = datos.get("repo") if isinstance(datos, dict) else None
    return str(repo) if repo else None


class OrigenIlegibleError(ValueError):
    """``origen.json`` existe pero no se puede leer como JSON."""


class CodificadorOnnx:
    """Frases → vectores normalizados, con la cuenta de sentence-transformers."""

    def __init__(self, sesion: SesionOnnx, tokenizer: Tokenizer, max_seq_length: int) -> None:
        self._sesion = sesion
        self._tokenizer = tokenizer
        # Truncado sí, relleno no: el relleno se hace aquí, por lote, para que
        # la máscara la construya el mismo código que luego la usa al promediar.
        tokenizer.no_padding()
        tokenizer.enable_truncation(max_length=max_seq_length)
        self._pad_id = _id_de_relleno(tokenizer)
        self._entradas = frozenset(nodo.name for nodo in sesion.get_inputs())
        self._salida = _salida_de_token(sesion)

    @classmethod
    def desde_directorio(cls, directorio: Path) -> CodificadorOnnx:
        """Carga ``model.onnx`` y ``tokenizer.json`` de ``directorio``.

        Import perezoso: ``onnxruntime`` solo hace falta donde hay modelo.
        """
        import onnxruntime as ort
        from tokenizers import Tokenizer

        opciones = ort.SessionOptions()
        opciones.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        sesion: SesionOnnx = ort.InferenceSession(
            str(directorio / FICHERO_MODELO),
            sess_options=opciones,
            providers=["CPUExecutionProvider"],
        )
        tokenizer = Tokenizer.from_file(str(directorio / FICHERO_TOKENIZADOR))
        return cls(sesion, tokenizer, leer_max_seq_length(directorio))

    def codificar(self, textos: Sequence[str], batch_size: int = 64) -> npt.NDArray[np.float32]:
        """Embeddings L2-normalizados, uno por texto y en el orden de entrada.

        Agrupa por longitud, como sentence-transformers, para que un lote no
        rellene veinte títulos cortos hasta el largo de un párrafo: el
        resultado no cambia (el relleno no cuenta en la media) y el cómputo sí.
        """
        if not textos:
            return np.zeros((0, 0), dtype=np.float32)
        codificados = self._tokenizer.encode_batch(list(textos))
        orden = sorted(range(len(codificados)), key=lambda i: -len(codificados[i].ids))
        salida: list[npt.NDArray[np.float32] | None] = [None] * len(codificados)
        paso = max(1, batch_size)
        for inicio in range(0, len(orden), paso):
            indices = orden[inicio : inicio + paso]
            vectores = self._codificar_lote([codificados[i].ids for i in indices])
            for fila, i in enumerate(indices):
                salida[i] = vectores[fila]
        return np.vstack([v for v in salida if v is not None]).astype(np.float32, copy=False)

    def _codificar_lote(self, ids_por_texto: list[list[int]]) -> npt.NDArray[np.float32]:
        largo = max(len(ids) for ids in ids_por_texto)
        input_ids = np.full((len(ids_por_texto), largo), self._pad_id, dtype=np.int64)
        mascara = np.zeros((len(ids_por_texto), largo), dtype=np.int64)
        for fila, ids in enumerate(ids_por_texto):
            input_ids[fila, : len(ids)] = ids
            mascara[fila, : len(ids)] = 1

        feed: dict[str, npt.NDArray[np.int64]] = {
            "input_ids": input_ids,
            "attention_mask": mascara,
        }
        if "token_type_ids" in self._entradas:
            feed["token_type_ids"] = np.zeros_like(input_ids)

        tokens = np.asarray(self._sesion.run([self._salida], feed)[0], dtype=np.float32)
        if tokens.ndim != 3:
            raise ModeloOnnxInvalido(
                f"La salida {self._salida!r} tiene forma {tokens.shape}: se esperaban "
                "embeddings de token (lote, secuencia, dimensión) para hacer mean pooling."
            )
        return _media_normalizada(tokens, mascara)


def _media_normalizada(
    tokens: npt.NDArray[np.float32], mascara: npt.NDArray[np.int64]
) -> npt.NDArray[np.float32]:
    """Mean pooling por máscara + L2, con los mismos epsilon que sentence-transformers.

    ``Pooling`` divide por ``clamp(sum(mask), min=1e-9)`` y
    ``torch.nn.functional.normalize`` por ``max(norma, 1e-12)``.
    """
    peso = mascara[..., np.newaxis].astype(np.float32)
    suma = (tokens * peso).sum(axis=1)
    cuenta = np.clip(peso.sum(axis=1), 1e-9, None)
    media = suma / cuenta
    norma = np.linalg.norm(media, axis=1, keepdims=True)
    # numpy tipa `np.clip` sobre float32 como Any; la anotación lo devuelve
    # al tipo real.
    normalizada: npt.NDArray[np.float32] = (media / np.maximum(norma, 1e-12)).astype(np.float32)
    return normalizada


def _id_de_relleno(tokenizer: Tokenizer) -> int:
    for token in _TOKENS_DE_RELLENO:
        token_id = tokenizer.token_to_id(token)
        if token_id is not None:
            return token_id
    # Sin token de relleno conocido da igual cuál: la máscara lo saca de la
    # media y de la atención.
    return 0


def _salida_de_token(sesion: SesionOnnx) -> str:
    nombres = [nodo.name for nodo in sesion.get_outputs()]
    if not nombres:
        raise ModeloOnnxInvalido("El grafo ONNX no declara salidas.")
    for preferida in _SALIDAS_DE_TOKEN:
        if preferida in nombres:
            return preferida
    return nombres[0]

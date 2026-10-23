"""Settings del codificador ONNX de embeddings (búsqueda por significado).

Módulo hermano de `config/settings.py` (P3 «Los dos módulos-dios»): un setting
**nuevo** va a un módulo por dominio. `Settings` hereda de esta clase, así que
la variable de entorno y el acceso (`settings.EMBEDDINGS_ONNX_DIR`) son los de
siempre.

Sin `model_config` propio, por lo mismo que `config/settings_resumen.py`: el de
`Settings` es el que manda al instanciar.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class EmbeddingsOnnxSettings(BaseSettings):
    """Dónde está el modelo ONNX con el que la API codifica la consulta."""

    # Directorio con `model.onnx` y `tokenizer.json` (y, si viene,
    # `sentence_bert_config.json` y el `origen.json` que escribe
    # `scripts/descargar_modelo_embeddings.py`). Vacío = desactivado: sin
    # sentence-transformers la búsqueda degrada a FTS, que es lo que hacía la
    # API hasta 2026-10. Tiene que ser el MISMO modelo que `EMBEDDING_MODEL`,
    # con el que se embebieron los fragmentos de `documento_chunks`: con otro,
    # el vector de la consulta y los guardados no son comparables
    # (`services/embeddings_onnx.py` lo comprueba contra `origen.json`).
    EMBEDDINGS_ONNX_DIR: str = ""

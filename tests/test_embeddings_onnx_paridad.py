"""Paridad del codificador ONNX con sentence-transformers (backlog P2, 3.1).

Los vectores de ``documento_chunks`` los calculó sentence-transformers; la API
codifica la consulta con ONNX (``services/embeddings_onnx.py``). Si los dos no
dan el mismo vector, la búsqueda por significado compara cosas distintas y
devuelve vecinos con aspecto de resultado. El listón —coseno ≥ 0,999 frase a
frase— es el de dos implementaciones del mismo grafo en float32, no el de dos
modelos «parecidos».

Solo corre donde están las dos cosas:

- el modelo ONNX, en ``EMBEDDINGS_ONNX_DIR`` (la imagen de la API lo trae en
  ``/opt/modelos/…``; en local, ``python scripts/descargar_modelo_embeddings.py``);
- sentence-transformers (extra ``[ml]``) con el modelo ya en la caché local de
  Hugging Face: el test no descarga nada (es ``unit`` y el guard de red de
  ``tests/conftest.py`` lo haría fallar).

Cuando se salta lo dice con el motivo; un salto aquí no es un verde.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from config import settings
from services.embeddings_onnx import CodificadorOnnx, modelo_onnx_presente

#: Frases fijas: objetos de contrato reales en forma y vocabulario, de largo
#: variado (una pasa del ``max_seq_length`` de 128 tokens para ejercer el
#: truncado), con tildes, eñes, siglas y cifras.
FRASES = [
    "Servicio de mantenimiento evolutivo de la plataforma SAP S/4HANA del Ayuntamiento",
    "Suministro de licencias de Microsoft 365 para el personal docente",
    "Limpieza de las dependencias municipales y del polideportivo",
    "Contratación del servicio de soporte técnico y centro de atención a usuarios (CAU)",
    "Adquisición de 250 ordenadores portátiles y monitores para la Consejería de Educación",
    "Migración de la infraestructura de servidores a la nube pública y servicios gestionados",
    "Auditoría de ciberseguridad y pruebas de intrusión en los sistemas del hospital",
    "Obras de reforma de la cubierta del colegio público Nuestra Señora del Pilar",
    "¿Dónde se publican los pliegos del contrato de recogida de residuos?",
    (
        "Servicio de desarrollo, implantación y mantenimiento de una plataforma de "
        "administración electrónica que integre el registro de entrada y salida, la "
        "gestión de expedientes, el portafirmas, la sede electrónica, las notificaciones "
        "por comparecencia y el archivo electrónico único, con interoperabilidad con los "
        "servicios comunes de la Administración General del Estado, migración de los "
        "datos históricos, formación a los empleados públicos y soporte durante dos años "
        "prorrogables por otros dos, incluyendo la adaptación al Esquema Nacional de "
        "Seguridad en categoría media y al Esquema Nacional de Interoperabilidad."
    ),
]

UMBRAL_COSENO = 0.999


def _directorio_modelo() -> Path:
    configurado = str(settings.EMBEDDINGS_ONNX_DIR or "").strip()
    if not configurado:
        pytest.skip("EMBEDDINGS_ONNX_DIR vacío: no hay modelo ONNX con el que comparar")
    directorio = Path(configurado)
    if not modelo_onnx_presente(directorio):
        pytest.skip(f"EMBEDDINGS_ONNX_DIR={configurado} no trae model.onnx y tokenizer.json")
    pytest.importorskip("onnxruntime", reason="onnxruntime no instalado")
    return directorio


def _modelo_sentence_transformers(monkeypatch: pytest.MonkeyPatch) -> Any:
    st = pytest.importorskip(
        "sentence_transformers", reason="sentence-transformers (extra [ml]) no instalado"
    )
    # Sin red: si el modelo no está ya en la caché local, se salta.
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    try:
        return st.SentenceTransformer(str(settings.EMBEDDING_MODEL), local_files_only=True)
    except Exception as exc:  # cualquier fallo de carga es «no está en la caché»
        pytest.skip(f"{settings.EMBEDDING_MODEL} no está en la caché local de Hugging Face: {exc}")


def test_onnx_reproduce_sentence_transformers(monkeypatch: pytest.MonkeyPatch) -> None:
    directorio = _directorio_modelo()
    referencia = _modelo_sentence_transformers(monkeypatch)

    esperados = np.asarray(
        referencia.encode(FRASES, batch_size=4, show_progress_bar=False, normalize_embeddings=True)
    )
    obtenidos = CodificadorOnnx.desde_directorio(directorio).codificar(FRASES, batch_size=4)

    assert obtenidos.shape == esperados.shape == (len(FRASES), 384)
    cosenos = (obtenidos * esperados).sum(axis=1)
    peor = int(np.argmin(cosenos))
    assert cosenos.min() >= UMBRAL_COSENO, (
        f"coseno {cosenos[peor]:.6f} < {UMBRAL_COSENO} en la frase {peor}: {FRASES[peor][:80]!r}"
    )

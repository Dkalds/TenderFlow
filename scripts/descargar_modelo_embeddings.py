"""Descarga el modelo ONNX de embeddings con revisión fija y sha256 verificado.

Lo usa ``docker/Dockerfile.api`` en la etapa builder para meter en la imagen de
la API el codificador de la consulta (``services/embeddings_onnx.py``), y sirve
igual en local para correr ``tests/test_embeddings_onnx_paridad.py``. Solo
biblioteca estándar: corre antes de que haya dependencias instaladas.

Qué baja, del repo de Hugging Face y en la revisión dada:

- ``onnx/model.onnx``           → ``<destino>/model.onnx``
- ``tokenizer.json``            → ``<destino>/tokenizer.json``
- ``sentence_bert_config.json`` → ``<destino>/sentence_bert_config.json``

y escribe ``<destino>/origen.json`` con el repo, la revisión y el sha256 de
cada fichero: ``services.embeddings`` lo coteja con ``EMBEDDING_MODEL`` antes de
usar el modelo.

Reglas, porque esto acaba en la imagen expuesta a internet:

- La revisión es un **commit** (40 hexadecimales), nunca una rama: ``main``
  puede cambiar de contenido entre dos builds.
- Cada fichero lleva su sha256 y no hay modo «sin verificar»: el hash es lo que
  convierte «lo que había en esa URL el día del build» en «lo que se revisó».
  Si alguno no cuadra, no se escribe nada en el destino.
- Sin revisión, no hace nada y sale con 0: la imagen se construye sin modelo y
  la API sigue degradando a FTS, como antes. Es el caso del CI y de cualquier
  build que no declare los argumentos.

Cómo obtener los hashes la primera vez (y al cambiar de revisión): la página de
cada fichero en Hugging Face muestra el «SHA256» de los que van por LFS
(``model.onnx``, ``tokenizer.json``); el de ``sentence_bert_config.json`` es el
``sha256sum`` del fichero descargado de esa misma revisión. Ver
``docs/runbooks/model-rollback.md`` § «Modelo ONNX de embeddings».

Uso::

    python scripts/descargar_modelo_embeddings.py \\
        --revision <commit> --destino /opt/modelos/embeddings \\
        --sha256-modelo <hex> --sha256-tokenizador <hex> --sha256-config <hex>

Los argumentos también se leen de ``EMBEDDINGS_ONNX_*`` (los del Dockerfile).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.request
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

REPO_POR_DEFECTO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
URL_BASE = "https://huggingface.co"

_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TROZO = 1024 * 1024
_TIMEOUT_S = 120


@dataclass(frozen=True)
class Fichero:
    """Un fichero del repo: dónde está allí, cómo se llama aquí y qué hash lleva."""

    ruta_en_repo: str
    nombre_local: str
    sha256: str


class DescargaInvalida(RuntimeError):
    """Argumentos mal formados o un fichero que no es el que se pidió."""


Abridor = Callable[[str], "_Respuesta"]


class _Respuesta:
    """Envoltorio mínimo de la respuesta HTTP: los tests lo sustituyen."""

    def __init__(self, cuerpo: BinaryIO) -> None:
        self._cuerpo = cuerpo

    def leer(self, n: int) -> bytes:
        return self._cuerpo.read(n)

    def cerrar(self) -> None:
        self._cuerpo.close()


def _abrir_url(url: str) -> _Respuesta:
    if not url.startswith("https://"):
        raise DescargaInvalida(f"Solo se descarga por HTTPS: {url}")
    peticion = urllib.request.Request(url, headers={"User-Agent": "tenderflow-build"})  # noqa: S310  # URL https fija, comprobada arriba
    return _Respuesta(urllib.request.urlopen(peticion, timeout=_TIMEOUT_S))  # noqa: S310  # idem


def ficheros(sha256_modelo: str, sha256_tokenizador: str, sha256_config: str) -> list[Fichero]:
    return [
        Fichero("onnx/model.onnx", "model.onnx", sha256_modelo),
        Fichero("tokenizer.json", "tokenizer.json", sha256_tokenizador),
        Fichero("sentence_bert_config.json", "sentence_bert_config.json", sha256_config),
    ]


def validar(revision: str, lista: Sequence[Fichero]) -> None:
    if not _COMMIT.match(revision):
        raise DescargaInvalida(
            f"La revisión tiene que ser un commit de 40 hexadecimales, no {revision!r}: "
            "una rama o un tag pueden cambiar de contenido entre dos builds."
        )
    for fichero in lista:
        if not _SHA256.match(fichero.sha256):
            raise DescargaInvalida(
                f"Falta el sha256 de {fichero.ruta_en_repo} (o no son 64 hexadecimales en "
                "minúscula): sin él no se descarga."
            )


def _descargar_uno(url: str, destino: Path, esperado: str, abrir: Abridor) -> None:
    resumen = hashlib.sha256()
    respuesta = abrir(url)
    try:
        with destino.open("wb") as salida:
            while trozo := respuesta.leer(_TROZO):
                resumen.update(trozo)
                salida.write(trozo)
    finally:
        respuesta.cerrar()
    obtenido = resumen.hexdigest()
    if obtenido != esperado:
        raise DescargaInvalida(
            f"sha256 de {url} no cuadra: esperado {esperado}, obtenido {obtenido}"
        )


@contextmanager
def _directorio_temporal(junto_a: Path) -> Iterator[Path]:
    junto_a.parent.mkdir(parents=True, exist_ok=True)
    temporal = Path(tempfile.mkdtemp(prefix=".descarga-", dir=junto_a.parent))
    try:
        yield temporal
    finally:
        shutil.rmtree(temporal, ignore_errors=True)


def descargar(
    *,
    repo: str,
    revision: str,
    destino: Path,
    lista: Sequence[Fichero],
    abrir: Abridor = _abrir_url,
) -> Path:
    """Descarga y verifica todo en un temporal; solo si todo cuadra, lo mueve al destino."""
    validar(revision, lista)
    with _directorio_temporal(destino) as temporal:
        for fichero in lista:
            url = f"{URL_BASE}/{repo}/resolve/{revision}/{fichero.ruta_en_repo}"
            _descargar_uno(url, temporal / fichero.nombre_local, fichero.sha256, abrir)
        origen = {
            "repo": repo,
            "revision": revision,
            "ficheros": {f.nombre_local: f.sha256 for f in lista},
        }
        (temporal / "origen.json").write_text(
            json.dumps(origen, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        destino.mkdir(parents=True, exist_ok=True)
        for hecho in temporal.iterdir():
            hecho.replace(destino / hecho.name)
    return destino


def main(argv: Sequence[str] | None = None) -> int:
    entorno = os.environ
    parser = argparse.ArgumentParser(
        description="Descarga el modelo ONNX de embeddings con revisión fija y sha256 verificado."
    )
    parser.add_argument("--repo", default=entorno.get("EMBEDDINGS_ONNX_REPO") or REPO_POR_DEFECTO)
    parser.add_argument("--revision", default=entorno.get("EMBEDDINGS_ONNX_REVISION", ""))
    parser.add_argument("--destino", type=Path, required=True)
    parser.add_argument("--sha256-modelo", default=entorno.get("EMBEDDINGS_ONNX_SHA256_MODELO", ""))
    parser.add_argument(
        "--sha256-tokenizador", default=entorno.get("EMBEDDINGS_ONNX_SHA256_TOKENIZADOR", "")
    )
    parser.add_argument("--sha256-config", default=entorno.get("EMBEDDINGS_ONNX_SHA256_CONFIG", ""))
    args = parser.parse_args(argv)

    destino: Path = args.destino
    if not args.revision:
        destino.mkdir(parents=True, exist_ok=True)
        print(
            "descargar_modelo_embeddings: sin EMBEDDINGS_ONNX_REVISION, la imagen va sin modelo "
            "ONNX y la búsqueda por significado degrada a FTS."
        )
        return 0
    lista = ficheros(args.sha256_modelo, args.sha256_tokenizador, args.sha256_config)
    try:
        descargar(repo=args.repo, revision=args.revision, destino=destino, lista=lista)
    except DescargaInvalida as exc:
        print(f"descargar_modelo_embeddings: {exc}", file=sys.stderr)
        return 1
    print(f"descargar_modelo_embeddings: {args.repo}@{args.revision} en {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

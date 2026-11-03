"""Repara el texto ya guardado de los PDF con las tildes cambiadas («ClÆusula»).

Desde el 2026-11-03 la extracción repara estos documentos al leerlos
(``shared/letras_cambiadas.py``); los que se extrajeron antes siguen con el
texto roto en ``documentos.texto`` y ``documento_pages``. Medido ese día sobre
una muestra del 6 %: el 1,5 % de las páginas, unas 6.000. Este script los
recorre por tramos de id, repara documento y páginas, y borra sus trozos para
que el job de embeddings los rehaga con el texto bueno.

Las fichas ya extraídas no se tocan: sus citas siguen casando, porque la
comparación de citas (``services/rag/fact_sheet.py::_normalize_quote``) ya
trata estas letras como iguales, y la sustitución no mueve ningún offset.

**Lo ejecuta el propietario contra producción** (dato de producción, AGENTS.md
§6): ver ``docs/runbooks/documentos-reencolar.md``. Por defecto solo cuenta::

    make reparar-letras-cambiadas               # cuenta, no escribe
    make reparar-letras-cambiadas APLICAR=1     # repara

    python scripts/reparar_letras_cambiadas.py [--aplicar] [--tramo N] [--json]

Requiere ``DATABASE_URL``. Es idempotente: un documento reparado ya no tiene la
huella y una segunda pasada no lo encuentra.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Protocol

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from shared.letras_cambiadas import (  # noqa: E402
    HUELLA_SQL,
    reparar_texto,
    tiene_letras_cambiadas,
)


class _Repo(Protocol):
    def max_documento_id(self) -> int: ...
    def ids_con_huella(self, huella_sql: str, *, desde_id: int, hasta_id: int) -> list[int]: ...
    # `Any`: es la forma de fila que devuelve el repositorio real.
    def get(self, documento_id: int) -> dict[str, Any] | None: ...
    def list_pages(self, documento_id: int) -> list[dict[str, Any]]: ...
    def reescribir_texto(
        self, documento_id: int, *, texto: str, paginas: dict[int, str]
    ) -> None: ...


def reparar(repo: _Repo, *, aplicar: bool, tramo: int = 2000) -> dict[str, int]:
    """Recorre los documentos y repara los que tienen la huella. Devuelve el recuento."""
    recuento = {"candidatos": 0, "reparados": 0, "paginas": 0}
    tope = repo.max_documento_id()
    for desde in range(0, tope + 1, tramo):
        for documento_id in repo.ids_con_huella(HUELLA_SQL, desde_id=desde, hasta_id=desde + tramo):
            recuento["candidatos"] += 1
            paginas = {
                int(p["page_number"]): str(p["texto"]) for p in repo.list_pages(documento_id)
            }
            if not tiene_letras_cambiadas(paginas.values()):
                continue
            documento = repo.get(documento_id) or {}
            reparadas = {numero: reparar_texto(texto) for numero, texto in paginas.items()}
            cambiadas = {n: t for n, t in reparadas.items() if t != paginas[n]}
            recuento["reparados"] += 1
            recuento["paginas"] += len(cambiadas)
            if aplicar:
                repo.reescribir_texto(
                    documento_id,
                    texto=reparar_texto(str(documento.get("texto") or "")),
                    paginas=cambiadas,
                )
    return recuento


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--aplicar",
        action="store_true",
        help="Repara de verdad. Sin esta opción solo se cuenta lo que se repararía.",
    )
    parser.add_argument("--tramo", type=int, default=2000, help="Documentos por consulta")
    parser.add_argument("--json", action="store_true", help="Salida en JSON")
    args = parser.parse_args(argv)

    from db.repositories.documentos import DocumentosRepository

    recuento = reparar(DocumentosRepository(), aplicar=args.aplicar, tramo=max(1, args.tramo))

    if args.json:
        print(json.dumps({"aplicado": args.aplicar, **recuento}, indent=2))
        return 0
    verbo = "Reparados" if args.aplicar else "Se repararían"
    print(
        f"{verbo} {recuento['reparados']} documentos ({recuento['paginas']} páginas); "
        f"{recuento['candidatos']} tenían alguna huella."
    )
    if not args.aplicar and recuento["reparados"]:
        print("Sin escribir nada. Repetí con --aplicar (make reparar-letras-cambiadas APLICAR=1).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

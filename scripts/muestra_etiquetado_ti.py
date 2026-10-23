"""Muestra estratificada para etiquetar «¿es TI?» a mano, y su vuelta al sistema.

Por qué existe
--------------
El gate real del binario ``es_ti`` es ``tests/fixtures/golden_ti.jsonl``, que
``scripts/exportar_golden_ti.py`` genera desde la revisión humana guardada en
``ml_feedback`` (``source='revision_ti'``). Hoy ese fichero solo tiene la
cabecera: la cola de ``/ops?vista=etiquetado`` se alimenta del desacuerdo con el
LLM, y la muestra del LLM (D3) sigue sin lanzarse. Este script da un camino
que no depende de eso: ~400 licitaciones estratificadas para que una persona
las etiquete leyendo el texto, sin propuesta de nadie delante.

Dos pasos::

    # 1. Generar la muestra SIN etiquetas (solo lectura contra la BD):
    ENV=dev PYTHONPATH="$PWD" python scripts/muestra_etiquetado_ti.py generar \\
        --salida data/etiquetado/muestra_ti.jsonl

    # 2. Tras etiquetar (rellenar `es_ti` y, si es TI, `tecnologia`), mandar las
    #    etiquetas a la API como revisión humana, igual que el formulario de /ops:
    TENDERFLOW_API_KEY=... python scripts/muestra_etiquetado_ti.py importar \\
        --entrada data/etiquetado/muestra_ti.jsonl --api-url https://<api>

Después, ``scripts/exportar_golden_ti.py`` regenera el golden como siempre.

Qué NO hace
-----------
- No etiqueta nada, ni con reglas ni con el LLM: una fila sin ``es_ti`` no se
  importa (una fila sin etiqueta **no** es un negativo, spec §3.5).
- No escribe en la BD directamente: ``importar`` pasa por ``POST
  /api/v1/feedback`` con una API key con scope ``feedback:write``, que es el
  camino auditado (``FEEDBACK_SUBMITTED``) por el que entra toda etiqueta humana.
- No promociona ningún modelo.

Instrucciones de etiquetado: ``docs/runbooks/etiquetado-ti.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

#: Tamaño de la muestra: ~500 revisiones era la estimación de D4 (~4 h); 400
#: deja margen para descartes («no se puede saber») sin bajar del orden.
TOTAL_POR_DEFECTO = 400
#: Semilla fija: con la misma tabla, la misma muestra.
SEMILLA_POR_DEFECTO = "etiquetado-ti-2026-10-23"
#: Primer año con estrato propio; lo anterior va a `antes`. Fijo (y no «hace
#: tres años») para que la muestra no cambie al cambiar de año.
ANIO_DESDE_POR_DEFECTO = 2023

#: Campos que rellena quien etiqueta. Se escriben vacíos.
CAMPOS_ETIQUETA = ("es_ti", "tecnologia", "tecnologias_secundarias", "nota", "etiquetado_por")

_CABECERA = """# Muestra estratificada para etiquetar «¿es TI?» a mano (plan 3.2).
# NO es el golden: no lleva etiquetas. Rellena `es_ti` (true/false) y, si es
# TI, `tecnologia` (y `tecnologias_secundarias` si aplica) siguiendo
# docs/runbooks/etiquetado-ti.md; deja `es_ti: null` si no se puede decidir.
# Se vuelca con `python scripts/muestra_etiquetado_ti.py importar`.
"""


def registro_sin_etiqueta(fila: Mapping[str, Any]) -> dict[str, Any]:
    """Una fila de la BD → una línea del fichero, con los campos de etiqueta vacíos."""
    return {
        "id_externo": str(fila["id_externo"]),
        "estrato": str(fila["estrato"]),
        "fuente": fila.get("fuente"),
        "fecha_publicacion": fila.get("fecha_publicacion"),
        "titulo": fila.get("titulo"),
        "descripcion": fila.get("descripcion"),
        "cpv": fila.get("cpv"),
        "organo_contratacion": fila.get("organo_contratacion"),
        "url": fila.get("url"),
        "es_ti": None,
        "tecnologia": None,
        "tecnologias_secundarias": [],
        "nota": "",
        "etiquetado_por": "",
    }


def escribir_muestra(registros: Iterable[Mapping[str, Any]], salida: Path, *, meta: str) -> int:
    salida.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with salida.open("w", encoding="utf-8") as f:
        f.write(_CABECERA)
        f.write(f"# {meta}\n")
        for registro in registros:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")
            n += 1
    return n


def leer_jsonl(ruta: Path) -> list[dict[str, Any]]:
    filas: list[dict[str, Any]] = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if linea.strip() and not linea.lstrip().startswith("#"):
            filas.append(json.loads(linea))
    return filas


class EtiquetaInvalida(ValueError):
    pass


def cuerpo_feedback(
    registro: Mapping[str, Any], etiquetas_validas: Sequence[str]
) -> dict[str, Any] | None:
    """El cuerpo de ``POST /feedback`` para una fila, o ``None`` si no está etiquetada.

    Valida aquí lo mismo que valida la API, para que un error de tecleo se vea
    antes de mandar nada en vez de a mitad del volcado.
    """
    es_ti = registro.get("es_ti")
    if es_ti is None:
        return None
    if not isinstance(es_ti, bool):
        raise EtiquetaInvalida(
            f"{registro.get('id_externo')}: es_ti debe ser true/false, no {es_ti!r}"
        )
    tecnologia = registro.get("tecnologia")
    secundarias = list(registro.get("tecnologias_secundarias") or [])
    validas = {e.upper() for e in etiquetas_validas}
    for valor in [tecnologia, *secundarias]:
        if valor is not None and str(valor).upper() not in validas:
            raise EtiquetaInvalida(
                f"{registro.get('id_externo')}: tecnología desconocida {valor!r}"
            )
    if not es_ti and (tecnologia or secundarias):
        raise EtiquetaInvalida(
            f"{registro.get('id_externo')}: es_ti=false con tecnología; una de las dos sobra"
        )
    nota = str(registro.get("nota") or "")
    autor = str(registro.get("etiquetado_por") or "").strip()
    if autor:
        nota = f"[muestra_etiquetado_ti · {autor}] {nota}".strip()
    return {
        "expediente": str(registro["id_externo"]),
        "relevante": es_ti,
        "nota": nota[:500],
        "tecnologia": str(tecnologia).upper() if tecnologia else None,
        "tecnologias_secundarias": [str(t).upper() for t in secundarias],
    }


Enviar = Callable[[dict[str, Any], str], int]


def _enviar_por_http(api_url: str, api_key: str) -> Enviar:
    import requests

    sesion = requests.Session()
    sesion.headers.update({"X-API-Key": api_key})

    def enviar(cuerpo: dict[str, Any], clave_idempotencia: str) -> int:
        respuesta = sesion.post(
            f"{api_url.rstrip('/')}/api/v1/feedback",
            json=cuerpo,
            headers={"Idempotency-Key": clave_idempotencia},
            timeout=30,
        )
        return int(respuesta.status_code)

    return enviar


def importar(
    registros: Sequence[Mapping[str, Any]],
    etiquetas_validas: Sequence[str],
    enviar: Enviar,
    *,
    semilla: str,
) -> dict[str, int]:
    """Valida todo primero; si algo no vale, no se manda nada."""
    cuerpos = [cuerpo_feedback(r, etiquetas_validas) for r in registros]
    resumen = {"enviadas": 0, "sin_etiqueta": 0, "fallidas": 0}
    for cuerpo in cuerpos:
        if cuerpo is None:
            resumen["sin_etiqueta"] += 1
            continue
        # La misma fila con la misma etiqueta no se duplica al relanzar.
        clave = f"muestra-ti:{semilla}:{cuerpo['expediente']}:{int(cuerpo['relevante'])}:{cuerpo['tecnologia']}"
        estado = enviar(cuerpo, clave[:200])
        resumen["enviadas" if 200 <= estado < 300 else "fallidas"] += 1
    return resumen


def _generar(args: argparse.Namespace) -> int:
    from db.repositories import muestra_etiquetado as repo
    from services.ml.muestra_estratificada import repartir_cuotas

    tamanos = repo.tamanos_estratos(anio_desde=args.anio_desde)
    cuotas = repartir_cuotas(tamanos, args.total)
    filas = repo.seleccionar(cuotas=cuotas, semilla=args.semilla, anio_desde=args.anio_desde)
    meta = (
        f"total={len(filas)} semilla={args.semilla} anio_desde={args.anio_desde} "
        f"estratos={len(cuotas)} universo={sum(tamanos.values())}"
    )
    n = escribir_muestra((registro_sin_etiqueta(f) for f in filas), args.salida, meta=meta)
    print(f"muestra_etiquetado_ti: {n} licitaciones en {args.salida} ({meta})")
    return 0


def _importar(args: argparse.Namespace) -> int:
    from config.keywords import TECH_LABELS

    api_key = os.environ.get("TENDERFLOW_API_KEY", "")
    if not api_key:
        print(
            "muestra_etiquetado_ti: falta TENDERFLOW_API_KEY (scope feedback:write)",
            file=sys.stderr,
        )
        return 2
    registros = leer_jsonl(args.entrada)
    try:
        resumen = importar(
            registros,
            list(TECH_LABELS),
            _enviar_por_http(args.api_url, api_key),
            semilla=args.semilla,
        )
    except EtiquetaInvalida as exc:
        print(f"muestra_etiquetado_ti: no se ha enviado nada — {exc}", file=sys.stderr)
        return 1
    print(f"muestra_etiquetado_ti: {resumen}")
    return 0 if resumen["fallidas"] == 0 else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Muestra para etiquetar «¿es TI?» a mano.")
    sub = parser.add_subparsers(dest="orden", required=True)

    gen = sub.add_parser("generar", help="Genera la muestra sin etiquetas (solo lectura)")
    gen.add_argument("--salida", type=Path, default=Path("data/etiquetado/muestra_ti.jsonl"))
    gen.add_argument("--total", type=int, default=TOTAL_POR_DEFECTO)
    gen.add_argument("--semilla", default=SEMILLA_POR_DEFECTO)
    gen.add_argument("--anio-desde", type=int, default=ANIO_DESDE_POR_DEFECTO)

    imp = sub.add_parser("importar", help="Manda las etiquetas a POST /api/v1/feedback")
    imp.add_argument("--entrada", type=Path, required=True)
    imp.add_argument("--api-url", required=True)
    imp.add_argument("--semilla", default=SEMILLA_POR_DEFECTO)

    args = parser.parse_args(argv)
    return _generar(args) if args.orden == "generar" else _importar(args)


if __name__ == "__main__":
    raise SystemExit(main())

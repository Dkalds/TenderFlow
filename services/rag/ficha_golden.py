"""Casos de referencia (golden) de la ficha del pliego.

Un caso es una carpeta con dos ficheros: ``paginas.jsonl`` —el texto por página
del expediente, tal como lo ve el extractor— y ``golden.json`` —los hechos que
una persona revisó, cada uno con su veredicto—. Este módulo solo los modela, los
lee y los escribe; el emparejamiento y las métricas viven en
``services/rag/ficha_eval.py``.

El porqué del formato está en ``docs/plans/2026-10-eval-ficha-pliego.md``. Lo
que importa aquí: un hecho que nadie revisó (``veredicto: null``) no es ni
acierto ni error, y el golden nunca envuelve ni modifica los modelos del
producto (``shared/tender_facts.py``): guarda cada hecho con la forma del
modelo de su familia y lo valida contra él.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, model_validator

from shared.tender_facts import FactItem, TenderFactSheet

Veredicto = Literal["correcto", "corregido", "añadido", "incorrecto"]

#: Veredictos que dejan un hecho cierto en el golden. ``corregido`` lo es por
#: el valor que escribió quien revisó, no por el que extrajo la app.
VEREDICTOS_POSITIVOS: frozenset[str] = frozenset({"correcto", "corregido", "añadido"})

FAMILIAS: tuple[str, ...] = tuple(TenderFactSheet.model_fields)

NOMBRE_GOLDEN = "golden.json"
NOMBRE_PAGINAS = "paginas.jsonl"
NOMBRE_PENDIENTES = "pendientes.json"

#: Lo único que se guarda de una página. ``uri`` queda fuera a propósito: las
#: de PLACSP llevan un token, y el eval no la necesita para nada.
CAMPOS_PAGINA: tuple[str, ...] = (
    "documento_id",
    "page_number",
    "tipo",
    "filename",
    "texto",
    "start_offset",
    "end_offset",
    "ocr",
)

#: Campos que identifican el dato de un hecho, por familia y en el orden en que
#: se comparan (``services.rag.ficha_eval.comparar_clave``). Son también los
#: únicos que la revisión deja corregir. Una familia sin campos solo se puede
#: emparejar por el texto de su cita.
CAMPOS_CLAVE: dict[str, tuple[str, ...]] = {
    "lots": ("lot_number", "amount_eur"),
    "award_criteria": ("weight_pct", "name"),
    "technical_solvency": (),
    "economic_solvency": ("amount_eur",),
    "guarantees": ("amount_eur",),
    "penalties": ("amount_eur",),
    "service_levels": ("name",),
    "subcontracting": (),
    "team_requirements": ("role", "minimum_years"),
    "certifications": ("name",),
    "extensions": (),
    "critical_deadlines": ("date_value", "name"),
    "technologies": ("name",),
    "price_formula": ("formula_type", "max_points"),
    "required_documents": ("name",),
    "rate_cards": ("role", "max_rate_eur_hour"),
    "budget_breakdown": ("category", "amount_eur"),
}


def modelo_de(familia: str) -> type[FactItem]:
    """Modelo de los elementos de una familia de ``TenderFactSheet``."""
    campo = TenderFactSheet.model_fields.get(familia)
    if campo is None:
        raise ValueError(f"Familia desconocida en la ficha del pliego: {familia!r}")
    (modelo,) = get_args(campo.annotation)
    if not (isinstance(modelo, type) and issubclass(modelo, FactItem)):
        raise TypeError(f"La familia {familia!r} no es una lista de hechos")
    return modelo


class HechoGolden(BaseModel):
    """Un hecho del golden y lo que una persona dijo de él."""

    model_config = ConfigDict(extra="forbid")

    veredicto: Veredicto | None
    # `Any`: la forma depende de la familia, que este modelo no conoce;
    # `CasoGolden` la valida contra `modelo_de(familia)`.
    hecho: dict[str, Any]
    #: Solo en ``corregido``: los campos clave tal como los extrajo la app,
    #: antes de la corrección. Es un error conocido, igual que un `incorrecto`.
    valor_extraido: dict[str, Any] | None = None


class CasoGolden(BaseModel):
    """Contenido de ``golden.json``."""

    model_config = ConfigDict(extra="forbid")

    licitacion_id: str
    #: ``True`` si alguien leyó el pliego entero y añadió lo que faltaba. Solo
    #: entonces un hecho extraído que no casa con nada es un falso positivo.
    completo: bool
    capturado_el: date
    extraction_version: str | None
    model: str | None
    status_origen: str | None
    hechos: dict[str, list[HechoGolden]]

    @model_validator(mode="after")
    def _hechos_con_la_forma_de_su_familia(self) -> CasoGolden:
        for familia, items in self.hechos.items():
            modelo = modelo_de(familia)
            for item in items:
                modelo.model_validate(item.hecho)
                if item.valor_extraido is not None:
                    modelo.model_validate({**item.hecho, **item.valor_extraido})
        return self


@dataclass(frozen=True)
class Caso:
    """Un caso leído de disco: su nombre, su golden y sus páginas."""

    nombre: str
    golden: CasoGolden
    # `Any`: filas de `documento_pages` con las claves de `CAMPOS_PAGINA`, la
    # misma forma que consume `services.rag.fact_sheet`.
    paginas: list[dict[str, Any]]


def positivos(golden: CasoGolden) -> dict[str, list[FactItem]]:
    """Hechos ciertos del caso, por familia (todas, aunque estén vacías)."""
    resultado: dict[str, list[FactItem]] = {familia: [] for familia in FAMILIAS}
    for familia, items in golden.hechos.items():
        modelo = modelo_de(familia)
        resultado[familia] = [
            modelo.model_validate(item.hecho)
            for item in items
            if item.veredicto in VEREDICTOS_POSITIVOS
        ]
    return resultado


def negativos(golden: CasoGolden) -> dict[str, list[FactItem]]:
    """Errores conocidos: los ``incorrecto`` y el valor original de cada ``corregido``."""
    resultado: dict[str, list[FactItem]] = {familia: [] for familia in FAMILIAS}
    for familia, items in golden.hechos.items():
        modelo = modelo_de(familia)
        for item in items:
            if item.veredicto == "incorrecto":
                resultado[familia].append(modelo.model_validate(item.hecho))
            elif item.veredicto == "corregido" and item.valor_extraido:
                resultado[familia].append(
                    modelo.model_validate({**item.hecho, **item.valor_extraido})
                )
    return resultado


def sin_revisar(golden: CasoGolden) -> int:
    """Cuántos hechos del caso siguen sin veredicto."""
    return sum(1 for items in golden.hechos.values() for item in items if item.veredicto is None)


def propuesta_desde_ficha(
    licitacion_id: str,
    # `Any`: la fila de `TenderFactSheetsRepository.get`, o `None` si no hay ficha.
    ficha: dict[str, Any] | None,
    *,
    completo: bool,
    hoy: date,
) -> CasoGolden:
    """Golden inicial de un caso: la ficha vigente, con todo sin veredicto.

    Una ficha ``failed`` o inexistente da un caso sin hechos, que es un caso
    válido: es justo el pliego donde lo que hay que medir es lo omitido.
    """
    fila = ficha or {}
    hechos: dict[str, list[HechoGolden]] = {}
    if fila.get("facts"):
        normalizada = TenderFactSheet.model_validate(fila["facts"]).model_dump(mode="json")
        hechos = {
            familia: [HechoGolden(veredicto=None, hecho=item) for item in items]
            for familia, items in normalizada.items()
            if items
        }
    return CasoGolden(
        licitacion_id=licitacion_id,
        completo=completo,
        capturado_el=hoy,
        extraction_version=_texto_o_none(fila.get("extraction_version")),
        model=_texto_o_none(fila.get("model")),
        status_origen=_texto_o_none(fila.get("status")),
        hechos=hechos,
    )


def _texto_o_none(valor: object) -> str | None:
    return None if valor is None else str(valor)


def listar_casos(raiz: Path) -> list[Path]:
    """Carpetas de ``raiz`` que contienen un ``golden.json``, en orden estable."""
    if not raiz.is_dir():
        return []
    return sorted(p for p in raiz.iterdir() if p.is_dir() and (p / NOMBRE_GOLDEN).is_file())


def leer_caso(carpeta: Path) -> Caso:
    """Lee y valida un caso. Lanza si el golden no encaja en su esquema."""
    golden = CasoGolden.model_validate_json((carpeta / NOMBRE_GOLDEN).read_text(encoding="utf-8"))
    ruta_paginas = carpeta / NOMBRE_PAGINAS
    paginas: list[dict[str, Any]] = []
    if ruta_paginas.is_file():
        paginas = [
            json.loads(linea)
            # `split("\n")` y no `splitlines()`: este también parte por U+2028,
            # U+2029 y U+0085, que `json.dumps` deja sin escapar dentro del texto.
            for linea in ruta_paginas.read_text(encoding="utf-8").split("\n")
            if linea.strip()
        ]
    return Caso(nombre=carpeta.name, golden=golden, paginas=paginas)


def escribir_golden(carpeta: Path, golden: CasoGolden) -> None:
    """Escribe ``golden.json`` entero. Atómico: a un temporal y luego rename.

    Se guarda después de cada veredicto, así que un corte a media escritura no
    puede dejar el fichero truncado: o está la versión anterior, o la nueva.
    """
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / NOMBRE_GOLDEN
    temporal = carpeta / (NOMBRE_GOLDEN + ".tmp")
    contenido = json.dumps(golden.model_dump(mode="json"), ensure_ascii=False, indent=2)
    # `newline="\n"`: en Windows `write_text` escribiría CRLF y el hook
    # `mixed-line-ending` tumbaría el primer intento de cada commit de un caso.
    temporal.write_text(contenido + "\n", encoding="utf-8", newline="\n")
    temporal.replace(destino)


def leer_pendientes(carpeta: Path) -> list[tuple[str, dict[str, Any]]]:
    """Hechos extraídos que nadie ha juzgado todavía, con su familia.

    Los deja ``scripts/eval_ficha.py --pendientes`` y los consume la revisión.
    Viven fuera de ``golden.json`` para que un caso ya etiquetado no vuelva a
    tener veredictos en ``null`` —y deje de evaluarse— por haber medido un
    extractor nuevo.
    """
    ruta = carpeta / NOMBRE_PENDIENTES
    if not ruta.is_file():
        return []
    return [
        (str(item["familia"]), dict(item["hecho"]))
        for item in json.loads(ruta.read_text(encoding="utf-8"))
    ]


def escribir_pendientes(carpeta: Path, pendientes: list[tuple[str, dict[str, Any]]]) -> None:
    """Escribe ``pendientes.json``; sin pendientes, borra el fichero."""
    ruta = carpeta / NOMBRE_PENDIENTES
    if not pendientes:
        ruta.unlink(missing_ok=True)
        return
    carpeta.mkdir(parents=True, exist_ok=True)
    temporal = carpeta / (NOMBRE_PENDIENTES + ".tmp")
    contenido = json.dumps(
        [{"familia": familia, "hecho": hecho} for familia, hecho in pendientes],
        ensure_ascii=False,
        indent=2,
    )
    temporal.write_text(contenido + "\n", encoding="utf-8", newline="\n")
    temporal.replace(ruta)


def escribir_paginas(carpeta: Path, paginas: list[dict[str, Any]]) -> int:
    """Escribe ``paginas.jsonl`` y devuelve los bytes escritos.

    Todas las páginas, también las vacías, y solo las claves de
    ``CAMPOS_PAGINA``. Las vacías se conservan porque producción las persiste
    y el selector trata la primera página de cada documento como portada:
    quitarlas haría que el eval eligiera otra portada que producción.
    """
    carpeta.mkdir(parents=True, exist_ok=True)
    lineas = [
        json.dumps(
            {campo: pagina[campo] for campo in CAMPOS_PAGINA if campo in pagina},
            ensure_ascii=False,
        )
        for pagina in paginas
    ]
    contenido = "".join(linea + "\n" for linea in lineas).encode("utf-8")
    (carpeta / NOMBRE_PAGINAS).write_bytes(contenido)
    return len(contenido)

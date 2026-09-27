"""El golden set real de «¿es TI?» y familias (plan de tres niveles, F2).

Sustituye a los 27 ejemplos de ``tests/fixtures/golden_set.jsonl``
(``services.ml_eval``, el binario SAP legacy) como gate del binario ``es_ti``
del plan de clasificación en tres niveles. La diferencia de fondo con aquel
golden set escrito a mano es la procedencia: este sale de la revisión humana
vigente en producción (``ml_feedback``, ``source='revision_ti'`` — ver
:data:`db.repositories.feedback.FUENTE_REVISION_TI`), así que crece solo con
lo que el equipo ya revisó, sin una campaña de etiquetado aparte.

Cada ejemplo lleva de dónde salió (``fuente``), cuándo se publicó la
licitación (``fecha``) y quién y cuándo lo etiquetó. El reparto es temporal y
fijo (spec: «reparto temporal fijo», holdout = el 50 % más reciente): la
primera exportación fija un corte, la fecha mediana (:func:`corte_mediano`), y
lo guarda en la cabecera del fichero (:data:`PREFIJO_CORTE_HOLDOUT`); cada
exportación posterior reparte contra ese corte (:func:`repartir`), así que
revisar después una licitación antigua no mueve un ejemplo de tune a holdout.
Igual que ``services.ml_eval.asignar_splits`` evita elegir el umbral donde se
reporta, pero aquí el criterio es temporal en vez de por hash, porque cada
ejemplo lleva fecha de publicación.

La Tarea 6 (informe de acuerdo LLM↔humano) construye su comparación sobre
:class:`EjemploGoldenTi`.

Uso típico::

    from db.repositories.feedback import FeedbackRepository
    from services.ml.golden_ti import RUTA_GOLDEN_TI, ejemplo_desde_fila, repartir

    filas = FeedbackRepository().filas_revision_ti()
    ejemplos, corte = repartir([ejemplo_desde_fila(f) for f in filas], RUTA_GOLDEN_TI)
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Literal

from config.keywords import TECH_LABEL_TIPO, TECH_LABELS
from observability.logging import get_logger

log = get_logger(__name__)

# Raíz del repo (este archivo vive en services/ml/).
_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Fichero real del golden set. Hoy solo tiene la cabecera: la revisión
#: humana (Tarea 4) todavía no ha corrido en producción. Lo regenera
#: ``scripts/exportar_golden_ti.py``.
RUTA_GOLDEN_TI: Path = _REPO_ROOT / "tests" / "fixtures" / "golden_ti.jsonl"

#: Línea de la cabecera que guarda el corte congelado del holdout: ``# corte_holdout:
#: AAAA-MM-DD``. Empieza por ``#``, así que :func:`cargar_golden_ti` la ignora
#: como cualquier comentario; la lee :func:`leer_corte_holdout`.
PREFIJO_CORTE_HOLDOUT = "# corte_holdout: "

_VALID_LABELS: frozenset[str] = frozenset(TECH_LABELS)
_SPLITS: frozenset[str] = frozenset({"tune", "holdout"})
#: Campos que toda línea necesita para construir un ``EjemploGoldenTi``.
#: ``cpv`` queda fuera (nullable, vía ``.get``); ``familias``/``fabricantes``
#: y ``split`` tienen su propia validación más abajo.
_CAMPOS_REQUERIDOS: tuple[str, ...] = (
    "id_externo",
    "fuente",
    "fecha",
    "titulo",
    "descripcion",
    "es_ti",
    "etiquetado_por",
    "etiquetado_at",
)


@dataclass(frozen=True)
class EjemploGoldenTi:
    """Un ejemplo del golden set real de «¿es TI?», con procedencia humana.

    Attributes:
        id_externo: Expediente de la licitación (``licitaciones.id_externo``).
        fuente: Fuente del anuncio (``licitaciones.fuente``): ``placsp``,
            ``pscp``…
        fecha: Fecha de publicación de la licitación (``fecha_publicacion``).
            Es la que reparte :func:`asignar_splits`, no la del etiquetado.
            Cadena vacía si la licitación no la tiene: ese ejemplo va a
            ``tune``.
        titulo: Título de la licitación.
        descripcion: Descripción / objeto del contrato. Cadena vacía si la
            licitación no tiene descripción (no es "sin dato": el humano la
            vio igual y decidió con lo que había).
        cpv: CPV de la licitación, si consta.
        es_ti: Si el humano dice que es TI (D1). Es lo único que significa
            ``ml_feedback.relevante`` desde el plan de tres niveles.
        familias: Etiquetas de categoría (``TECH_LABEL_TIPO == "categoria"``)
            que el humano marcó, sin repetidos y en el orden en que las
            escribió.
        fabricantes: Etiquetas de fabricante (``TECH_LABEL_TIPO ==
            "fabricante"``) que el humano marcó, sin repetidos y en el orden
            en que las escribió.
        etiquetado_por: Quién puso la etiqueta. Siempre ``"humano"``: el
            golden set es, por definición, juicio humano.
        etiquetado_at: Cuándo se etiquetó (``ml_feedback.created_at`` de la
            fila vigente para ese expediente).
        split: ``"tune"`` (elegir el umbral) u ``"holdout"`` (reportar). Lo
            asigna :func:`asignar_splits`; un ejemplo construido a mano (p.
            ej. en un test) lo declara explícitamente.
    """

    id_externo: str
    fuente: str
    fecha: str
    titulo: str
    descripcion: str
    cpv: str | None
    es_ti: bool
    familias: tuple[str, ...]
    fabricantes: tuple[str, ...]
    etiquetado_por: str
    etiquetado_at: str
    split: Literal["tune", "holdout"]


def _tecnologias_de_fila(fila: Mapping[str, object]) -> list[str]:
    """Tecnología principal + secundarias de una fila, sin repetidos y en orden.

    ``tecnologias_secundarias`` llega como JSON (lo escribe
    ``FeedbackRepository.insert``); ``None`` o cadena vacía cuentan como
    "ninguna", igual que ``tecnologia`` a ``None``.
    """
    combinadas: list[str] = []
    principal = fila.get("tecnologia")
    if principal:
        combinadas.append(str(principal))
    secundarias_raw = fila.get("tecnologias_secundarias")
    if secundarias_raw:
        for tecnologia in json.loads(str(secundarias_raw)):
            texto = str(tecnologia)
            if texto not in combinadas:
                combinadas.append(texto)
    return combinadas


def ejemplo_desde_fila(fila: Mapping[str, object]) -> EjemploGoldenTi:
    """Construye un ejemplo a partir de una fila de
    ``FeedbackRepository.filas_revision_ti``. Cada columna se convierte aquí
    a su tipo, así que la fila basta con que sea un mapping.

    Reparte ``tecnologia``/``tecnologias_secundarias`` en familias (categoría)
    y fabricantes según :data:`TECH_LABEL_TIPO`. El ``split`` se deja en
    ``"tune"`` como placeholder: el reparto real en tune/holdout lo hace
    :func:`asignar_splits`, que necesita ver el conjunto entero para partirlo
    por fecha.

    Una tecnología que no esté en :data:`TECH_LABEL_TIPO` (un label retirado
    o un dato legacy corrupto) no entra en ninguna de las dos tuplas, pero no
    desaparece en silencio: se loguea con el expediente y el valor, igual que
    :func:`cargar_golden_ti` falla en vez de tragarse una etiqueta mala.
    """
    expediente = str(fila["expediente"])
    combinadas = _tecnologias_de_fila(fila)
    familias: list[str] = []
    fabricantes: list[str] = []
    for tecnologia in combinadas:
        tipo = TECH_LABEL_TIPO.get(tecnologia)
        if tipo == "categoria":
            familias.append(tecnologia)
        elif tipo == "fabricante":
            fabricantes.append(tecnologia)
        else:
            log.warning(
                "golden_ti.tecnologia_desconocida",
                expediente=expediente,
                tecnologia=tecnologia,
            )
    fecha_publicacion = fila.get("fecha_publicacion")
    return EjemploGoldenTi(
        id_externo=expediente,
        fuente=str(fila["fuente"]),
        # Sin fecha, cadena vacía y no «None»: esa cadena ordena detrás de
        # cualquier fecha y metía el ejemplo en el holdout.
        fecha=str(fecha_publicacion) if fecha_publicacion is not None else "",
        titulo=str(fila["titulo"]),
        descripcion=str(fila.get("descripcion") or ""),
        cpv=str(fila["cpv"]) if fila.get("cpv") is not None else None,
        es_ti=bool(fila["relevante"]),
        familias=tuple(familias),
        fabricantes=tuple(fabricantes),
        etiquetado_por="humano",
        etiquetado_at=str(fila["created_at"]),
        split="tune",
    )


def _dia(fecha: str) -> str:
    """``AAAA-MM-DD`` de una fecha ISO, con hora o sin ella: el corte es un día."""
    return fecha[:10]


def corte_mediano(ejemplos: list[EjemploGoldenTi]) -> str | None:
    """El corte de la primera exportación: el día que deja en ``holdout`` la
    mitad más reciente de los ejemplos con fecha.

    Es el día del ejemplo que queda en la posición ``n // 2`` al ordenar por
    ``(fecha, id_externo)``: con fechas distintas, ``holdout`` son las
    ``n - n // 2`` más recientes (la mitad, o la mitad más uno con ``n``
    impar). Con varios ejemplos en el día del corte, van todos a ``holdout``:
    el corte es una fecha, no una posición. ``None`` si ningún ejemplo tiene
    fecha.
    """
    fechadas = sorted((e.fecha, e.id_externo) for e in ejemplos if e.fecha)
    if not fechadas:
        return None
    return _dia(fechadas[len(fechadas) // 2][0])


def asignar_splits(
    ejemplos: list[EjemploGoldenTi], corte: str | None = None
) -> list[EjemploGoldenTi]:
    """Reparte el golden set en ``tune``/``holdout`` contra un corte de fecha.

    ``holdout`` es todo ejemplo publicado el día ``corte`` o después; el resto
    va a ``tune``. El umbral se elige en el pasado y se reporta en el futuro
    más próximo, no al revés. Sin ``corte``, se usa el de
    :func:`corte_mediano` (el de una primera exportación); para las
    siguientes, el corte congelado lo da :func:`repartir`.

    Un ejemplo sin fecha no puede ser «de los más recientes»: va a ``tune``, y
    se avisa porque es un hueco del dato, no una decisión.

    A diferencia de ``services.ml_eval.asignar_splits`` (que reparte por hash
    del id para no reasignar ejemplos existentes al crecer el set a mano),
    aquí el criterio es temporal; lo que evita reasignar es que el corte no
    se recalcula.

    Devuelve una lista nueva, ordenada por ``(fecha, id_externo)`` — el orden
    en el que ``scripts/exportar_golden_ti.py`` escribe el fichero.
    """
    corte_vigente = corte if corte is not None else corte_mediano(ejemplos)
    resultado: list[EjemploGoldenTi] = []
    for ejemplo in sorted(ejemplos, key=lambda e: (e.fecha, e.id_externo)):
        split: Literal["tune", "holdout"] = "tune"
        if not ejemplo.fecha:
            log.warning("golden_ti.sin_fecha", id_externo=ejemplo.id_externo)
        elif corte_vigente is not None and _dia(ejemplo.fecha) >= corte_vigente:
            split = "holdout"
        resultado.append(replace(ejemplo, split=split))
    return resultado


def leer_corte_holdout(path: Path | None = None) -> str | None:
    """El corte congelado en la cabecera del golden, o ``None`` si el fichero
    no existe o todavía no lo trae (nunca se exportó con ejemplos).

    Args:
        path: Ruta al JSONL. Si es ``None``, :data:`RUTA_GOLDEN_TI`.
    """
    target = path if path is not None else RUTA_GOLDEN_TI
    if not target.exists():
        return None
    for linea in target.read_text(encoding="utf-8").splitlines():
        if linea.startswith(PREFIJO_CORTE_HOLDOUT):
            corte = linea[len(PREFIJO_CORTE_HOLDOUT) :].strip()
            return corte or None
    return None


def repartir(
    ejemplos: list[EjemploGoldenTi], path: Path | None = None
) -> tuple[list[EjemploGoldenTi], str | None]:
    """Reparte con el corte congelado en ``path`` o, si aún no hay ninguno, con
    uno nuevo en la mediana (:func:`corte_mediano`).

    Devuelve los ejemplos repartidos (ver :func:`asignar_splits`) y el corte
    usado, que el exportador escribe en la cabecera
    (:data:`PREFIJO_CORTE_HOLDOUT`) para la siguiente exportación.
    """
    corte = leer_corte_holdout(path) or corte_mediano(ejemplos)
    return asignar_splits(ejemplos, corte), corte


def a_linea(ejemplo: EjemploGoldenTi) -> str:
    """Serializa un ejemplo a una línea JSON, con claves en orden estable."""
    datos = asdict(ejemplo)
    datos["familias"] = list(datos["familias"])
    datos["fabricantes"] = list(datos["fabricantes"])
    return json.dumps(datos, ensure_ascii=False, sort_keys=True)


def cargar_golden_ti(path: Path | None = None) -> list[EjemploGoldenTi]:
    """Carga el golden set real. Tolera líneas vacías y comentarios (``#``).

    Args:
        path: Ruta al JSONL. Si es ``None``, :data:`RUTA_GOLDEN_TI`.

    Returns:
        Lista de :class:`EjemploGoldenTi`, en el orden del fichero. Vacía si
        el fichero no existe o solo tiene cabecera.

    Raises:
        ValueError: JSON inválido, falta alguno de :data:`_CAMPOS_REQUERIDOS`,
            ``split`` fuera de ``{"tune", "holdout"}``, o una familia/fabricante
            fuera de :data:`TECH_LABELS` — nombra el campo o valor malo, para
            que una línea rota no se cuele como un negativo silencioso.
    """
    target = path if path is not None else RUTA_GOLDEN_TI
    if not target.exists():
        log.warning("golden_ti.fichero_no_existe", path=str(target))
        return []

    ejemplos: list[EjemploGoldenTi] = []
    for lineno, raw_line in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Golden TI: JSON inválido en línea {lineno}: {exc}") from exc

        faltantes = [campo for campo in _CAMPOS_REQUERIDOS if campo not in obj]
        if faltantes:
            raise ValueError(f"Golden TI: faltan campos {faltantes} en línea {lineno}")

        split_raw = obj.get("split")
        if split_raw not in _SPLITS:
            raise ValueError(
                f"Golden TI: split inválido {split_raw!r} en línea {lineno}. "
                f"Válidos: {sorted(_SPLITS)}"
            )

        familias = tuple(str(t) for t in (obj.get("familias") or ()))
        fabricantes = tuple(str(t) for t in (obj.get("fabricantes") or ()))
        for etiqueta in (*familias, *fabricantes):
            if etiqueta not in _VALID_LABELS:
                raise ValueError(
                    f"Golden TI: etiqueta desconocida '{etiqueta}' en línea {lineno}. "
                    f"Válidas: {sorted(_VALID_LABELS)}"
                )

        ejemplos.append(
            EjemploGoldenTi(
                id_externo=str(obj["id_externo"]),
                fuente=str(obj["fuente"]),
                fecha=str(obj["fecha"] or ""),
                titulo=str(obj["titulo"]),
                descripcion=str(obj["descripcion"]),
                cpv=str(obj["cpv"]) if obj.get("cpv") is not None else None,
                es_ti=bool(obj["es_ti"]),
                familias=familias,
                fabricantes=fabricantes,
                etiquetado_por=str(obj["etiquetado_por"]),
                etiquetado_at=str(obj["etiquetado_at"]),
                split=split_raw,
            )
        )
    log.info("golden_ti.cargado", path=str(target), n=len(ejemplos))
    return ejemplos


__all__ = [
    "PREFIJO_CORTE_HOLDOUT",
    "RUTA_GOLDEN_TI",
    "EjemploGoldenTi",
    "a_linea",
    "asignar_splits",
    "cargar_golden_ti",
    "corte_mediano",
    "ejemplo_desde_fila",
    "leer_corte_holdout",
    "repartir",
]

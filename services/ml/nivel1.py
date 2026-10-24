"""Modelo de nivel 1, «¿es TI?» (plan de tres niveles, F3, §4).

Sustituye la etiqueta circular del binario de hoy («alguna keyword», en
:func:`services.ml.classifier_training.etiquetar_dataset_sap`) por etiquetas que
no salen de las reglas: la revisión humana (``ml_feedback``,
``source='revision_ti'``) y, solo si su acuerdo con los humanos pasa la regla
de §3.5 (:func:`services.ml.acuerdo_llm.medir_acuerdo`), el marcador ``es_ti``
del LLM.

Qué hay aquí:

- **Features** (§4): título + descripción real (en PLACSP la ``descripcion`` es
  el ``<summary>`` del Atom, «Id licitación; Órgano; Importe; Estado», y no
  entra), CPV como tokens jerárquicos de 2, 3 y 4 cifras **sin** el token
  ``CPV_TI`` que en la población puntuada vale siempre lo mismo, e idioma.
- **Dataset**: :func:`etiqueta_nivel1` (humano > LLM apto > nada; una fila sin
  etiqueta no es un negativo) y :func:`dataset_entrenamiento`, que deja fuera
  el golden entero —por id y por convocatoria casi idéntica— para que el
  holdout no se entrene.
- **Candidatos** A (TF-IDF de palabras y caracteres + LR), B (embeddings
  ``settings.EMBEDDING_MODEL`` + LR) y A+B, con calibración isotónica sobre el
  pliegue temporal más reciente del entrenamiento y reentrenamiento final con
  todo (:func:`entrenar_candidato`). No se submuestrean negativos.
- :func:`comparar_candidatos`: entrena, elige bandas en el ``tune`` del golden
  y evalúa en el ``holdout`` con :func:`services.ml.nivel1_eval.evaluar_nivel1`.

Qué **no** hay: lectura de la BD (``db.repositories.ml_dataset.
filas_etiquetadas_nivel1``), registro en ``model_versions``, publicación del
artefacto ni sombra. Lo junta ``scripts/entrenar_nivel1.py``, que no registra
ni activa nada.

El nombre técnico sigue siendo ``sap_classifier`` hasta F5 (§4): cuando un
candidato pase el gate y la sombra, se servirá por ese nombre y ``ml_proba``
pasará a ser P(es TI).
"""

from __future__ import annotations

import importlib.util
import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from config import CPV_PREFIXES_TI
from observability.logging import get_logger
from services.ml.classifier_pipeline import _clave_grupo, _fecha_clave
from services.ml.golden_ti import EjemploGoldenTi
from services.ml.nivel1_eval import (
    N_BOOTSTRAP,
    ORDEN_SIMPLICIDAD,
    SEMILLA_BOOTSTRAP,
    Bandas,
    CasoEval,
    InformeNivel1,
    elegir_bandas,
    evaluar_nivel1,
)

log = get_logger(__name__)

Origen = Literal["humano", "llm"]

#: Fracción más reciente del entrenamiento que calibra (isotónica, §4).
FRAC_CALIBRACION = 0.2
#: Por debajo de esto, la isotónica memoriza en vez de calibrar.
MIN_CALIBRACION = 30
MIN_ENTRENAMIENTO = 50

# ── Features ────────────────────────────────────────────────────────────────

#: El ``<summary>`` de PLACSP (``scraper.codice_parser._SUMMARY_RE``): metadatos,
#: no objeto del contrato. El nombre del órgano hacía de keyword.
_SUMMARY_PLACSP_RE = re.compile(
    r"Id licitaci[oó]n:.*?[ÓO]rgano de Contrataci[oó]n:", flags=re.IGNORECASE | re.DOTALL
)
_CPV_RE = re.compile(r"(?<![0-9])([0-9]{8})(?![0-9])")
_PALABRA_RE = re.compile(r"[a-zà-ÿ·']+")

#: Palabras que delatan el idioma y que no comparten las otras tres lenguas
#: oficiales. Es un rasgo grueso a propósito: el TF-IDF ya ve el texto, y el
#: token solo deja al modelo condicionar por lengua (la PSCP publica en catalán
#: y el diccionario casa peor ahí).
_MARCADORES_IDIOMA: dict[str, frozenset[str]] = {
    "es": frozenset(
        {"el", "los", "las", "del", "y", "con", "por", "servicio", "servicios", "suministro"}
        | {"mantenimiento", "ayuntamiento", "gestión"}
    ),
    "ca": frozenset(
        {"els", "les", "dels", "amb", "per", "i", "servei", "serveis", "subministrament"}
        | {"contractació", "manteniment", "ajuntament", "gestió"}
    ),
    "gl": frozenset(
        {"os", "as", "do", "da", "dos", "das", "e", "servizo", "servizos", "subministración"}
        | {"mantemento", "concello", "xestión"}
    ),
    "eu": frozenset(
        {"eta", "zerbitzua", "zerbitzuak", "kontratua", "hornidura", "hornikuntza"}
        | {"mantentze", "udala", "udalaren", "kudeaketa"}
    ),
}


def es_fuente_placsp(fuente: str | None) -> bool:
    texto = (fuente or "").lower()
    return texto.startswith(("placsp", "bulk_"))


def texto_nivel1(titulo: str | None, descripcion: str | None, fuente: str | None) -> str:
    """Título + descripción real. En PLACSP la descripción es el ``summary``
    (metadatos) y se descarta; en cualquier fuente, también si lo parece."""
    partes = [(titulo or "").strip()]
    desc = (descripcion or "").strip()
    if desc and not es_fuente_placsp(fuente) and not _SUMMARY_PLACSP_RE.search(desc):
        partes.append(desc)
    return " ".join(p for p in partes if p)


def codigos_cpv(cpv: str | None) -> list[str]:
    """Los códigos de 8 cifras del campo, con cualquier separador (PSCP une con ``||``)."""
    return list(dict.fromkeys(_CPV_RE.findall(cpv or "")))


def cpv_es_ti(cpv: str | None) -> bool:
    return any(c.startswith(tuple(CPV_PREFIXES_TI)) for c in codigos_cpv(cpv))


def tokens_cpv(cpv: str | None) -> list[str]:
    """CPV jerárquico: división (2), grupo (3) y clase (4) de cada código.

    Sin ``CPV_TI``: en la población puntuada (CPV 48/72 sin keyword) ese token
    vale siempre lo mismo y saturaba el modelo de mayo (§1).
    """
    tokens: list[str] = []
    for codigo in codigos_cpv(cpv):
        tokens += [f"CPV2_{codigo[:2]}", f"CPV3_{codigo[:3]}", f"CPV4_{codigo[:4]}"]
    return list(dict.fromkeys(tokens)) or ["CPV_NINGUNO"]


def idioma_aproximado(texto: str) -> str:
    """``es``/``ca``/``gl``/``eu`` por palabras marcadoras, o ``und``.

    Empate: gana el castellano si está entre los empatados (es la lengua por
    defecto de PLACSP); si no, el primero en orden alfabético, para que el
    resultado no dependa del orden del diccionario.
    """
    palabras = _PALABRA_RE.findall(unicodedata.normalize("NFC", texto.lower()))
    cuentas = {
        idioma: sum(1 for p in palabras if p in marcadores)
        for idioma, marcadores in _MARCADORES_IDIOMA.items()
    }
    maximo = max(cuentas.values(), default=0)
    if maximo == 0:
        return "und"
    empatados = sorted(i for i, n in cuentas.items() if n == maximo)
    return "es" if "es" in empatados else empatados[0]


def estructura_nivel1(cpv: str | None, texto: str) -> str:
    """Tokens no textuales: CPV jerárquico e idioma."""
    return " ".join([*tokens_cpv(cpv), f"LANG_{idioma_aproximado(texto)}"])


# ── Dataset ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FilaNivel1:
    """Un ejemplo etiquetado, ya con sus features."""

    id_externo: str
    fuente: str
    fecha: str
    titulo: str
    texto: str
    estructura: str
    es_ti: bool
    origen: Origen
    tiene_keyword: bool
    cpv_ti: bool

    @property
    def caso(self) -> CasoEval:
        return CasoEval(self.es_ti, self.tiene_keyword, self.cpv_ti)

    @property
    def grupo(self) -> str:
        return _clave_grupo(self.texto, "")


def etiqueta_nivel1(
    humano_es_ti: object, llm_es_ti: bool | None, *, usar_llm: bool
) -> tuple[bool, Origen] | None:
    """La etiqueta de entrenamiento de una fila, o ``None`` si no tiene.

    Manda el humano (``ml_feedback.relevante`` de la revisión vigente). El LLM
    solo si ``usar_llm`` —su acuerdo con el golden pasó §3.5— y si se
    pronunció: ``None`` incluye ``__sin_evidencia__``, que el lector de la BD ya
    trata como «no se pronunció» (nota de §6 para F3). Una fila sin etiqueta
    no es un negativo (§3.5): se queda fuera.
    """
    if humano_es_ti is not None:
        return bool(humano_es_ti), "humano"
    if usar_llm and llm_es_ti is not None:
        return bool(llm_es_ti), "llm"
    return None


def fila_desde_golden(ejemplo: EjemploGoldenTi, *, tiene_keyword: bool) -> FilaNivel1:
    """Un ejemplo del golden con las mismas features que el entrenamiento.

    ``tiene_keyword`` lo decide el llamador con la puerta de reglas vigente
    (``scraper.puerta_tecnologica.senal_tecnologica``): ``services`` no importa
    de ``scraper``.
    """
    texto = texto_nivel1(ejemplo.titulo, ejemplo.descripcion, ejemplo.fuente)
    return FilaNivel1(
        id_externo=ejemplo.id_externo,
        fuente=ejemplo.fuente,
        fecha=_fecha_clave(ejemplo.fecha) or "",
        titulo=ejemplo.titulo,
        texto=texto,
        estructura=estructura_nivel1(ejemplo.cpv, texto),
        es_ti=ejemplo.es_ti,
        origen="humano",
        tiene_keyword=tiene_keyword,
        cpv_ti=cpv_es_ti(ejemplo.cpv),
    )


@dataclass(frozen=True)
class ResumenDataset:
    """Qué entró y qué no, para el informe."""

    n_filas: int
    n_etiquetadas: int
    n_humanas: int
    n_llm: int
    n_positivos: int
    excluidas_golden_id: int
    excluidas_golden_grupo: int
    usar_llm: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "n_filas_leidas": self.n_filas,
            "n_etiquetadas": self.n_etiquetadas,
            "n_humanas": self.n_humanas,
            "n_llm": self.n_llm,
            "n_positivos": self.n_positivos,
            "pct_positivos": (
                round(100.0 * self.n_positivos / self.n_etiquetadas, 2)
                if self.n_etiquetadas
                else 0.0
            ),
            "excluidas_por_id_del_golden": self.excluidas_golden_id,
            "excluidas_por_convocatoria_del_golden": self.excluidas_golden_grupo,
            "usa_etiquetas_llm": self.usar_llm,
        }


def dataset_entrenamiento(
    filas: Sequence[Mapping[str, Any]],  # filas psycopg de filas_etiquetadas_nivel1
    golden: Sequence[EjemploGoldenTi],
    *,
    usar_llm: bool,
) -> tuple[list[FilaNivel1], ResumenDataset]:
    """Las filas etiquetadas que entrenan, fuera el golden entero.

    El golden (tune **y** holdout) no entrena: el tune elige los umbrales y el
    holdout decide el gate, y los dos tienen que ser fuera de muestra. Se
    excluye por id y por convocatoria (:func:`_clave_grupo`): un lote o una
    republicación casi idéntica de un ejemplo del golden en el entrenamiento
    es el mismo ejemplo con otro id.

    ``filas`` son las de ``db.repositories.ml_dataset.filas_etiquetadas_nivel1``:
    ``id_externo``, ``fuente``, ``fecha_publicacion``, ``titulo``,
    ``descripcion``, ``cpv``, ``tecnologia``, ``humano_es_ti`` y ``llm_es_ti``.
    """
    ids_golden = {e.id_externo for e in golden}
    grupos_golden = {
        _clave_grupo(texto_nivel1(e.titulo, e.descripcion, e.fuente), "") for e in golden
    }
    salida: list[FilaNivel1] = []
    por_id = por_grupo = 0
    for fila in filas:
        etiqueta = etiqueta_nivel1(
            fila.get("humano_es_ti"), fila.get("llm_es_ti"), usar_llm=usar_llm
        )
        if etiqueta is None:
            continue
        id_externo = str(fila["id_externo"])
        if id_externo in ids_golden:
            por_id += 1
            continue
        fuente = str(fila.get("fuente") or "")
        texto = texto_nivel1(
            str(fila.get("titulo") or ""), str(fila.get("descripcion") or ""), fuente
        )
        if _clave_grupo(texto, "") in grupos_golden:
            por_grupo += 1
            continue
        cpv = fila.get("cpv")
        cpv_txt = str(cpv) if cpv is not None else None
        salida.append(
            FilaNivel1(
                id_externo=id_externo,
                fuente=fuente,
                fecha=_fecha_clave(fila.get("fecha_publicacion")) or "",
                titulo=str(fila.get("titulo") or ""),
                texto=texto,
                estructura=estructura_nivel1(cpv_txt, texto),
                es_ti=etiqueta[0],
                origen=etiqueta[1],
                tiene_keyword=bool(str(fila.get("tecnologia") or "").strip()),
                cpv_ti=cpv_es_ti(cpv_txt),
            )
        )
    resumen = ResumenDataset(
        n_filas=len(filas),
        n_etiquetadas=len(salida),
        n_humanas=sum(1 for f in salida if f.origen == "humano"),
        n_llm=sum(1 for f in salida if f.origen == "llm"),
        n_positivos=sum(1 for f in salida if f.es_ti),
        excluidas_golden_id=por_id,
        excluidas_golden_grupo=por_grupo,
        usar_llm=usar_llm,
    )
    return salida, resumen


# ── Candidatos ──────────────────────────────────────────────────────────────


def embeddings_disponibles() -> bool:
    """B y A+B necesitan ``sentence-transformers`` (extra opcional, arrastra torch)."""
    return importlib.util.find_spec("sentence_transformers") is not None


def construir_candidato(nombre: str, *, min_df: int = 2) -> Any:  # sklearn Pipeline (sin stubs)
    """El pipeline sin entrenar de un candidato de §4.

    Entrada: un DataFrame con columnas ``texto`` y ``estructura``. La
    estructura (CPV e idioma) entra en los tres como bolsa de tokens binaria;
    sin ella B no vería el CPV.
    """
    from sklearn.compose import ColumnTransformer
    from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import MaxAbsScaler

    if nombre not in ORDEN_SIMPLICIDAD:
        raise ValueError(f"candidato desconocido: {nombre!r}; válidos {ORDEN_SIMPLICIDAD}")
    transformadores: list[tuple[str, Any, str]] = []
    if nombre in ("A", "A+B"):
        transformadores += [
            (
                "word",
                TfidfVectorizer(
                    analyzer="word",
                    ngram_range=(1, 2),
                    max_features=20_000,
                    sublinear_tf=True,
                    min_df=min_df,
                    strip_accents="unicode",
                ),
                "texto",
            ),
            (
                "char",
                TfidfVectorizer(
                    analyzer="char_wb",
                    ngram_range=(2, 4),
                    max_features=15_000,
                    sublinear_tf=True,
                    min_df=min_df,
                ),
                "texto",
            ),
        ]
    if nombre in ("B", "A+B"):
        from services.ml.classifier_pipeline import SentenceEmbeddingTransformer

        transformadores.append(("embeddings", SentenceEmbeddingTransformer(), "texto"))
    transformadores.append(
        (
            "estructura",
            CountVectorizer(token_pattern=r"\S+", lowercase=False, binary=True),  # noqa: S106  # nosec B106 — patrón de tokens, no una contraseña
            "estructura",
        )
    )
    return Pipeline(
        [
            ("features", ColumnTransformer(transformadores)),
            ("scaler", MaxAbsScaler()),
            (
                "clf",
                # `balanced` pesa, no submuestrea: todas las filas entrenan y
                # la isotónica devuelve la probabilidad a la prevalencia real.
                LogisticRegression(C=1.0, max_iter=1000, class_weight="balanced", random_state=42),
            ),
        ]
    )


def _marco(filas: Sequence[FilaNivel1]) -> Any:  # pandas.DataFrame
    import pandas as pd

    return pd.DataFrame(
        {"texto": [f.texto for f in filas], "estructura": [f.estructura for f in filas]}
    )


class DatosInsuficientes(ValueError):
    """El entrenamiento no da para ajustar o calibrar con las dos clases."""


@dataclass
class ModeloNivel1:
    """Un candidato entrenado: pipeline base + calibrador isotónico.

    ``bandas`` se rellenan después, en el ``tune`` del golden.
    """

    nombre: str
    base: Any  # sklearn Pipeline (sin stubs)
    calibrador: Any  # sklearn IsotonicRegression (sin stubs)
    bandas: Bandas | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def predict_proba(self, filas: Sequence[FilaNivel1]) -> list[float]:
        """P(es TI) calibrada, en el orden de ``filas``."""
        if not filas:
            return []
        crudo = self.base.predict_proba(_marco(filas))[:, 1]
        return [min(1.0, max(0.0, float(p))) for p in self.calibrador.predict(crudo)]


def _clases(filas: Sequence[FilaNivel1]) -> tuple[int, int]:
    positivos = sum(1 for f in filas if f.es_ti)
    return positivos, len(filas) - positivos


def entrenar_candidato(
    nombre: str,
    filas: Sequence[FilaNivel1],
    *,
    frac_calibracion: float = FRAC_CALIBRACION,
    min_df: int = 2,
    construir: Callable[[str], Any] | None = None,
) -> ModeloNivel1:
    """Ajusta, calibra en el pliegue temporal más reciente y reentrena con todo.

    1. Ordena por ``(fecha, id)``; el último ``frac_calibracion`` calibra y el
       resto ajusta. Temporal, como el holdout del golden: el modelo se
       calibra sobre lo que viene después de lo que aprendió.
    2. Isotónica sobre la salida cruda en ese pliegue, con su prevalencia real.
    3. Reentrena el pipeline con todas las filas (§4: «al final se reentrena
       con todos los datos») y conserva el calibrador.

    Raises:
        DatosInsuficientes: menos de :data:`MIN_ENTRENAMIENTO` filas, menos de
            :data:`MIN_CALIBRACION` en el pliegue de calibración, o alguna
            parte sin las dos clases.
    """
    from sklearn.isotonic import IsotonicRegression

    hacer = construir or (lambda n: construir_candidato(n, min_df=min_df))
    if len(filas) < MIN_ENTRENAMIENTO:
        raise DatosInsuficientes(f"{len(filas)} filas etiquetadas < {MIN_ENTRENAMIENTO}")
    ordenadas = sorted(filas, key=lambda f: (f.fecha, f.id_externo))
    corte = int(len(ordenadas) * (1.0 - frac_calibracion))
    ajuste, calibracion = ordenadas[:corte], ordenadas[corte:]
    if len(calibracion) < MIN_CALIBRACION:
        raise DatosInsuficientes(
            f"pliegue de calibración de {len(calibracion)} filas < {MIN_CALIBRACION}"
        )
    for parte, nombre_parte in (
        (ajuste, "ajuste"),
        (calibracion, "calibración"),
        (ordenadas, "total"),
    ):
        pos, neg = _clases(parte)
        if pos == 0 or neg == 0:
            raise DatosInsuficientes(f"{nombre_parte}: {pos} positivos y {neg} negativos")

    base = hacer(nombre)
    base.fit(_marco(ajuste), [f.es_ti for f in ajuste])
    crudo = base.predict_proba(_marco(calibracion))[:, 1]
    calibrador = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    calibrador.fit(crudo, [1.0 if f.es_ti else 0.0 for f in calibracion])

    final = hacer(nombre)
    final.fit(_marco(ordenadas), [f.es_ti for f in ordenadas])
    pos_total, _ = _clases(ordenadas)
    pos_cal, _ = _clases(calibracion)
    return ModeloNivel1(
        nombre=nombre,
        base=final,
        calibrador=calibrador,
        metadata={
            "n_entrenamiento": len(ordenadas),
            "n_ajuste": len(ajuste),
            "n_calibracion": len(calibracion),
            "prevalencia_entrenamiento": round(pos_total / len(ordenadas), 4),
            "prevalencia_calibracion": round(pos_cal / len(calibracion), 4),
            "calibracion_desde": calibracion[0].fecha,
            "calibracion": "isotonic_temporal",
        },
    )


@dataclass(frozen=True)
class ResultadoComparacion:
    """Los modelos entrenados y el informe que decide entre ellos."""

    modelos: dict[str, ModeloNivel1]
    informe: InformeNivel1


def comparar_candidatos(
    entrenamiento: Sequence[FilaNivel1],
    tune: Sequence[FilaNivel1],
    holdout: Sequence[FilaNivel1],
    *,
    candidatos: Sequence[str] = ORDEN_SIMPLICIDAD,
    n_bootstrap: int = N_BOOTSTRAP,
    semilla: int = SEMILLA_BOOTSTRAP,
    min_df: int = 2,
    construir: Callable[[str], Any] | None = None,
) -> ResultadoComparacion:
    """Entrena cada candidato, fija sus bandas en ``tune`` y evalúa en ``holdout``.

    Un candidato que no se puede entrenar (sin embeddings, datos que no dan)
    queda en ``informe.sin_evaluar`` con el motivo, y el resto sigue.
    """
    modelos: dict[str, ModeloNivel1] = {}
    sin_evaluar: dict[str, str] = {}
    scores: dict[str, list[float]] = {}
    bandas: dict[str, Bandas] = {}
    y_tune = [f.es_ti for f in tune]
    for nombre in candidatos:
        if construir is None and nombre in ("B", "A+B") and not embeddings_disponibles():
            sin_evaluar[nombre] = "sentence-transformers no está instalado"
            continue
        try:
            modelo = entrenar_candidato(nombre, entrenamiento, min_df=min_df, construir=construir)
        except DatosInsuficientes as exc:
            sin_evaluar[nombre] = str(exc)
            continue
        if any(y_tune):
            modelo.bandas = elegir_bandas(y_tune, modelo.predict_proba(tune))
            bandas[nombre] = modelo.bandas
        modelos[nombre] = modelo
        scores[nombre] = modelo.predict_proba(holdout)
        log.info("nivel1.candidato_entrenado", candidato=nombre, **modelo.metadata)

    informe = evaluar_nivel1(
        [f.caso for f in holdout],
        scores,
        bandas,
        sin_evaluar=sin_evaluar,
        n_bootstrap=n_bootstrap,
        semilla=semilla,
    )
    return ResultadoComparacion(modelos=modelos, informe=informe)


__all__ = [
    "FRAC_CALIBRACION",
    "MIN_CALIBRACION",
    "MIN_ENTRENAMIENTO",
    "DatosInsuficientes",
    "FilaNivel1",
    "ModeloNivel1",
    "ResultadoComparacion",
    "ResumenDataset",
    "codigos_cpv",
    "comparar_candidatos",
    "construir_candidato",
    "cpv_es_ti",
    "dataset_entrenamiento",
    "embeddings_disponibles",
    "entrenar_candidato",
    "es_fuente_placsp",
    "estructura_nivel1",
    "etiqueta_nivel1",
    "fila_desde_golden",
    "idioma_aproximado",
    "texto_nivel1",
    "tokens_cpv",
]

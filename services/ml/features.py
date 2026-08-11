"""Extracción de features para los modelos predictivos (Fase 6, RFC 20260611-2).

Tres garantías que este módulo sostiene, y que antes no sostenía:

**1. Ancla temporal única.** Cada observación se mira desde la fecha de
publicación de su licitación, en entrenamiento y en scoring. Antes las features
estacionales se anclaban a ``fecha_adjudicacion`` al entrenar y a
``datetime.now()`` al servir --dos eventos distintos-- y los agregados
históricos se calculaban as-of-adjudicación, meses de información que en
scoring todavía no existen. El precio de la simetría es descartar el histórico
posterior a la publicación de una licitación abierta antigua; la alternativa
era una distribución de entrada distinta en cada camino.

**2. Ausencia de fuga temporal.** Las filas se recorren en orden de fecha
ancla y los eventos de adjudicación se incorporan a los acumuladores solo
cuando su fecha es **estrictamente anterior** al ancla de la fila que se está
calculando (merge de dos flujos ordenados, :func:`_procesar`). Como el ancla
está acotada a no superar la fecha de adjudicación (``LEAST`` en
``db.repositories.ml_dataset``), una fila nunca puede ver su propio resultado
ni ninguno posterior a su publicación.

**3. Features que existen al predecir.** Ninguna columna se lee de
``adjudicaciones``. ``n_ofertas_recibidas`` era la señal más fuerte del
dataset y solo existe *después* de adjudicar: en scoring era NaN en el 100% de
las filas, así que el MAE de validación describía un modelo que no era el que
se servía. Se sustituye por la competencia **histórica** del segmento
(``n_ofertas_media_*``), que sí se conoce antes de adjudicar.

Los agregados históricos van suavizados (empirical Bayes hacia el prior del
segmento padre) y acompañados de su ``n_obs``: un órgano con una sola
observación entregaba antes ese valor a cara descubierta. El HHI del segmento
usa ventana expansiva (todo el histórico estricto anterior al ancla) en lugar
de 24 meses móviles -- misma garantía anti-fuga, coste O(1) por fila.

Sin dependencias nuevas: dict/deque de stdlib; numpy solo aparece en los
módulos de modelo.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from db.repositories.ml_dataset import MlDatasetRepository
from shared.estados import ESTADOS_CERRADOS

# Bandas de importe con cortes en los umbrales SARA habituales (€, sin IVA).
_BANDAS_IMPORTE = (15_000.0, 60_000.0, 143_000.0, 221_000.0, 750_000.0, 5_538_000.0)

# Ventanas de los agregados históricos de baja: la larga da nivel estable, la
# corta permite seguir un desplazamiento reciente. Un GBM no extrapola
# tendencia, así que el nivel reciente hay que dárselo explícito.
_VENTANA_MESES = 24
_VENTANA_CORTA_MESES = 6

# Peso del prior en el suavizado empirical-Bayes de las medias por segmento:
# con n observaciones, la media publicada es (n*media + k*prior) / (n + k).
# k = 10 significa "hasta ~10 observaciones confío más en el segmento padre".
_SHRINKAGE_K_DEFECTO = 10.0

# Plazo de presentación admisible (días). Fuera de rango son errores de fuente
# (fecha límite anterior a la publicación, o plazos de años).
_PLAZO_MAX_DIAS = 400

# Unidades de duración de CODICE a meses (mismo mapeo que FECHA_FIN_SQL).
_UNIDAD_A_MESES = {"ANN": 12.0, "MON": 1.0, "DAY": 1.0 / 30.0}

# Clave única del acumulador global (prior del suavizado). Reutiliza _MediaMovil
# para que el prior comparta ventana temporal con las medias por segmento.
_CLAVE_GLOBAL = "__global__"

# Orden canónico de columnas del dataset (el modelo depende de él y
# ``BajaModel.predict`` lo verifica contra el que se serializó).
FEATURE_COLUMNS: tuple[str, ...] = (
    # categóricas
    "cpv2",
    "cpv4",
    "tipo_contrato",
    "ccaa",
    "provincia",
    "organo",
    "fuente",
    "banda_importe",
    # numéricas (NaN permitido — HistGradientBoosting lo maneja nativo)
    "log_importe",
    "plazo_dias",
    "duracion_meses",
    "log_importe_mensual",
    "n_lotes",
    "mes",
    "trimestre",
    "baja_media_organo",
    "baja_media_cpv4",
    "baja_media_organo_cpv4",
    "baja_media_cpv4_6m",
    "baja_media_organo_cpv4_6m",
    "baja_std_cpv4",
    "n_obs_organo",
    "n_obs_cpv4",
    "n_obs_organo_cpv4",
    "n_ofertas_media_cpv4",
    "n_ofertas_media_organo_cpv4",
    "hhi_segmento",
)
CATEGORICAL_COLUMNS: tuple[str, ...] = FEATURE_COLUMNS[:8]


@dataclass
class FilaDataset:
    """Una observación: features + target (None en filas de scoring)."""

    licitacion_id: str
    fecha: str
    features: dict[str, Any]
    baja: float | None = None


@dataclass
class _Evento:
    """Adjudicación resuelta que alimenta los acumuladores históricos."""

    fecha: datetime
    organo: str | None
    cpv4: str | None
    baja: float
    n_ofertas: float | None


@dataclass
class _Cuota:
    """Importe que una empresa se llevó de un expediente (alimenta el HHI)."""

    fecha: datetime
    cpv4: str | None
    ccaa: str | None
    empresa: Any
    importe: float


def _banda_importe(importe: float | None) -> str:
    if not importe or importe <= 0:
        return "b_na"
    for i, corte in enumerate(_BANDAS_IMPORTE):
        if importe < corte:
            return f"b{i}"
    return f"b{len(_BANDAS_IMPORTE)}"


def _cpv4(cpv: str | None) -> str | None:
    digits = (cpv or "").strip()[:4]
    return digits if len(digits) == 4 and digits.isdigit() else None


def _fecha_dt(fecha: str) -> datetime:
    return datetime.strptime(fecha[:10], "%Y-%m-%d")


def _fecha_opt(fecha: Any) -> datetime | None:
    """Parseo tolerante: las columnas de fecha son TEXT y admiten basura."""
    if not fecha:
        return None
    try:
        return _fecha_dt(str(fecha))
    except ValueError:
        return None


def _plazo_dias(publicacion: Any, limite: Any) -> float | None:
    """Días entre publicación y fecha límite de presentación.

    Proxy de tramitación urgente: un plazo corto reduce el número de
    licitadores y con él la baja. ``None`` fuera de rango plausible.
    """
    pub, lim = _fecha_opt(publicacion), _fecha_opt(limite)
    if pub is None or lim is None:
        return None
    dias = (lim - pub).days
    return float(dias) if 0 <= dias <= _PLAZO_MAX_DIAS else None


def _duracion_meses(valor: Any, unidad: Any) -> float | None:
    if valor is None:
        return None
    factor = _UNIDAD_A_MESES.get(str(unidad or "").strip().upper())
    if factor is None:
        return None
    meses = float(valor) * factor
    return meses if meses > 0 else None


def _shrink(
    n: int, media: float | None, prior: float | None, k: float = _SHRINKAGE_K_DEFECTO
) -> float | None:
    """Media suavizada hacia ``prior`` con peso ``k`` (empirical Bayes)."""
    if media is None or n <= 0:
        return prior
    if prior is None:
        return media
    return (n * media + k * prior) / (n + k)


class _MediaMovil:
    """Media móvil por clave con ventana temporal, con conteo y dispersión.

    Las consultas llegan en orden de fecha no decreciente (las filas se
    procesan ordenadas por su ancla) y el recorte de la cola es destructivo:
    consultar hacia atrás daría un resultado incorrecto.
    """

    def __init__(self, meses: int = _VENTANA_MESES) -> None:
        self._delta = timedelta(days=meses * 30)
        self._colas: dict[str, deque[tuple[datetime, float]]] = defaultdict(deque)
        self._sumas: dict[str, float] = defaultdict(float)
        self._sumas_sq: dict[str, float] = defaultdict(float)

    def _recortar(self, clave: str, fecha: datetime) -> deque[tuple[datetime, float]]:
        cola = self._colas[clave]
        limite = fecha - self._delta
        while cola and cola[0][0] < limite:
            _, valor = cola.popleft()
            self._sumas[clave] -= valor
            self._sumas_sq[clave] -= valor * valor
        return cola

    def stats(self, clave: str | None, fecha: datetime) -> tuple[int, float | None, float | None]:
        """``(n, media, desviación típica)`` de la ventana. std None si n < 2."""
        if clave is None:
            return 0, None, None
        cola = self._recortar(clave, fecha)
        n = len(cola)
        if n == 0:
            return 0, None, None
        media = self._sumas[clave] / n
        if n < 2:
            return n, media, None
        varianza = max(self._sumas_sq[clave] / n - media * media, 0.0)
        return n, media, math.sqrt(varianza)

    def media(self, clave: str | None, fecha: datetime) -> float | None:
        return self.stats(clave, fecha)[1]

    def agregar(self, clave: str | None, fecha: datetime, valor: float) -> None:
        if clave is None:
            return
        self._colas[clave].append((fecha, valor))
        self._sumas[clave] += valor
        self._sumas_sq[clave] += valor * valor


class _HhiExpansivo:
    """HHI por segmento sobre todo el histórico estricto anterior."""

    def __init__(self) -> None:
        self._importes: dict[str, dict[Any, float]] = defaultdict(lambda: defaultdict(float))
        self._totales: dict[str, float] = defaultdict(float)

    def hhi(self, segmento: str | None) -> float | None:
        if segmento is None:
            return None
        total = self._totales.get(segmento) or 0.0
        if total <= 0:
            return None
        return sum((importe * 100.0 / total) ** 2 for importe in self._importes[segmento].values())

    def agregar(self, segmento: str | None, empresa: Any, importe: float | None) -> None:
        if segmento is None or not importe or importe <= 0:
            return
        self._importes[segmento][empresa] += importe
        self._totales[segmento] += importe


@dataclass
class _Acumuladores:
    """Estado histórico compartido entre dataset de entrenamiento y scoring."""

    por_organo: _MediaMovil = field(default_factory=_MediaMovil)
    por_cpv4: _MediaMovil = field(default_factory=_MediaMovil)
    por_organo_cpv4: _MediaMovil = field(default_factory=_MediaMovil)
    por_cpv4_corta: _MediaMovil = field(default_factory=lambda: _MediaMovil(_VENTANA_CORTA_MESES))
    por_organo_cpv4_corta: _MediaMovil = field(
        default_factory=lambda: _MediaMovil(_VENTANA_CORTA_MESES)
    )
    ofertas_cpv4: _MediaMovil = field(default_factory=_MediaMovil)
    ofertas_organo_cpv4: _MediaMovil = field(default_factory=_MediaMovil)
    hhi: _HhiExpansivo = field(default_factory=_HhiExpansivo)
    # Prior global del suavizado. Comparte ventana con las medias por segmento a
    # propósito: con un prior expansivo, una baja de hace tres años seguiría
    # tirando de la media reciente de un CPV que solo tiene una observación.
    global_: _MediaMovil = field(default_factory=_MediaMovil)

    def features_historicas(
        self, *, organo: str | None, cpv4: str | None, ccaa: str | None, fecha: datetime
    ) -> dict[str, float | None]:
        """Agregados del segmento vistos desde ``fecha``, suavizados.

        Cada media se encoge hacia su prior padre (órgano-CPV → CPV-4 → global)
        y se publica junto a su ``n_obs``, para que el modelo pueda aprender
        cuánta confianza darle en vez de tratar una observación como cien.
        """
        clave_oc = f"{organo}|{cpv4}" if organo and cpv4 else None
        segmento = f"{cpv4}|{ccaa}" if cpv4 and ccaa else None
        global_ = self.global_.media(_CLAVE_GLOBAL, fecha)

        n_org, media_org, _ = self.por_organo.stats(organo, fecha)
        n_cpv, media_cpv, std_cpv = self.por_cpv4.stats(cpv4, fecha)
        n_oc, media_oc, _ = self.por_organo_cpv4.stats(clave_oc, fecha)

        prior_cpv = _shrink(n_cpv, media_cpv, global_)
        n_cpv_c, media_cpv_c, _ = self.por_cpv4_corta.stats(cpv4, fecha)
        n_oc_c, media_oc_c, _ = self.por_organo_cpv4_corta.stats(clave_oc, fecha)

        return {
            "baja_media_organo": _shrink(n_org, media_org, global_),
            "baja_media_cpv4": prior_cpv,
            "baja_media_organo_cpv4": _shrink(n_oc, media_oc, prior_cpv),
            "baja_media_cpv4_6m": _shrink(n_cpv_c, media_cpv_c, prior_cpv),
            "baja_media_organo_cpv4_6m": _shrink(n_oc_c, media_oc_c, prior_cpv),
            "baja_std_cpv4": std_cpv,
            "n_obs_organo": float(n_org),
            "n_obs_cpv4": float(n_cpv),
            "n_obs_organo_cpv4": float(n_oc),
            "n_ofertas_media_cpv4": self.ofertas_cpv4.media(cpv4, fecha),
            "n_ofertas_media_organo_cpv4": self.ofertas_organo_cpv4.media(clave_oc, fecha),
            "hhi_segmento": self.hhi.hhi(segmento),
        }

    def incorporar(self, evento: _Evento) -> None:
        """Añade una adjudicación resuelta al histórico."""
        clave_oc = f"{evento.organo}|{evento.cpv4}" if evento.organo and evento.cpv4 else None
        self.por_organo.agregar(evento.organo, evento.fecha, evento.baja)
        self.por_cpv4.agregar(evento.cpv4, evento.fecha, evento.baja)
        self.por_cpv4_corta.agregar(evento.cpv4, evento.fecha, evento.baja)
        if clave_oc:
            self.por_organo_cpv4.agregar(clave_oc, evento.fecha, evento.baja)
            self.por_organo_cpv4_corta.agregar(clave_oc, evento.fecha, evento.baja)
        if evento.n_ofertas is not None:
            self.ofertas_cpv4.agregar(evento.cpv4, evento.fecha, evento.n_ofertas)
            if clave_oc:
                self.ofertas_organo_cpv4.agregar(clave_oc, evento.fecha, evento.n_ofertas)
        self.global_.agregar(_CLAVE_GLOBAL, evento.fecha, evento.baja)

    def incorporar_cuota(self, cuota: _Cuota) -> None:
        """Añade la cuota de una empresa al HHI de su segmento."""
        if cuota.cpv4 and cuota.ccaa:
            self.hhi.agregar(f"{cuota.cpv4}|{cuota.ccaa}", cuota.empresa, cuota.importe)


def _features_estaticas(row: dict[str, Any], ancla: datetime) -> dict[str, Any]:
    """Features conocidas en el momento de publicar. Nada de ``adjudicaciones``.

    El tamaño se toma siempre de ``licitaciones.importe`` (el presupuesto del
    expediente) en ambos caminos, aunque el denominador del target sea el de
    los lotes efectivamente adjudicados: es la única lectura disponible cuando
    la licitación está abierta, así que usarla también al entrenar mantiene la
    feature idéntica en los dos lados.
    """
    importe = row.get("importe")
    cpv = row.get("cpv")
    duracion = _duracion_meses(row.get("duracion_valor"), row.get("duracion_unidad"))
    importe_f = float(importe) if importe and float(importe) > 0 else None
    n_lotes = row.get("n_lotes")
    return {
        "cpv2": (cpv or "")[:2] or "na",
        "cpv4": _cpv4(cpv) or "na",
        "tipo_contrato": row.get("tipo_contrato") or "na",
        "ccaa": row.get("ccaa") or "na",
        "provincia": row.get("provincia") or "na",
        "organo": row.get("organo") or "na",
        "fuente": row.get("fuente") or "placsp",
        "banda_importe": _banda_importe(importe_f),
        "log_importe": math.log1p(importe_f) if importe_f else None,
        "plazo_dias": _plazo_dias(row.get("fecha_publicacion"), row.get("fecha_limite")),
        "duracion_meses": duracion,
        "log_importe_mensual": (
            math.log1p(importe_f / duracion) if importe_f and duracion else None
        ),
        "n_lotes": float(n_lotes) if n_lotes is not None else None,
        "mes": float(ancla.month),
        "trimestre": float((ancla.month - 1) // 3 + 1),
    }


def _ancla(row: dict[str, Any], defecto: datetime) -> datetime:
    return (
        _fecha_opt(row.get("fecha_anchor")) or _fecha_opt(row.get("fecha_publicacion")) or defecto
    )


def _eventos_de_pares(pares: list[dict[str, Any]]) -> list[_Evento]:
    """Eventos de adjudicación ordenados por fecha de adjudicación.

    Las filas llegan ordenadas por fecha ancla (publicación); los acumuladores
    se alimentan por fecha de adjudicación, que es cuando el resultado pasa a
    ser conocido. Son dos ordenaciones distintas del mismo conjunto.
    """
    eventos: list[_Evento] = []
    for row in pares:
        fecha = _fecha_opt(row.get("fecha_adjudicacion"))
        if fecha is None:
            continue
        eventos.append(
            _Evento(
                fecha=fecha,
                organo=row.get("organo"),
                cpv4=_cpv4(row.get("cpv")),
                baja=_baja_agregada(row),
                n_ofertas=(
                    float(row["n_ofertas_media"])
                    if row.get("n_ofertas_media") is not None
                    else None
                ),
            )
        )
    eventos.sort(key=lambda e: e.fecha)
    return eventos


def _cuotas_de_rows(rows: list[dict[str, Any]]) -> list[_Cuota]:
    """Cuotas por (expediente, empresa) ordenadas por fecha de adjudicación."""
    cuotas: list[_Cuota] = []
    for row in rows:
        fecha = _fecha_opt(row.get("fecha"))
        importe = row.get("importe")
        if fecha is None or importe is None:
            continue
        cuotas.append(
            _Cuota(
                fecha=fecha,
                cpv4=_cpv4(row.get("cpv")),
                ccaa=row.get("ccaa"),
                empresa=row.get("empresa"),
                importe=float(importe),
            )
        )
    cuotas.sort(key=lambda c: c.fecha)
    return cuotas


def _baja_agregada(row: dict[str, Any]) -> float:
    """Target: baja del expediente contra el presupuesto de lo adjudicado.

    ``presupuesto_efectivo`` lo resuelve ``db.repositories.ml_dataset`` (suma
    de los lotes adjudicados cuando todos están resueltos, ``l.importe`` si
    no). Es la misma magnitud que mide ``calibration.py`` y que sirve
    ``predicciones_baja``, una fila por licitación.
    """
    presupuesto = float(row["presupuesto_efectivo"])
    return (presupuesto - float(row["total_adjudicado"])) / presupuesto


def _procesar(
    *,
    # Sequence y no list: las dos llamadas construyen listas de target float y
    # de target None respectivamente, y list es invariante.
    filas: Sequence[tuple[dict[str, Any], datetime, float | None]],
    eventos: list[_Evento],
    cuotas: list[_Cuota],
) -> tuple[list[FilaDataset], _Acumuladores]:
    """Merge de filas (por ancla) y eventos (por adjudicación), anti-fuga.

    ``filas`` llega ordenada por ancla ascendente. Para cada una se incorporan
    primero todos los eventos **estrictamente anteriores** a su ancla y solo
    después se leen las features: ninguna fila ve su propio resultado ni
    ninguno posterior a su publicación. Los tres punteros solo avanzan, así que
    el coste total es lineal.
    """
    acum = _Acumuladores()
    i_ev = 0
    i_cu = 0
    out: list[FilaDataset] = []
    for row, ancla, target in filas:
        while i_ev < len(eventos) and eventos[i_ev].fecha < ancla:
            acum.incorporar(eventos[i_ev])
            i_ev += 1
        while i_cu < len(cuotas) and cuotas[i_cu].fecha < ancla:
            acum.incorporar_cuota(cuotas[i_cu])
            i_cu += 1

        features = _features_estaticas(row, ancla)
        features.update(
            acum.features_historicas(
                organo=row.get("organo"),
                cpv4=_cpv4(row.get("cpv")),
                ccaa=row.get("ccaa"),
                fecha=ancla,
            )
        )
        out.append(
            FilaDataset(
                licitacion_id=str(row["id_externo"]),
                fecha=ancla.strftime("%Y-%m-%d"),
                features=features,
                baja=target,
            )
        )

    # Los eventos que quedan (posteriores al ancla de la última fila) se
    # incorporan para que los acumuladores devueltos tengan todo el histórico:
    # el camino de scoring los reutiliza.
    while i_ev < len(eventos):
        acum.incorporar(eventos[i_ev])
        i_ev += 1
    while i_cu < len(cuotas):
        acum.incorporar_cuota(cuotas[i_cu])
        i_cu += 1
    return out, acum


def construir_dataset_baja(
    hasta: str | None = None,
) -> tuple[list[FilaDataset], _Acumuladores]:
    """Dataset de entrenamiento del modelo de baja, en orden de fecha ancla.

    Una fila por expediente adjudicado (no por lote): es la granularidad que
    sirve ``predicciones_baja`` y la que mide ``calibration.py``.

    Devuelve también los acumuladores con todo el histórico procesado.
    """
    repo = MlDatasetRepository()
    pares = repo.pares_baja_agregada(hasta)
    if not pares:
        return [], _Acumuladores()
    cuotas = _cuotas_de_rows(repo.adjudicaciones_por_empresa(hasta))
    eventos = _eventos_de_pares(pares)
    defecto = _fecha_opt(hasta) or datetime.now()
    filas = [(row, _ancla(row, defecto), _baja_agregada(row)) for row in pares]
    filas.sort(key=lambda t: (t[1], str(t[0]["id_externo"])))
    return _procesar(filas=filas, eventos=eventos, cuotas=cuotas)


def features_licitaciones_abiertas(
    *, ahora: str | None = None, limit: int = 5000
) -> list[FilaDataset]:
    """Features de scoring para licitaciones sin adjudicación (batch nocturno).

    Construcción idéntica a la de entrenamiento, incluida el ancla: cada
    licitación abierta se mira desde su propia fecha de publicación, no desde
    hoy. Anclar en hoy daría a las filas de scoring una ventana histórica más
    larga que la que vio cualquier fila de entrenamiento, que es exactamente el
    tipo de asimetría que este módulo existe para evitar.
    """
    repo = MlDatasetRepository()
    pares = repo.pares_baja_agregada(ahora)
    cuotas = _cuotas_de_rows(repo.adjudicaciones_por_empresa(ahora))
    eventos = _eventos_de_pares(pares)
    defecto = _fecha_opt(ahora) or datetime.now()
    abiertas = repo.licitaciones_abiertas(estados_cerrados=ESTADOS_CERRADOS, limit=limit)
    filas = [(row, _ancla(row, defecto), None) for row in abiertas]
    filas.sort(key=lambda t: (t[1], str(t[0]["id_externo"])))
    scoreadas, _ = _procesar(filas=filas, eventos=eventos, cuotas=cuotas)
    return scoreadas

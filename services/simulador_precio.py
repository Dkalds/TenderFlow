"""F2.2 — cuántos puntos me da esta baja, y cuánto me falta contra un rival.

Los escenarios de precio y los criterios de adjudicación existían por separado
desde hace meses. Nadie los unía, así que la pregunta que se hace de verdad
quien fija el precio —«¿cuántos puntos me da bajar un 12 %?»— se respondía en
una hoja de cálculo aparte, con la fórmula copiada a mano del pliego.

La regla que gobierna este módulo
---------------------------------
**Sin fórmula extraída no se calcula.** Se dice «fórmula no encontrada en el
pliego» y se acaba. Lo mismo sin puntos que repartir. Un simulador que
aproxima con la fórmula más común acierta muchas veces y falla justo donde
importa —el pliego raro, el que nadie ha leído entero—, y quien lo use no
tiene forma de saber en cuál de los dos casos está.

Las tres formas que se calculan salen del catálogo de ``PriceFormulaType``:
proporcional inversa, lineal por tramos y proporcional con umbral de
temeridad. ``otra`` no se calcula, por lo mismo.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from observability.logging import get_logger
from shared.tender_facts import PriceFormulaFact

log = get_logger(__name__)

__all__ = [
    "BAJAS_POR_DEFECTO",
    "MOTIVOS_SIN_CALCULO",
    "EscenarioPuntos",
    "SimulacionPrecio",
    "simular",
    "simular_precio_de",
]

#: Por qué no se ha podido calcular. Cerrado, para que la UI pueda escribir un
#: texto distinto por caso en vez de un «no disponible» genérico.
MotivoSinCalculo = Literal[
    "sin_formula",
    "formula_no_calculable",
    "sin_puntos_de_precio",
]

MOTIVOS_SIN_CALCULO: tuple[str, ...] = (
    "sin_formula",
    "formula_no_calculable",
    "sin_puntos_de_precio",
)


class EscenarioPuntos(BaseModel):
    """Los puntos de precio que da una baja concreta."""

    model_config = ConfigDict(extra="forbid")

    #: Baja en tanto por uno (0.12 = 12 %).
    baja: float = Field(ge=0, le=1)
    puntos: float = Field(ge=0)
    #: ``True`` si esta baja cae por debajo del umbral de temeridad publicado y
    #: por tanto obligaría a justificarla.
    temeraria: bool = False


class SimulacionPrecio(BaseModel):
    """Respuesta del simulador: puntos por escenario, o el motivo de no calcular."""

    model_config = ConfigDict(extra="forbid")

    licitacion_id: str
    #: `None` cuando no se ha podido calcular.
    formula_tipo: str | None = None
    #: Puntos que reparte el criterio de precio, y de dónde salió ese número.
    puntos_precio: float | None = None
    puntos_precio_origen: Literal["pliego", "peso_precio", "desconocido"] = "desconocido"
    escenarios: list[EscenarioPuntos] = Field(default_factory=list)
    #: Puntos que le sacaría (o que le faltarían) a la baja de referencia. El
    #: signo es lo informativo: negativo = hay que compensar en juicio de valor.
    hueco_vs_referencia: float | None = None
    baja_referencia: float | None = None
    #: `None` = se calculó. Con valor, `escenarios` va vacío.
    sin_calculo: MotivoSinCalculo | None = None


def _puntos_proporcional_inversa(baja: float, baja_mayor: float, maximo: float) -> float:
    """``max * (baja / baja_mayor)``, la forma más común en España.

    ``baja_mayor`` es la mejor oferta esperada, no la propia: es lo que hace
    que el simulador responda «cuántos puntos me da» y no «cuántos me daría si
    fuera el único». Con ``baja_mayor`` a cero —nadie baja— todas las ofertas
    empatan y se lleva el máximo.
    """
    if baja_mayor <= 0:
        return maximo
    return maximo * min(baja / baja_mayor, 1.0)


def _puntos_por_tramos(baja: float, tramos: dict[str, float], maximo: float) -> float:
    """Escalones: la clave es la baja mínima del tramo, el valor sus puntos.

    Se elige el tramo de mayor umbral que la baja alcanza. Fuera de todos los
    tramos (baja por debajo del primero) son cero puntos, que es lo que dice
    un pliego por tramos: por debajo del primer escalón no se puntúa.
    """
    aplicables = [
        (float(umbral), puntos) for umbral, puntos in tramos.items() if baja >= float(umbral)
    ]
    if not aplicables:
        return 0.0
    return min(max(p for _u, p in aplicables), maximo)


def simular(
    licitacion_id: str,
    formulas: list[PriceFormulaFact],
    *,
    bajas: list[float],
    baja_referencia: float | None = None,
    baja_mayor_esperada: float | None = None,
    peso_precio_pct: float | None = None,
) -> SimulacionPrecio:
    """Puntos de precio por cada baja de ``bajas``.

    ``baja_mayor_esperada`` es la baja de la mejor oferta rival que se prevé
    (p90 de ``prediccion-baja``, o la de referencia del CPV). Sin ella se usa
    la mayor de las bajas simuladas, que es el supuesto conservador: presupone
    que alguien va a bajar tanto como el escenario más agresivo que se está
    considerando.

    ``peso_precio_pct`` (v85) es el respaldo cuando el pliego no publica los
    puntos del criterio de precio. Se usa **declarándolo** en
    ``puntos_precio_origen``: no es lo mismo un 45 leído del pliego que un 45
    inferido del peso, y quien fije un precio con esto tiene que poder verlo.
    """
    formula = formulas[0] if formulas else None
    if formula is None:
        return SimulacionPrecio(licitacion_id=licitacion_id, sin_calculo="sin_formula")
    if formula.formula_type == "otra":
        return SimulacionPrecio(
            licitacion_id=licitacion_id,
            formula_tipo=formula.formula_type,
            sin_calculo="formula_no_calculable",
        )

    if formula.max_points is not None:
        maximo, origen = float(formula.max_points), "pliego"
    elif peso_precio_pct is not None:
        maximo, origen = float(peso_precio_pct), "peso_precio"
    else:
        return SimulacionPrecio(
            licitacion_id=licitacion_id,
            formula_tipo=formula.formula_type,
            sin_calculo="sin_puntos_de_precio",
        )

    candidatas = [b for b in bajas if 0 <= b <= 1]
    mayor = baja_mayor_esperada if baja_mayor_esperada is not None else max(candidatas, default=0.0)
    tramos = formula.params

    def _puntos(baja: float) -> float:
        if formula.formula_type == "lineal_por_tramos":
            return _puntos_por_tramos(baja, tramos, maximo)
        # `con_umbral_temeridad` reparte igual que la proporcional inversa; lo
        # que cambia es que marca las ofertas por debajo del umbral, porque el
        # órgano puede excluirlas. El simulador no las excluye por su cuenta:
        # una temeraria justificada se acepta, y decidir eso no le toca a él.
        return _puntos_proporcional_inversa(baja, mayor, maximo)

    umbral = formula.umbral_temeridad
    escenarios = [
        EscenarioPuntos(
            baja=baja,
            puntos=round(_puntos(baja), 2),
            temeraria=bool(umbral is not None and baja >= umbral),
        )
        for baja in sorted(candidatas)
    ]

    hueco: float | None = None
    if baja_referencia is not None and escenarios:
        # Contra la mejor de las bajas simuladas: es la que el equipo está
        # considerando de verdad, no la primera de la lista.
        mejor_propia = max(e.puntos for e in escenarios)
        hueco = round(mejor_propia - _puntos(baja_referencia), 2)

    return SimulacionPrecio(
        licitacion_id=licitacion_id,
        formula_tipo=formula.formula_type,
        puntos_precio=maximo,
        puntos_precio_origen=origen,  # type: ignore[arg-type]  # los tres literales, uno por rama
        escenarios=escenarios,
        hueco_vs_referencia=hueco,
        baja_referencia=baja_referencia,
    )


#: Escenarios que se simulan cuando el cliente no pide bajas concretas. Son los
#: mismos tramos que ya usan los escenarios de precio de la ficha, para que las
#: dos pantallas hablen de las mismas bajas.
BAJAS_POR_DEFECTO: tuple[float, ...] = (0.05, 0.10, 0.15, 0.20, 0.25)


def simular_precio_de(
    licitacion_id: str,
    *,
    bajas: list[float] | None = None,
    baja_referencia: float | None = None,
) -> SimulacionPrecio:
    """Lee la ficha del pliego y simula. Es la entrada que usa la ruta.

    Vive aquí y no en la ruta porque decide **de dónde** sale cada dato —la
    fórmula de la ficha, el peso del precio de la tabla— y eso es dominio, no
    HTTP. La ruta sólo traduce parámetros.

    Una ficha que no existe todavía no es un error: es «no lo sabemos aún», y
    se responde con `sin_formula` igual que un pliego sin fórmula. Para quien
    fija un precio las dos situaciones piden lo mismo: leer el pliego a mano.
    """
    from db.repositories.licitaciones import LicitacionRepository
    from services.rag.fact_sheet import get_fact_sheet

    record = get_fact_sheet(licitacion_id)
    formulas = list(record.facts.price_formula) if record and record.facts else []

    peso_precio: float | None = None
    try:
        fila = LicitacionRepository().get_by_id(licitacion_id)
        if fila is not None and fila.get("peso_precio_pct") is not None:
            peso_precio = float(fila["peso_precio_pct"])
    except Exception as exc:
        log.warning("simulador_peso_precio_error", error=str(exc)[:200])

    return simular(
        licitacion_id,
        formulas,
        bajas=list(bajas) if bajas else list(BAJAS_POR_DEFECTO),
        baja_referencia=baja_referencia,
        peso_precio_pct=peso_precio,
    )

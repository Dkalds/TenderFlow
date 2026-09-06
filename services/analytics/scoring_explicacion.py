"""F1.3 — por qué esta licitación puntúa lo que puntúa, en castellano.

El Radar enseñaba el desglose como seis barras numéricas dentro de un popover.
Eso responde «de qué está hecho el 82», no «por qué debería mirar esta».
Este módulo convierte el mismo cálculo —sin recalcular nada, sin LLM— en tres
o cuatro frases que se leen de un vistazo.

Reglas que hacen que esto sea seguro de publicar
------------------------------------------------
1. **Cero cifras nuevas.** Cada número que aparece en una frase sale del
   ``desglose`` o de una señal que ya viajaba en la respuesta (media de
   ofertas, baja esperada). No se calculan porcentajes de conveniencia, no se
   redondean magnitudes a «millones» y no se cita el importe: la tarjeta ya lo
   muestra, y repetirlo aquí abriría la puerta a formatearlo distinto en dos
   sitios. ``test_scoring_explicacion.py`` lo comprueba token a token.
2. **Lo que falta se dice.** Una dimensión neutral por falta de dato produce
   su propia frase («sin importe publicado: puntúa neutral») en vez de
   desaparecer. Un hueco silencioso se lee como una valoración, que es
   exactamente lo que ADR-014 prohíbe.
3. **La procedencia viaja con el dato.** La frase del margen dice si la baja
   la estimó un modelo entrenado o el histórico, y la de afinidad si hubo
   embeddings o el fallback por palabras. Son estimaciones de calidad distinta
   y presentarlas iguales las hace indistinguibles.
4. **Sin adjetivos de venta.** «Poca competencia» es un hecho medido; «gran
   oportunidad» es una opinión que el producto no puede sostener.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "FLAG_EXPLICACIONES",
    "HechosDeFila",
    "explicar",
]

# Umbral por encima del cual una dimensión se considera "aporta de verdad",
# como fracción de su peso. Por debajo la frase sería ruido: un 3 % del peso
# de competencia no es una razón para mirar nada.
_FRACCION_RELEVANTE = 0.55
# Y por debajo de esto, la dimensión resta de forma visible y también merece
# frase: enseñar solo lo bueno es media explicación.
_FRACCION_POBRE = 0.30


@dataclass(frozen=True, slots=True)
class HechosDeFila:
    """Lo que ``_score_row`` supo de una fila, sin pandas de por medio.

    Se pasa como estructura y no como el ``dict`` del desglose porque las
    frases necesitan el **hecho** (dos ofertas de media) y no solo su
    traducción a puntos (12,5 de 25).
    """

    score: int
    # Fracción del peso que se llevó cada dimensión, 0-1. `None` = la
    # dimensión no participa en este perfil (afinidad sin portfolio, señal
    # técnica con peso 0) y por tanto no se explica.
    fraccion: dict[str, float | None] = field(default_factory=dict)
    # Hechos crudos de las señales. `None` = no había dato; el flag
    # correspondiente ya lo cuenta.
    media_ofertas: float | None = None
    baja_esperada: float | None = None
    margen_origen: str = "desconocido"
    afinidad_metodo: str = "unavailable"
    risk_flags: tuple[str, ...] = ()


# Una frase por bandera de riesgo. Están aquí y no dispersas en `if`s para que
# añadir un flag nuevo al scoring (F1.4 añade `organo_anula_frecuente`) sea
# añadir una línea, y para que el test pueda exigir que **toda** bandera que
# el scoring emite tenga texto: una bandera sin frase es una penalización
# invisible.
FLAG_EXPLICACIONES: dict[str, str] = {
    "sin_importe": "Sin importe publicado: esa parte puntúa neutral, ni suma ni resta.",
    "sin_plazo": "Sin fecha límite publicada: el plazo puntúa neutral.",
    "sin_titulo": "Sin título en la fuente: no se puede valorar el objeto del contrato.",
    "sin_historico_competencia": (
        "Sin adjudicaciones históricas de este CPV: la competencia esperada puntúa neutral."
    ),
    "sin_prediccion": "Sin baja estimada para este expediente: el margen puntúa neutral.",
    "sin_senal_tecnica": (
        "Sin evidencia de la tecnología en los pliegos: la señal técnica puntúa neutral."
    ),
    "fuera_de_rango": (
        "El importe queda fuera del rango que fijaste en tu perfil: penaliza la puntuación."
    ),
    "organo_anula_frecuente": (
        "Este órgano anula o deja desiertos más expedientes de lo normal: penaliza la puntuación."
    ),
}


def _pct(fraccion: float) -> str:
    """Porcentaje entero. Sin decimales: son estimaciones, no mediciones."""
    return f"{round(fraccion * 100)} %"


def _num(valor: float) -> str:
    """Un decimal, coma decimal española, y sin el ``,0`` de los enteros."""
    texto = f"{valor:.1f}".replace(".", ",")
    return texto[:-2] if texto.endswith(",0") else texto


def _frase_competencia(hechos: HechosDeFila) -> str | None:
    media = hechos.media_ofertas
    if media is None:
        return None
    # El número es el de la señal, tal cual. Lo que cambia es el calificativo,
    # y su umbral es el mismo que usa el scoring (1 oferta = 100 %, ≥10 = 0 %).
    if media < 3:
        return f"Poca competencia esperada: {_num(media)} ofertas de media en este CPV."
    if media < 6:
        return f"Competencia media: {_num(media)} ofertas de media en este CPV."
    return f"Mucha competencia esperada: {_num(media)} ofertas de media en este CPV."


_ORIGEN_MARGEN = {
    "modelo": "según el modelo de baja",
    "baseline": "según el histórico del CPV",
    "mixto": "según modelo e histórico",
    "sin_predicciones": "según el histórico",
}


def _frase_margen(hechos: HechosDeFila) -> str | None:
    baja = hechos.baja_esperada
    if baja is None:
        return None
    fuente = _ORIGEN_MARGEN.get(hechos.margen_origen)
    # Origen desconocido → se omite la coletilla en vez de inventar una
    # procedencia. La frase sigue siendo cierta; solo dice menos.
    cola = f" {fuente}" if fuente else ""
    if baja >= 0.25:
        return f"Baja esperada del {_pct(baja)}{cola}: margen apretado."
    return f"Baja esperada del {_pct(baja)}{cola}."


_METODO_AFINIDAD = {
    "semantic_embeddings": "por similitud semántica con tu portfolio",
    "keyword_cpv_fallback": "por coincidencia de palabras y CPV",
}


def _frase_afinidad(fraccion: float, metodo: str) -> str | None:
    detalle = _METODO_AFINIDAD.get(metodo)
    if detalle is None:
        # `unavailable`: no hubo forma de medir afinidad. No se afirma nada.
        return None
    if fraccion >= _FRACCION_RELEVANTE:
        return f"Encaja con tu perfil {detalle}."
    if fraccion <= _FRACCION_POBRE:
        return f"Encaja poco con tu perfil {detalle}."
    return None


def _frase_importe(fraccion: float) -> str | None:
    if fraccion >= _FRACCION_RELEVANTE:
        return "Importe en el tramo alto del mercado que puntúas."
    if fraccion <= _FRACCION_POBRE:
        return "Importe en el tramo bajo del mercado que puntúas."
    return None


def _frase_plazo(fraccion: float) -> str | None:
    # Escalones del scoring: 1.0 entre 7 y 90 días, 0.5 por debajo de 7, 0.7
    # hasta 180, 0.3 más allá, 0.0 vencido. El texto no repite la fecha —la
    # tarjeta ya la enseña— y traduce el escalón a lo único que importa aquí:
    # si da tiempo a preparar la oferta.
    if fraccion >= 0.95:
        return "Plazo cómodo para preparar la oferta."
    if fraccion <= 0.01:
        return "Plazo vencido."
    if fraccion <= 0.55:
        return "Plazo justo: queda poco margen para preparar la oferta."
    return None


def _frase_tecnica(fraccion: float) -> str | None:
    if fraccion >= _FRACCION_RELEVANTE:
        return "La tecnología aparece confirmada en los pliegos."
    if fraccion <= _FRACCION_POBRE:
        return "Evidencia débil de la tecnología en los pliegos."
    return None


def explicar(hechos: HechosDeFila) -> list[str]:
    """Las frases que explican un score, en orden de lectura.

    Primero el encabezado con la puntuación, después las dimensiones que
    tienen algo que decir, y al final lo que falta o penaliza. Ese orden no es
    estético: quien tría lee las dos primeras líneas, y las razones para mirar
    tienen que estar antes que las advertencias.

    Una dimensión que puntúa en la banda intermedia no genera frase. No es
    información: decir «importe ni alto ni bajo» ocupa una línea de las tres
    que el usuario va a leer.
    """
    frases: list[str] = [f"Puntúa {hechos.score} sobre 100."]

    def _fraccion(dimension: str) -> float | None:
        return hechos.fraccion.get(dimension)

    orden: list[str | None] = []
    if (f_importe := _fraccion("importe")) is not None:
        orden.append(_frase_importe(f_importe))
    if (f_plazo := _fraccion("plazo")) is not None:
        orden.append(_frase_plazo(f_plazo))
    orden.append(_frase_competencia(hechos))
    orden.append(_frase_margen(hechos))
    if (f_afinidad := _fraccion("afinidad")) is not None:
        orden.append(_frase_afinidad(f_afinidad, hechos.afinidad_metodo))
    if (f_tecnica := _fraccion("senal_tecnica")) is not None:
        orden.append(_frase_tecnica(f_tecnica))

    frases.extend(frase for frase in orden if frase)

    # Los huecos y las penalizaciones, al final y en el orden en que el
    # scoring los emitió (determinista). Un flag sin texto se ignora en vez de
    # romper la respuesta: el test es quien impide que eso llegue a existir.
    frases.extend(
        FLAG_EXPLICACIONES[flag] for flag in hechos.risk_flags if flag in FLAG_EXPLICACIONES
    )
    return frases

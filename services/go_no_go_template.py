"""Plantilla de go/no-go ponderada (C6.4, D30).

`pursuits.decision` registraba **qué** se decidió y no **por qué**: dos meses
después nadie podía responder «¿en qué nos equivocamos al decidir?», que es la
única pregunta que convierte un histórico de decisiones en aprendizaje.

Aquí vive el **criterio** (qué se puntúa, cómo se pondera, cuándo la puntuación
recomienda ir). El SQL está en `db/repositories/go_no_go.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Los cinco criterios de D30, en orden de presentación.
#:
#: Fijos para todas las organizaciones a propósito: dejar que cada una los
#: defina daría un histórico incomparable **dentro de la propia organización**
#: en cuanto alguien edite la lista, y comparar decisiones pasadas es justo para
#: lo que sirve la plantilla.
CRITERIOS: tuple[str, ...] = ("encaje", "capacidad", "competencia", "rentabilidad", "riesgo")

ETIQUETAS: dict[str, str] = {
    "encaje": "Encaje estratégico",
    "capacidad": "Capacidad de ejecución",
    "competencia": "Posición frente a la competencia",
    "rentabilidad": "Rentabilidad esperada",
    "riesgo": "Riesgo (5 = riesgo bajo)",
}

#: `riesgo` se puntúa **invertido**: 5 es poco riesgo.
#:
#: Así la suma ponderada tiene una sola dirección —más alto, mejor— y el umbral
#: no necesita saber qué criterios restan. Sin esta convención, esa lógica
#: acabaría duplicada en cada consumidor, y bastaría con que uno la olvidase
#: para que su recomendación fuese la contraria.
CRITERIO_INVERTIDO = "riesgo"

PUNTUACION_MIN = 1
PUNTUACION_MAX = 5

#: Umbral por defecto sobre la puntuación normalizada (1-5).
#:
#: 3,0 es el punto medio de la escala: por debajo, la mayoría de los criterios
#: están por debajo de «regular». No es un número calibrado con datos —no los
#: hay todavía— y por eso es un **default configurable por organización** y no
#: una constante escondida: cuando haya histórico, se calibra.
UMBRAL_DEFECTO = 3.0

#: Peso por defecto de cada criterio: todos iguales.
#:
#: Empezar con pesos distintos sería afirmar cuál importa más sin saberlo. Que
#: cada organización los mueva es la decisión que D30 le deja.
PESO_DEFECTO = 1.0


@dataclass(frozen=True)
class Puntuacion:
    """Resultado de aplicar la plantilla a una oportunidad."""

    total: float
    umbral: float
    recomendacion: str
    criterios_puntuados: int
    completa: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": round(self.total, 2),
            "umbral": self.umbral,
            "recomendacion": self.recomendacion,
            "criterios_puntuados": self.criterios_puntuados,
            "completa": self.completa,
        }


def pesos_por_defecto() -> dict[str, float]:
    return dict.fromkeys(CRITERIOS, PESO_DEFECTO)


def normalizar_pesos(pesos: dict[str, float]) -> dict[str, float]:
    """Rellena los criterios ausentes y descarta los desconocidos.

    Un criterio sin peso guardado usa el default en vez de valer cero: valer
    cero lo sacaría del cálculo en silencio, y «no configurado» y «no cuenta»
    son cosas distintas.
    """
    completos = {c: float(pesos.get(c, PESO_DEFECTO)) for c in CRITERIOS}
    if all(p == 0 for p in completos.values()):
        # Todos a cero haría el total indefinido. Se trata como «sin configurar».
        return pesos_por_defecto()
    return completos


def calcular(
    puntuaciones: dict[str, int],
    pesos: dict[str, float] | None = None,
    *,
    umbral: float = UMBRAL_DEFECTO,
) -> Puntuacion:
    """Media ponderada de lo puntuado, en la misma escala 1-5.

    **Solo se promedian los criterios puntuados**, no los cinco. Contar los
    ausentes como cero haría que una ficha a medias recomendara siempre no ir, y
    el equipo aprendería a rellenarla a bulto para que no le mienta. `completa`
    dice si están los cinco, para que quien lea el número sepa sobre cuántos se
    calculó.

    `riesgo` llega ya en su escala invertida (5 = poco riesgo), así que no se
    transforma aquí: hacerlo en dos sitios es cómo se acaba invirtiendo dos
    veces.
    """
    efectivos = normalizar_pesos(pesos or {})
    validos = {
        c: int(p)
        for c, p in puntuaciones.items()
        if c in CRITERIOS and PUNTUACION_MIN <= int(p) <= PUNTUACION_MAX
    }
    if not validos:
        return Puntuacion(
            total=0.0,
            umbral=umbral,
            recomendacion="sin_datos",
            criterios_puntuados=0,
            completa=False,
        )

    peso_total = sum(efectivos[c] for c in validos)
    if peso_total == 0:
        peso_total = float(len(validos))
        total = sum(validos.values()) / peso_total
    else:
        total = sum(validos[c] * efectivos[c] for c in validos) / peso_total

    return Puntuacion(
        total=total,
        umbral=umbral,
        recomendacion=("go" if total >= umbral else "no_go"),
        criterios_puntuados=len(validos),
        completa=len(validos) == len(CRITERIOS),
    )


def discrepa(decision: str | None, puntuacion: Puntuacion) -> bool:
    """Si la decisión tomada contradice lo que la plantilla recomienda.

    Es la métrica que `make product-status` publica («go por debajo del
    umbral»): no para impedir la decisión —el equipo sabe cosas que la plantilla
    no— sino para que discrepar sea **visible** y se pueda revisar después.
    Una plantilla que bloquea se rellena para pasarla; una que solo señala se
    rellena para pensar.
    """
    if decision not in ("go", "no_go") or puntuacion.recomendacion == "sin_datos":
        return False
    return decision != puntuacion.recomendacion

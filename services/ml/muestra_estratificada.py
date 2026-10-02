"""Reparto de cuotas de la muestra estratificada de F2 (plan de clasificación
en tres niveles, `docs/plans/2026-09-27-clasificacion-tres-niveles.md` §3.2).

El job de etiquetado por LLM (`scheduler/jobs/llm_tech_labeling.py`) recorre
hoy el backlog de lo más nuevo a lo más viejo. F2 necesita en cambio una
muestra que cubra cada estrato -- fuente x CPV x idioma x si tiene
keyword x banda del modelo actual -- para poder medir el acuerdo LLM-humano
por separado en cada uno, incluidos los minoritarios.

:func:`repartir_cuotas` es la única pieza de dominio: cuántas licitaciones
tomar de cada estrato para sumar un total dado. Proporcional a la **raíz
cuadrada** del tamaño de cada estrato y no al tamaño lineal -- con miles de
PSCP sin keyword y unas pocas decenas de estratos minoritarios, un reparto
lineal vaciaría la muestra casi entera en el estrato mayor y dejaría los
demás sin representación; la raíz cuadrada suaviza esa desproporción sin
igualar del todo. Pura -- sin BD, sin sklearn -- para poder probarla sin
Postgres; `db.repositories.tecnologia_pliego.TecnologiaPliegoRepository`
aporta los tamaños reales (`tamanos_estratos_muestra`) y la selección
determinista dentro de cada estrato (`list_muestra_pending_llm_signal`).
"""

from __future__ import annotations

import math
from collections.abc import Mapping

#: Tamaño de la muestra estratificada que aprobó el propietario (spec §3.2, D3).
MUESTRA_POR_DEFECTO = 4000

#: Semilla fija de `md5(id_externo || semilla)`, el desempate determinista
#: dentro de cada estrato en `TecnologiaPliegoRepository.
#: list_muestra_pending_llm_signal`: con la misma semilla, relanzar el
#: drenado manual (p.ej. tras un corte de presupuesto) selecciona el mismo
#: universo de licitaciones, así que la corrida es resumible de verdad.
SEMILLA_POR_DEFECTO = "f2-2026-09-28"


def repartir_cuotas(tamanos: Mapping[str, int], total: int) -> dict[str, int]:
    """Cuántas licitaciones tomar de cada estrato para sumar `total`.

    Reglas (spec §3.2, diseño aprobado por el propietario):

    - Los estratos de tamaño 0 se ignoran: no aparecen en el resultado.
    - Ninguna cuota supera el tamaño de su propio estrato.
    - La suma de las cuotas es exactamente ``min(total, sum(tamanos))``.
    - Si `total` alcanza o supera el universo, cada estrato se lleva su
      tamaño entero.
    - Si `total` es menor o igual que el número de estratos no vacíos, se
      da 1 a los `total` estratos más grandes (empate por tamaño lo rompe la
      clave en orden ascendente) y el resto queda fuera del resultado.
    - En cualquier otro caso, ningún estrato no vacío se queda en 0: primero
      se le da 1 a cada uno, y el resto se reparte proporcional a la raíz
      cuadrada de su tamaño sobre la capacidad que le queda (``tamano - 1``),
      capando iterativamente el que se pase (se fija en su tope y el sobrante
      se re-esparce sobre los demás) y redondeando por resto mayor -- empate
      determinista: resto más grande, luego estrato más grande, luego clave
      en orden ascendente.

    Raises:
        ValueError: si `total` no es positivo.
    """
    if total <= 0:
        raise ValueError(f"total debe ser positivo: {total!r}")

    no_vacios = {clave: tamano for clave, tamano in tamanos.items() if tamano > 0}
    if not no_vacios:
        return {}

    universo = sum(no_vacios.values())
    if total >= universo:
        return dict(no_vacios)

    if total <= len(no_vacios):
        mayores = sorted(no_vacios, key=lambda clave: (-no_vacios[clave], clave))[:total]
        return {clave: 1 for clave in mayores}

    # Ningún estrato se queda en 0: 1 de entrada para cada uno, y el resto se
    # reparte por √tamaño sobre la capacidad que le queda (tamano - 1).
    pesos = {clave: math.sqrt(tamano) for clave, tamano in no_vacios.items()}
    topes = {clave: tamano - 1 for clave, tamano in no_vacios.items()}
    extra = _repartir_con_topes(pesos, topes, total - len(no_vacios), tamanos=no_vacios)
    return {clave: 1 + extra.get(clave, 0) for clave in no_vacios}


def _repartir_con_topes(
    pesos: Mapping[str, float],
    topes: Mapping[str, int],
    unidades: int,
    *,
    tamanos: Mapping[str, int],
) -> dict[str, int]:
    """Reparte `unidades` proporcionalmente a `pesos`, sin exceder `topes[clave]`.

    Cuando la parte proporcional de un estrato excede su tope, se fija ahí
    (sale del reparto) y lo que sobra se reparte de nuevo entre los que
    quedan -- se repite hasta que ninguno se pase. Lo que sobra tras el
    `floor` de la parte proporcional final se asigna de a una unidad,
    empezando por el resto más grande; el empate lo rompe primero el
    `tamanos[clave]` más grande y después la clave en orden ascendente.
    """
    fijos: dict[str, int] = {}
    libres = dict(pesos)
    restantes = unidades

    while libres:
        suma_pesos = sum(libres.values())
        if suma_pesos <= 0 or restantes <= 0:
            break
        excedidos = [
            clave for clave in libres if (libres[clave] / suma_pesos) * restantes > topes[clave]
        ]
        if not excedidos:
            break
        for clave in excedidos:
            fijos[clave] = topes[clave]
            restantes -= topes[clave]
            del libres[clave]

    resultado: dict[str, int] = dict(fijos)
    if not libres or restantes <= 0:
        for clave in libres:
            resultado[clave] = 0
        return resultado

    suma_pesos = sum(libres.values())
    shares = {clave: (peso / suma_pesos) * restantes for clave, peso in libres.items()}
    pisos = {clave: math.floor(valor) for clave, valor in shares.items()}
    sobrante = restantes - sum(pisos.values())
    restos = {clave: shares[clave] - pisos[clave] for clave in libres}
    orden = sorted(libres, key=lambda clave: (-restos[clave], -tamanos[clave], clave))

    for clave in libres:
        resultado[clave] = pisos[clave]
    for clave in orden[:sobrante]:
        resultado[clave] += 1
    return resultado

"""Fuzzing del contrato API: ninguna operación puede devolver 5xx.

Qué cubre que no cubran los tests
---------------------------------
La suite prueba los caminos que alguien pensó en escribir. Este script genera
entradas desde el propio OpenAPI —enteros gigantes, cadenas unicode, enums
fuera de rango, cuerpos con campos ausentes— y las lanza contra las 140+
operaciones. Un 400 o un 422 es una respuesta correcta: significa que la
validación hizo su trabajo. Un **500 no lo es nunca**: es una excepción sin
manejar, y encontrarlas antes que un usuario es todo el objetivo.

Corre contra la app ASGI en proceso (sin servidor ni red) con una BD real
sembrada. Los middlewares se ejecutan igual que en producción, incluido el
limitador de peticiones, que hay que neutralizar (ver
``_desactivar_rate_limiter``): un fuzzer supera 120 req/min al instante y sin
eso el run entero sería 429s — verde por no haber tocado ninguna ruta.

El resumen imprime siempre la distribución de códigos de respuesta,
precisamente para que ese falso verde se vea de un vistazo.

El ratchet
----------
``KNOWN_5XX`` lista las operaciones que ya devolvían 5xx al introducir el gate.
**El gate falla cuando aparece una operación con 5xx que no está en esa lista.**
Añadir líneas está prohibido: si tu cambio hace fallar una operación, arreglala.

Una entrada de la lista que en una ejecución concreta no falla se avisa, pero
no tumba el job. Es una diferencia deliberada respecto a los otros ratchets del
repo (TID251, ``check_openapi_contract.py``), y el motivo está en la sección
siguiente: aquí el resultado no depende solo del código.

Por qué esta mitad no es un error
---------------------------------
``derandomize=True`` fija las **entradas** que genera Hypothesis, pero no el
**estado de la base**: el fuzzer crea, modifica y borra filas mientras corre, y
lo que devuelve una operación depende de lo que hicieron las anteriores. Dos
ejecuciones seguidas del mismo comando sobre la misma base dieron 3 y 1
operaciones con 5xx respectivamente — no por aleatoriedad, sino porque la
segunda partía de los datos que dejó la primera.

Con eso, exigir que la lista coincida exactamente convertiría el gate en un
generador de rojos espurios: bastaría añadir una licitación al seed para que
una operación dejara de tocar el camino que fallaba. Lo que sí es siempre
concluyente —y por eso es lo único bloqueante— es lo contrario: si una
operación devuelve 5xx, hay una excepción sin manejar, con independencia de
cómo llegara ahí.

Para limpiar la lista tras arreglar algo, ejecutá ``--list`` **sobre una base
recién migrada y sembrada** (como hace CI) y comparalo con la lista actual.

Uso::

    python scripts/fuzz_api_contract.py           # gate (exit 1 si hay 5xx nuevos)
    python scripts/fuzz_api_contract.py --list    # imprime lo que falla, exit 0
    python scripts/fuzz_api_contract.py --max-examples 50   # exploración manual
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Operaciones excluidas, cada una con su motivo ────────────────────────────
# No es una allowlist de fallos: son operaciones que no se pueden fuzzear sin
# efectos fuera del proceso. Una entrada nueva aquí necesita justificación.
EXCLUDED_OPERATIONS: frozenset[str] = frozenset(
    {
        # SSE: la respuesta es un stream que no termina solo.
        "GET /api/v1/licitaciones/stream",
        # Llama al proveedor LLM: coste real y respuesta no determinista.
        "POST /api/v1/ask",
        # Dependen de que Google conteste.
        "GET /api/v1/auth/oauth/google/authorize",
        "GET /api/v1/auth/oauth/google/callback",
        # Hace una petición HTTP saliente al endpoint del webhook.
        "POST /api/v1/webhooks/{webhook_id}/ping",
        # Con ids pequeños generados por Hypothesis, desactivarían al propio
        # usuario del fuzzer a mitad de ejecución y el resto del run se
        # convertiría en 401s.
        "POST /api/v1/admin/users/{user_id}/deactivate",
        "PUT /api/v1/admin/users/{user_id}/admin",
        # Exporta métricas Prometheus, no forma parte del contrato de negocio.
        "GET /metrics",
    }
)

# Ejemplos por operación en el gate. Más ejemplos exploran más superficie y
# encuentran más: con 10 no aparecía el 5xx de `watchlist/items` que sí aparece
# con 25. Subirlo es bienvenido —el coste es tiempo de job—; bajarlo debilita el
# gate sin avisar.
MAX_EXAMPLES_GATE = 25

# ── Operaciones que ya devolvían 5xx al introducir el gate ──────────────────
# Todas comparten forma: una entrada malformada atraviesa la validación y
# revienta en una capa que no la esperaba.
#
#   - bulk-get / feature-flags: un byte NUL (0x00) dentro de una cadena llega
#     hasta Postgres, que no lo admite en columnas de texto.
#   - watchlist/items: bytes que no son UTF-8 válido en el path (`%ff`) rompen
#     la decodificación antes de que la ruta llegue a ejecutarse.
#
# El arreglo correcto no es endpoint por endpoint sino decidir dónde se sanea
# (validador compartido en los DTO, middleware en la frontera HTTP, o ambos):
# es un cambio transversal con su propia discusión, anotado en
# docs/IMPROVEMENT_BACKLOG.md. Al resolverlo, borrá su línea de aquí.
KNOWN_5XX: frozenset[str] = frozenset(
    {
        "POST /api/v1/licitaciones/bulk-get",
        "PUT /api/v1/feature-flags",
        "DELETE /api/v1/watchlist/items/{id_externo}",
    }
)


@dataclass
class Resultado:
    """Recuento y primer ejemplo reproducible por operación."""

    ejemplos: int = 0
    fallos: int = 0
    repro: str | None = None


@dataclass
class Informe:
    por_operacion: dict[str, Resultado] = field(default_factory=dict)
    operaciones_fuzzeadas: int = 0
    excluidas: int = 0
    # Distribución de códigos de respuesta. Se imprime siempre porque es la
    # única forma de ver que el fuzzing ejercitó algo: un run compuesto de
    # 429s o 401s sale "sin 5xx" sin haber tocado una sola ruta.
    status: dict[int, int] = field(default_factory=dict)

    @property
    def fallando(self) -> set[str]:
        return {label for label, r in self.por_operacion.items() if r.fallos}


def _desactivar_rate_limiter() -> None:
    """Sustituye el limitador por un no-op, como hace ``tests/conftest.py``.

    Sin esto el fuzzer se come un 429 a partir de la petición 120 y el resto
    del run no ejercita ninguna ruta: mediría el limitador, no el contrato, y
    saldría verde por no llegar nunca al código. **No sirve subir
    ``API_RATE_LIMIT_MAX_CALLS`` por entorno**: `api/app.py` lo lee con
    ``getattr(settings, ...)`` y ``Settings`` no declara ese campo (tiene
    ``extra="ignore"``), así que la variable se descarta y siempre vale 120.

    El limitador tiene sus propios tests (``tests/test_rate_limit.py``); lo que
    aquí importa es que ninguna ruta reviente con la entrada que reciba.
    """
    import api.middleware

    class _SinLimite:
        def check(self, key: str, *, max_calls: int = 120, window_seconds: float = 60.0) -> bool:
            return True

    api.middleware.get_rate_limiter = lambda: _SinLimite()  # type: ignore[assignment]


def _preparar_entorno() -> None:
    os.environ.setdefault("ENV", "dev")


def _crear_api_key() -> str:
    """Emite una clave con scopes totales, propiedad del admin del seed.

    Con el admin como dueño, las rutas que exigen ``is_admin`` se ejercitan por
    el camino de éxito y no solo por su 403.
    """
    from api.auth import create_api_key
    from db.users import get_user_by_email

    admin = get_user_by_email("admin@tenderflow.dev")
    user_id = int(admin["id"]) if admin else None
    return create_api_key("fuzz-ci", scopes="*", user_id=user_id)


def _fuzzear_operacion(
    operacion: Any, api_key: str, max_examples: int, status: dict[int, int]
) -> Resultado:
    from hypothesis import HealthCheck, given, settings

    resultado = Resultado()

    @given(case=operacion.as_strategy())
    @settings(
        max_examples=max_examples,
        deadline=None,
        derandomize=True,
        suppress_health_check=list(HealthCheck),
    )
    def ejecutar(case: Any) -> None:
        resultado.ejemplos += 1
        try:
            respuesta = case.call(headers={"X-API-Key": api_key})
        except Exception as exc:
            # Una excepción que escapa del transporte es tan grave como un 500.
            resultado.fallos += 1
            if resultado.repro is None:
                resultado.repro = f"excepción {type(exc).__name__}: {str(exc)[:200]}"
            return
        status[respuesta.status_code] = status.get(respuesta.status_code, 0) + 1
        if respuesta.status_code >= 500:
            resultado.fallos += 1
            if resultado.repro is None:
                resultado.repro = f"HTTP {respuesta.status_code} con {_describir(case)}"

    ejecutar()
    return resultado


def _describir(case: Any) -> str:
    partes = []
    for atributo in ("path_parameters", "query", "body", "headers"):
        valor = getattr(case, atributo, None)
        if valor:
            partes.append(f"{atributo}={str(valor)[:120]}")
    return ", ".join(partes) or "sin parámetros"


def ejecutar_fuzzing(max_examples: int) -> Informe:
    """Fuzzea todas las operaciones: primero lecturas, luego mutaciones.

    El orden importa: las lecturas ven el seed intacto, que es cuando más
    cobertura real dan. Después van las mutaciones, cuyos efectos sobre la BD
    no son un problema —la base muere con el job, y un 500 provocado porque
    otro ejemplo borró una fila sigue siendo un bug: debería ser 404 o 409.
    """
    import schemathesis

    from api.app import app

    _desactivar_rate_limiter()
    schema = schemathesis.openapi.from_asgi("/api/openapi.json", app)
    api_key = _crear_api_key()

    operaciones = []
    for resultado in schema.get_all_operations():
        operacion = resultado.ok()
        label = f"{operacion.method.upper()} {operacion.path}"
        operaciones.append((label, operacion))

    informe = Informe()
    seguras = [(la, op) for la, op in operaciones if op.method.upper() in {"GET", "HEAD"}]
    mutaciones = [(la, op) for la, op in operaciones if op.method.upper() not in {"GET", "HEAD"}]

    for label, operacion in seguras + mutaciones:
        if label in EXCLUDED_OPERATIONS:
            informe.excluidas += 1
            continue
        informe.por_operacion[label] = _fuzzear_operacion(
            operacion, api_key, max_examples, informe.status
        )
        informe.operaciones_fuzzeadas += 1

    return informe


def _imprimir_resumen(informe: Informe) -> None:
    total_ejemplos = sum(r.ejemplos for r in informe.por_operacion.values())
    print(
        f"\nOperaciones fuzzeadas: {informe.operaciones_fuzzeadas} "
        f"({informe.excluidas} excluidas) · ejemplos: {total_ejemplos}"
    )
    distribucion = " ".join(f"{code}:{n}" for code, n in sorted(informe.status.items()))
    print(f"Respuestas: {distribucion}")
    fallando = sorted(informe.fallando)
    print(f"Con 5xx: {len(fallando)} · allowlist: {len(KNOWN_5XX)}")
    for label in fallando:
        resultado = informe.por_operacion[label]
        print(f"  {label}  ({resultado.fallos}/{resultado.ejemplos})")
        print(f"      {resultado.repro}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-examples",
        type=int,
        default=MAX_EXAMPLES_GATE,
        help=(
            f"Ejemplos por operación (el gate usa {MAX_EXAMPLES_GATE}). Más "
            "ejemplos exploran más superficie y tardan más."
        ),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Imprime las operaciones con 5xx y sale 0 (para poblar KNOWN_5XX)",
    )
    args = parser.parse_args()

    _preparar_entorno()

    from db.database import init_db

    init_db()

    informe = ejecutar_fuzzing(args.max_examples)
    _imprimir_resumen(informe)

    fallando = informe.fallando

    if args.list:
        print("\n# Copiá esto a KNOWN_5XX (y arreglá lo que puedas antes):")
        for label in sorted(fallando):
            print(f'        "{label}",')
        return 0

    nuevas = sorted(fallando - KNOWN_5XX)
    resueltas = sorted(KNOWN_5XX - fallando)

    if nuevas:
        print("\n[FALLO] Operación(es) que devuelven 5xx y no estaban en la allowlist:")
        for label in nuevas:
            print(f"  {label}: {informe.por_operacion[label].repro}")
        print("\nUn 4xx es una respuesta válida; un 5xx es una excepción sin manejar.")

    # Informativo, nunca bloqueante: que una entrada no falle en ESTA ejecución
    # no prueba que esté arreglada, porque el resultado depende del estado que
    # dejaron las operaciones anteriores (ver "Por qué esta mitad no es un
    # error" en el docstring). Confirmalo con `--list` sobre una base limpia.
    if resueltas:
        print("\n[AVISO] Entrada(s) de KNOWN_5XX que no fallaron en esta ejecución:")
        for label in resueltas:
            print(f"  {label}")
        print(
            "Si ya están arregladas, borralas de la allowlist. Comprobalo con "
            "`--list` sobre una base recién migrada y sembrada: el resultado "
            "depende del estado de la BD, no solo del código."
        )

    if nuevas:
        return 1

    print("\nSin 5xx fuera de la allowlist.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

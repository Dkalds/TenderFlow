#!/usr/bin/env python3
"""Ratchet de superficie: una operación nueva de la API se justifica por escrito.

AGENTS.md §0 pide, antes de añadir una superficie, comprobar que ninguna
existente cubre ya el caso. Era una frase: la API pasó de 154 operaciones
(2026-08-07, el día que se declaró el congelamiento) a 292 (2026-10-10) sin que
nada preguntara por qué hacía falta cada una. Este gate convierte la frase en
un paso del cambio.

Cómo funciona
-------------

* ``api/superficie_congelada.txt`` es la línea base: las operaciones que
  existían al escribir el gate, una por línea (``MÉTODO /ruta``). **No se le
  añaden líneas.** Cuando una operación se retira, su línea se borra y la base
  encoge: es la medida de cuánta superficie heredada queda.
* ``NUEVAS`` (aquí abajo) es el único camino para añadir una operación: su
  clave y un motivo que diga **qué superficie existente se miró y por qué no
  alcanza**. Un motivo vacío o de compromiso falla.
* Una operación que no está en ninguna de las dos falla. Una entrada de
  cualquiera de las dos que ya no existe en la app también: las listas tienen
  que describir la API real.

No es un congelamiento: añadir un endpoint cuesta una línea. Lo que impide es
añadirlo sin haberse hecho la pregunta.

La superficie la calcula ``api.rutas.operaciones`` (anclada en
``app.openapi()``, más las rutas fuera del esquema) con ``ENV=dev`` y
``APP_PROFILE=api``, igual que ``scripts/gen_status.py``: en ``dev`` existe
``/auth/dev-login``, y el perfil ``worker`` solo monta ``health``. Con otro
entorno la lista sería otra.

Uso::

    ENV=dev python scripts/check_api_surface.py           # el gate
    ENV=dev python scripts/check_api_surface.py --list    # operaciones de hoy
    ENV=dev python scripts/check_api_surface.py --count   # solo el número
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_BASE = _ROOT / "api" / "superficie_congelada.txt"

#: Un motivo más corto que esto no puede nombrar una superficie y decir por qué
#: no alcanza. No mide la calidad del motivo —eso es de la revisión—, solo
#: impide el ``"hace falta"``.
MOTIVO_MINIMO = 40

# ── Operaciones añadidas después de la línea base ───────────────────────────
# Formato: ``"MÉTODO /ruta": "qué superficie existente se miró y por qué no
# alcanza"``. Una por línea, en orden alfabético de ruta, para que dos ramas
# que añaden operaciones distintas no choquen al fusionar.
NUEVAS: dict[str, str] = {
    "POST /api/v1/auth/password/change": (
        "Se miró POST /auth/password-reset/confirm, que cambia la contraseña pero exige el "
        "token de un solo uso que llega por correo, no la contraseña actual: quien la "
        "conoce tenía que pedirse un enlace para cambiarla, y ese camino revoca también la "
        "sesión desde la que se hace. PUT /me/profile y PUT /me/notification-preferences no "
        "tocan credenciales. El cambio pide la actual, deja viva la sesión que lo hace y "
        "revoca las demás y las claves de API (backlog, recuperación de contraseña punto 3)."
    ),
    "POST /api/v1/auth/verify-email": (
        "Se miró POST /auth/password-reset/confirm, que consume un token de un solo uso "
        "llegado por correo, pero cambia la contraseña y revoca sesiones: la activación "
        "del alta (RFC 2026-10-21) no cambia nada de la cuenta salvo marcarla verificada, "
        "abre sesión y activa invitaciones. Meterla ahí haría que un mismo endpoint "
        "hiciera dos cosas según qué tabla guardara el token. POST "
        "/organizations/invitations/accept exige sesión, que es justo lo que aún no hay."
    ),
    "GET /api/v1/admin/api-keys": (
        "Se miró GET /me/keys, que lista solo las claves de quien pregunta (WHERE user_id = "
        "el suyo), y GET /admin/users, que lista personas y no credenciales. Ninguna "
        "enseña las claves de otros ni las que no tienen dueño, que es justo lo que hay "
        "que inventariar: 89 activas en producción con user_id nulo y sin expires_at "
        "(backlog, «Inventariar las claves de API sin dueño»)."
    ),
    "DELETE /api/v1/admin/api-keys/{key_id}": (
        "Se miró DELETE /me/keys/{key_id}, que revoca solo una clave propia (el dueño va "
        "en el WHERE), y POST /admin/users/{id}/deactivate, que revoca todas las de una "
        "persona al darla de baja. Una clave sin dueño no la alcanza ninguna de las dos: "
        "no es de nadie que se pueda desactivar ni de quien mira."
    ),
    "GET /api/v1/admin/revision/duplicados": (
        "Se miró GET /empresas/reviews, que lista la cola de identidad de EMPRESAS "
        "(empresa_review_queue), no pares de licitaciones; GET /admin/dlq, que es de "
        "extracciones fallidas de la ingesta; y GET /analytics/quality, que solo cuenta. "
        "Ninguna enseña los pares pending de licitaciones_duplicados con las dos filas "
        "a la vista, que es lo que hace falta para decidir si son el mismo contrato."
    ),
    "POST /api/v1/admin/revision/duplicados/{id_externo:path}/resolver": (
        "Se miró POST /empresas/reviews/{id}, que resuelve la cola de empresas y vincula "
        "adjudicaciones, y POST /admin/dlq/{id}/reintentar, que reencola filas de "
        "ingesta. Ninguna cambia el status de licitaciones_duplicados: hasta ahora un "
        "par pending solo se resolvía desde un test."
    ),
    "GET /api/v1/admin/revision/organos": (
        "Se miró GET /empresas/reviews, que decide identidad de empresas y no de órganos "
        "de contratación, y GET /analytics/quality, que publica solo el tamaño de "
        "organo_review_queue (organos_revision_pendiente). Ninguna lista las grafías "
        "dudosas con su candidato, que es lo que se necesita para decidir la fusión."
    ),
    "POST /api/v1/admin/revision/organos/{revision_id}/resolver": (
        "Se miró POST /empresas/reviews/{id}, que es el mismo patrón para empresas pero "
        "escribe en empresas/empresa_aliases y adjudicaciones, no en organos ni en "
        "licitaciones.organo_id. No existía ninguna función, ni ruta, que resolviera "
        "organo_review_queue: la cola solo crecía."
    ),
    "GET /api/v1/admin/revision/verdad": (
        "Se miró GET /analytics/quality, que mide completitud y frescura pero no aplica "
        "los umbrales calibrados de la auditoría de verdad del dato, y GET /admin/dlq, "
        "que es de la ingesta. scripts/audit_domain_truth.py solo sale por correo y como "
        "artefacto de Actions: sin esta ruta la consola no puede enseñar sus violaciones."
    ),
    "GET /api/v1/licitaciones/{id_externo:path}/condiciones-oficiales": (
        "Se miró GET /licitaciones/{id}/ficha-pliego, que sirve la extracción LLM del "
        "pliego y responde 404 mientras no se ha extraído: meter ahí el dato de PLACSP "
        "mezclaría dos procedencias en un mismo contrato y lo escondería tras ese 404. "
        "GET /licitaciones/{id} (detalle) no lo trae y engordaría la lectura más "
        "caliente de la API con tres tablas que solo pide la pestaña Pliego y el "
        "checklist Go/No-Go."
    ),
    "DELETE /api/v1/me/keys/{key_id}": (
        "Se miró POST /me/keys/rotate, que deja la clave vieja viva durante la gracia "
        "(con 0 días sigue acuñando otra), DELETE /me, que revoca todas a la vez junto con "
        "la cuenta, y POST /security/leaked-key, que solo acepta el webhook "
        "firmado de GitHub. Ninguna deja al dueño apagar una clave concreta al momento, "
        "que es lo que hace falta cuando una se filtra o deja de usarse."
    ),
    "POST /api/v1/me/profile/preview": (
        "Se miró GET /analytics/scoring, que puntúa siempre con el perfil guardado: "
        "no admite uno de prueba, y unos pesos con sus palabras clave y CPV no caben "
        "en una query. PUT /me/profile lo aceptaría, pero guardándolo. La vista previa "
        "necesita además las dos pasadas (prueba y guardado) sobre el mismo universo "
        "en una sola respuesta, para poder decir cuánto se mueve cada oportunidad."
    ),
    "GET /api/v1/notifications/alerts": (
        "Se miró GET /notifications: devuelve las 30 alertas más recientes con las no "
        "leídas primero, sin total ni desplazamiento, y arrastra los contadores de "
        "mercado (`hoy`, deprecado pero aún calculado por compatibilidad), una consulta "
        "sobre licitaciones que cada página de «Ver todas» y cada refresco de la campana "
        "pagarían sin pintarla. Ampliarlo con filtro y paginación habría mezclado dos "
        "contratos en uno; la bandeja paginada con filtro de lectura y el número sin leer "
        "es la que pide la campana «solo lo tuyo»."
    ),
    "GET /api/v1/pursuits/adjuntos/politica": (
        "Se miraron GET /pursuits/{id}/adjuntos, que devuelve una lista y no admite "
        "metadatos sin romper su contrato, y POST /pursuits/{id}/adjuntos, que solo "
        "dice que no hay almacén (503), que el fichero es grande (413) o que el tipo "
        "no vale (415) después de recibir hasta 25 MiB. /meta/filters es el catálogo "
        "de filtros de licitaciones, cacheado y ajeno. La consola necesita saber antes "
        "de ofrecer la subida si el entorno tiene almacén, el tope y la lista blanca, "
        "sin llevar su propia copia de las constantes del servidor."
    ),
}


def leer_base(ruta: Path = _BASE) -> set[str]:
    """Operaciones de la línea base. Ignora líneas vacías y comentarios ``#``."""
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    return {s for linea in lineas if (s := linea.strip()) and not s.startswith("#")}


def operaciones() -> list[str]:
    """Operaciones que expone la app hoy, como ``"MÉTODO /ruta"``.

    Reusa el recorrido de ``scripts/gen_status.py`` para que ``docs/STATUS.md``
    y este gate no puedan contar dos superficies distintas.
    """
    for carpeta in (_ROOT, _ROOT / "scripts"):
        if str(carpeta) not in sys.path:
            sys.path.insert(0, str(carpeta))
    import gen_status

    return sorted(f"{metodo} {ruta}" for metodo, ruta in gen_status._endpoints())


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="imprime las operaciones actuales")
    parser.add_argument("--count", action="store_true", help="imprime solo el conteo")
    args = parser.parse_args(argv)

    actuales = set(operaciones())

    if args.count:
        print(len(actuales))
        return 0
    if args.list:
        print("\n".join(sorted(actuales)))
        return 0

    base = leer_base()
    sin_justificar = sorted(actuales - base - set(NUEVAS))
    fosiles_base = sorted(base - actuales)
    fosiles_nuevas = sorted(set(NUEVAS) - actuales)
    duplicadas = sorted(set(NUEVAS) & base)
    motivos_cortos = sorted(
        op for op, motivo in NUEVAS.items() if len(motivo.strip()) < MOTIVO_MINIMO
    )

    if sin_justificar:
        print(
            f"{len(sin_justificar)} operación(es) NUEVA(s) sin justificar:",
            file=sys.stderr,
        )
        for op in sin_justificar:
            print(f"  - {op}", file=sys.stderr)
        print(
            "\nAGENTS.md §0: antes de añadir una superficie, comprobá que ninguna "
            "existente cubre ya el caso (un filtro más, un campo más en un DTO, "
            "otra vista del mismo recurso). Si de verdad hace falta, añadí la "
            "operación a NUEVAS en scripts/check_api_surface.py con el motivo: qué "
            "superficie miraste y por qué no alcanza. La línea base "
            "(api/superficie_congelada.txt) no admite líneas nuevas.",
            file=sys.stderr,
        )
    if fosiles_base:
        print(
            f"\n{len(fosiles_base)} línea(s) de api/superficie_congelada.txt ya no "
            "existen en la app: bórralas, la base solo puede encoger.",
            file=sys.stderr,
        )
        for op in fosiles_base:
            print(f"  - {op}", file=sys.stderr)
    if fosiles_nuevas:
        print(
            f"\n{len(fosiles_nuevas)} entrada(s) de NUEVAS ya no existen en la app: bórralas.",
            file=sys.stderr,
        )
        for op in fosiles_nuevas:
            print(f"  - {op}", file=sys.stderr)
    if duplicadas:
        print(
            f"\n{len(duplicadas)} entrada(s) de NUEVAS ya están en la línea base: "
            "una operación heredada no necesita motivo, quitalas de NUEVAS.",
            file=sys.stderr,
        )
        for op in duplicadas:
            print(f"  - {op}", file=sys.stderr)
    if motivos_cortos:
        print(
            f"\n{len(motivos_cortos)} motivo(s) de NUEVAS no dicen qué superficie "
            f"existente se miró (menos de {MOTIVO_MINIMO} caracteres):",
            file=sys.stderr,
        )
        for op in motivos_cortos:
            print(f"  - {op}", file=sys.stderr)

    if sin_justificar or fosiles_base or fosiles_nuevas or duplicadas or motivos_cortos:
        return 1

    heredadas = len(actuales & base)
    print(
        f"Ratchet de superficie OK: {len(actuales)} operaciones "
        f"({heredadas} de la línea base, {len(NUEVAS)} añadidas con motivo)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

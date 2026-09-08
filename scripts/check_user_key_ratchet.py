#!/usr/bin/env python3
"""Ratchet de ``user_key``: la lista de ficheros que la usan solo puede encoger.

D18 del plan de arquitectura 2026-09 v2, fase 1. La identidad interna de
TenderFlow se deriva hoy del correo (``shared.identity.user_key_from_email``),
así que cambiar de dirección pierde favoritos, reglas, vistas, descartes,
notificaciones y oportunidades. La fase 2 (T4) migra a ``user_id`` con columna
doble y lectura dual; hasta entonces lo que hay que impedir es que el problema
siga creciendo, que es exactamente lo que hace este script:

* Un fichero de la lista congelada puede seguir usando ``user_key``.
* Un fichero **nuevo** que la use falla el gate.
* Un fichero que deja de usarla se borra de la lista y esta encoge. Si sigue en
  la lista sin usarla, el script también falla: una whitelist que no se limpia
  acumula fósiles y miente sobre el tamaño real de la deuda (misma lección que
  ``_stale_whitelist_entries`` en ``scripts/gen_status.py``).

Qué se escanea y qué no
-----------------------

Solo código de producción. Quedan fuera:

* ``tests/`` — un test que verifica el comportamiento de ``user_key`` **tiene**
  que nombrarla; congelar los tests castigaría escribir cobertura sobre la
  deuda que se quiere retirar.
* ``db/alembic/versions/`` — las migraciones son append-only e históricas.
  Además T4 necesitará escribir migraciones que nombren la columna para
  poder eliminarla, y un gate que lo prohibiera bloquearía su propia solución.

Uso::

    python scripts/check_user_key_ratchet.py           # falla si hay ficheros nuevos
    python scripts/check_user_key_ratchet.py --list    # imprime los que la usan hoy
    python scripts/check_user_key_ratchet.py --count   # solo el número (make status)
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

#: Símbolo que se persigue. Se busca como subcadena a propósito: ``user_key``,
#: ``_user_key``, ``user_key_from_email`` y ``export_by_user_key`` son la misma
#: deuda y todas empiezan por lo mismo.
_SIMBOLO = "user_key"

#: Directorios excluidos del escaneo (ver el docstring del módulo).
_EXCLUIDOS = ("tests/", "db/alembic/versions/")

#: Ficheros que *informan* sobre el ratchet en vez de usar `user_key`. Este
#: script y el generador de `docs/STATUS.md` nombran el símbolo para poder
#: contarlo: incluirlos sería contar el termómetro como parte de la fiebre.
_REPORTEROS = frozenset(
    {
        "scripts/gen_status.py",
        # Llega con #272. Su docstring nombra ``user_key`` para decir que
        # ninguna consulta del módulo la acepta —cuentas objetivo y etiquetas
        # son de organización, no de usuario—. Mencionar la deuda para negarla
        # no es tenerla, y congelarlo habría inflado el conteo de STATUS.md con
        # un fichero que no tiene nada que migrar.
        "db/repositories/cuentas.py",
    }
)

# ── RATCHET: ficheros de producción que todavía usan ``user_key`` ───────────
# Medido con este mismo script el 2026-09-06 sobre la cabeza del repo.
# **Añadir líneas está prohibido.** Para quitar una: deja de usar ``user_key``
# en ese fichero y borra su entrada.
#
# Excepción anotada a mano el 2026-09-06, el único camino que este script admite
# (ver el docstring): ``db/events.py`` y ``services/contract_events.py`` entraron
# el mismo día desde S4, y su uso no es identidad nueva sino la lectura de
# ``watchlist_items.user_key`` —una columna que ya existe y que el despachador de
# eventos tiene que consultar para saber a quién notificar—. Sin ellas, el gate
# habría bloqueado el stream que las trae sin ofrecerle alternativa: la columna
# la retira T4, y estas dos entradas se van con ella. Se anotan aquí, y no se
# ocultan ampliando el escaneo, para que el conteo de ``docs/STATUS.md`` siga
# diciendo la verdad sobre el tamaño de la deuda.
#
# Segunda tanda de excepciones del 2026-09-07, por el mismo motivo y el mismo
# camino. Las destapó CI, no una revisión: el ratchet hizo exactamente su
# trabajo el primer día que corrió.
#
#   - ``scheduler/jobs/event_dispatch.py`` es el ÚNICO punto donde el
#     despachador traduce ``user_id`` a ``user_key``, y está centralizado ahí a
#     propósito: los eventos de ``pursuit.*`` viajan con ids de usuario, pero
#     ``user_notifications`` y ``pending_digests`` se indexan por ``user_key``.
#     La alternativa que pide D18 —usar el ``user_id`` del principal— no existe
#     hasta que T4 añada la columna a esas dos tablas. Tener la traducción en un
#     solo sitio es además lo que hará barato quitarla: T4 borra esta función,
#     no treinta llamadas repartidas.
#   - ``shared/events.py`` no usa ``user_key`` como identidad: lo nombra como
#     CAMPO del payload de ``watchlist_rule.matched``, un evento de webhook que
#     ya existía antes del catálogo. Renombrar esa clave sería un cambio
#     breaking del contrato publicado para quien tenga ese webhook suscrito, así
#     que se retira cuando se retire la columna, y no antes.
#
# Tercera tanda del 2026-09-07, al fusionar master: la trae #272 (plan de
# funcionalidades), que creció en paralelo a este gate y por tanto sin poder
# respetarlo. El criterio no es nuevo, es el de las dos tandas anteriores:
#
#   - ``db/repositories/novedades.py`` y ``services/novedades.py`` leen
#     ``watchlist_items.user_key`` para contestar «qué ha cambiado en lo que
#     sigo». Es la misma columna que consulta ``db/events.py`` y se retira con
#     ella en T4; hasta entonces no hay ``user_id`` por el que filtrar.
#   - ``services/cuentas.py`` traduce ``user_id`` a ``user_key`` en un único
#     punto —``_copiar_para_miembro``— porque ``create_rule`` y ``save_filter``
#     siguen tecleadas por ``user_key``. Cuando T4 les cambie la clave, la
#     traducción se va con ellas: es una línea, no treinta.
#
# La alternativa era rehacer código de producto ya fusionado para satisfacer un
# gate que se escribió después: eso no retira deuda, la muda de sitio y arriesga
# funcionalidad que ya está en master.
#
# 2026-09-08 — tres ficheros más, por lo mismo y con un matiz. Llegan de
# `claude/plan-arquitectura-complementario-b5888b`, escrita sobre `master` =
# `17169ce`, es decir **antes** de que este ratchet existiera: no son código
# nuevo que ignore el gate, es código que se escribió sin él.
#
#   - ``db/idempotency.py`` es el único de los tres que de verdad carga la
#     deuda: el ámbito de una clave de idempotencia se teclea por el
#     ``user_key`` derivado del correo, que es lo que le llega desde las rutas.
#     Se va con T4, como el resto.
#   - ``services/gonogo.py`` y ``services/tech_dictionary.py`` NO derivan nada
#     del correo: pasan ``user_key=f"user:{user_id}"`` a ``db.audit.log_event``,
#     que es exactamente la forma que D18 persigue. Están aquí porque el ratchet
#     cuenta el identificador y no su semántica, y porque el parámetro de
#     ``log_event`` se llama así; cuando T4 lo renombre, los dos salen sin tocar
#     una línea de producto.
CONGELADOS: frozenset[str] = frozenset(
    {
        "api/routes/admin_solicitudes.py",
        "api/routes/admin_users.py",
        "api/routes/analytics.py",
        "api/routes/ask.py",
        "api/routes/auth.py",
        "api/routes/competitive.py",
        "api/routes/dual_auth.py",
        "api/routes/empresas.py",
        "api/routes/exports.py",
        "api/routes/feature_flags.py",
        "api/routes/feedback.py",
        "api/routes/licitaciones.py",
        "api/routes/me.py",
        "api/routes/notifications.py",
        "api/routes/pursuits.py",
        "api/routes/radar.py",
        "api/routes/saved_filters.py",
        "api/routes/watchlist_feed.py",
        "api/routes/watchlist_items.py",
        "api/routes/watchlist_rules.py",
        "api/routes/webhooks.py",
        "db/audit.py",
        "db/events.py",
        "db/idempotency.py",
        "db/notifications.py",
        "db/radar_dismissals.py",
        "db/repositories/agenda.py",
        "db/repositories/audit.py",
        "db/repositories/novedades.py",
        "db/repositories/organizations.py",
        "db/repositories/pursuits.py",
        "db/repositories/user_profiles.py",
        "db/repositories/watchlist.py",
        "db/repositories/watchlist_rules.py",
        "db/saved_filters.py",
        "db/watchlist.py",
        "db/watchlist_empresas.py",
        "llm/budget.py",
        "scheduler/jobs/event_dispatch.py",
        "scheduler/jobs/watchlist_rules.py",
        "scheduler/watchlist_alerts.py",
        "scheduler/watchlist_rules_alerts.py",
        "scripts/asignar_organizacion_huerfanos.py",
        "services/analytics/quality.py",
        "services/analytics/scoring.py",
        "services/audit.py",
        "services/contract_events.py",
        "services/cuentas.py",
        "services/deadline_reminders.py",
        "services/email_digest.py",
        "services/gdpr.py",
        "services/gonogo.py",
        "services/notifications.py",
        "services/novedades.py",
        "services/organizations.py",
        "services/pursuit_awards.py",
        "services/pursuits.py",
        "services/saved_filters.py",
        "services/tech_dictionary.py",
        "services/watchlist.py",
        "services/watchlist_rules.py",
        "shared/cache.py",
        "shared/dto.py",
        "shared/events.py",
        "shared/identity.py",
        "shared/types.py",
        "shared/user_key.py",
    }
)


def _ficheros_con_user_key() -> list[str]:
    """Ficheros ``.py`` versionados que nombran ``user_key``, sin los excluidos.

    Se pregunta a git (y no a un ``Path.rglob``) por la misma razón que el resto
    de gates del repo: lo que no está versionado —``.venv``, artefactos, caches—
    no es código del proyecto y no debe contar.
    """
    git = shutil.which("git")
    if git is None:  # pragma: no cover - CI y pre-commit siempre lo tienen
        raise RuntimeError("Este gate necesita git en el PATH para enumerar el repo.")
    # argv fijo, sin shell y sin ninguna entrada del usuario.
    salida = subprocess.run(
        [git, "ls-files", "*.py"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    encontrados: list[str] = []
    propio = Path(__file__).resolve().relative_to(_ROOT).as_posix()
    for linea in salida.splitlines():
        ruta = linea.strip()
        if not ruta or ruta.startswith(_EXCLUIDOS) or ruta == propio or ruta in _REPORTEROS:
            continue
        try:
            texto = (_ROOT / ruta).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _SIMBOLO in texto:
            encontrados.append(ruta)
    return sorted(encontrados)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="imprime los ficheros actuales")
    parser.add_argument("--count", action="store_true", help="imprime solo el conteo")
    args = parser.parse_args(argv)

    actuales = _ficheros_con_user_key()

    if args.count:
        print(len(actuales))
        return 0
    if args.list:
        print("\n".join(actuales))
        return 0

    nuevos = sorted(set(actuales) - CONGELADOS)
    fosiles = sorted(CONGELADOS - set(actuales))

    if nuevos:
        print(
            f"{len(nuevos)} fichero(s) NUEVO(s) usan `user_key` (D18 lo prohíbe en código nuevo):",
            file=sys.stderr,
        )
        for ruta in nuevos:
            print(f"  - {ruta}", file=sys.stderr)
        print(
            "\nLa identidad interna se está migrando a `user_id` (D18/T4). Usa el "
            "`user_id` del principal; si de verdad no hay alternativa, la excepción "
            "se discute en el PR y se anota aquí a mano.",
            file=sys.stderr,
        )
    if fosiles:
        print(
            f"\n{len(fosiles)} entrada(s) de la lista ya no usan `user_key`: "
            "bórralas de CONGELADOS, el ratchet solo puede encoger.",
            file=sys.stderr,
        )
        for ruta in fosiles:
            print(f"  - {ruta}", file=sys.stderr)

    if nuevos or fosiles:
        return 1

    print(f"Ratchet user_key OK: {len(actuales)} ficheros de producción, ninguno nuevo.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

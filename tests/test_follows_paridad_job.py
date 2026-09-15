"""El paso que mide la paridad de `follows` en cada pasada (ADR-031 §B).

Por qué este job existe, y por qué se prueba
--------------------------------------------
La medición estaba desde el principio en `scripts/check_follows_paridad.py` y
la ejecutaba nadie: el plan la listaba como «acción humana — ejecutar contra
producción». Un número que hay que ir a buscar no es un número que exista, y
mientras no existiera, la migración de ADR-031 §B no podía avanzar.

Lo que se fija aquí es lo que hace ese paso y, sobre todo, **lo que no hace**:

1. Mide y deja el número en `ops_events`, donde se consulta como serie.
2. Cuando falta una fila lo dice como aviso —no como error— y **el valor del
   evento es `faltan`**, que es el único que bloquea la migración.
3. **No repara nada.** Ni reescribe `follows`, ni mueve una lectura, ni borra.
   Si algún día lo hiciera, sería un backfill disfrazado de medición, y el
   número dejaría de significar lo que ADR-031 le pide que signifique.
4. Una medición que falla no tumba la pasada: es advisory.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

from scheduler.jobs.follows_paridad import TIPO_EVENTO, ejecutar


def _usuario(db_mod: Any, correo: str) -> tuple[int, int, str]:
    from db.repositories.organizations import OrganizationRepository
    from db.users import create_user
    from shared.identity import user_key_from_email

    user_id = create_user(email=correo, password_hash="x")  # pragma: allowlist secret
    org_id = int(OrganizationRepository().ensure_personal_organization(user_id)["id"])
    return user_id, org_id, user_key_from_email(correo, user_id)


def _licitacion(db_mod: Any, id_externo: str) -> None:
    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion) "
            "VALUES (%s, %s, %s) ON CONFLICT (id_externo) DO NOTHING",
            (id_externo, "Expediente de prueba", "2026-09-01T00:00:00+00:00"),
        )


def test_con_escritura_doble_la_paridad_sale_en_cero(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    from db.repositories.watchlist import WatchlistRepository

    user_id, org_id, user_key = _usuario(db_mod, "job-paridad@example.test")
    _licitacion(db_mod, "LIC-JOB-OK")
    WatchlistRepository().add_item(user_key, user_id, "LIC-JOB-OK", org_id, "private")

    with patch("observability.ops_events.record_event") as evento:
        resumen = ejecutar()

    assert resumen.ok
    assert resumen.faltan == 0
    assert resumen.pares == 3
    assert resumen.filas_origen >= 1
    evento.assert_called_once()
    assert evento.call_args.args[0] == TIPO_EVENTO
    assert evento.call_args.kwargs["value"] == 0.0


def test_una_fila_sin_reflejar_sale_en_el_evento_y_no_se_repara(tmp_db: Any) -> None:
    """Lo importante de este test es la segunda mitad.

    Que el job cuente la fila que falta es lo obvio. Que **no la escriba** es
    lo que hay que fijar: la tentación de «ya que lo he detectado, lo arreglo»
    convertiría el número en una tautología —siempre cero, porque el propio
    medidor lo pone a cero— y ADR-031 §B se quedaría sin la señal que pide.
    """
    db_mod, _ = tmp_db

    user_id, org_id, user_key = _usuario(db_mod, "job-hueco@example.test")
    _licitacion(db_mod, "LIC-JOB-HUECO")
    # Se escribe saltándose la escritura doble: la forma exacta de un backfill
    # a medias.
    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO watchlist_items (user_key, user_id, id_externo, created_at, "
            " organization_id, visibility) VALUES (%s, %s, %s, %s, %s, %s)",
            (
                user_key,
                user_id,
                "LIC-JOB-HUECO",
                "2026-09-01T00:00:00+00:00",
                org_id,
                "private",
            ),
        )

    def _follows() -> int:
        with db_mod.connect_read() as c:
            return int(c.execute("SELECT COUNT(*) FROM follows").fetchone()[0])

    antes = _follows()
    with patch("observability.ops_events.record_event") as evento:
        resumen = ejecutar()

    assert not resumen.ok
    assert resumen.faltan == 1
    assert resumen.usuarios_con_diferencias == 1
    assert evento.call_args.kwargs["value"] == 1.0
    detalle = json.loads(evento.call_args.kwargs["detail"])
    assert detalle["watchlist_items"]["faltan"] == 1

    # La mitad que importa: la fila sigue faltando.
    assert _follows() == antes


def test_el_detalle_no_lleva_identificadores_de_personas(tmp_db: Any) -> None:
    """`ops_events` se consulta sin ceremonia; no es sitio para `user_key`.

    El script a mano sí enseña ejemplos —quien lo corre está delante de su
    pantalla y los necesita para reparar—. El job pide `detalle=0` justamente
    para que la serie quede limpia.
    """
    db_mod, _ = tmp_db

    user_id, org_id, user_key = _usuario(db_mod, "job-pii@example.test")
    _licitacion(db_mod, "LIC-JOB-PII")
    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO watchlist_items (user_key, user_id, id_externo, created_at, "
            " organization_id, visibility) VALUES (%s, %s, %s, %s, %s, %s)",
            (user_key, user_id, "LIC-JOB-PII", "2026-09-01T00:00:00+00:00", org_id, "private"),
        )

    with patch("observability.ops_events.record_event") as evento:
        ejecutar()

    detalle = evento.call_args.kwargs["detail"]
    assert user_key not in detalle
    assert "LIC-JOB-PII" not in detalle


def test_si_la_medicion_falla_el_paso_no_lanza(tmp_db: Any) -> None:
    """Advisory: un fallo aquí no puede tumbar la pasada de ingesta."""
    with (
        patch("scripts.check_follows_paridad.medir", side_effect=RuntimeError("base caída")),
        patch("observability.ops_events.record_event") as evento,
    ):
        resumen = ejecutar()

    assert resumen.pares == 0
    # Sin medición no hay número: registrar un cero sería peor que no registrar
    # nada, porque el cero es exactamente la señal de «ya se puede migrar».
    evento.assert_not_called()


def test_el_paso_esta_declarado_y_es_advisory() -> None:
    from scheduler.pipeline_runs import CANONICAL_STEPS, STEP_TIER

    assert "follows_paridad" in CANONICAL_STEPS
    assert STEP_TIER["follows_paridad"] == "advisory"


def test_el_ejecutor_resuelve_el_paso_por_convencion() -> None:
    """`_run_{nombre}`: si el paso está en la lista y la función no existe, la
    pasada falla en runtime y no al importar."""
    import scheduler.pipeline_runs as mod

    assert callable(mod._run_follows_paridad)

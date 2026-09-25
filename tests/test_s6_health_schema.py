"""El endpoint de salud compara el código desplegado con el schema aplicado.

Motivación (S6.2)
-----------------
Nada relacionaba las dos cosas. ``migrate.yml`` es ``workflow_dispatch`` a
propósito y el arranque de la API solo hace ping a la BD, así que ``deploy.yml``
podía publicar código que exige la revisión N+1 sobre una base en N y **todos**
los gates salían verdes. Es literalmente el incidente que motivó crear
``migrate.yml``: ``column "lote_id" of relation "adjudicaciones" does not
exist`` en los runs de scrape del 31-jul/1-ago.

Estos tests corren **sin base de datos**: inyectan las dos revisiones (la
aplicada y la del repo) en la función pura ``comparar_revisiones`` y sustituyen
los sondeos por dobles. Lo único que toca disco es el test que lee las cabezas
del propio checkout, que es lectura de ``db/alembic/versions``.

Desde 2026-09 la comparación vive en ``db/schema_revision.py``, compartida con
el preflight de los workflows de datos (``python -m db.schema_revision``, cuyo
contrato fija ``tests/test_unit_schema_revision.py``). Aquí se sigue fijando lo
que es del endpoint: que publica el mismo vocabulario, que solo ``behind`` y
``ahead`` degradan, que un fallo nunca propaga y la caché.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import pytest

from api.routes import health
from db import schema_revision

_CABEZA = "v98_mv_canonicas_universo_tecnologico"
_ANTERIOR = "v97_pursuit_comments"
_CONOCIDAS = (_ANTERIOR, _CABEZA)


# ---------------------------------------------------------------------------
# La comparación pura
# ---------------------------------------------------------------------------


def test_revision_aplicada_igual_a_la_cabeza_es_ok() -> None:
    assert (
        schema_revision.comparar_revisiones([_CABEZA], [_CABEZA], _CONOCIDAS) == f"ok ({_CABEZA})"
    )


def test_revision_por_detras_es_behind_con_las_dos_revisiones() -> None:
    """El detalle tiene que nombrar ambas: sin ellas nadie sabe qué aplicar."""
    detalle = schema_revision.comparar_revisiones([_ANTERIOR], [_CABEZA], _CONOCIDAS)
    assert detalle == f"behind ({_ANTERIOR} < {_CABEZA})"


def test_base_sin_migrar_es_behind_y_no_un_crash() -> None:
    """``alembic_version`` vacía es el caso de una BD nueva, no un error."""
    detalle = schema_revision.comparar_revisiones([], [_CABEZA], _CONOCIDAS)
    assert detalle == f"behind (ninguna < {_CABEZA})"


def test_revision_desconocida_es_ahead_y_no_behind() -> None:
    """La BD tiene una revisión que este checkout no conoce.

    Se distingue de ``behind`` porque se arregla al revés: aquí el código
    desplegado es MÁS VIEJO que el schema, así que migrar no arregla nada — hay
    que desplegar el código correcto.
    """
    detalle = schema_revision.comparar_revisiones(["v99_futura"], [_CABEZA], _CONOCIDAS)
    assert detalle.startswith("ahead (")
    assert "v99_futura" in detalle


def test_sin_cabezas_no_se_afirma_nada() -> None:
    """Un repo del que no se pudieron leer cabezas no autoriza a decir 'behind'."""
    assert schema_revision.comparar_revisiones([_ANTERIOR], [], _CONOCIDAS) == "unknown"


def test_orden_de_las_revisiones_no_altera_el_resultado() -> None:
    """Múltiples cabezas (merge alembic) se comparan como conjunto ordenado."""
    a = schema_revision.comparar_revisiones([_ANTERIOR, _CABEZA], [_CABEZA, _ANTERIOR], _CONOCIDAS)
    b = schema_revision.comparar_revisiones([_CABEZA, _ANTERIOR], [_ANTERIOR, _CABEZA], _CONOCIDAS)
    assert a == b
    assert a.startswith("ok (")


# ---------------------------------------------------------------------------
# El efecto sobre el estado global
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("schema", ["behind (v97 < v98)", "ahead (v99 > v98)"])
def test_schema_desalineado_degrada_el_estado_global(schema: str) -> None:
    assert health._overall_status("ok", "ok", "ok", schema) == "degraded"


@pytest.mark.parametrize("schema", ["unknown", "unconfigured", "ok (v98)"])
def test_schema_no_afirmado_no_degrada(schema: str) -> None:
    """Un sondeo que no pudo leer la revisión no es un schema desalineado.

    Es la diferencia entre "no lo sé" y "está mal": si `unknown` degradase, un
    despliegue sin ``DATABASE_URL`` visible para el sondeo dejaría el endpoint
    en amarillo permanente y la señal dejaría de significar nada.
    """
    assert health._overall_status("ok", "ok", "ok", schema) == "ok"


def test_la_bd_caida_sigue_mandando_sobre_el_schema() -> None:
    assert health._overall_status("error", "ok", "ok", "ok (v98)") == "degraded"


def test_schema_desalineado_no_devuelve_503() -> None:
    """El 503 sigue reservado a la BD caída.

    Un 503 por schema haría que Render retirase la instancia y dejase la
    superficie pública caída por algo que se arregla corriendo una migración.
    Quien tiene que fallar es el pipeline, no el balanceador.
    """
    assert health._http_status_for_readiness("ok") == 200


# ---------------------------------------------------------------------------
# El sondeo: nunca propaga, y respeta la caché
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _sin_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """La caché es estado de módulo: cada test arranca con ella vacía."""
    monkeypatch.setattr(health, "_schema_cache", None)
    monkeypatch.setenv("HEALTH_SCHEMA_TTL_SECONDS", "0")


def test_check_schema_no_propaga_si_alembic_revienta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un fallo del sondeo devuelve 'unknown'; jamás tumba el endpoint."""

    def _revienta() -> tuple[str, ...]:
        raise RuntimeError("alembic no disponible")

    monkeypatch.setattr(health, "_repo_revisions", _revienta)
    monkeypatch.setattr(health, "_applied_revisions", _revienta)
    monkeypatch.setattr(health, "_database_url", lambda: "postgresql://x/y")

    assert health._check_schema() == "unknown"


def test_check_schema_sin_database_url_es_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health, "_database_url", lambda: "")
    assert health._check_schema() == "unconfigured"


def test_check_schema_cachea_para_no_abrir_una_conexion_por_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Con TTL vivo el segundo sondeo no vuelve a tocar la BD.

    Importa porque este sondeo abre su propia conexión ``NullPool``, fuera de
    los dos pools de psycopg cuyo presupuesto cuenta ``render.yaml`` al detalle.
    Sin caché, el HEALTHCHECK del Dockerfile (cada 30 s) abriría una conexión
    cada 30 s solo para leer una tabla de una fila.
    """
    monkeypatch.setenv("HEALTH_SCHEMA_TTL_SECONDS", "300")
    llamadas: list[int] = []
    monkeypatch.setattr(health, "_database_url", lambda: "postgresql://x/y")
    monkeypatch.setattr(health, "_repo_revisions", lambda: ((_CABEZA,), _CONOCIDAS))

    def _aplicadas() -> tuple[str, ...]:
        llamadas.append(1)
        return (_CABEZA,)

    monkeypatch.setattr(health, "_applied_revisions", _aplicadas)

    primero = health._check_schema()
    segundo = health._check_schema()

    assert primero == segundo == f"ok ({_CABEZA})"
    assert len(llamadas) == 1, "el sondeo abrió una conexión de más pese al TTL"


def test_ttl_cero_desactiva_la_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Durante un incidente hace falta ver el efecto de la migración al instante."""
    llamadas: list[int] = []
    monkeypatch.setattr(health, "_database_url", lambda: "postgresql://x/y")
    monkeypatch.setattr(health, "_repo_revisions", lambda: ((_CABEZA,), _CONOCIDAS))

    def _aplicadas() -> tuple[str, ...]:
        llamadas.append(1)
        return (_CABEZA,)

    monkeypatch.setattr(health, "_applied_revisions", _aplicadas)

    health._check_schema()
    health._check_schema()

    assert len(llamadas) == 2


def test_un_fallo_del_sondeo_se_loguea_con_el_evento_de_siempre_y_sin_credenciales(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``health_schema_check_failed`` sobrevive a la mudanza de la lógica a ``db/``.

    Y su ``error`` llega sin la contraseña, también en la forma
    ``postgresql+psycopg://`` que construye el sondeo y que ``redact_dsn`` no
    reconoce.
    """
    registro = MagicMock()
    monkeypatch.setattr(health, "log", registro)
    monkeypatch.setattr(health, "_database_url", lambda: "postgresql://x/y")
    monkeypatch.setattr(health, "_repo_revisions", lambda: ((_CABEZA,), _CONOCIDAS))

    def _revienta() -> tuple[str, ...]:
        raise RuntimeError(
            "no conecta: postgresql+psycopg://app:secreta@db.example/tf"  # pragma: allowlist secret
        )

    monkeypatch.setattr(health, "_applied_revisions", _revienta)

    assert health._check_schema() == "unknown"
    registro.warning.assert_called_once()
    argumentos, campos = registro.warning.call_args
    assert argumentos == ("health_schema_check_failed",)
    assert campos["error"].startswith("RuntimeError: no conecta")
    assert "secreta" not in campos["error"]


# ---------------------------------------------------------------------------
# El endpoint entero, y el mismo criterio que el preflight de los jobs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("aplicadas", "schema", "status"),
    [
        ((_CABEZA,), f"ok ({_CABEZA})", "ok"),
        ((_ANTERIOR,), f"behind ({_ANTERIOR} < {_CABEZA})", "degraded"),
        (("v99_futura",), f"ahead (v99_futura > {_CABEZA})", "degraded"),
    ],
)
def test_readiness_publica_el_schema_y_solo_el_desfase_degrada(
    monkeypatch: pytest.MonkeyPatch, aplicadas: tuple[str, ...], schema: str, status: str
) -> None:
    """``/health/ready`` sin BD: el mismo payload y el mismo 200 de siempre.

    Un schema desalineado tiñe ``status`` de ``degraded`` pero no toca el
    código HTTP: el 503 sigue reservado a la BD caída.
    """
    monkeypatch.setattr(health, "_check_db", lambda: "ok")
    monkeypatch.setattr(health, "_check_redis", lambda: "unconfigured")
    monkeypatch.setattr(health, "_check_disk", lambda: "ok")
    monkeypatch.setattr(health, "_database_url", lambda: "postgresql://x/y")
    monkeypatch.setattr(health, "_repo_revisions", lambda: ((_CABEZA,), _CONOCIDAS))
    monkeypatch.setattr(health, "_applied_revisions", lambda: aplicadas)

    respuesta = asyncio.run(health.readiness())

    assert respuesta.status_code == 200
    cuerpo = json.loads(respuesta.body)
    assert cuerpo["schema_revision"] == schema
    assert cuerpo["status"] == status


def test_endpoint_y_preflight_comparten_las_fuentes() -> None:
    """Los alias de este módulo son las funciones de ``db.schema_revision``.

    Una copia reescrita aquí podría discrepar del preflight de los jobs sobre
    qué es un desfase: el deploy saldría verde con un job que bloquea, o al
    revés.
    """
    assert health._database_url is schema_revision.database_url
    assert health._repo_revisions is schema_revision.revisiones_repo
    assert health._applied_revisions is schema_revision.revisiones_aplicadas


# ---------------------------------------------------------------------------
# El repo de verdad
# ---------------------------------------------------------------------------


def test_las_cabezas_del_repo_se_leen_sin_base_de_datos() -> None:
    """``_repo_revisions`` solo lee ``db/alembic/versions``; no abre conexiones.

    Y tiene que devolver exactamente una cabeza: dos significan una bifurcación
    de migraciones sin mergear, que es un problema por sí mismo.
    """
    cabezas, todas = health._repo_revisions()
    assert len(cabezas) == 1, f"el repo tiene {len(cabezas)} cabezas alembic: {cabezas}"
    assert cabezas[0] in todas
    assert len(todas) > 50


def test_el_payload_declara_el_campo_de_schema() -> None:
    """El campo va en el modelo, no colgado del JSON.

    Sin esto el contrato OpenAPI no lo documenta y el cliente tipado del
    frontend no lo ve — que es como se cuelan los campos fantasma.
    """
    assert "schema_revision" in health.HealthResponse.model_fields
    modelo = health.HealthResponse(
        status="ok", db="ok", redis="ok", disk="ok", timestamp="2026-09-03T00:00:00+00:00"
    )
    assert modelo.schema_revision == "unknown"

"""``shared.tenant_context``: el ámbito de organización y su propagación (ADR-034).

Sin base de datos. Lo que se fija aquí es el contrato del que depende el
respaldo RLS de ``v128``: que el ámbito viva en un ``ContextVar``, que
``tenant_scope`` restaure siempre el valor anterior, que ``run_db`` lo lleve
al hilo del pool donde ``db/connection.py`` lo lee, y que dos tareas
concurrentes no se lo contagien. Las pruebas contra Postgres están en
``tests/test_rls_tenant_scope_integration.py``.
"""

from __future__ import annotations

import threading
from typing import Any

import anyio
import pytest

from shared.tenant_context import (
    current_organization,
    reset_organization,
    set_organization,
    tenant_scope,
)


def test_sin_ambito_por_defecto() -> None:
    assert current_organization() is None


def test_tenant_scope_fija_y_restaura_anidado() -> None:
    with tenant_scope(7):
        assert current_organization() == 7
        with tenant_scope(9):
            assert current_organization() == 9
        assert current_organization() == 7
    assert current_organization() is None


def test_tenant_scope_restaura_aunque_el_bloque_lance() -> None:
    with pytest.raises(RuntimeError), tenant_scope(5):
        raise RuntimeError("boom")
    assert current_organization() is None


def test_set_y_reset_con_token() -> None:
    token = set_organization(3)
    assert current_organization() == 3
    reset_organization(token)
    assert current_organization() is None


def test_none_limpia_el_ambito_de_forma_explicita() -> None:
    """Una operación transversal dentro de una petición acotada puede soltar el ámbito."""
    with tenant_scope(3):
        with tenant_scope(None):
            assert current_organization() is None
        assert current_organization() == 3


@pytest.mark.parametrize("valor", [0, -1, True, "7", 7.0])
def test_rechaza_lo_que_no_sea_un_entero_positivo(valor: Any) -> None:
    """El valor acaba interpolado en un ``SET LOCAL``: nada que no sea int pasa."""
    with pytest.raises((TypeError, ValueError)):
        set_organization(valor)
    assert current_organization() is None


def test_run_db_lleva_el_ambito_al_hilo_del_pool() -> None:
    """``api.concurrency.run_db`` ejecuta en otro hilo y el ámbito llega intacto.

    Es lo que permite que ``db/connection.py`` lea el ámbito desde el código
    síncrono que abre la conexión. Si anyio dejara de copiar el contexto al
    hilo, este test lo diría antes que producción.
    """
    from api.concurrency import run_db

    def _en_el_hilo() -> tuple[threading.Thread, int | None]:
        return threading.current_thread(), current_organization()

    async def _main() -> tuple[threading.Thread, int | None]:
        with tenant_scope(42):
            return await run_db(_en_el_hilo)

    hilo, organizacion = anyio.run(_main)
    assert organizacion == 42
    assert hilo is not threading.main_thread()
    assert current_organization() is None


def test_el_ambito_fijado_dentro_del_hilo_vive_esa_llamada_y_muere_con_ella() -> None:
    """La otra dirección, y de la que depende el respaldo RLS de pursuits.

    ``services.organizations.resolve_organization`` fija el ámbito **desde
    dentro** de ``run_db``, porque es ahí donde resuelve. Eso sólo sirve si se
    cumplen tres cosas a la vez, y las tres las comprueba este test:

    1. lo que se fija dentro lo ven las consultas que vienen después en esa
       misma llamada —si no, la resolución armaría un respaldo que nadie usa—;
    2. no vuelve a la corrutina de la petición, que seguiría creyéndose sin
       ámbito y con razón;
    3. no lo hereda el siguiente trabajo que caiga en ese hilo del pool, que
       es lo que convertiría un detalle de implementación en una fuga de datos
       entre organizaciones.

    Son garantías de ``contextvars`` + ``anyio``, no del proyecto. Por eso se
    fijan aquí: el día que cambien, este test lo dice y no producción.
    """
    from api.concurrency import run_db

    def _fija_y_relee() -> tuple[int | None, int | None]:
        antes = current_organization()
        set_organization(7)
        return antes, current_organization()

    async def _main() -> tuple[tuple[int | None, int | None], int | None, int | None]:
        primera = await run_db(_fija_y_relee)
        fuera = current_organization()
        segunda = await run_db(_fija_y_relee)
        return primera, fuera, segunda[0]

    primera, fuera, antes_de_la_segunda = anyio.run(_main)

    assert primera == (None, 7), "lo fijado dentro no se ve en la misma llamada"
    assert fuera is None, "el ámbito del hilo se filtró a la corrutina de la petición"
    assert antes_de_la_segunda is None, "el hilo del pool arrastró el ámbito anterior"


def test_el_ambito_no_se_contagia_entre_tareas_concurrentes() -> None:
    """Cada tarea nace con su copia del contexto: una petición no ve la de otra."""

    async def _main() -> dict[str, int | None]:
        vistos: dict[str, int | None] = {}

        async def _con_ambito() -> None:
            with tenant_scope(1):
                await anyio.sleep(0.02)
                vistos["con"] = current_organization()

        async def _sin_ambito() -> None:
            await anyio.sleep(0.01)
            vistos["sin"] = current_organization()

        async with anyio.create_task_group() as tg:
            tg.start_soon(_con_ambito)
            tg.start_soon(_sin_ambito)
        return vistos

    assert anyio.run(_main) == {"con": 1, "sin": None}

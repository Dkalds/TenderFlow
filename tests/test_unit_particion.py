"""``tests/particion.py``: cómo se reparte la suite entre las máquinas de CI."""

from __future__ import annotations

import random
from types import SimpleNamespace

import pytest

from tests import particion
from tests.particion import leer_parte, repartir

# Con la forma de la suite: muchos ficheros ligeros y unos pocos que pesan cientos.
_AZAR = random.Random(20261119)
PESOS = {
    f"tests/test_{n:03d}.py": _AZAR.choice([1, 5, 40]) * _AZAR.randint(1, 30) for n in range(200)
}


@pytest.mark.parametrize("partes", [1, 2, 3, 7])
def test_las_partes_son_disjuntas_y_cubren_todos_los_ficheros(partes: int) -> None:
    grupos = repartir(PESOS, partes)

    assert len(grupos) == partes
    assert sum(len(grupo) for grupo in grupos) == len(PESOS)
    assert set().union(*grupos) == set(PESOS)


def test_el_reparto_no_depende_del_orden_de_entrada() -> None:
    # Cada worker de xdist colecciona por su cuenta: el orden no puede decidir.
    claves = list(PESOS)
    random.Random(1).shuffle(claves)

    assert repartir({clave: PESOS[clave] for clave in claves}, 2) == repartir(PESOS, 2)


@pytest.mark.parametrize("partes", [2, 3])
def test_las_cargas_difieren_como_mucho_en_el_fichero_mas_pesado(partes: int) -> None:
    cargas = [sum(PESOS[fichero] for fichero in grupo) for grupo in repartir(PESOS, partes)]

    assert max(cargas) - min(cargas) <= max(PESOS.values())


@pytest.mark.parametrize(("valor", "esperado"), [("1/2", (1, 2)), ("2/2", (2, 2)), ("1/1", (1, 1))])
def test_leer_parte_acepta_i_de_n(valor: str, esperado: tuple[int, int]) -> None:
    assert leer_parte(valor) == esperado


@pytest.mark.parametrize("valor", ["", "2", "0/2", "3/2", "1/0", "-1/2", "a/b", "1/2/3", " 1/2"])
def test_leer_parte_rechaza_lo_mal_formado(valor: str) -> None:
    with pytest.raises(pytest.UsageError, match="TF_PARTE"):
        leer_parte(valor)


class _Item:
    def __init__(self, nodeid: str, *, unit: bool) -> None:
        self.nodeid = nodeid
        self._unit = unit

    def get_closest_marker(self, nombre: str) -> object | None:
        return pytest.mark.unit.mark if nombre == "unit" and self._unit else None


def _coleccionar(monkeypatch: pytest.MonkeyPatch, valor: str | None, items: list[_Item]):
    """Pasa ``items`` por los dos hooks del plugin; devuelve (seleccionados, deseleccionados)."""
    if valor is None:
        monkeypatch.delenv(particion.VARIABLE, raising=False)
    else:
        monkeypatch.setenv(particion.VARIABLE, valor)
    fuera: list[_Item] = []
    config = SimpleNamespace(
        stash=pytest.Stash(),
        hook=SimpleNamespace(pytest_deselected=lambda items: fuera.extend(items)),
    )
    particion.pytest_configure(config)
    seleccion = list(items)
    particion.pytest_collection_modifyitems(config, seleccion)
    return seleccion, fuera


# a: un test de integración (peso 30); b: 29 unitarios (29); c: uno unitario (1).
# Si el hook no mirara el marker `unit`, b pesaría 870 y se quedaría solo en la parte 1.
_A = [_Item("tests/test_a.py::test_bd", unit=False)]
_B = [_Item(f"tests/test_b.py::test_{n}", unit=True) for n in range(29)]
_C = [_Item("tests/test_c.py::test_solo", unit=True)]


def test_el_hook_reparte_por_fichero_y_pesa_por_el_marker_unit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items = _B + _A + _C

    parte_1, fuera_1 = _coleccionar(monkeypatch, "1/2", items)
    parte_2, fuera_2 = _coleccionar(monkeypatch, "2/2", items)

    assert parte_1 == _A
    assert parte_2 == _B + _C
    assert fuera_1 == parte_2
    assert fuera_2 == parte_1


def test_sin_tf_parte_el_hook_no_toca_la_coleccion(monkeypatch: pytest.MonkeyPatch) -> None:
    items = _A + _B + _C

    seleccion, fuera = _coleccionar(monkeypatch, None, items)

    assert seleccion == items
    assert fuera == []

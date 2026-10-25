"""Presupuesto de First Load JS por ruta (`scripts/check_bundle_budget.py`).

Lo que se fija: el techo sigue siendo un ratchet (falla al engordar, `--update`
solo baja) y los ``objetivos`` son un destino válido —entero, de una ruta que
existe y por debajo de su techo— que no hace fallar la build, que se informa y
que `--update` conserva. El último test mira el fichero real.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import check_bundle_budget as presupuesto

_REAL = Path(__file__).resolve().parent.parent / "web" / "bundle-budget.json"

#: Las cuatro rutas del ítem del backlog «Un objetivo de bajada para el First
#: Load JS del dashboard», con su techo del 2026-10-17. El compromiso era bajar
#: al menos un 25 % y darles un objetivo.
_TECHOS_2026_10_17 = {
    "/resumen": 1_630_448,
    "/oportunidades/[id]": 1_371_738,
    "/equipo": 1_267_098,
    "/detalle": 1_265_491,
}


@pytest.fixture
def entorno(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Apunta el script a una build y un presupuesto de prueba."""
    stats = tmp_path / "route-bundle-stats.json"
    fichero = tmp_path / "bundle-budget.json"
    monkeypatch.setattr(presupuesto, "_STATS", stats)
    monkeypatch.setattr(presupuesto, "_PRESUPUESTO", fichero)

    def preparar(medido: dict[str, int], datos: dict[str, object]) -> Path:
        stats.write_text(
            json.dumps(
                [{"route": r, "firstLoadUncompressedJsBytes": b} for r, b in medido.items()]
            ),
            encoding="utf-8",
        )
        fichero.write_text(json.dumps(datos), encoding="utf-8")
        return fichero

    return preparar


class TestValidarObjetivos:
    def test_un_objetivo_bajo_su_techo_vale(self) -> None:
        assert presupuesto.validar_objetivos({"/a": 900}, {"/a": 1000}) == []

    @pytest.mark.parametrize("valor", [0, -5, 12.5, "800000", True, None])
    def test_tiene_que_ser_un_entero_positivo(self, valor: object) -> None:
        (error,) = presupuesto.validar_objetivos({"/a": valor}, {"/a": 1000})
        assert "entero positivo" in error

    def test_una_ruta_sin_techo_es_un_objetivo_huerfano(self) -> None:
        (error,) = presupuesto.validar_objetivos({"/ya-no-existe": 10}, {"/a": 1000})
        assert "no techo" in error

    def test_por_encima_del_techo_no_es_un_destino(self) -> None:
        (error,) = presupuesto.validar_objetivos({"/a": 1001}, {"/a": 1000})
        assert "por encima del techo" in error


class TestComprobacion:
    def test_el_objetivo_no_hace_fallar_y_dice_cuanto_falta(self, entorno, capsys) -> None:
        entorno({"/a": 3072}, {"rutas": {"/a": 4096}, "objetivos": {"/a": 2048}})
        assert presupuesto.main([]) == 0
        assert "faltan 1 KB para el objetivo de 2 KB" in capsys.readouterr().out

    def test_avisa_del_objetivo_alcanzado(self, entorno, capsys) -> None:
        entorno({"/a": 1024}, {"rutas": {"/a": 4096}, "objetivos": {"/a": 2048}})
        assert presupuesto.main([]) == 0
        assert "alcanzado" in capsys.readouterr().out

    def test_un_objetivo_mal_formado_si_falla(self, entorno, capsys) -> None:
        entorno({"/a": 1024}, {"rutas": {"/a": 4096}, "objetivos": {"/a": 9999}})
        assert presupuesto.main([]) == 1
        assert "por encima del techo" in capsys.readouterr().err

    def test_sin_objetivos_el_formato_de_siempre_sigue_valiendo(self, entorno) -> None:
        entorno({"/a": 1000}, {"rutas": {"/a": 1100}})
        assert presupuesto.main([]) == 0

    def test_engordar_por_encima_del_techo_falla(self, entorno, capsys) -> None:
        entorno({"/a": 1200}, {"rutas": {"/a": 1100}, "objetivos": {"/a": 900}})
        assert presupuesto.main([]) == 1
        assert "> techo" in capsys.readouterr().err


class TestUpdate:
    def test_baja_los_techos_y_conserva_los_objetivos(self, entorno) -> None:
        fichero = entorno(
            {"/a": 1000, "/b": 5000},
            {
                "rutas": {"/a": 2000, "/b": 5000, "/retirada": 700},
                "_comentario_objetivos": "por qué",
                "objetivos": {"/a": 800, "/retirada": 600},
            },
        )
        assert presupuesto.main(["--update"]) == 0
        datos = json.loads(fichero.read_text(encoding="utf-8"))
        # `/a` baja a lo medido más el margen; `/b` no sube; `/retirada` sale.
        assert datos["rutas"] == {"/a": int(1000 * (1 + presupuesto.MARGEN)), "/b": 5000}
        # El objetivo no lo toca la medición; el de una ruta retirada se va con ella.
        assert datos["objetivos"] == {"/a": 800}
        assert datos["_comentario_objetivos"] == "por qué"


def test_el_fichero_real_tiene_objetivos_validos_y_cumple_la_bajada() -> None:
    datos = json.loads(_REAL.read_text(encoding="utf-8"))
    techos = {r: int(v) for r, v in datos["rutas"].items()}
    objetivos = datos.get("objetivos", {})

    assert presupuesto.validar_objetivos(objetivos, techos) == []
    assert datos.get("_comentario_objetivos"), "cada objetivo lleva escrito de dónde sale"
    for ruta, techo_anterior in _TECHOS_2026_10_17.items():
        assert ruta in objetivos, f"{ruta} no tiene objetivo"
        assert techos[ruta] <= techo_anterior * 0.75, f"{ruta} no bajó un 25 % desde el 2026-10-17"

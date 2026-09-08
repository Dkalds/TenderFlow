"""C6.5 — «mi baja frente al mercado»: orquestación (`services/mi_baja.py`).

El módulo salió del stream con **cero cobertura**: el gate de cobertura del diff
lo señaló al abrir la PR. No es una cifra que arreglar, son cuatro decisiones sin
fijar, y las cuatro son las que el ítem pide:

1. La respuesta declara `base: "sin_iva"` y no `mixta`. Es lo que separa este
   número de la baja del mercado: aquí solo entran expedientes con base
   declarada (C1.1), así que no hay población mixta. Declarar `sin_iva` sobre
   una población mixta sería la mentira del 21 % que ADR-032 vino a quitar.
2. Un segmento cuya referencia de mercado falla **sale igual**, con la baja del
   mercado a `null`. Perder mi propia cifra porque la del mercado no se pudo
   calcular es esconder el dato que sí tengo.
3. El tope de `MAX_SEGMENTOS` acota las consultas al mercado, y se aplica sobre
   una lista **ordenada por población**: el corte se lleva los segmentos con
   menos ofertas, que son justo los que menos se pueden interpretar.
4. Cada segmento declara su `n` y si llega al mínimo del ítem (cinco ofertas).
   Los que no llegan salen igual **con su `n`**: saber que solo hay dos es
   información; no saberlo es lo que engaña.

Se prueba con el repositorio y la referencia de mercado simulados: lo que decide
este módulo es el orden de las llamadas y qué hace cuando una falla, y eso no
necesita Postgres.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest


def _oferta(
    *,
    cpv: str = "72220000",
    organo: str = "Ayuntamiento de Madrid",
    presupuesto: float = 100_000.0,
    oferta: float = 80_000.0,
) -> dict[str, Any]:
    """Una oferta presentada, en la forma que devuelve `ofertas_presentadas`."""
    return {
        "cpv": cpv,
        "organo_contratacion": organo,
        "presupuesto": presupuesto,
        "offer_price_eur": oferta,
    }


def _correr(ofertas: list[dict[str, Any]], referencia: Any = None) -> dict[str, Any]:
    """Ejecuta `mi_baja` con la organización, el repo y el mercado simulados."""
    import services.mi_baja as mod

    if referencia is None:
        referencia = {"baja_media_pct": 15.0, "n": 40}

    with (
        patch.object(mod, "resolve_organization", return_value=(7, "owner")),
        patch.object(mod._pursuits, "ofertas_presentadas", return_value=ofertas),
        patch(
            "services.competitive.bajas.baja_de_referencia",
            side_effect=(referencia if callable(referencia) else lambda **_kw: referencia),
        ),
    ):
        return mod.mi_baja(1, organization_id=None)


class TestMiBaja:
    def test_declara_base_sin_iva_y_no_mixta(self) -> None:
        """Aquí no hay población mixta que declarar: solo entra base declarada."""
        resultado = _correr([_oferta()])

        assert resultado["base"] == "sin_iva"
        assert resultado["organization_id"] == 7

    def test_pide_la_referencia_solo_con_base_declarada(self) -> None:
        """`solo_base_declarada=True`: mezclar bases daría una baja que es el IVA."""
        import services.mi_baja as mod

        vistos: list[dict[str, Any]] = []

        def _referencia(**kwargs: Any) -> dict[str, Any]:
            vistos.append(kwargs)
            return {"baja_media_pct": 15.0}

        with (
            patch.object(mod, "resolve_organization", return_value=(7, "owner")),
            patch.object(mod._pursuits, "ofertas_presentadas", return_value=[_oferta()]),
            patch("services.competitive.bajas.baja_de_referencia", side_effect=_referencia),
        ):
            mod.mi_baja(1)

        assert vistos, "no se consultó la referencia de mercado"
        assert all(k.get("solo_base_declarada") is True for k in vistos)

    def test_los_dos_ejes_salen_por_separado(self) -> None:
        """CPV4 y órgano no se combinan: cruzarlos daría casi siempre `n = 1`."""
        resultado = _correr([_oferta()])

        tipos = {s["segmento"] for s in resultado["segmentos"]}
        assert tipos == {"cpv4", "organo"}
        assert any(s["clave"] == "7222" for s in resultado["segmentos"])

    def test_un_segmento_sin_referencia_sale_igual(self) -> None:
        """Perder mi cifra porque falló la del mercado sería esconder lo que sé."""

        def _revienta(**_kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("la consulta de mercado se cayó")

        resultado = _correr([_oferta()], referencia=_revienta)

        assert resultado["segmentos"], "el fallo del mercado se llevó mis segmentos"
        for segmento in resultado["segmentos"]:
            assert segmento["baja_mercado_pct"] is None
            assert segmento["baja_propia_pct"] == 20.0

    def test_cada_segmento_declara_su_n_aunque_no_llegue_al_minimo(self) -> None:
        """Dos ofertas no son evidencia, pero saber que son dos sí es información."""
        resultado = _correr([_oferta(), _oferta()])

        cpv = next(s for s in resultado["segmentos"] if s["segmento"] == "cpv4")
        assert cpv["n"] == 2
        assert cpv["suficiente"] is False

    def test_con_cinco_ofertas_el_segmento_es_suficiente(self) -> None:
        resultado = _correr([_oferta() for _ in range(5)])

        cpv = next(s for s in resultado["segmentos"] if s["segmento"] == "cpv4")
        assert cpv["n"] == 5
        assert cpv["suficiente"] is True

    def test_una_oferta_sin_presupuesto_no_cuenta(self) -> None:
        """Sin presupuesto no hay baja que calcular; la fila no inventa un 0 %."""
        resultado = _correr([_oferta(), _oferta(presupuesto=0.0)])

        cpv = next(s for s in resultado["segmentos"] if s["segmento"] == "cpv4")
        assert cpv["n"] == 1

    def test_el_tope_corta_por_los_segmentos_con_menos_poblacion(self) -> None:
        """El orden es por población, así que el corte se lleva los menos legibles."""
        import services.mi_baja as mod

        # Un órgano con muchas ofertas y `MAX_SEGMENTOS` órganos con una cada uno.
        ofertas = [_oferta(organo="Órgano grande") for _ in range(9)]
        ofertas += [_oferta(organo=f"Órgano {i}") for i in range(mod.MAX_SEGMENTOS + 5)]

        resultado = _correr(ofertas)

        assert len(resultado["segmentos"]) == mod.MAX_SEGMENTOS
        claves = [s["clave"] for s in resultado["segmentos"]]
        assert "Órgano grande" in claves, "el corte se llevó el segmento con más población"

    def test_cuenta_las_ofertas_consideradas(self) -> None:
        resultado = _correr([_oferta(), _oferta()])

        assert resultado["ofertas_consideradas"] == 2

    def test_sin_ofertas_no_hay_segmentos_ni_error(self) -> None:
        """Una organización que no ha presentado nada ve la pantalla vacía, no un 500."""
        resultado = _correr([])

        assert resultado["segmentos"] == []
        assert resultado["ofertas_consideradas"] == 0
        assert resultado["base"] == "sin_iva"


class TestBajaPropia:
    """El cálculo, que vive en `services/pursuit_bajas.py`."""

    @pytest.mark.parametrize(
        ("presupuesto", "oferta", "esperado"),
        [
            (100_000.0, 80_000.0, 20.0),
            (100_000.0, 100_000.0, 0.0),
            (None, 80_000.0, None),
            (100_000.0, None, None),
            (0.0, 80_000.0, None),
        ],
    )
    def test_baja_propia_pct(
        self, presupuesto: float | None, oferta: float | None, esperado: float | None
    ) -> None:
        from services.pursuit_bajas import baja_propia_pct

        assert baja_propia_pct(presupuesto, oferta) == esperado

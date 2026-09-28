"""Tests de ``repartir_cuotas`` (F2, spec §3.2): pura, sin BD ni sklearn.

Los ejemplos usan tamaños que son cuadrados perfectos (4, 9, 16, 25, 900...)
para que la raíz cuadrada dé un número exacto y las cuentas se puedan
verificar a mano sin arrastrar redondeos de más.
"""

from __future__ import annotations

import pytest

from services.ml.muestra_estratificada import repartir_cuotas


class TestRepartirCuotas:
    def test_exact_sum(self):
        """La suma de las cuotas es exactamente ``min(total, sum(tamaños))``,
        sin importar cómo se reparta internamente."""
        tamanos = {"a": 50, "b": 130, "c": 7, "d": 300}

        resultado = repartir_cuotas(tamanos, 80)

        assert sum(resultado.values()) == 80
        assert set(resultado) == set(tamanos)

    def test_caps_a_stratum_at_its_own_size(self):
        """El estrato pequeño no puede recibir más que su propio tamaño: se
        fija en su tope (aquí, 4) y el resto del reparto (396) se re-esparce
        sobre lo que queda (aquí, el único que queda: B)."""
        tamanos = {"A": 4, "B": 900}

        resultado = repartir_cuotas(tamanos, 400)

        assert resultado == {"A": 4, "B": 396}
        assert sum(resultado.values()) == 400
        assert resultado["A"] <= tamanos["A"]
        assert resultado["B"] <= tamanos["B"]

    def test_every_non_empty_stratum_gets_at_least_one(self):
        """``a`` tiene tamaño 1 (no le cabe ni una unidad extra) y a ``b`` le
        tocaría menos de 1 por proporción pura: ambos deben salir con 1
        igualmente, nunca con 0."""
        tamanos = {"a": 1, "b": 2, "c": 1000}

        resultado = repartir_cuotas(tamanos, 50)

        assert resultado == {"a": 1, "b": 2, "c": 47}
        assert all(cuota >= 1 for cuota in resultado.values())

    def test_hand_computed_square_root_example(self):
        """9, 16 y 25 son cuadrados perfectos: √ da 3, 4 y 5 exactos.

        Con ``total=10`` y 3 estratos, cada uno recibe 1 de entrada y quedan
        7 por repartir a razón de 3:4:5 (suma 12): 1.75, 2.3333 y 2.9167.
        ``floor`` da 1, 2 y 2 (suma 5); sobran 2, que van a los restos más
        grandes -- C (0.9167) y A (0.75) -- antes que B (0.3333)."""
        tamanos = {"A": 9, "B": 16, "C": 25}

        resultado = repartir_cuotas(tamanos, 10)

        assert resultado == {"A": 3, "B": 3, "C": 4}
        assert sum(resultado.values()) == 10

    def test_total_at_or_above_the_universe_gives_every_stratum_its_size(self):
        tamanos = {"x": 3, "y": 7}

        assert repartir_cuotas(tamanos, 100) == tamanos
        # En el borde exacto (total == universo) también: nadie recibe de más.
        assert repartir_cuotas(tamanos, 10) == tamanos

    def test_total_below_the_number_of_strata(self):
        """Con menos cupo que estratos, solo los ``total`` más grandes
        entran, cada uno con 1; el resto queda fuera del resultado."""
        tamanos = {"a": 5, "b": 50, "c": 2, "d": 9}

        resultado = repartir_cuotas(tamanos, 2)

        assert resultado == {"b": 1, "d": 1}

    def test_raises_on_non_positive_total(self):
        with pytest.raises(ValueError):
            repartir_cuotas({"a": 5}, 0)
        with pytest.raises(ValueError):
            repartir_cuotas({"a": 5}, -1)

    def test_deterministic_tie_break(self):
        """Tres estratos del mismo tamaño reparten igual (resto empatado):
        desempata la clave en orden ascendente -- A y M se llevan la unidad
        que sobra antes que Z."""
        tamanos = {"Z": 9, "A": 9, "M": 9}

        resultado = repartir_cuotas(tamanos, 5)

        assert resultado == {"A": 2, "M": 2, "Z": 1}

    def test_zero_size_strata_are_ignored(self):
        tamanos = {"a": 0, "b": 5, "c": 0, "d": 10}

        resultado = repartir_cuotas(tamanos, 3)

        assert "a" not in resultado
        assert "c" not in resultado
        assert resultado == {"b": 1, "d": 2}

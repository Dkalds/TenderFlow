"""F4.3 — cartera de contratos en ejecución.

Dos cosas se fijan aquí. La primera, que **la fecha de fin declara su origen**:
una publicada por la fuente y una derivada de «doce meses desde el inicio» no
valen lo mismo en la pantalla donde alguien decide cuándo preparar una
renovación. La segunda, que sin fecha de ninguna clase **no se inventa una**:
el contrato entra en la cartera sin ventana de aviso, que es honesto, en vez
de con un año por defecto que nadie recordará de dónde salió.
"""

from __future__ import annotations

import pytest

from services.cartera import (
    MESES_ANTES_RELICITACION,
    VENTANAS_AVISO_MESES,
    fin_efectivo,
    ventana_relicitacion,
)


class TestFechaPublicada:
    def test_gana_a_la_duracion(self) -> None:
        """Es un dato; la otra es una cuenta."""
        fecha, origen = fin_efectivo(
            fecha_fin_publicada="2027-03-31",
            fecha_inicio="2026-01-01",
            duracion_valor=12,
            duracion_unidad="meses",
        )
        assert fecha == "2027-03-31"
        assert origen == "publicada"

    def test_se_declara_siempre(self) -> None:
        _fecha, origen = fin_efectivo(fecha_fin_publicada="2027-03-31")
        assert origen == "publicada"


class TestDerivadaDeLaDuracion:
    def test_meses(self) -> None:
        fecha, origen = fin_efectivo(
            fecha_inicio="2026-01-15", duracion_valor=12, duracion_unidad="meses"
        )
        assert fecha == "2027-01-15"
        assert origen == "duracion"

    def test_anos(self) -> None:
        fecha, _origen = fin_efectivo(
            fecha_inicio="2026-01-15", duracion_valor=2, duracion_unidad="años"
        )
        assert fecha == "2028-01-15"

    def test_dias_solo_si_son_al_menos_un_mes(self) -> None:
        """45 días no son «un mes y medio» para una ventana de aviso."""
        fecha, _o = fin_efectivo(
            fecha_inicio="2026-01-15", duracion_valor=15, duracion_unidad="dias"
        )
        assert fecha is None

    def test_unidad_desconocida_no_adivina(self) -> None:
        fecha, origen = fin_efectivo(
            fecha_inicio="2026-01-15", duracion_valor=4, duracion_unidad="trimestres"
        )
        assert (fecha, origen) == (None, None)

    def test_duracion_cero_o_negativa(self) -> None:
        assert fin_efectivo(
            fecha_inicio="2026-01-15", duracion_valor=0, duracion_unidad="meses"
        ) == (None, None)


class TestSinFecha:
    def test_no_se_inventa_ninguna(self) -> None:
        """Un año por defecto sería una fecha que nadie recuerda que se inventó."""
        assert fin_efectivo() == (None, None)

    def test_sin_inicio_la_duracion_no_sirve(self) -> None:
        assert fin_efectivo(duracion_valor=12, duracion_unidad="meses") == (None, None)

    def test_fecha_malformada(self) -> None:
        assert fin_efectivo(fecha_fin_publicada="31/03/2027") == (None, None)


class TestProrrogas:
    def test_mueven_la_fecha_y_cambian_el_origen(self) -> None:
        """Lo que el usuario tiene delante ya no es lo que publicó la fuente."""
        fecha, origen = fin_efectivo(fecha_fin_publicada="2027-03-31", prorrogas_meses=12)
        assert fecha == "2028-03-31"
        assert origen == "prorroga"

    def test_tambien_sobre_la_derivada(self) -> None:
        fecha, origen = fin_efectivo(
            fecha_inicio="2026-01-01",
            duracion_valor=12,
            duracion_unidad="meses",
            prorrogas_meses=6,
        )
        assert fecha == "2027-07-01"
        assert origen == "prorroga"

    def test_cero_prorrogas_no_cambia_el_origen(self) -> None:
        _f, origen = fin_efectivo(fecha_fin_publicada="2027-03-31", prorrogas_meses=0)
        assert origen == "publicada"


class TestAritmeticaDeMeses:
    def test_fin_de_mes_corto(self) -> None:
        """«Un mes después del 31 de enero» es el 28, no un desbordamiento."""
        fecha, _o = fin_efectivo(
            fecha_inicio="2026-01-31", duracion_valor=1, duracion_unidad="meses"
        )
        assert fecha == "2026-02-28"

    def test_ano_bisiesto(self) -> None:
        fecha, _o = fin_efectivo(
            fecha_inicio="2028-01-31", duracion_valor=1, duracion_unidad="meses"
        )
        assert fecha == "2028-02-29"

    def test_cruce_de_ano(self) -> None:
        fecha, _o = fin_efectivo(
            fecha_inicio="2026-11-15", duracion_valor=3, duracion_unidad="meses"
        )
        assert fecha == "2027-02-15"


class TestVentanaDeRelicitacion:
    def test_es_un_intervalo_y_no_una_fecha(self) -> None:
        """Un intervalo no se lee como un compromiso; una fecha sí."""
        desde, hasta = ventana_relicitacion("2027-06-30")
        assert desde == "2026-12-30"
        assert hasta == "2027-03-30"
        assert desde is not None and hasta is not None and desde < hasta

    def test_sin_fecha_de_fin_no_hay_ventana(self) -> None:
        assert ventana_relicitacion(None) == (None, None)
        assert ventana_relicitacion("") == (None, None)

    def test_resta_por_meses_no_por_dias(self) -> None:
        """Tres meses antes del 31 de marzo es el 31 de diciembre."""
        _desde, hasta = ventana_relicitacion("2027-03-31")
        assert hasta == "2026-12-31"

    def test_recorta_al_ultimo_dia_del_mes_destino(self) -> None:
        _desde, hasta = ventana_relicitacion("2027-05-31")
        assert hasta == "2027-02-28"


class TestConstantes:
    def test_tres_ventanas_de_aviso(self) -> None:
        """Menos dejan pasar el primero; más se ignoran todos."""
        assert VENTANAS_AVISO_MESES == (6, 3, 1)

    def test_la_ventana_de_relicitacion_va_de_mas_a_menos(self) -> None:
        assert MESES_ANTES_RELICITACION[0] > MESES_ANTES_RELICITACION[1]

    @pytest.mark.parametrize("meses", VENTANAS_AVISO_MESES)
    def test_las_ventanas_son_positivas(self, meses: int) -> None:
        assert meses > 0

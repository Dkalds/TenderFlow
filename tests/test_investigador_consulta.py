"""``services/investigador/consulta.py``: qué se entiende de una frase.

Función pura, sin BD ni red. Cada patrón tiene dos mitades que se fijan aquí:
lo que **sí** lee como filtro, y lo que se parece y **no** lo es. La segunda
importa más: un filtro mal entendido esconde resultados sin que se note.
"""

from __future__ import annotations

from datetime import date

import pytest

from services.investigador.consulta import (
    ALIAS_CCAA,
    MAX_TERMINOS,
    ConsultaInterpretada,
    interpretar,
)
from shared.geo import NUTS3_TO_CCAA

HOY = date(2026, 10, 9)


def _i(frase: str, **kw: object) -> ConsultaInterpretada:
    return interpretar(frase, hoy=HOY, **kw)  # type: ignore[arg-type]


class TestLasBusquedasQueFallabanEnProduccion:
    """Medidas el 2026-10-09: el placeholder, las dos del log y los ejemplos."""

    def test_el_ejemplo_del_placeholder(self) -> None:
        r = _i("mantenimiento SAP en Andalucía")

        assert r.terminos == ("mantenimiento", "sap")
        assert r.ccaa == ("Andalucía",)

    def test_una_peticion_hablada_se_queda_con_lo_que_nombra(self) -> None:
        """El último recurso buscaba «Puedes»: el primer token de cuatro letras."""
        r = _i("Puedes mirar licitaciones relacionadas con licencia")

        assert r.terminos == ("licencia",)
        assert not r.tiene_filtros

    def test_una_pregunta(self) -> None:
        r = _i("Que licitaciones han tenido bajada temeraria?")

        assert r.terminos == ("bajada", "temeraria")

    def test_el_ejemplo_con_importe(self) -> None:
        r = _i("Buscar licitaciones de S/4HANA con importe mayor a 500K")

        # «S/4HANA» entero: Postgres lo guarda como un solo lexema.
        assert r.terminos == ("s/4hana",)
        assert r.importe_min == 500_000.0
        assert r.importe_max is None

    def test_las_mas_recientes_es_un_orden_no_un_texto(self) -> None:
        r = _i("¿Cuáles son las licitaciones más recientes?")

        assert r.terminos == ()
        assert r.orden == "recientes"
        assert not r.tiene_texto


class TestComunidades:
    def test_cada_alias_apunta_a_un_nombre_que_la_bd_guarda(self) -> None:
        """``licitaciones.ccaa`` guarda los nombres de ``shared.geo``; un alias
        hacia otra grafía sería un filtro que no casa con nada."""
        assert set(ALIAS_CCAA.values()) <= set(NUTS3_TO_CCAA.values())
        assert set(NUTS3_TO_CCAA.values()) <= set(ALIAS_CCAA.values())

    @pytest.mark.parametrize(
        ("frase", "esperado"),
        [
            ("sap en Madrid", ("Madrid",)),
            ("sap en la Comunidad de Madrid", ("Madrid",)),
            ("sap en el País Vasco", ("País Vasco",)),
            ("sap en Euskadi", ("País Vasco",)),
            ("sap en la Rioja", ("La Rioja",)),
            ("sap en Castilla-La Mancha", ("Castilla-La Mancha",)),
            ("sap en castilla la mancha", ("Castilla-La Mancha",)),
            ("sap en Castilla y León", ("Castilla y León",)),
            ("sap en Catalunya", ("Cataluña",)),
            ("sap en Valencia", ("Comunidad Valenciana",)),
            ("sap en la comunidad autónoma de Andalucía", ("Andalucía",)),
            ("sap en Madrid y Cataluña", ("Madrid", "Cataluña")),
            ("sap en Madrid, Galicia o Aragón", ("Madrid", "Galicia", "Aragón")),
        ],
    )
    def test_detras_de_en_es_un_filtro(self, frase: str, esperado: tuple[str, ...]) -> None:
        r = _i(frase)

        assert r.ccaa == esperado
        assert r.terminos == ("sap",)

    @pytest.mark.parametrize(
        "frase",
        [
            "Ayuntamiento de Madrid ciberseguridad",
            "Metro de Madrid",
            "Universidad de Castilla-La Mancha",
            "suministro en madridejos",
        ],
    )
    def test_sin_en_delante_es_una_palabra_mas(self, frase: str) -> None:
        """«Ayuntamiento de Madrid» nombra un órgano, no pide un ámbito."""
        assert _i(frase).ccaa == ()

    def test_castilla_y_leon_no_se_parte_por_la_y(self) -> None:
        assert _i("obras en Castilla y León y Galicia").ccaa == ("Castilla y León", "Galicia")


class TestImportes:
    @pytest.mark.parametrize(
        ("frase", "minimo", "maximo"),
        [
            ("sap de más de 500K", 500_000.0, None),
            ("sap de más de 500 k", 500_000.0, None),
            ("sap mayor de 1,5 M€", 1_500_000.0, None),
            ("sap superior a 2 millones", 2_000_000.0, None),
            ("sap de más de 500.000 €", 500_000.0, None),
            ("sap de más de 500.000 euros", 500_000.0, None),
            ("sap con importe mayor a 500000", 500_000.0, None),
            ("sap con presupuesto superior a 1.000.000", 1_000_000.0, None),
            ("sap > 250k", 250_000.0, None),
            ("sap de menos de 100.000 €", None, 100_000.0),
            ("sap hasta 300 mil euros", None, 300_000.0),
            ("sap inferior a 1M", None, 1_000_000.0),
            ("sap entre 100.000 y 500.000 euros", 100_000.0, 500_000.0),
            ("sap entre 500k y 100k", 100_000.0, 500_000.0),
            ("sap de más de 100k y menos de 2M", 100_000.0, 2_000_000.0),
        ],
    )
    def test_con_unidad_moneda_o_la_palabra_importe(
        self, frase: str, minimo: float | None, maximo: float | None
    ) -> None:
        r = _i(frase)

        assert (r.importe_min, r.importe_max) == (minimo, maximo)
        assert r.terminos == ("sap",)

    @pytest.mark.parametrize(
        "frase",
        [
            "más de 500 usuarios de Salesforce",
            "obras de más de 2 m de altura",
            "menos de 30 días de plazo",
            "desde 2024",
            "hasta 2025",
        ],
    )
    def test_una_cifra_sin_unidad_no_es_un_importe(self, frase: str) -> None:
        r = _i(frase)

        assert r.importe_min is None
        assert r.importe_max is None

    def test_un_anio_seguido_de_moneda_no_es_una_fecha(self) -> None:
        r = _i("contratos de 2025 euros")

        assert r.fecha_desde is None


class TestFechas:
    @pytest.mark.parametrize(
        ("frase", "desde", "hasta"),
        [
            ("erp en 2025", "2025-01-01", "2025-12-31"),
            ("erp de 2025", "2025-01-01", "2025-12-31"),
            ("erp del año 2025", "2025-01-01", "2025-12-31"),
            ("erp desde 2024", "2024-01-01", None),
            ("erp hasta 2024", None, "2024-12-31"),
            ("erp desde 2024 hasta 2025", "2024-01-01", "2025-12-31"),
            ("erp este año", "2026-01-01", None),
            ("erp de este mes", "2026-10-01", None),
            ("erp esta semana", "2026-10-05", None),  # el 9 es viernes
            ("erp en los últimos 30 días", "2026-09-09", None),
            ("erp de las últimas 2 semanas", "2026-09-25", None),
            ("erp en el último mes", "2026-09-09", None),
        ],
    )
    def test_fechas_de_publicacion(self, frase: str, desde: str | None, hasta: str | None) -> None:
        r = _i(frase)

        assert (r.fecha_desde, r.fecha_hasta) == (desde, hasta)
        assert r.terminos == ("erp",)

    @pytest.mark.parametrize("frase", ["expediente 2025/0034", "plan 2025", "horizonte 2030"])
    def test_un_numero_de_expediente_o_un_nombre_no_es_una_fecha(self, frase: str) -> None:
        r = _i(frase)

        assert r.fecha_desde is None
        assert r.fecha_hasta is None


class TestAbiertasYOrden:
    @pytest.mark.parametrize(
        "frase",
        [
            "sap abiertas",
            "sap que sigan abiertas",
            "sap todavía abiertas",
            "sap en plazo",
            "sap sin adjudicar",
        ],
    )
    def test_abiertas(self, frase: str) -> None:
        r = _i(frase)

        assert r.solo_abiertas is True
        assert r.terminos == ("sap",)

    @pytest.mark.parametrize(
        "frase", ["procedimiento abierto", "portal de datos abiertos", "código abierto"]
    )
    def test_el_masculino_no_es_el_estado(self, frase: str) -> None:
        """«Procedimiento abierto» es un tipo de procedimiento y «datos
        abiertos», un tema: tacharlos borraría justo lo que se busca."""
        r = _i(frase)

        assert r.solo_abiertas is False
        assert any(t.startswith("abiert") for t in r.terminos)

    @pytest.mark.parametrize(
        "frase", ["últimas licitaciones de oracle", "oracle más recientes", "lo último de oracle"]
    )
    def test_recientes(self, frase: str) -> None:
        r = _i(frase)

        assert r.orden == "recientes"
        assert r.terminos == ("oracle",)

    def test_ultimos_n_dias_es_una_fecha_no_un_orden(self) -> None:
        r = _i("oracle en los últimos 15 días")

        assert r.orden == "relevancia"
        assert r.fecha_desde == "2026-09-24"


class TestTerminos:
    def test_sin_repetir_y_en_su_orden(self) -> None:
        assert _i("SAP mantenimiento sap HANA").terminos == ("sap", "mantenimiento", "hana")

    def test_las_siglas_de_dos_letras_cuentan(self) -> None:
        """«IA» y «BI» son tecnologías; ``extract_keywords`` las tiraba por cortas."""
        assert _i("IA y BI").terminos == ("ia", "bi")

    def test_los_signos_de_fuera_se_quitan_y_los_de_dentro_no(self) -> None:
        assert _i("¿ISO-27001, (S/4HANA)?").terminos == ("iso-27001", "s/4hana")

    def test_tope_de_terminos(self) -> None:
        frase = " ".join(f"termino{i:02d}" for i in range(30))

        assert len(_i(frase).terminos) == MAX_TERMINOS

    def test_los_verbos_de_pregunta_sobre_un_documento_no_son_terminos(self) -> None:
        """Dentro de un pasaje de pliego se exigen todos: con «hablan», ninguno casa."""
        assert _i("¿Qué pliegos hablan de baja temeraria?").terminos == ("baja", "temeraria")

    def test_solo_palabras_vacias_no_deja_nada(self) -> None:
        r = _i("¿Qué hay de las licitaciones?")

        assert r.terminos == ()
        assert not r.tiene_texto


class TestOperadores:
    def test_las_comillas_se_respetan_como_expresion(self) -> None:
        r = _i('gestión documental "archivo electrónico" -obra')

        assert r.con_operadores is True
        assert r.texto == 'gestión documental "archivo electrónico" -obra'
        assert r.terminos == ()
        assert r.tiene_texto

    def test_los_filtros_se_leen_tambien_con_operadores(self) -> None:
        r = _i('"gestión documental" en Madrid de más de 100k')

        assert r.con_operadores is True
        assert r.texto == '"gestión documental"'
        assert r.ccaa == ("Madrid",)
        assert r.importe_min == 100_000.0

    def test_un_guion_dentro_de_una_palabra_no_es_una_exclusion(self) -> None:
        assert _i("pre-venta ISO-27001").con_operadores is False


class TestSinInterpretar:
    def test_filtros_false_deja_la_frase_como_terminos(self) -> None:
        r = _i("sap abiertas en Madrid de más de 500K", filtros=False)

        assert not r.tiene_filtros
        assert r.orden == "relevancia"
        assert "madrid" in r.terminos
        assert "abiertas" in r.terminos

    def test_todo_junto(self) -> None:
        r = _i("soporte SAP abiertas en Madrid y Cataluña de más de 1,5 M€ desde 2025")

        assert r == ConsultaInterpretada(
            original="soporte SAP abiertas en Madrid y Cataluña de más de 1,5 M€ desde 2025",
            texto="soporte sap",
            terminos=("soporte", "sap"),
            ccaa=("Madrid", "Cataluña"),
            importe_min=1_500_000.0,
            solo_abiertas=True,
            fecha_desde="2025-01-01",
        )

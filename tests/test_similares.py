"""Predecesor y expedientes similares (C1.3).

`services/embeddings.py` sabía buscar textos parecidos desde siempre y ninguna
ruta de la API ni pantalla del frontend lo exponía (hecho 3 del plan). El único
uso del concepto de incumbente vivía dentro del modelo de retención.

Lo que estos tests fijan es la **asimetría entre las dos preguntas**, que es la
parte que se pierde si alguien las unifica por parecerse: proponer un incumbente
equivocado hace que alguien prepare su oferta contra un competidor que no
existe; una fila de más en «similares» solo ocupa sitio.
"""

from __future__ import annotations

import re
from pathlib import Path

from services.similares import (
    UMBRAL_PREDECESOR,
    UMBRAL_SOLAPE_FTS,
    _baja,
    _cpv4,
    _solape,
    _terminos,
)

ROOT = Path(__file__).resolve().parent.parent


class TestTerminos:
    def test_las_palabras_administrativas_no_distinguen(self) -> None:
        """«Servicio de mantenimiento» se parece a cualquier cosa sin esto."""
        assert "servicio" not in _terminos("Servicio de limpieza")
        assert "mantenimiento" not in _terminos("Mantenimiento de ascensores")
        assert "limpieza" in _terminos("Servicio de limpieza")

    def test_las_palabras_cortas_se_ignoran(self) -> None:
        assert _terminos("de la el en") == set()

    def test_sin_texto_no_hay_terminos(self) -> None:
        assert _terminos(None) == set()
        assert _terminos("") == set()


class TestSolape:
    def test_dos_redacciones_del_mismo_objeto_se_parecen(self) -> None:
        a = "Servicio de mantenimiento de la plataforma SAP S/4HANA"
        b = "Mantenimiento evolutivo de plataforma SAP S/4HANA"
        assert _solape(a, b) >= UMBRAL_SOLAPE_FTS

    def test_dos_objetos_distintos_no(self) -> None:
        a = "Suministro de reactivos de laboratorio"
        b = "Servicio de mantenimiento de la plataforma SAP"
        assert _solape(a, b) < UMBRAL_SOLAPE_FTS

    def test_sin_texto_da_cero(self) -> None:
        assert _solape(None, "algo") == 0.0
        assert _solape("algo", None) == 0.0


class TestCpv4:
    def test_toma_los_cuatro_primeros_digitos(self) -> None:
        assert _cpv4("72267100-0") == "7226"

    def test_rechaza_lo_que_no_son_cuatro_digitos(self) -> None:
        for malo in (None, "", "72", "AB12", "72-6"):
            assert _cpv4(malo) is None


class TestBaja:
    def test_calcula_la_baja_del_predecesor(self) -> None:
        assert _baja(100_000, 80_000) == 20.0

    def test_sin_datos_no_inventa(self) -> None:
        """`None` es la respuesta correcta cuando no se puede calcular."""
        assert _baja(None, 80_000) is None
        assert _baja(100_000, None) is None
        assert _baja(0, 80_000) is None
        assert _baja(-10, 80_000) is None


class TestAsimetria:
    def test_el_predecesor_exige_mas_evidencia_que_un_similar(self) -> None:
        """La afirmación es más fuerte, así que el listón es más alto."""
        assert UMBRAL_PREDECESOR > UMBRAL_SOLAPE_FTS

    def test_el_predecesor_exige_mismo_organo(self) -> None:
        """Sin órgano coincidente, «predecesor» no significa nada."""
        fuente = (ROOT / "db" / "repositories" / "similares.py").read_text(encoding="utf-8")
        cuerpo = re.search(r"def candidatos_a_predecesor\(.*?\n\ndef ", fuente, re.S) or re.search(
            r"def candidatos_a_predecesor\(.*", fuente, re.S
        )
        assert cuerpo
        texto = cuerpo.group(0)
        assert "organo_id = %s" in texto
        assert "return []" in texto, "sin órgano tiene que devolver vacío, no relajar el criterio"

    def test_el_predecesor_exige_anterioridad(self) -> None:
        fuente = (ROOT / "db" / "repositories" / "similares.py").read_text(encoding="utf-8")
        assert "antes_de" in fuente
        assert "< %s" in fuente

    def test_los_similares_no_exigen_mismo_organo(self) -> None:
        """Acotarlos al mismo comprador los convertiría en la otra pregunta."""
        fuente = (ROOT / "db" / "repositories" / "similares.py").read_text(encoding="utf-8")
        cuerpo = re.search(r"def candidatos_a_similar\(.*", fuente, re.S)
        assert cuerpo
        assert "organo_id" not in cuerpo.group(0)


class TestContrato:
    def test_declara_metodo_y_n(self) -> None:
        """Una lista ordenada por un criterio desconocido no se interpreta."""
        from api.routes.licitaciones import SimilaresResult

        assert {"metodo", "n"} <= set(SimilaresResult.model_fields)

    def test_sin_predecesor_devuelve_none_no_el_mas_parecido(self) -> None:
        from api.routes.licitaciones import SimilaresResult

        assert SimilaresResult.model_fields["predecesor"].default is None

    def test_solo_el_predecesor_trae_adjudicatario(self) -> None:
        """En un similar no hay adjudicación que respalde ese dato."""
        from api.routes.licitaciones import SimilarOut

        for campo in ("adjudicatario", "importe_adjudicado", "baja_pct"):
            assert SimilarOut.model_fields[campo].default is None

    def test_la_ruta_existe_y_esta_tipada(self) -> None:
        from api.app import app

        operacion = app.openapi()["paths"]["/api/v1/licitaciones/{id_externo}/similares"]["get"]
        esquema = operacion["responses"]["200"]["content"]["application/json"]["schema"]
        assert "$ref" in esquema, "la ruta nace tipada (AGENTS.md §3.5)"

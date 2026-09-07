"""F1.7 — procedimiento, tramitación y tipo de contrato legibles.

El criterio de aceptación que de verdad protege esto es el último:
:class:`TestCorpusCubierto` recorre el corpus CODICE de CI y exige etiqueta
para cada código que aparece. Si mañana un fixture nuevo trae un procedimiento
que el catálogo no conoce, falla aquí y no en la pantalla del usuario.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from services.classification import TIPO_CONTRATO_LABELS, tipo_contrato_label
from shared.procedimientos import (
    PROCEDIMIENTOS,
    TIPOS_CONTRATO,
    TRAMITACIONES,
    catalogado,
    catalogo,
    etiqueta_procedimiento,
    etiqueta_tipo_contrato,
    etiqueta_tramitacion,
    no_catalogados,
    opciones,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestEtiquetas:
    def test_procedimiento_conocido(self) -> None:
        assert etiqueta_procedimiento("1") == "Abierto"
        assert etiqueta_procedimiento("9") == "Abierto simplificado"

    def test_tramitacion_conocida(self) -> None:
        assert etiqueta_tramitacion("1") == "Ordinaria"
        assert etiqueta_tramitacion("2") == "Urgente"

    def test_tipo_contrato_conocido(self) -> None:
        assert etiqueta_tipo_contrato("2") == "Servicios"

    def test_ausente_devuelve_marca_de_vacio(self) -> None:
        assert etiqueta_procedimiento(None) == "—"
        assert etiqueta_procedimiento("") == "—"
        assert etiqueta_procedimiento("   ") == "—"

    def test_codigo_desconocido_se_muestra_tal_cual(self) -> None:
        """Nunca una etiqueta inventada: el código crudo y nada más."""
        assert etiqueta_procedimiento("77") == "77"
        assert etiqueta_tramitacion("42") == "42"

    def test_ceros_a_la_izquierda_no_rompen_la_busqueda(self) -> None:
        """La fuente publica ``01`` y ``1`` para lo mismo según el emisor."""
        assert etiqueta_procedimiento("01") == "Abierto"
        assert etiqueta_procedimiento(" 09 ") == "Abierto simplificado"
        assert catalogado("procedimiento", "001")


class TestCatalogado:
    def test_conocido(self) -> None:
        assert catalogado("procedimiento", "1")

    def test_desconocido(self) -> None:
        assert not catalogado("procedimiento", "77")

    def test_ausente_no_cuenta_como_no_catalogado(self) -> None:
        """Un hueco de cobertura no es un código sin traducir: son dos métricas."""
        assert catalogado("procedimiento", None)
        assert catalogado("procedimiento", "")

    def test_no_catalogados_deduplica_y_ordena(self) -> None:
        assert no_catalogados("procedimiento", ["1", "77", "77", None, "42", "9"]) == ["42", "77"]

    def test_no_catalogados_sin_hallazgos(self) -> None:
        assert no_catalogados("tramitacion", ["1", "2", "3", None]) == []


class TestOpciones:
    @pytest.mark.parametrize("familia", ["procedimiento", "tramitacion", "tipo_contrato"])
    def test_toda_entrada_tiene_etiqueta_y_descripcion(self, familia: str) -> None:
        """F1.8 sirve el tooltip desde aquí: sin descripción no hay glosario."""
        for entrada in opciones(familia):  # type: ignore[arg-type]  # familia viene del parametrize
            assert entrada.etiqueta.strip(), entrada.codigo
            assert entrada.descripcion.strip(), entrada.codigo
            assert entrada.descripcion.endswith("."), entrada.codigo

    def test_orden_numerico_y_no_lexicografico(self) -> None:
        """Con orden de string el 10 se cuela entre el 1 y el 2."""
        codigos = [c.codigo for c in opciones("procedimiento")]
        assert codigos == sorted(codigos, key=int)
        assert codigos.index("2") < codigos.index("10")

    def test_catalogo_es_inmutable(self) -> None:
        with pytest.raises(TypeError):
            catalogo("procedimiento")["1"] = None  # type: ignore[index]  # es lo que se prueba

    @pytest.mark.parametrize("familia", ["procedimiento", "tramitacion", "tipo_contrato"])
    def test_sin_etiquetas_duplicadas(self, familia: str) -> None:
        """Dos códigos con la misma etiqueta harían el filtro ambiguo."""
        etiquetas = [c.etiqueta for c in opciones(familia)]  # type: ignore[arg-type]  # parametrize
        assert len(etiquetas) == len(set(etiquetas))


class TestTipoContratoCorregido:
    """El mapa que vivía en ``classification.py`` tenía 40 y 50 desplazados."""

    def test_40_es_colaboracion_publico_privada(self) -> None:
        assert etiqueta_tipo_contrato("40") == "Colaboración público-privada"

    def test_50_es_patrimonial(self) -> None:
        assert etiqueta_tipo_contrato("50") == "Patrimonial"

    def test_8_es_privado(self) -> None:
        assert etiqueta_tipo_contrato("8") == "Privado"

    @pytest.mark.parametrize("codigo", ["7", "8", "22", "32"])
    def test_codigos_que_faltaban(self, codigo: str) -> None:
        assert catalogado("tipo_contrato", codigo)

    def test_classification_delega_en_el_catalogo(self) -> None:
        """Una sola fuente: el re-export no puede divergir del catálogo."""
        assert {c: e.etiqueta for c, e in TIPOS_CONTRATO.items()} == TIPO_CONTRATO_LABELS
        assert tipo_contrato_label("2") == "Servicios"
        assert tipo_contrato_label(None) == "—"
        assert tipo_contrato_label("99") == "99"


class TestCorpusCubierto:
    """Todo código presente en el corpus CODICE de CI tiene etiqueta."""

    @staticmethod
    def _codigos(tag: str) -> list[str | None]:
        patron = re.compile(rf"<cbc:{tag}\b[^>]*>([^<]*)</cbc:{tag}>")
        encontrados: list[str | None] = []
        for xml in (FIXTURES / "placsp").glob("*.xml"):
            encontrados.extend(patron.findall(xml.read_text(encoding="utf-8")))
        return encontrados

    def test_el_corpus_trae_procedimientos(self) -> None:
        """Guarda del propio test: sin códigos, los dos de abajo pasan vacíos."""
        assert self._codigos("ProcedureCode"), "el corpus dejó de traer ProcedureCode"

    def test_todo_procedimiento_del_corpus_tiene_etiqueta(self) -> None:
        assert no_catalogados("procedimiento", self._codigos("ProcedureCode")) == []

    def test_toda_tramitacion_del_corpus_tiene_etiqueta(self) -> None:
        assert no_catalogados("tramitacion", self._codigos("UrgencyCode")) == []


class TestCoberturaDeLaCodelist:
    """El catálogo cubre la lista controlada completa, no solo lo visto."""

    def test_procedimientos_de_la_codelist(self) -> None:
        # SyndicationTenderingProcessCode-2.07 mas TenderingProcessCode-2.13.
        esperados = {*(str(n) for n in range(1, 15)), "100", "999"}
        assert set(PROCEDIMIENTOS) == esperados

    def test_tramitaciones_de_la_lcsp(self) -> None:
        # Sin codelist publicada (el listURI del ATOM da 404): LCSP arts. 116/119/120.
        assert set(TRAMITACIONES) == {"1", "2", "3"}

    def test_tipos_de_contrato_de_la_codelist(self) -> None:
        # SyndicationContractCode-2.07.
        assert set(TIPOS_CONTRATO) == {
            "1",
            "2",
            "3",
            "7",
            "8",
            "21",
            "22",
            "31",
            "32",
            "40",
            "50",
            "999",
        }

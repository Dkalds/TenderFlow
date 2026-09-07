"""F5.1–F5.3 (avisos con nombre) y F5.4 (diff desde la última visita).

La campana tenía un genérico «este expediente ha cambiado» para todo. El test
que importa es :class:`TestPrioridad`: un expediente que se anula cambia
también de fecha y de importe, y avisar de «importe corregido» cuando lo que
ha pasado es que se ha anulado es exacto y completamente inútil.

El segundo es :class:`TestCajon`: un cambio que no encaja en ningún subtipo
**no se descarta**. Perder un aviso por no saber nombrarlo sería peor que el
problema que estos módulos resuelven.
"""

from __future__ import annotations

from typing import Any

import pytest

from services.avisos import (
    CATALOGO_AVISOS,
    SUBTIPOS,
    aviso_documento_nuevo,
    aviso_recurso,
    clasificar_cambio,
    etiqueta_de,
)


def _lic(**campos: Any) -> dict[str, Any]:
    base = {"estado": "PUB", "fecha_limite": "2026-10-01", "importe": 100_000.0}
    return {**base, **campos}


class TestCatalogo:
    def test_todo_subtipo_tiene_etiqueta(self) -> None:
        """Un subtipo sin nombre saldría en crudo en la campana."""
        for subtipo in SUBTIPOS:
            assert subtipo in CATALOGO_AVISOS
            assert CATALOGO_AVISOS[subtipo].strip()

    def test_un_subtipo_desconocido_degrada_al_generico(self) -> None:
        assert etiqueta_de("inventado") == CATALOGO_AVISOS["cambio"]

    def test_al_menos_ocho_tipos_con_nombre(self) -> None:
        """Métrica de cierre del plan: de 2 tipos de aviso a ocho o más."""
        assert len(SUBTIPOS) >= 8


class TestPlazo:
    def test_ampliado_dice_la_fecha_nueva_y_la_vieja(self) -> None:
        aviso = clasificar_cambio(_lic(), _lic(fecha_limite="2026-10-12"))
        assert aviso.subtipo == "plazo_ampliado"
        assert "12/10/2026" in aviso.titulo
        assert aviso.detalle is not None
        assert "01/10/2026" in aviso.detalle

    def test_acortado_es_otro_subtipo(self) -> None:
        """Adelantar el cierre es una urgencia; ampliarlo, un respiro."""
        aviso = clasificar_cambio(_lic(), _lic(fecha_limite="2026-09-20"))
        assert aviso.subtipo == "plazo_acortado"

    def test_misma_fecha_no_es_cambio_de_plazo(self) -> None:
        aviso = clasificar_cambio(_lic(), _lic())
        assert aviso.subtipo == "cambio"

    def test_fecha_con_hora_se_compara_por_el_dia(self) -> None:
        aviso = clasificar_cambio(_lic(), _lic(fecha_limite="2026-10-01T23:59:00"))
        assert aviso.subtipo == "cambio"


class TestImporte:
    def test_corregido_dice_los_dos_importes(self) -> None:
        aviso = clasificar_cambio(_lic(), _lic(importe=150_000.0))
        assert aviso.subtipo == "importe_corregido"
        assert "150.000" in aviso.titulo
        assert aviso.detalle is not None
        assert "100.000" in aviso.detalle

    def test_una_diferencia_de_centimos_no_es_correccion(self) -> None:
        """El redondeo de la fuente no puede generar un aviso."""
        aviso = clasificar_cambio(_lic(), _lic(importe=100_000.001))
        assert aviso.subtipo == "cambio"

    def test_de_nulo_a_publicado_no_se_llama_correccion(self) -> None:
        """Que aparezca un importe que faltaba no es corregirlo."""
        aviso = clasificar_cambio(_lic(importe=None), _lic(importe=100_000.0))
        assert aviso.subtipo == "cambio"


class TestEstadoTerminal:
    def test_anulado(self) -> None:
        aviso = clasificar_cambio(_lic(), _lic(estado="ANUL"))
        assert aviso.subtipo == "anulado"

    def test_adjudicado(self) -> None:
        aviso = clasificar_cambio(_lic(), _lic(estado="ADJ"))
        assert aviso.subtipo == "adjudicado"

    def test_desierto_solo_si_la_fuente_lo_dice(self) -> None:
        """Nunca se deduce de «adjudicado sin adjudicatario», que también es
        un hueco de ingesta."""
        aviso = clasificar_cambio(_lic(resultado=None), _lic(resultado="Declarado desierto"))
        assert aviso.subtipo == "desierto"

    def test_un_estado_que_no_cambia_no_dispara_terminal(self) -> None:
        aviso = clasificar_cambio(_lic(estado="ANUL"), _lic(estado="ANUL", importe=5.0))
        assert aviso.subtipo == "importe_corregido"


class TestPrioridad:
    def test_lo_terminal_gana_al_plazo_y_al_importe(self) -> None:
        """Un expediente anulado suele cambiar también fecha e importe."""
        aviso = clasificar_cambio(
            _lic(),
            _lic(estado="ANUL", fecha_limite="2026-11-01", importe=200_000.0),
        )
        assert aviso.subtipo == "anulado"

    def test_el_plazo_gana_al_importe(self) -> None:
        """Una rectificación que mueve el cierre es lo que hay que mirar."""
        aviso = clasificar_cambio(_lic(), _lic(fecha_limite="2026-10-12", importe=200_000.0))
        assert aviso.subtipo == "plazo_ampliado"


class TestCajon:
    def test_un_cambio_sin_nombre_no_se_pierde(self) -> None:
        aviso = clasificar_cambio(_lic(), _lic(), ["cpv", "titulo"])
        assert aviso.subtipo == "cambio"
        assert aviso.detalle is not None
        assert "cpv" in aviso.detalle

    def test_el_generico_dice_al_menos_que_campos(self) -> None:
        aviso = clasificar_cambio(_lic(), _lic(), ["organo_contratacion"])
        assert aviso.detalle == "organo_contratacion"

    def test_sin_campos_el_generico_no_inventa_detalle(self) -> None:
        assert clasificar_cambio(_lic(), _lic()).detalle is None

    def test_no_lista_mas_de_cinco_campos(self) -> None:
        aviso = clasificar_cambio(_lic(), _lic(), [f"c{i}" for i in range(20)])
        assert aviso.detalle is not None
        assert aviso.detalle.count(",") <= 4


class TestDocumentoNuevo:
    def test_el_tipo_va_en_el_titular(self) -> None:
        """Un pliego, una rectificación y unas respuestas no piden lo mismo."""
        assert "PCAP" in aviso_documento_nuevo("PCAP").titulo

    def test_sin_tipo_sigue_avisando(self) -> None:
        aviso = aviso_documento_nuevo(None)
        assert aviso.subtipo == "documento_nuevo"
        assert aviso.titulo


class TestRecurso:
    @pytest.mark.parametrize("sentido", ["estimado", "desestimado", "inadmitido"])
    def test_el_sentido_va_en_el_titular(self, sentido: str) -> None:
        """Un recurso estimado puede reabrir el plazo; uno inadmitido, no."""
        assert sentido in aviso_recurso(sentido).titulo

    def test_sentido_desconocido_no_inventa(self) -> None:
        aviso = aviso_recurso("desistimiento")
        assert aviso.subtipo == "recurso"
        assert "desistimiento" not in aviso.titulo

    def test_sin_sentido(self) -> None:
        assert aviso_recurso(None).subtipo == "recurso"

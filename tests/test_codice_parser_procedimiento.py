"""Procedimiento, tramitación y peso del precio (v85) en el parser CODICE.

Los tres campos salen del mismo sitio del expediente pero tienen naturalezas
distintas y por eso se prueban aparte:

- ``procedimiento`` y ``tramitacion`` son lecturas directas de dos ``cbc:``
  hermanos del plazo de presentación. Lo único que hay que congelar es que se
  guarda el **código crudo** y que su ausencia es ``None``, no ``""``.
- ``peso_precio_pct`` es el único de los tres que **deduce** algo: CODICE
  publica los pesos de los criterios sin decir en qué escala están, y el parser
  la infiere de la suma. Ahí está el grueso de estos tests, incluida la
  frontera donde la escala deja de ser deducible y el campo debe quedar NULL en
  vez de inventar un porcentaje.
"""

from __future__ import annotations

import textwrap

import pytest
from lxml import etree

from scraper.codice_parser import parse_entry, parse_entry_unfiltered, parse_peso_precio

_NS = {
    "cbc": "urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2",
    "cacext": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2",
    "cbcext": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2",
}


def _make_entry(
    *,
    lic_id: str = "PROC-001",
    procedure_code: str | None = "1",
    urgency_code: str | None = "2",
    criterios_xml: str = "",
    con_tendering_process: bool = True,
) -> bytes:
    """Entry CODICE mínima (universo SAP) con ``TenderingProcess`` y criterios.

    ``con_tendering_process=False`` omite el bloque entero, que es el caso de
    los expedientes que ya avanzaron a fase de adjudicación y dejan de
    publicarlo.
    """
    procedure_xml = (
        f"<cbc:ProcedureCode>{procedure_code}</cbc:ProcedureCode>" if procedure_code else ""
    )
    urgency_xml = f"<cbc:UrgencyCode>{urgency_code}</cbc:UrgencyCode>" if urgency_code else ""
    tendering_process_xml = (
        f"""
            <cac:TenderingProcess>
              {procedure_xml}
              {urgency_xml}
              <cac:TenderSubmissionDeadlinePeriod>
                <cbc:EndDate>2026-05-20</cbc:EndDate>
              </cac:TenderSubmissionDeadlinePeriod>
            </cac:TenderingProcess>"""
        if con_tendering_process
        else ""
    )

    xml = textwrap.dedent(f"""\
        <entry xmlns="http://www.w3.org/2005/Atom"
               xmlns:cbc="{_NS["cbc"]}"
               xmlns:cac="{_NS["cac"]}"
               xmlns:cacext="{_NS["cacext"]}"
               xmlns:cbcext="{_NS["cbcext"]}">
          <id>https://example.com/{lic_id}</id>
          <title>Mantenimiento SAP ERP</title>
          <updated>2026-03-15T00:00:00Z</updated>
          <link href="https://example.com/{lic_id}" rel="alternate"/>
          <summary>
            Id licitación: {lic_id}; Órgano de Contratación: Ministerio;
            Importe: 100000.00 EUR; Estado: PUB
          </summary>
          <cacext:ContractFolderStatus>
            <cbc:ContractFolderID>{lic_id}</cbc:ContractFolderID>
            <cbcext:ContractFolderStatusCode>PUB</cbcext:ContractFolderStatusCode>
            <cac:ProcurementProject>
              <cbc:Name>Mantenimiento SAP ERP</cbc:Name>
              <cac:BudgetAmount>
                <cbc:TaxExclusiveAmount currencyID="EUR">100000.00</cbc:TaxExclusiveAmount>
              </cac:BudgetAmount>
            </cac:ProcurementProject>{tendering_process_xml}
            {criterios_xml}
          </cacext:ContractFolderStatus>
        </entry>
    """)
    return xml.encode()


def _criterios(*criterios: str) -> str:
    """Envuelve criterios ya serializados en ``TenderingTerms/AwardingTerms``."""
    cuerpo = "".join(criterios)
    return (
        f"<cac:TenderingTerms><cac:AwardingTerms>{cuerpo}</cac:AwardingTerms></cac:TenderingTerms>"
    )


def _criterio(
    descripcion: str,
    peso: str | None,
    *,
    tag: str = "AwardingCriteria",
    tipo: str | None = None,
    subordinados: str = "",
) -> str:
    peso_xml = f"<cbc:WeightNumeric>{peso}</cbc:WeightNumeric>" if peso is not None else ""
    tipo_tag = (
        "AwardingCriteriaTypeCode" if tag == "AwardingCriteria" else "AwardingCriterionTypeCode"
    )
    tipo_xml = f"<cbc:{tipo_tag}>{tipo}</cbc:{tipo_tag}>" if tipo else ""
    return (
        f"<cac:{tag}>{tipo_xml}<cbc:Description>{descripcion}</cbc:Description>"
        f"{peso_xml}{subordinados}</cac:{tag}>"
    )


def _parse(xml: bytes):
    entry = etree.fromstring(xml)
    lic = parse_entry(entry)
    assert lic is not None
    return lic


def _peso(criterios_xml: str) -> float | None:
    return parse_peso_precio(etree.fromstring(_make_entry(criterios_xml=criterios_xml)))


# ─── procedimiento y tramitación ─────────────────────────────────────────────


def test_procedimiento_y_tramitacion_se_guardan_como_codigo_crudo() -> None:
    """El código CODICE viaja tal cual: traducirlo exigiría embeber la codelist."""
    lic = _parse(_make_entry(procedure_code="9", urgency_code="2"))

    assert lic.procedimiento == "9"
    assert lic.tramitacion == "2"


def test_sin_tendering_process_los_dos_codigos_son_none() -> None:
    """Ausencia es ``None``, nunca cadena vacía: el upsert la distingue."""
    lic = _parse(_make_entry(con_tendering_process=False))

    assert lic.procedimiento is None
    assert lic.tramitacion is None
    assert lic.peso_precio_pct is None


def test_procedimiento_sin_tramitacion_no_arrastra_al_otro() -> None:
    """Los dos códigos son opcionales por separado en el feed real."""
    lic = _parse(_make_entry(procedure_code="1", urgency_code=None))

    assert lic.procedimiento == "1"
    assert lic.tramitacion is None


def test_parse_entry_unfiltered_extrae_los_mismos_campos() -> None:
    """El camino no-TI alimenta el dataset ML: no puede quedarse corto."""
    entry = etree.fromstring(
        _make_entry(
            lic_id="NEG-001",
            procedure_code="6",
            urgency_code="1",
            criterios_xml=_criterios(
                _criterio("Precio", "100"),
            ),
        )
    )

    lic = parse_entry_unfiltered(entry)

    assert lic is not None
    assert (lic.procedimiento, lic.tramitacion, lic.peso_precio_pct) == ("6", "1", 100.0)


# ─── peso del precio: escala deducible ───────────────────────────────────────


def test_pesos_en_porcentaje_suman_cien_y_el_precio_se_devuelve_tal_cual() -> None:
    assert _peso(_criterios(_criterio("Precio", "60"), _criterio("Calidad técnica", "40"))) == 60.0


def test_pesos_en_fraccion_se_reescalan_a_porcentaje() -> None:
    """Media PLACSP publica 0.6/0.4; sin reescalar, el modelo vería un 0.6%."""
    assert _peso(_criterios(_criterio("Precio", "0.6"), _criterio("Memoria", "0.4"))) == 60.0


def test_peso_con_coma_decimal_se_parsea() -> None:
    """El feed alterna coma y punto según quién publique el expediente."""
    assert _peso(_criterios(_criterio("Precio", "51,5"), _criterio("Calidad", "48,5"))) == 51.5


def test_varios_criterios_economicos_se_suman() -> None:
    """El precio se trocea a menudo (precio hora, precio licencia, descuento)."""
    criterios = _criterios(
        _criterio("Precio de la hora de consultoría", "40"),
        _criterio("Oferta económica de licencias", "25"),
        _criterio("Solvencia técnica", "35"),
    )

    assert _peso(criterios) == 65.0


def test_sin_criterio_economico_el_peso_es_cero_no_none() -> None:
    """Adjudicar solo por juicio de valor es un dato, no una ausencia de dato."""
    criterios = _criterios(_criterio("Calidad técnica", "70"), _criterio("Plazo", "30"))

    assert _peso(criterios) == 0.0


@pytest.mark.parametrize(
    "descripcion",
    ["Proposición Económica", "PRECIO OFERTADO", "Coste del ciclo de vida", "criterios economicos"],
)
def test_deteccion_del_criterio_economico_ignora_acentos_y_mayusculas(descripcion: str) -> None:
    assert _peso(_criterios(_criterio(descripcion, "70"), _criterio("Memoria", "30"))) == 70.0


def test_tipo_price_de_ubl_gana_aunque_la_descripcion_no_lo_diga() -> None:
    """UBL 2.1/eForms codifican el tipo en texto; ahí no hace falta el heurístico."""
    criterios = _criterios(
        _criterio("Oferta", "55", tag="AwardingCriterion", tipo="PRICE"),
        _criterio("Memoria", "45", tag="AwardingCriterion"),
    )

    assert _peso(criterios) == 55.0


def test_grafia_ubl_awarding_criterion_se_reconoce_igual() -> None:
    """Las dos grafías conviven en el feed según la versión del esquema."""
    criterios = _criterios(
        _criterio("Precio", "80", tag="AwardingCriterion"),
        _criterio("Calidad", "20", tag="AwardingCriterion"),
    )

    assert _peso(criterios) == 80.0


@pytest.mark.parametrize("tag_subordinado", ["SubordinateAwardingCriteria", "AwardingCriteria"])
def test_subcriterios_no_cuentan_dos_veces(tag_subordinado: str) -> None:
    """El subcriterio reparte el peso de SU padre, no el del expediente.

    Sumarlo junto al padre daría total=200 y sacaría al expediente de la banda
    de porcentaje, convirtiendo un dato perfectamente legible en NULL.

    Las dos grafías del anidamiento importan: con el tag ``Subordinate...`` el
    subcriterio ni siquiera entra en la selección, pero hay expedientes que
    anidan ``AwardingCriteria`` dentro de ``AwardingCriteria`` y ahí lo único
    que lo descarta es el filtro por ancestro.
    """
    subordinados = (
        f"<cac:{tag_subordinado}>"
        "<cbc:Description>Precio hora junior</cbc:Description>"
        "<cbc:WeightNumeric>30</cbc:WeightNumeric>"
        f"</cac:{tag_subordinado}>"
        f"<cac:{tag_subordinado}>"
        "<cbc:Description>Precio hora senior</cbc:Description>"
        "<cbc:WeightNumeric>70</cbc:WeightNumeric>"
        f"</cac:{tag_subordinado}>"
    )
    criterios = _criterios(
        _criterio("Oferta económica", "60", subordinados=subordinados),
        _criterio("Calidad", "40"),
    )

    assert _peso(criterios) == 60.0


# ─── peso del precio: escala NO deducible → NULL ─────────────────────────────


def test_criterios_publicados_a_medias_no_producen_porcentaje() -> None:
    """Un solo criterio del 60% sin el resto: el denominador es desconocido.

    Devolver 60 aquí sería afirmar que el precio pesa el 60% del total cuando
    lo único observado es que pesa 60 de un total que nadie publicó.
    """
    assert _peso(_criterios(_criterio("Precio", "60"))) is None


def test_criterios_sin_peso_publicado_no_producen_porcentaje() -> None:
    criterios = _criterios(_criterio("Precio", None), _criterio("Calidad", None))

    assert _peso(criterios) is None


def test_sin_bloque_de_criterios_el_peso_es_none() -> None:
    assert _peso("") is None


def test_pesos_negativos_se_ignoran() -> None:
    """Basura de fuente: un peso negativo no debe descuadrar el total."""
    criterios = _criterios(
        _criterio("Precio", "60"), _criterio("Calidad", "40"), _criterio("Ruido", "-10")
    )

    assert _peso(criterios) == 60.0


def test_criterio_unico_de_precio_al_cien_por_cien_es_valido() -> None:
    """Subasta pura: total=100, escala deducible, respuesta 100.0."""
    assert _peso(_criterios(_criterio("Precio", "100"))) == 100.0


# ─── contrato de persistencia ────────────────────────────────────────────────


def test_upsert_escribe_las_tres_columnas_y_no_las_nulea_al_reingerir() -> None:
    """Las tres cuelgan de bloques que desaparecen en fase ADJ/RES.

    Sin COALESCE, la re-ingesta de un expediente adjudicado borraría el dato
    justo en las filas que el modelo de baja puede usar para entrenar.
    """
    from db.upsert import _LIC_COALESCE_UPDATE_FIELDS, _LIC_KEYS, _LIC_UPDATES

    nuevas = ("procedimiento", "tramitacion", "peso_precio_pct")

    assert set(nuevas) <= set(_LIC_KEYS)
    assert set(nuevas) <= _LIC_COALESCE_UPDATE_FIELDS
    for columna in nuevas:
        assert f"{columna}=COALESCE(excluded.{columna}, licitaciones.{columna})" in _LIC_UPDATES


def test_las_tres_columnas_existen_en_la_tabla_sqlalchemy() -> None:
    """`db/models.py` compila queries: una columna que falte ahí es invisible."""
    from db.models import licitaciones

    assert {"procedimiento", "tramitacion", "peso_precio_pct"} <= set(licitaciones.c.keys())


def test_las_features_nuevas_siguen_fuera_del_contrato_del_modelo() -> None:
    """El gate del backlog: entran solo con la cobertura medida por encima del 50%.

    Este test es el que se pone en rojo a propósito el día que alguien las
    cablee: obliga a que ese cambio pase por aquí y por el reentrenamiento, en
    vez de colarse como un añadido inocente a una tupla.
    """
    from services.ml.features import FEATURE_COLUMNS, FEATURES_PENDIENTES_COBERTURA

    assert not set(FEATURES_PENDIENTES_COBERTURA) & set(FEATURE_COLUMNS)


def test_features_procedimiento_normaliza_ausencias() -> None:
    from services.ml.features import features_procedimiento

    assert features_procedimiento({}) == {
        "procedimiento": "na",
        "tramitacion": "na",
        "peso_precio_pct": None,
    }
    assert features_procedimiento(
        {"procedimiento": "1", "tramitacion": "2", "peso_precio_pct": 60}
    ) == {"procedimiento": "1", "tramitacion": "2", "peso_precio_pct": 60.0}

"""Proyectos y módulos por familias de la taxonomía (2026-10).

Hasta 2026-10 la vista solo entendía módulos SAP: sobre un corpus que ya
clasifica por categorías (ERP, CRM, cloud, ciberseguridad…) enseñaba S/4HANA,
FI o Ariba y nada más. Ahora agrupa por las **categorías** de
``config/keywords.py`` y los módulos SAP quedan como desglose dentro de ERP.

Fija:

1. **Qué es una familia.** Las categorías de la taxonomía, en su orden; un
   fabricante cuenta en la familia de su línea de producto
   (``FAMILIA_DE_FABRICANTE``) y los transversales no cuentan en ninguna, y la
   respuesta lo dice en vez de esconderlo.
2. **Sin doble conteo.** Una licitación de dos familias cuenta en las dos,
   pero el total y el importe a nivel licitación la cuentan una vez.
3. **El desglose de ERP es de ERP.** Los módulos SAP se detectan solo sobre lo
   etiquetado como SAP: un «asesoramiento financiero» sin SAP no es SAP FI.

Los cuatro primeros tests no tocan la base de datos (auto-marcados ``unit``);
el resto siembra licitaciones reales en el schema aislado (``tmp_db``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from config.keywords import (
    FAMILIA_DE_FABRICANTE,
    FAMILIAS_TECNOLOGICAS,
    TECH_CATEGORIAS,
    TECH_LABEL_TIPO,
    codigos_de_familia,
    etiqueta_familia,
)
from services.analytics.proyectos_modulos import ProyectosModulosFilters, get_proyectos_modulos

TRANSVERSALES = {"ORACLE", "MICROSOFT", "IBM", "SERVICENOW", "SOPRA"}


# ── qué es una familia ──────────────────────────────────────────────────────


def test_las_familias_son_las_categorias_de_la_taxonomia_en_su_orden():
    categorias = [label for label, tipo in TECH_LABEL_TIPO.items() if tipo == "categoria"]
    assert list(FAMILIAS_TECNOLOGICAS) == categorias
    # Las nueve que nombra el producto están, y en cabeza ERP y CRM.
    for familia in (
        "ERP",
        "CRM",
        "CLOUD_INFRA",
        "CIBERSEGURIDAD",
        "DATOS_IA",
        "DESARROLLO",
        "GIS",
        "SANIDAD_DIGITAL",
        "ADMIN_ELECTRONICA",
    ):
        assert familia in FAMILIAS_TECNOLOGICAS
    assert FAMILIAS_TECNOLOGICAS[:2] == ("ERP", "CRM")


def test_la_etiqueta_de_una_familia_no_dice_generico():
    # «ERP (genérico)» nombra el label sin fabricante; la familia ERP incluye
    # además a SAP, Unit4, Sage e Infor.
    assert etiqueta_familia("ERP") == "ERP"
    assert etiqueta_familia("CRM") == "CRM"
    assert etiqueta_familia("CLOUD_INFRA") == TECH_CATEGORIAS["CLOUD_INFRA"]


def test_cada_fabricante_cuenta_en_una_familia_o_en_ninguna():
    for fabricante, familia in FAMILIA_DE_FABRICANTE.items():
        assert TECH_LABEL_TIPO[fabricante] == "fabricante"
        assert familia in FAMILIAS_TECNOLOGICAS
    # SAP es el desglose de ERP: tiene que estar dentro.
    assert FAMILIA_DE_FABRICANTE["SAP"] == "ERP"
    assert FAMILIA_DE_FABRICANTE["SALESFORCE"] == "CRM"
    # Los que venden en varias familias no se reparten por intuición.
    assert TRANSVERSALES.isdisjoint(FAMILIA_DE_FABRICANTE)
    fabricantes = {label for label, tipo in TECH_LABEL_TIPO.items() if tipo == "fabricante"}
    assert set(FAMILIA_DE_FABRICANTE) | TRANSVERSALES == fabricantes


def test_codigos_de_una_familia_son_su_categoria_y_sus_fabricantes():
    assert codigos_de_familia("ERP") == ["ERP", "SAP", "UNIT4", "SAGE", "INFOR"]
    assert codigos_de_familia("CRM") == ["CRM", "SALESFORCE"]
    assert codigos_de_familia("GIS") == ["GIS"]


# ── agregados sobre licitaciones reales ─────────────────────────────────────


def _dias_atras(n: int) -> str:
    return (datetime.now(UTC) - timedelta(days=n)).strftime("%Y-%m-%d")


def _insert(rows: list[dict]) -> None:
    from db.upsert import Licitacion, upsert_licitaciones

    upsert_licitaciones(
        [
            Licitacion(
                id_externo=r["id_externo"],
                titulo=r.get("titulo", "Contrato TI"),
                importe=r.get("importe"),
                estado=r.get("estado", "PUB"),
                fecha_publicacion=r.get("fecha_publicacion", _dias_atras(30)),
                tipo_contrato="2",
                cpv="72000000",
                tecnologia=r.get("tecnologia"),
            )
            for r in rows
        ]
    )


def _corpus() -> list[dict]:
    return [
        {
            "id_externo": "F1",
            "titulo": "Implantación SAP S/4HANA",
            "importe": 500_000.0,
            "tecnologia": "SAP",
        },
        {
            "id_externo": "F2",
            "titulo": "Suministro de un ERP",
            "importe": 100_000.0,
            "tecnologia": "ERP",
        },
        {
            "id_externo": "F3",
            "titulo": "SOC y SAP Ariba",
            "importe": 200_000.0,
            "tecnologia": "SAP,CIBERSEGURIDAD",
        },
        {
            "id_externo": "F4",
            "titulo": "Plataforma Salesforce",
            "importe": 80_000.0,
            "tecnologia": "SALESFORCE",
        },
        {
            "id_externo": "F5",
            "titulo": "Licencias Oracle Database",
            "importe": 60_000.0,
            "tecnologia": "ORACLE",
        },
        {
            "id_externo": "F6",
            "titulo": "Limpieza de edificios",
            "importe": 900_000.0,
            "tecnologia": None,
        },
    ]


def test_agrupa_por_familia_con_los_fabricantes_dentro(tmp_db):
    _insert(_corpus())

    result = get_proyectos_modulos(ProyectosModulosFilters())

    familias = {f.familia: f for f in result.familias}
    # ERP = el ERP genérico + lo de SAP (F1, F2, F3).
    assert familias["ERP"].count == 3
    assert familias["ERP"].importe == 800_000.0
    assert familias["ERP"].etiqueta == "ERP"
    assert familias["ERP"].importe_medio == round(800_000.0 / 3, 2)
    assert familias["CRM"].count == 1
    assert familias["CIBERSEGURIDAD"].count == 1
    # Una familia sin licitaciones no se pinta como un cero.
    assert "GIS" not in familias
    # De mayor a menor.
    assert [f.count for f in result.familias] == sorted(
        (f.count for f in result.familias), reverse=True
    )


def test_una_licitacion_de_dos_familias_cuenta_en_las_dos_y_una_vez_en_el_total(tmp_db):
    _insert(_corpus())

    result = get_proyectos_modulos(ProyectosModulosFilters())

    assert result.total == 6
    # F1, F2, F3 y F4: Oracle es transversal y la limpieza no es TI.
    assert result.total_con_familia == 4
    assert result.menciones_familia == 5  # F3 cuenta en ERP y en Ciberseguridad
    assert result.importe_con_familia == 880_000.0  # F3 una sola vez
    assert result.ticket_medio_familia == 220_000.0
    assert result.pct_con_familia == round(4 / 6 * 100, 2)
    assert result.familias_por_licitacion == 1.25


def test_dice_que_fabricantes_no_cuentan_en_ninguna_familia(tmp_db):
    _insert(_corpus())

    result = get_proyectos_modulos(ProyectosModulosFilters())

    assert result.fabricantes_sin_familia == sorted(TECH_CATEGORIAS[f] for f in TRANSVERSALES)


def test_los_modulos_sap_son_un_desglose_de_lo_etiquetado_sap(tmp_db):
    _insert(
        [
            *_corpus(),
            # «financiero» es una keyword de SAP FI, pero esto no es SAP.
            {
                "id_externo": "F7",
                "titulo": "Asesoramiento financiero externo",
                "importe": 40_000.0,
                "tecnologia": "DESARROLLO",
            },
        ]
    )

    result = get_proyectos_modulos(ProyectosModulosFilters())

    modulos = {m.modulo: m for m in result.modulos}
    assert "FI" not in modulos
    assert modulos["S/4HANA"].count == 1
    assert modulos["Ariba"].count == 1
    # Denominador del desglose: las licitaciones SAP del ámbito.
    assert result.total_sap == 2
    assert result.total_clasificados == 2
    assert result.pct_sap_con_modulo == 100.0


def test_la_familia_que_mas_crece(tmp_db):
    _insert(
        [
            {
                "id_externo": "Y1",
                "titulo": "SOC",
                "tecnologia": "CIBERSEGURIDAD",
                "fecha_publicacion": _dias_atras(20),
            },
            {
                "id_externo": "Y2",
                "titulo": "SIEM",
                "tecnologia": "CIBERSEGURIDAD",
                "fecha_publicacion": _dias_atras(40),
            },
            {
                "id_externo": "Y3",
                "titulo": "EDR",
                "tecnologia": "CIBERSEGURIDAD",
                "fecha_publicacion": _dias_atras(400),
            },
            {
                "id_externo": "Y4",
                "titulo": "ERP",
                "tecnologia": "ERP",
                "fecha_publicacion": _dias_atras(30),
            },
            {
                "id_externo": "Y5",
                "titulo": "ERP",
                "tecnologia": "ERP",
                "fecha_publicacion": _dias_atras(380),
            },
            {
                "id_externo": "Y6",
                "titulo": "ERP",
                "tecnologia": "ERP",
                "fecha_publicacion": _dias_atras(390),
            },
        ]
    )

    result = get_proyectos_modulos(ProyectosModulosFilters())

    assert result.top_familia_yoy is not None
    assert result.top_familia_yoy.familia == "CIBERSEGURIDAD"
    assert result.top_familia_yoy.etiqueta == "Ciberseguridad"
    assert result.top_familia_yoy.crecimiento_pct == 100.0
    assert result.top_familia_yoy.n_act == 2


def test_el_filtro_de_fechas_acota_las_familias(tmp_db):
    _insert(
        [
            *_corpus(),
            {
                "id_externo": "F8",
                "titulo": "Visor GIS",
                "tecnologia": "GIS",
                "fecha_publicacion": _dias_atras(400),
            },
        ]
    )

    result = get_proyectos_modulos(
        ProyectosModulosFilters(fecha_desde=(datetime.now(UTC) - timedelta(days=90)).date())
    )

    assert "GIS" not in {f.familia for f in result.familias}
    assert result.total_con_familia == 4


def test_sin_licitaciones_no_divide_por_cero(tmp_db):
    result = get_proyectos_modulos(ProyectosModulosFilters())

    assert result.familias == []
    assert result.total_con_familia == 0
    assert result.pct_con_familia == 0.0
    assert result.familias_por_licitacion == 0.0
    assert result.ticket_medio_familia == 0.0
    assert result.top_familia_yoy is None
    assert result.total_sap == 0
    assert result.pct_sap_con_modulo == 0.0

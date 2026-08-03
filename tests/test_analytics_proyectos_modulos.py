"""Tests unitarios para services/analytics/proyectos_modulos.

Caracterización de la migración pandas -> SQL (ADR-023): siembran el dataset
sintético en el schema aislado (``tmp_db``) — la detección de módulos corre
ahora en el motor (``titulo ~* patrón``) con los mismos patrones que
``_detect_modules`` compila en Python. Cubre la detección regex, el YoY y los
agregados tipo×estado / CPV.

Nota histórica: la rama de "columna explícita" (``modulo_sap``/``modulos``)
desapareció con la migración — esa columna nunca existió en la proyección de
stats, así que la rama era código muerto en producción. Su test se sustituye
por uno de multi-módulo (un título que matchea dos módulos cuenta en ambos,
pero el importe distinct solo una vez), que sí es contrato vigente.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from services.analytics.proyectos_modulos import (
    ProyectosModulosFilters,
    _detect_modules,
    get_proyectos_modulos,
)


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
                estado=r.get("estado"),
                fecha_publicacion=r.get("fecha_publicacion"),
                tipo_contrato=r.get("tipo_contrato"),
                cpv=r.get("cpv"),
                tecnologia=r.get("tecnologia"),
            )
            for r in rows
        ]
    )


def _rows_regex() -> list[dict]:
    """Fuerza la detección regex sobre títulos."""
    return [
        {
            "id_externo": "L1",
            "titulo": "Implantación SAP Ariba",
            "importe": 100_000.0,
            "estado": "ADJ",
            "fecha_publicacion": _dias_atras(30),
            "tipo_contrato": "2",
            "cpv": "72000000",
            "tecnologia": "SAP",
        },
        {
            "id_externo": "L2",
            "titulo": "Ampliación SAP Ariba fase II",
            "importe": 200_000.0,
            "estado": "PUB",
            "fecha_publicacion": _dias_atras(60),
            "tipo_contrato": "2",
            "cpv": "72000000",
            "tecnologia": "SAP",
        },
        {
            "id_externo": "L3",
            "titulo": "Renovación SAP Ariba",  # año anterior → base del YoY
            "importe": 80_000.0,
            "estado": "ADJ",
            "fecha_publicacion": _dias_atras(400),
            "tipo_contrato": "2",
            "cpv": "48000000",
            "tecnologia": "SAP",
        },
        {
            "id_externo": "L4",
            "titulo": "Obra civil del edificio",  # sin módulo SAP
            "importe": 999_000.0,
            "estado": "PUB",
            "fecha_publicacion": _dias_atras(30),
            "tipo_contrato": "3",
            "cpv": "45000000",
            "tecnologia": "SAP",
        },
    ]


# ── _detect_modules (paridad con los patrones SQL) ──────────────────────────


def test_detect_modules_basico():
    assert "Ariba" in _detect_modules("Implantación SAP Ariba")
    assert "SuccessFactors" in _detect_modules("Soporte SuccessFactors nómina")
    assert _detect_modules("Obra civil del edificio") == []
    assert _detect_modules("") == []


def test_detect_modules_case_insensitive():
    assert "S/4HANA" in _detect_modules("migración a s/4hana")


# ── detección regex en el motor ─────────────────────────────────────────────


def test_modulos_deteccion_regex_en_titulos(tmp_db):
    _insert(_rows_regex())

    result = get_proyectos_modulos(ProyectosModulosFilters())

    modulos = {m.modulo: m for m in result.modulos}
    assert "Ariba" in modulos
    assert modulos["Ariba"].count == 3
    assert modulos["Ariba"].importe == 380_000.0
    # L4 no clasifica → 3 clasificadas; el importe SAP excluye la obra civil
    assert result.total_clasificados == 3
    assert result.importe_total_sap == 380_000.0
    assert result.ticket_medio_sap == round(380_000.0 / 3, 2)


def test_modulos_multimodulo_cuenta_en_ambos_pero_importe_distinct(tmp_db):
    """Un título con dos módulos cuenta en ambos; el importe distinct solo una vez."""
    _insert(
        [
            {
                "id_externo": "MM1",
                "titulo": "Migración SAP HANA y SAP Ariba",
                "importe": 100_000.0,
                "estado": "PUB",
                "fecha_publicacion": _dias_atras(10),
                "tipo_contrato": "2",
                "cpv": "72000000",
                "tecnologia": "SAP",
            }
        ]
    )

    result = get_proyectos_modulos(ProyectosModulosFilters())

    modulos = {m.modulo: m for m in result.modulos}
    assert modulos["HANA"].count == 1
    assert modulos["Ariba"].count == 1
    # KPI a nivel licitación: una sola licitación clasificada, importe una vez.
    assert result.total_clasificados == 1
    assert result.importe_total_sap == 100_000.0


def test_top_modulo_yoy_crecimiento(tmp_db):
    """2 menciones último año vs 1 el anterior → +100%."""
    _insert(_rows_regex())

    result = get_proyectos_modulos(ProyectosModulosFilters())

    assert result.top_modulo_yoy is not None
    assert result.top_modulo_yoy.modulo == "Ariba"
    assert result.top_modulo_yoy.crecimiento_pct == 100.0
    assert result.top_modulo_yoy.n_act == 2


def test_top_modulo_yoy_nuevo_sentinel(tmp_db):
    """Módulo sin histórico el año anterior → sentinel 999.0 (NUEVO)."""
    _insert(
        [
            {
                "id_externo": f"L{i}",
                "titulo": "Soporte SuccessFactors",
                "importe": 10_000.0,
                "estado": "PUB",
                "fecha_publicacion": _dias_atras(20 + i),
                "tipo_contrato": "2",
                "cpv": "72000000",
                "tecnologia": "SAP",
            }
            for i in range(2)
        ]
    )

    result = get_proyectos_modulos(ProyectosModulosFilters())

    assert result.top_modulo_yoy is not None
    assert result.top_modulo_yoy.modulo == "SuccessFactors"
    assert result.top_modulo_yoy.crecimiento_pct == 999.0


# ── agregados auxiliares ────────────────────────────────────────────────────


def test_tipos_proyecto_y_tipo_estado(tmp_db):
    _insert(_rows_regex())

    result = get_proyectos_modulos(ProyectosModulosFilters())

    tipos = {t.tipo: t for t in result.tipos_proyecto}
    assert tipos["2"].count == 3
    assert tipos["3"].count == 1
    # Cross-tab: cada fila clasificada por tipo aparece una vez
    assert sum(e.n for e in result.tipo_estado) == 4
    assert {e.tipo for e in result.tipo_estado} == {"2", "3"}


def test_cpv_top_con_descripcion(tmp_db):
    _insert(_rows_regex())

    result = get_proyectos_modulos(ProyectosModulosFilters())

    cpvs = {c.cpv: c for c in result.cpv}
    assert cpvs["72000000"].count == 2
    assert isinstance(cpvs["72000000"].cpv_desc, str)


def test_filtro_fechas_reduce_dataset(tmp_db):
    _insert(_rows_regex())

    result = get_proyectos_modulos(
        ProyectosModulosFilters(fecha_desde=(datetime.now(UTC) - timedelta(days=90)).date())
    )

    # Quedan L1, L2 (Ariba) y L4 (sin módulo); L3 (400 días) fuera
    assert result.total_clasificados == 2


def test_dataset_vacio(tmp_db):
    result = get_proyectos_modulos(ProyectosModulosFilters())
    assert result.modulos == []
    assert result.total_clasificados == 0
    assert result.top_modulo_yoy is None

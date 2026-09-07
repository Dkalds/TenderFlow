"""Tests del generador de ``docs/database-schema.md`` (``scripts/gen_schema_doc.py``).

Solo la parte pura: agrupación por familia, render del markdown y comparación
de ``--check``. La lectura real del catálogo necesita un Postgres migrado y por
eso vive en el job ``static-analysis`` de CI, no aquí; estas pruebas usan filas
de ``information_schema`` simuladas para que el formato del documento tenga red
sin depender de una base de datos.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.gen_schema_doc import (
    _MARKER,
    _OTRAS,
    _SIN_BD,
    Columna,
    Esquema,
    Indice,
    Restriccion,
    agrupar,
    diferencias,
    familia,
    main,
    render,
    sin_fecha,
)


def _esquema_demo() -> Esquema:
    """Dos tablas de familias distintas, una matview y una vista."""
    return Esquema(
        revision="v102_mv_canonicas_clave_inmutable",
        columnas=(
            Columna("licitaciones", "id_externo", "text", nullable=False),
            Columna("licitaciones", "importe", "double precision", nullable=True),
            Columna("pursuits", "id", "integer", nullable=False),
            Columna("pursuits", "banda_al_abrir", "text", nullable=True),
            # La tabla de control de Alembic llega del catálogo y no se publica.
            Columna("alembic_version", "version_num", "character varying", nullable=False),
        ),
        restricciones=(
            Restriccion("licitaciones", "PRIMARY KEY (id_externo)"),
            Restriccion("pursuits", "UNIQUE (organization_id, licitacion_id)"),
            Restriccion("pursuits", "PRIMARY KEY (id)"),
            Restriccion("alembic_version", "PRIMARY KEY (version_num)"),
        ),
        indices=(
            Indice("licitaciones", "idx_fecha_pub", unico=False),
            Indice("licitaciones", "idx_lic_clave_canonica_v101", unico=True),
            Indice("licitaciones_canonicas", "uq_licitaciones_canonicas_id_externo", unico=True),
        ),
        matviews=("licitaciones_canonicas",),
        vistas=("licitaciones_history_2026",),
    )


# ─────────────────────────── agrupación por familia ───────────────────────────


@pytest.mark.parametrize(
    ("tabla", "esperada"),
    [
        ("licitaciones", "Licitaciones y fuente"),
        ("licitaciones_history", "Licitaciones y fuente"),
        ("documento_chunks", "Documentos y pliegos"),
        ("tender_fact_sheets", "Documentos y pliegos"),
        ("empresa_aliases", "Empresas y mercado"),
        ("pursuit_events", "Organizaciones y oportunidades"),
        ("organization_memberships", "Organizaciones y oportunidades"),
        ("api_keys", "Identidad, acceso y auditoría"),
        ("totp_secrets", "Identidad, acceso y auditoría"),
        ("watchlist_rules", "Seguimiento y notificaciones"),
        ("webhook_deliveries", "Seguimiento y notificaciones"),
        ("predicciones_baja", "ML y predicciones"),
        ("domain_events", "Operación y observabilidad"),
    ],
)
def test_familia_clasifica_por_nombre_y_prefijo(tabla: str, esperada: str) -> None:
    assert familia(tabla) == esperada


def test_licitacion_tecnologia_no_cae_en_licitaciones() -> None:
    """El prefijo de la familia es ``licitaciones_`` (plural) justo por esto.

    ``licitacion_tecnologia_score`` es una tabla de ML: si el prefijo fuese
    ``licitacion`` se la llevaría la familia equivocada por parecido de nombre.
    """
    assert familia("licitacion_tecnologia_score") == "ML y predicciones"
    assert familia("licitacion_tecnologia_pliego") == "ML y predicciones"


def test_tabla_desconocida_cae_en_otras() -> None:
    """Una tabla nueva sin familia no rompe el render: aparece en «Otras»."""
    assert familia("tabla_que_nadie_clasifico") == _OTRAS


def test_agrupar_ordena_por_familia_y_alfabeticamente() -> None:
    grupos = agrupar(["pursuits", "licitaciones", "adjudicaciones", "tabla_rara"])
    assert grupos == [
        ("Licitaciones y fuente", ["adjudicaciones", "licitaciones"]),
        ("Organizaciones y oportunidades", ["pursuits"]),
        (_OTRAS, ["tabla_rara"]),
    ]
    # «Otras» siempre al final, aunque su tabla llegase primera.
    assert grupos[-1][0] == _OTRAS


# ───────────────────────────────── render ─────────────────────────────────


def test_render_lleva_cabecera_de_generado_y_revision() -> None:
    doc = render(_esquema_demo(), hoy="2026-09-06")
    assert _MARKER in doc
    assert "Generado: 2026-09-06" in doc
    assert "Revisión Alembic aplicada: `v102_mv_canonicas_clave_inmutable`." in doc


def test_render_no_resucita_el_motor_retirado_salvo_en_una_nota() -> None:
    """Criterio de aceptación de O0.7(a), verificado sobre el render.

    El documento anterior describía SQLite y su índice FTS5; el nuevo solo puede
    mencionarlos en la nota histórica de una línea que explica de dónde viene.
    """
    doc = render(_esquema_demo(), hoy="2026-09-06")
    con_motor_viejo = [ln for ln in doc.splitlines() if "SQLite" in ln or "FTS5" in ln]
    assert len(con_motor_viejo) == 1
    assert con_motor_viejo[0].startswith("> Nota histórica:")


def test_render_pinta_columnas_con_tipo_y_nulabilidad() -> None:
    doc = render(_esquema_demo(), hoy="2026-09-06")
    assert "| `id_externo` | `text` | no |" in doc
    assert "| `importe` | `double precision` | sí |" in doc


def test_render_pone_la_clave_primaria_antes_que_las_unicas() -> None:
    doc = render(_esquema_demo(), hoy="2026-09-06")
    assert "Claves: `PRIMARY KEY (id)` · `UNIQUE (organization_id, licitacion_id)`" in doc


def test_render_marca_los_indices_unicos() -> None:
    doc = render(_esquema_demo(), hoy="2026-09-06")
    assert "Índices: `idx_fecha_pub`, `idx_lic_clave_canonica_v101` (único)" in doc


def test_render_excluye_la_tabla_de_control_de_alembic() -> None:
    doc = render(_esquema_demo(), hoy="2026-09-06")
    assert "alembic_version" not in doc
    assert "**Total** | **2**" in doc


def test_render_lista_vistas_materializadas_con_sus_indices() -> None:
    doc = render(_esquema_demo(), hoy="2026-09-06")
    assert "## Vistas materializadas" in doc
    assert "| `licitaciones_canonicas` | `uq_licitaciones_canonicas_id_externo` (único) |" in doc
    assert "| `licitaciones_history_2026` | — |" in doc


def test_render_es_determinista() -> None:
    """Dos renders del mismo esquema son idénticos: ``--check`` no puede parpadear."""
    assert render(_esquema_demo(), hoy="2026-09-06") == render(_esquema_demo(), hoy="2026-09-06")


def test_render_omite_las_secciones_de_vistas_si_no_hay() -> None:
    doc = render(Esquema(revision="v1", columnas=(Columna("t", "c", "text", nullable=True),)))
    assert "## Vistas" not in doc


# ──────────────────────────── comparación --check ────────────────────────────


def test_sin_fecha_ignora_solo_la_linea_generado() -> None:
    ayer = render(_esquema_demo(), hoy="2026-09-05")
    hoy = render(_esquema_demo(), hoy="2026-09-06")
    assert ayer != hoy
    assert sin_fecha(ayer) == sin_fecha(hoy)


def test_diferencias_vacias_cuando_solo_cambia_la_fecha() -> None:
    ayer = render(_esquema_demo(), hoy="2026-09-05")
    hoy = render(_esquema_demo(), hoy="2026-09-06")
    assert diferencias(ayer, hoy) == []


def test_diferencias_detecta_una_columna_nueva() -> None:
    antiguo = render(_esquema_demo(), hoy="2026-09-06")
    demo = _esquema_demo()
    nuevo = render(
        Esquema(
            revision=demo.revision,
            columnas=(*demo.columnas, Columna("pursuits", "lote_id", "integer", nullable=True)),
            restricciones=demo.restricciones,
            indices=demo.indices,
            matviews=demo.matviews,
            vistas=demo.vistas,
        ),
        hoy="2026-09-06",
    )
    diff = diferencias(antiguo, nuevo)
    assert diff, "una columna nueva tiene que desfasar el documento"
    assert any("lote_id" in linea for linea in diff)


# ─────────────────────────── ausencia de Postgres ───────────────────────────


def test_sin_test_database_url_sale_con_codigo_propio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Sin BD el generador no puede fallar como si el documento estuviera mal.

    Son dos problemas distintos —«el documento está desfasado» (1) y «aquí no
    hay con qué generarlo» (2)— y quien lee el log de CI necesita distinguirlos.
    """
    import scripts.gen_schema_doc as gen

    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.setattr(gen, "_ROOT", tmp_path)  # sin `.env` del que leerla

    assert main(["--check"]) == _SIN_BD
    assert _SIN_BD != 1
    assert "TEST_DATABASE_URL" in capsys.readouterr().err

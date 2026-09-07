"""S3.2 — el Radar responde por fin si prioriza bien.

``score_al_abrir`` y ``banda_al_abrir`` se persisten desde la revisión ``v93``
y hasta 2026-09 **ningún módulo de producción los leía**: sólo existía la
escritura. Esto fija el cierre de ese bucle.

Todo lo de aquí es unitario a propósito: ``calcular_radar_quality`` es una
función pura sobre las filas que ``metric_rows`` ya trae, así que la regla de
producto se comprueba sin Postgres y no puede quedarse sin cubrir por no haber
base delante. Lo que sí necesita base —que la consulta traiga la banda— vive en
``tests/test_s3_lotes_api.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from services.pursuits import RADAR_QUALITY_MINIMO, calcular_radar_quality


def _fila(
    banda: str | None,
    outcome: str,
    *,
    dia: int = 1,
) -> dict[str, Any]:
    """Una fila tal como la devuelve ``PursuitRepository.metric_rows``."""
    cerrada = outcome in {"won", "lost", "cancelled"}
    return {
        "status": {"won": "won", "lost": "lost", "cancelled": "withdrawn"}.get(
            outcome, "submitted"
        ),
        "outcome": outcome,
        "awarded_amount_eur": 100_000 if outcome == "won" else None,
        "identified_at": f"2026-06-{dia:02d}T09:00:00+00:00",
        "decision_at": f"2026-06-{dia:02d}T12:00:00+00:00",
        "submitted_at": f"2026-06-{dia:02d}T15:00:00+00:00",
        "closed_at": f"2026-07-{dia:02d}T15:00:00+00:00" if cerrada else None,
        "banda_al_abrir": banda,
    }


def _doce_cerradas_calientes() -> list[dict[str, Any]]:
    """Doce oportunidades cerradas abiertas desde la banda Caliente: 8-4.

    Doce y no diez: el umbral es ``>= 10``, así que un fixture de exactamente
    diez no distinguiría «se publica porque llega» de «se publica siempre».
    """
    ganadas = [_fila("Caliente", "won", dia=i) for i in range(1, 9)]
    perdidas = [_fila("Caliente", "lost", dia=i) for i in range(9, 13)]
    return [*ganadas, *perdidas]


def test_precision_de_la_banda_con_denominador_suficiente() -> None:
    """«Precisión de la banda Caliente en tu organización: 8/12»."""
    calidad = calcular_radar_quality(_doce_cerradas_calientes())

    assert calidad is not None
    caliente = next(b for b in calidad.bandas if b.banda == "Caliente")
    assert caliente.ganadas == 8
    assert caliente.perdidas == 4
    assert caliente.resueltas == 12
    assert caliente.precision == 8 / 12
    assert caliente.suficiente is True
    # El umbral viaja con el dato: el cliente no lo reinventa (ADR-014).
    assert calidad.minimo_por_banda == RADAR_QUALITY_MINIMO


def test_por_debajo_del_minimo_no_hay_porcentaje_sino_base() -> None:
    """Nueve resueltas es una anécdota, no una precisión.

    ``None`` y no ``0.0``: un cero diría «el Radar nunca acierta en esa banda»,
    que es una afirmación que estos datos no sostienen (ADR-014).
    """
    filas = [_fila("Atractiva", "won", dia=i) for i in range(1, 6)]
    filas += [_fila("Atractiva", "lost", dia=i) for i in range(6, 10)]

    calidad = calcular_radar_quality(filas)

    assert calidad is not None
    atractiva = next(b for b in calidad.bandas if b.banda == "Atractiva")
    assert atractiva.resueltas == 9
    assert atractiva.precision is None
    assert atractiva.suficiente is False
    # La base sí se publica: es lo que permite decir "9 de 10 necesarias".
    assert (atractiva.ganadas, atractiva.perdidas) == (5, 4)


def test_las_retiradas_cuentan_para_el_cierre_pero_no_para_la_precision() -> None:
    """Una retirada no dice quién habría ganado, pero sí que dejó de ocupar."""
    filas = _doce_cerradas_calientes()
    filas += [_fila("Caliente", "cancelled", dia=13) for _ in range(2)]
    filas += [_fila("Caliente", "pending", dia=14) for _ in range(2)]

    calidad = calcular_radar_quality(filas)

    assert calidad is not None
    caliente = next(b for b in calidad.bandas if b.banda == "Caliente")
    assert caliente.resueltas == 12
    assert caliente.precision == 8 / 12
    assert caliente.abiertas == 16
    assert caliente.cerradas == 14
    assert caliente.tasa_cierre == 14 / 16


def test_sin_ninguna_banda_sellada_la_metrica_no_existe() -> None:
    """``None``, no un objeto con ceros: no se midió, no es que salga 0 %.

    Es el estado de todas las oportunidades anteriores a la revisión ``v93``.
    """
    filas = [_fila(None, "won", dia=i) for i in range(1, 13)]

    assert calcular_radar_quality(filas) is None


def test_la_cobertura_declara_sobre_cuanto_habla() -> None:
    """Doce con banda de veinticuatro oportunidades: 50 % de cobertura."""
    filas = _doce_cerradas_calientes()
    filas += [_fila(None, "won", dia=i) for i in range(1, 13)]

    calidad = calcular_radar_quality(filas)

    assert calidad is not None
    assert calidad.pursuits_con_banda == 12
    assert calidad.pursuits_total == 24
    assert calidad.cobertura_pct == 50.0


def test_una_banda_sin_oportunidades_no_se_inventa_con_ceros() -> None:
    """Descarte sin nada abierto no aparece: no hay nada que decir de ella."""
    calidad = calcular_radar_quality(_doce_cerradas_calientes())

    assert calidad is not None
    assert [b.banda for b in calidad.bandas] == ["Caliente"]


def test_la_ventana_observada_sale_de_las_filas_cuando_no_se_pide_periodo() -> None:
    """La métrica declara la ventana: sin ella, «8/12» no dice de cuándo."""
    calidad = calcular_radar_quality(_doce_cerradas_calientes())

    assert calidad is not None
    assert calidad.ventana_origen == "historico_observado"
    assert calidad.ventana_desde == datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
    assert calidad.ventana_hasta == datetime(2026, 6, 12, 9, 0, tzinfo=UTC)


def test_la_ventana_pedida_manda_sobre_la_observada() -> None:
    """Con periodo explícito, la ventana declarada es la que acotó la consulta."""
    desde = datetime(2026, 1, 1, tzinfo=UTC)
    hasta = datetime(2026, 9, 1, tzinfo=UTC)

    calidad = calcular_radar_quality(
        _doce_cerradas_calientes(),
        period_from=desde,
        period_to=hasta,
    )

    assert calidad is not None
    assert calidad.ventana_origen == "periodo_solicitado"
    assert (calidad.ventana_desde, calidad.ventana_hasta) == (desde, hasta)


def test_una_banda_que_el_scoring_renombre_no_contamina_la_metrica() -> None:
    """El vocabulario lo fija ``_band()``; aquí se ignora lo que no reconoce.

    Sumar una banda desconocida al conteo con banda inflaría la cobertura con
    filas que ninguna fila de la tabla puede explicar.
    """
    filas = _doce_cerradas_calientes()
    filas += [_fila("Ardiente", "won", dia=1)]

    calidad = calcular_radar_quality(filas)

    assert calidad is not None
    assert calidad.pursuits_con_banda == 12
    assert calidad.pursuits_total == 13
    assert [b.banda for b in calidad.bandas] == ["Caliente"]

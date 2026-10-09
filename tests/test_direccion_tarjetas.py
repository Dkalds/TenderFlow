"""F4.2 — las tarjetas del cuadro de mando de dirección.

La regla que fijan estos tests es la de todo el cuadro: **por debajo del
mínimo no hay número**, hay `valor=None` con una `nota` que dice «sin base» y
por qué. Un ciclo de 3 días sobre un único cierre, o una precisión del Radar
del 100 % sobre dos, se toman por ciertos; el hueco se pregunta.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

import services.pursuits as pursuits_mod
from services.direccion import (
    MINIMO_CICLO,
    MINIMO_POR_CORTE,
    CorteDireccion,
    CuadroDireccion,
    TarjetaMetrica,
    Ventana,
    cambios_de_evento,
    construir_cuadro,
    intervalo_wilson,
    ventana_anterior,
)
from services.pursuits import MINIMO_PERDIDAS_POR_MOTIVO, RADAR_QUALITY_MINIMO
from shared.dto import OrganizationSettings

#: «Ahora» fijo: la ventana anterior y los días de las listas dependen de él.
AHORA = datetime(2026, 10, 9, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _sin_lead_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """El valor ponderado consulta el lead-time por órgano para la previsión.

    Aquí sólo interesa el valor, que no depende de él: sin histórico la
    previsión cae a la fecha límite, que es lo que haría un órgano nuevo.
    """
    monkeypatch.setattr(pursuits_mod, "_lead_time_por_organo", lambda _organos: {})


def _cuadro(
    filas: list[dict[str, Any]],
    ajustes: OrganizationSettings | None = None,
    *,
    ventana: Ventana | None = None,
) -> CuadroDireccion:
    return construir_cuadro(
        7, filas, ajustes or OrganizationSettings(), ventana=ventana, ahora=AHORA
    )


def _tarjeta(cuadro: CuadroDireccion, clave: str) -> TarjetaMetrica:
    return next(t for t in cuadro.tarjetas if t.clave == clave)


_IDS = iter(range(1, 10_000))


def _cierre(
    outcome: str,
    *,
    dias: int = 30,
    motivo: str | None = None,
    banda: str | None = None,
    inicio: datetime | None = None,
    importe: float | None = None,
    adjudicado: float | None = None,
    **extra: Any,
) -> dict[str, Any]:
    inicio = inicio or datetime(2026, 1, 1, 9, tzinfo=UTC)
    return {
        "pursuit_id": next(_IDS),
        "licitacion_id": "EXP",
        "titulo": "Soporte",
        "status": outcome,
        "outcome": outcome,
        "identified_at": inicio.isoformat(),
        "closed_at": (inicio + timedelta(days=dias, hours=1)).isoformat(),
        "outcome_reason_code": motivo,
        "banda_al_abrir": banda,
        "tender_importe": importe,
        "awarded_amount_eur": adjudicado,
        **extra,
    }


def _abierta(status: str, importe: float | None) -> dict[str, Any]:
    return {
        "status": status,
        "outcome": "pending",
        "identified_at": "2026-08-01T09:00:00+00:00",
        "tender_importe": importe,
        "tender_deadline": "2026-10-15",
        "tender_organo": "Ayuntamiento",
    }


class TestTarjetasSiempreDeclaradas:
    def test_cuatro_tarjetas_en_orden_con_universo(self) -> None:
        """Lo ganado, el éxito, lo que viene y el tiempo, en ese orden."""
        cuadro = _cuadro([])
        assert [t.clave for t in cuadro.tarjetas] == [
            "importe_adjudicado",
            "tasa_exito",
            "valor_ponderado",
            "ciclo_dias",
        ]
        for tarjeta in cuadro.tarjetas:
            assert tarjeta.universo
            assert tarjeta.unidad in ("eur", "dias", "pct")

    def test_sin_datos_ninguna_publica_numero(self) -> None:
        """Un cuadro vacío no enseña ceros: enseña «sin base»."""
        for tarjeta in _cuadro([]).tarjetas:
            assert tarjeta.valor is None
            assert tarjeta.nota is not None
            assert tarjeta.nota.startswith("Sin base")


class TestValorPonderado:
    def test_pondera_con_las_probabilidades_de_la_organizacion(self) -> None:
        ajustes = OrganizationSettings(probabilidades_etapa={"preparing": 50})
        cuadro = _cuadro([_abierta("preparing", 100_000)], ajustes)
        tarjeta = _tarjeta(cuadro, "valor_ponderado")
        assert tarjeta.valor == 50_000
        assert tarjeta.unidad == "eur"
        assert tarjeta.n == 1
        assert cuadro.probabilidades_etapa_usadas == {"preparing": 50}

    def test_sin_importe_no_cuenta_como_cero_y_se_declara(self) -> None:
        ajustes = OrganizationSettings(probabilidades_etapa={"preparing": 50})
        filas = [_abierta("preparing", 100_000), _abierta("preparing", None)]
        tarjeta = _tarjeta(_cuadro(filas, ajustes), "valor_ponderado")
        assert tarjeta.valor == 50_000
        assert tarjeta.n == 1
        assert tarjeta.nota is not None and "sin importe" in tarjeta.nota

    def test_abiertas_sin_ningun_importe_es_sin_base_no_cero(self) -> None:
        tarjeta = _tarjeta(_cuadro([_abierta("preparing", None)]), "valor_ponderado")
        assert tarjeta.valor is None
        assert tarjeta.nota is not None and tarjeta.nota.startswith("Sin base")

    def test_las_cerradas_no_son_pipeline(self) -> None:
        tarjeta = _tarjeta(_cuadro([_cierre("won")] * 3), "valor_ponderado")
        assert tarjeta.valor is None
        assert tarjeta.n == 0


class TestCiclo:
    def test_por_debajo_del_minimo_no_hay_mediana(self) -> None:
        tarjeta = _tarjeta(_cuadro([_cierre("won", dias=10)] * (MINIMO_CICLO - 1)), "ciclo_dias")
        assert tarjeta.valor is None
        assert tarjeta.n == MINIMO_CICLO - 1
        assert tarjeta.n_minimo == MINIMO_CICLO

    def test_mediana_en_dias_de_ganadas_y_perdidas(self) -> None:
        filas = [_cierre("won", dias=d) for d in (10, 20, 30)] + [
            _cierre("lost", dias=d) for d in (40, 300)
        ]
        tarjeta = _tarjeta(_cuadro(filas), "ciclo_dias")
        assert tarjeta.valor == 30
        assert tarjeta.unidad == "dias"
        assert tarjeta.n == 5

    def test_las_retiradas_no_miden_el_ciclo(self) -> None:
        filas = [_cierre("won", dias=10)] * MINIMO_CICLO + [_cierre("cancelled", dias=200)] * 10
        assert _tarjeta(_cuadro(filas), "ciclo_dias").n == MINIMO_CICLO

    def test_sin_fecha_de_cierre_no_cuenta(self) -> None:
        fila = _cierre("won")
        fila["closed_at"] = None
        assert _tarjeta(_cuadro([fila] * 10), "ciclo_dias").n == 0


class TestPerdidas:
    def test_por_debajo_del_minimo_no_hay_reparto(self) -> None:
        filas = [_cierre("lost", motivo="precio")] * (MINIMO_PERDIDAS_POR_MOTIVO - 1)
        cuadro = _cuadro(filas)
        assert cuadro.perdidas_por_motivo == []
        assert cuadro.perdidas_n_minimo == MINIMO_PERDIDAS_POR_MOTIVO
        assert cuadro.perdidas == MINIMO_PERDIDAS_POR_MOTIVO - 1

    def test_reparto_y_cuantas_no_tienen_motivo(self) -> None:
        """Las pérdidas sin motivo dejan de ser una tarjeta: van con su reparto."""
        filas = [_cierre("lost", motivo="precio") for _ in range(3)] + [
            _cierre("lost", dias=40 + i) for i in range(2)
        ]
        cuadro = _cuadro(filas)
        assert [(p.motivo, p.n) for p in cuadro.perdidas_por_motivo] == [
            ("precio", 3),
            ("sin_codificar", 2),
        ]
        assert (cuadro.perdidas, cuadro.perdidas_sin_motivo) == (5, 2)
        # Las sin motivo se listan para codificarlas, la más reciente primero.
        muestra = cuadro.perdidas_sin_motivo_muestra
        assert len(muestra) == 2
        assert muestra[0].desde is not None and muestra[1].desde is not None
        assert muestra[0].desde > muestra[1].desde
        assert "perdidas_codificadas" not in {t.clave for t in cuadro.tarjetas}


class TestActividadPorRol:
    """F4.5 — el feed es para todos los roles; sólo cambia qué eventos ve cada uno."""

    @staticmethod
    def _preparar(monkeypatch: pytest.MonkeyPatch, rol: str) -> dict[str, Any]:
        import db.repositories.cuentas as cuentas_mod
        import services.direccion as direccion_mod

        llamada: dict[str, Any] = {}

        @contextmanager
        def _alcance(_user_id: int, _organization_id: int | None) -> Iterator[tuple[int, str]]:
            yield 7, rol

        def _feed(_self: Any, organization_id: int, **kwargs: Any) -> list[dict[str, Any]]:
            llamada.update(kwargs, organization_id=organization_id)
            return [
                {
                    "id": 3,
                    "pursuit_id": 1,
                    "licitacion_id": "EXP-1",
                    "titulo": "Soporte SAP",
                    "event_type": "pursuit.created",
                    "actor": "Ana",
                    "created_at": "2026-09-01T10:00:00+00:00",
                }
            ]

        monkeypatch.setattr(direccion_mod, "alcance_resuelto", _alcance)
        monkeypatch.setattr(cuentas_mod.ActividadRepository, "feed", _feed)
        return llamada

    def test_un_member_ve_el_feed_sin_eventos_de_administracion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services.direccion import actividad_de_organizacion

        llamada = self._preparar(monkeypatch, "member")
        feed = actividad_de_organizacion(5, organization_id=7)
        assert [i.evento for i in feed.items] == ["pursuit.created"]
        assert llamada["incluir_admin"] is False
        assert llamada["organization_id"] == 7
        assert feed.filtrado_por_rol is True

    @pytest.mark.parametrize("rol", ["owner", "admin"])
    def test_owner_y_admin_lo_ven_entero(self, monkeypatch: pytest.MonkeyPatch, rol: str) -> None:
        from services.direccion import actividad_de_organizacion

        llamada = self._preparar(monkeypatch, rol)
        feed = actividad_de_organizacion(5, organization_id=7)
        assert llamada["incluir_admin"] is True
        assert feed.filtrado_por_rol is False


class TestRadar:
    def test_sin_banda_sellada_no_hay_medida(self) -> None:
        cuadro = _cuadro([_cierre("won")] * 20)
        assert cuadro.radar_quality is None
        assert cuadro.radar_ordena_bien is None
        # La precisión del Radar ya no es tarjeta: repetía el panel por banda.
        assert "precision_radar" not in {t.clave for t in cuadro.tarjetas}

    def test_escalera_que_baja_ordena_bien(self) -> None:
        filas = [_cierre("won", banda="Caliente")] * 6 + [_cierre("lost", banda="Caliente")] * 4
        filas += [_cierre("won", banda="Tibia")] * 2 + [_cierre("lost", banda="Tibia")] * 8
        assert _cuadro(filas).radar_ordena_bien is True

    def test_escalera_invertida_no_ordena(self) -> None:
        filas = [_cierre("won", banda="Caliente")] * 2 + [_cierre("lost", banda="Caliente")] * 8
        filas += [_cierre("won", banda="Tibia")] * 6 + [_cierre("lost", banda="Tibia")] * 4
        assert _cuadro(filas).radar_ordena_bien is False

    def test_una_sola_banda_con_base_no_es_escalera(self) -> None:
        filas = [_cierre("won", banda="Caliente")] * RADAR_QUALITY_MINIMO
        filas += [_cierre("lost", banda="Tibia")] * (RADAR_QUALITY_MINIMO - 1)
        assert _cuadro(filas).radar_ordena_bien is None


class TestVentana:
    """La ventana de Dirección es de **cierres**: un resultado es del periodo en que se cerró."""

    def test_cuenta_por_fecha_de_cierre_no_de_alta(self) -> None:
        # Identificada hace dos años, cerrada dentro de la ventana: cuenta.
        vieja = _cierre("won", inicio=datetime(2024, 9, 1, tzinfo=UTC), dias=760)
        # Identificada dentro de la ventana pero cerrada antes de su inicio: no.
        fuera = _cierre("won", inicio=datetime(2025, 1, 1, tzinfo=UTC), dias=10)
        ventana = Ventana(datetime(2025, 10, 9, tzinfo=UTC), None)
        cuadro = _cuadro([vieja, fuera], ventana=ventana)
        assert cuadro.cierres == 1
        assert cuadro.cierres_historico == 2

    def test_sin_fecha_de_cierre_solo_cuenta_en_el_historico(self) -> None:
        fila = _cierre("won")
        fila["closed_at"] = None
        assert _cuadro([fila]).cierres == 1
        assert _cuadro([fila], ventana=Ventana(datetime(2026, 1, 1, tzinfo=UTC))).cierres == 0

    def test_la_anterior_es_el_mismo_periodo_de_hace_un_anio(self) -> None:
        """«Este año» se compara con enero-octubre del año pasado, no con el final del año."""
        anterior = ventana_anterior(Ventana(datetime(2026, 1, 1, tzinfo=UTC)), AHORA)
        assert anterior == Ventana(datetime(2025, 1, 1, tzinfo=UTC), AHORA.replace(year=2025))

    def test_una_ventana_de_mas_de_un_anio_se_compara_con_la_contigua(self) -> None:
        desde = datetime(2023, 10, 9, tzinfo=UTC)
        anterior = ventana_anterior(Ventana(desde, AHORA), AHORA)
        assert anterior is not None
        assert anterior.hasta == desde
        assert anterior.desde == desde - (AHORA - desde)

    def test_el_historico_no_tiene_anterior(self) -> None:
        assert ventana_anterior(Ventana(), AHORA) is None
        cuadro = _cuadro([_cierre("won")] * 6)
        assert cuadro.anterior_desde is None
        assert all(t.n_anterior is None and t.delta is None for t in cuadro.tarjetas)

    def test_una_ventana_del_anio_1_no_tiene_anterior(self) -> None:
        """Un ``period_from`` extremo no revienta: se publica sin comparación."""
        assert ventana_anterior(Ventana(datetime(1, 1, 1, tzinfo=UTC)), AHORA) is None

    def test_29_de_febrero_cae_en_el_28(self) -> None:
        bisiesto = datetime(2028, 2, 29, tzinfo=UTC)
        anterior = ventana_anterior(Ventana(bisiesto, datetime(2028, 6, 1, tzinfo=UTC)), AHORA)
        assert anterior is not None and anterior.desde == datetime(2027, 2, 28, tzinfo=UTC)


class TestComparacion:
    @staticmethod
    def _filas() -> list[dict[str, Any]]:
        este = datetime(2026, 3, 1, tzinfo=UTC)
        pasado = datetime(2025, 3, 1, tzinfo=UTC)
        # Este año: 4 de 5 ganadas. El mismo periodo del año pasado: 1 de 5.
        return [
            *(_cierre("won", inicio=este, dias=20, adjudicado=100_000) for _ in range(4)),
            _cierre("lost", inicio=este, dias=40),
            _cierre("won", inicio=pasado, dias=30, adjudicado=50_000),
            *(_cierre("lost", inicio=pasado, dias=60) for _ in range(4)),
        ]

    def test_cada_tarjeta_trae_el_anterior_y_la_diferencia(self) -> None:
        cuadro = _cuadro(self._filas(), ventana=Ventana(datetime(2026, 1, 1, tzinfo=UTC)))
        tasa = _tarjeta(cuadro, "tasa_exito")
        assert tasa.valor == pytest.approx(0.8)
        assert tasa.anterior == pytest.approx(0.2)
        assert tasa.delta == pytest.approx(0.6)
        assert tasa.n_anterior == 5
        importe = _tarjeta(cuadro, "importe_adjudicado")
        assert (importe.valor, importe.anterior, importe.delta) == (400_000, 50_000, 350_000)
        assert cuadro.anterior_desde == datetime(2025, 1, 1, tzinfo=UTC)

    def test_el_ciclo_mejora_bajando(self) -> None:
        cuadro = _cuadro(self._filas(), ventana=Ventana(datetime(2026, 1, 1, tzinfo=UTC)))
        ciclo = _tarjeta(cuadro, "ciclo_dias")
        assert ciclo.mejor_si == "baja"
        assert ciclo.delta is not None and ciclo.delta < 0

    def test_sin_base_en_el_anterior_no_hay_diferencia(self) -> None:
        este = datetime(2026, 3, 1, tzinfo=UTC)
        filas = [_cierre("won", inicio=este) for _ in range(5)]
        filas.append(_cierre("lost", inicio=datetime(2025, 3, 1, tzinfo=UTC)))
        tasa = _tarjeta(
            _cuadro(filas, ventana=Ventana(datetime(2026, 1, 1, tzinfo=UTC))), "tasa_exito"
        )
        assert tasa.valor == 1.0
        assert tasa.anterior is None
        assert tasa.n_anterior == 1
        assert tasa.delta is None

    def test_el_pipeline_es_una_foto_y_no_se_compara(self) -> None:
        ajustes = OrganizationSettings(probabilidades_etapa={"preparing": 50})
        cuadro = _cuadro(
            [_abierta("preparing", 100_000)],
            ajustes,
            ventana=Ventana(datetime(2026, 1, 1, tzinfo=UTC)),
        )
        tarjeta = _tarjeta(cuadro, "valor_ponderado")
        assert tarjeta.depende_del_periodo is False
        assert tarjeta.n_anterior is None and tarjeta.delta is None
        assert cuadro.prevision_trimestral  # la previsión viaja con la cifra
        assert cuadro.probabilidades_etapa_usadas == {"preparing": 50}


class TestImporteYTasa:
    def test_ganada_sin_importe_no_cuenta_como_cero(self) -> None:
        filas = [_cierre("won", adjudicado=100_000), _cierre("won", adjudicado=None)]
        importe = _tarjeta(_cuadro(filas), "importe_adjudicado")
        assert importe.valor == 100_000
        assert importe.n == 1
        assert importe.nota is not None and "sin importe" in importe.nota

    def test_la_tasa_no_se_publica_por_debajo_del_minimo(self) -> None:
        filas = [_cierre("won")] * (MINIMO_POR_CORTE - 1)
        tasa = _tarjeta(_cuadro(filas), "tasa_exito")
        assert tasa.valor is None
        assert tasa.nota is not None and tasa.nota.startswith("Sin base")

    def test_las_retiradas_no_son_un_resultado(self) -> None:
        filas = [_cierre("won")] * 5 + [_cierre("cancelled")] * 5
        assert _tarjeta(_cuadro(filas), "tasa_exito").valor == 1.0


class TestIntervalo:
    def test_wilson_con_cinco_cierres(self) -> None:
        """Con cinco cierres, un 60 % cabe entre un 23 % y un 88 %."""
        bajo, alto = intervalo_wilson(3, 5)
        assert bajo == pytest.approx(0.231, abs=1e-3)
        assert alto == pytest.approx(0.882, abs=1e-3)

    def test_wilson_no_colapsa_en_los_extremos(self) -> None:
        bajo, alto = intervalo_wilson(5, 5)
        assert alto == 1.0
        assert 0 < bajo < 1


def _corte(cuadro: CuadroDireccion, clave: str) -> CorteDireccion:
    return next(c for c in cuadro.cortes if c.clave == clave)


class TestCortes:
    def test_cuatro_cortes_en_orden(self) -> None:
        assert [c.clave for c in _cuadro([]).cortes] == [
            "tecnologia",
            "tramo_importe",
            "procedimiento",
            "organo",
        ]

    def test_los_campos_anteriores_siguen_en_la_respuesta(self) -> None:
        """Quitar `win_rate_por_*` rompería el contrato: siguen, ya en la ventana."""
        filas = [_cierre("won", tender_tecnologia="SAP", tender_organo="Madrid") for _ in range(5)]
        filas.append(
            _cierre(
                "lost",
                inicio=datetime(2020, 1, 1, tzinfo=UTC),
                tender_tecnologia="SAP",
                tender_organo="Madrid",
            )
        )
        cuadro = _cuadro(filas, ventana=Ventana(datetime(2025, 10, 9, tzinfo=UTC)))
        assert [(c.clave, c.n, c.valor) for c in cuadro.win_rate_por_tecnologia] == [
            ("SAP", 5, 1.0)
        ]
        assert [(c.clave, c.n) for c in cuadro.win_rate_por_organo] == [("Madrid", 5)]

    def test_las_filas_sin_base_van_aparte_con_sus_cierres(self) -> None:
        filas = [_cierre("won", tender_organo="Madrid") for _ in range(5)]
        filas += [_cierre("lost", tender_organo=f"Órgano {i}") for i in range(3)]
        organo = _corte(_cuadro(filas), "organo")
        assert [c.clave for c in organo.filas] == ["Madrid"]
        assert len(organo.filas_sin_base) == 3
        assert organo.cierres_sin_base == 3
        assert all(c.valor is None and c.intervalo_bajo is None for c in organo.filas_sin_base)

    def test_posicion_solo_cuando_el_intervalo_queda_a_un_lado(self) -> None:
        # SAP: 10/10 ganadas; ORACLE: 0/10. Media de la organización: 50 %.
        filas = [_cierre("won", tender_tecnologia="SAP") for _ in range(10)]
        filas += [_cierre("lost", tender_tecnologia="ORACLE") for _ in range(10)]
        # Y una con base pero indistinguible de la media.
        filas += [_cierre("won", tender_tecnologia="CRM") for _ in range(3)]
        filas += [_cierre("lost", tender_tecnologia="CRM") for _ in range(3)]
        tecnologia = _corte(_cuadro(filas), "tecnologia")
        posiciones = {c.clave: c.posicion for c in tecnologia.filas}
        assert posiciones == {"SAP": "por_encima", "ORACLE": "por_debajo", "CRM": "en_linea"}
        assert tecnologia.media == pytest.approx(0.5)

    def test_sin_media_publicada_no_hay_posicion(self) -> None:
        filas = [_cierre("won", tender_tecnologia="SAP") for _ in range(5)]
        tecnologia = _corte(_cuadro(filas), "tecnologia")
        assert tecnologia.media == 1.0  # cinco cierres: la tasa global ya se publica
        sin_media = _corte(_cuadro(filas[:4]), "tecnologia")
        assert sin_media.media is None
        assert all(c.posicion is None for c in sin_media.filas + sin_media.filas_sin_base)

    def test_tramos_de_importe_en_su_orden_y_con_etiqueta(self) -> None:
        filas = [_cierre("won", importe=2_000_000) for _ in range(5)]
        filas += [_cierre("lost", importe=50_000) for _ in range(5)]
        filas += [_cierre("lost", importe=None) for _ in range(5)]
        tramo = _corte(_cuadro(filas), "tramo_importe")
        assert [c.clave for c in tramo.filas] == ["hasta_100k", "desde_1m", "sin_importe"]
        assert tramo.filas[0].etiqueta == "Menos de 100.000 €"

    def test_el_procedimiento_se_agrupa_por_su_etiqueta(self) -> None:
        """La fuente publica ``01`` y ``1`` para el mismo procedimiento."""
        filas = [_cierre("won", tender_procedimiento="1") for _ in range(3)]
        filas += [_cierre("lost", tender_procedimiento="01") for _ in range(2)]
        procedimiento = _corte(_cuadro(filas), "procedimiento")
        assert len(procedimiento.filas) == 1
        assert procedimiento.filas[0].n == 5


class TestPendientesDeResultado:
    def test_presentadas_sin_resultado_de_la_mas_antigua_a_la_mas_reciente(self) -> None:
        filas = [
            {
                "pursuit_id": 10 + i,
                "licitacion_id": f"EXP-{i}",
                "titulo": f"Oferta {i}",
                "status": "submitted",
                "outcome": "pending",
                "submitted_at": f"2026-0{i + 1}-15T10:00:00+00:00",
            }
            for i in range(3)
        ]
        cuadro = _cuadro(filas)
        assert cuadro.pendientes_resultado == 3
        primera = cuadro.pendientes_resultado_muestra[0]
        assert (primera.pursuit_id, primera.desde) == (10, "2026-01-15")
        assert primera.dias == (AHORA.date() - datetime(2026, 1, 15).date()).days

    def test_la_muestra_tiene_techo_y_el_recuento_no(self) -> None:
        filas = [
            {"pursuit_id": i + 1, "licitacion_id": "E", "status": "submitted", "outcome": None}
            for i in range(20)
        ]
        cuadro = _cuadro(filas)
        assert cuadro.pendientes_resultado == 20
        assert len(cuadro.pendientes_resultado_muestra) < 20


class TestCambiosDeEvento:
    def test_publica_solo_los_campos_enumerados(self) -> None:
        payload = (
            '{"changes": {"status": {"from": "preparing", "to": "submitted"},'
            ' "outcome_reason": {"from": null, "to": "texto libre"},'
            ' "offer_price_eur": {"from": 1, "to": 2}}}'
        )
        cambios = cambios_de_evento(payload)
        assert [(c.campo, c.desde, c.hasta) for c in cambios] == [
            ("status", "preparing", "submitted")
        ]

    def test_un_payload_ilegible_no_rompe_el_feed(self) -> None:
        assert cambios_de_evento("{no es json") == []
        assert cambios_de_evento(None) == []
        assert cambios_de_evento('{"changes": []}') == []

    def test_un_cambio_que_no_cambia_nada_no_se_publica(self) -> None:
        assert cambios_de_evento('{"changes": {"status": {"from": "won", "to": "won"}}}') == []

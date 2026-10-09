"""Unit tests de la agenda de Mi Pipeline (``services.pursuits.get_agenda``).

Las bandas de urgencia, el orden y la fusión son el contrato que el frontend
renderiza sin recalcular (ADR-014): si esto se mueve, la agenda entera miente.
Todo es puro o mockeado — sin Postgres.

Desde la reestructura de «Mi Pipeline» la agenda fusiona cinco ``kind`` y cada
fila lleva **una** fecha que dice de qué clase es (``due_kind``). Lo que se fija
aquí, sobre todo, es que cada compromiso conserve su reloj: el plazo de
presentación de un pursuit, el vencimiento de una tarea y la ventana de
relicitación de un contrato propio son tres cosas distintas, y antes las dos
primeras se aplastaban en un mismo ``due_date`` del que nadie sabía cuál era.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

import services.pursuits as sp
from services.cartera import ContratoCartera
from services.watchlist_rules import WatchlistRule
from tests.dobles_tenencia import alcance_fijo

# ── Bandas de urgencia ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("dias", "banda"),
    [
        (None, "sin_fecha"),
        (-30, "vencida"),
        (-1, "vencida"),
        (0, "hoy"),
        (1, "semana"),
        (7, "semana"),
        (8, "mes"),
        (30, "mes"),
        (31, "despues"),
        (365, "despues"),
    ],
)
def test_urgencia_bandas(dias: int | None, banda: str) -> None:
    assert sp._urgencia(dias) == banda


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("2026-08-20", date(2026, 8, 20)),
        ("2026-08-20T14:00:00+00:00", date(2026, 8, 20)),
        ("2026-08-20 14:00:00.123+00", date(2026, 8, 20)),
        (date(2026, 8, 20), date(2026, 8, 20)),
        (datetime(2026, 8, 20, 14, 0, tzinfo=UTC), date(2026, 8, 20)),
        ("garbage", None),
        ("", None),
        (None, None),
        (42, None),
    ],
)
def test_parse_iso_date(valor: object, esperado: date | None) -> None:
    assert sp._parse_iso_date(valor) == esperado


# ── Construcción de items ───────────────────────────────────────────────────


def _pursuit_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "pursuit_id": 11,
        "licitacion_id": "EXP-1",
        "titulo": "Mantenimiento S/4",
        "tender_deadline": None,
        "importe_eur": 100_000.0,
        "organo": "Junta",
        "ccaa": "Andalucía",
        "tecnologia": "SAP",
        "url": "https://example.org",
        "responsible_user_id": 3,
        "responsible_name": "Dana",
        "status": "preparing",
        "decision": "go",
        "next_action": None,
        "next_action_due": None,
        "version": 2,
    }
    row.update(overrides)
    return row


def _tarea_row(**overrides: Any) -> dict[str, Any]:
    """Fila de ``PursuitTasksRepository.agenda_rows``: la tarea **y** su pursuit."""
    row = _pursuit_row()
    row.update(
        {
            "tarea_id": 41,
            "tarea_texto": "Pedir el certificado de solvencia",
            "tarea_vence": None,
            "tarea_estado": "pendiente",
            "tarea_responsable_user_id": 3,
        }
    )
    row.update(overrides)
    return row


def _contrato(**overrides: Any) -> ContratoCartera:
    campos: dict[str, Any] = {
        "id": 77,
        "organization_id": 7,
        "pursuit_id": 11,
        "licitacion_id": "CTR-1",
        "titulo": "Soporte S/4 2024-2027",
        "organo_contratacion": "Junta",
        "tecnologia": "SAP",
        "ccaa": "Andalucía",
        "url": "https://example.org/ctr-1",
        "importe_adjudicado": 480_000.0,
        "fecha_fin_efectiva": "2027-03-31",
        "fecha_fin_origen": "publicada",
        "prorrogas_aplicadas": 1,
        "relicitacion_desde": "2026-09-30",
        "relicitacion_hasta": "2026-12-31",
    }
    campos.update(overrides)
    return ContratoCartera(**campos)


class TestItemPursuit:
    """Un pursuit vale por su plazo externo, y por nada más."""

    def test_due_date_es_solo_el_plazo_de_presentacion(self) -> None:
        """Antes era el mínimo con ``next_action_due``, y eso mentía.

        Con las dos fechas aplastadas en una, la fila decía «vence en 2 días»
        sin distinguir si lo que vencía era la licitación o una nota que el
        propio usuario se había puesto. La acción ahora tiene su fila ``tarea``.
        """
        item = sp._pursuit_item(
            _pursuit_row(tender_deadline="2026-08-30T00:00:00+00:00", next_action_due="2026-08-15"),
            date(2026, 8, 13),
        )
        assert (item.due_date, item.due_kind) == (date(2026, 8, 30), "plazo")
        assert item.dias_restantes == 17
        assert item.urgencia == "mes"
        # El dato sigue viajando: es informativo, no es la fecha del compromiso.
        assert item.next_action_due == date(2026, 8, 15)

    def test_sin_plazo_va_a_sin_fecha_aunque_haya_accion_pendiente(self) -> None:
        item = sp._pursuit_item(
            _pursuit_row(next_action="Llamar al órgano", next_action_due="2026-08-15"),
            date(2026, 8, 13),
        )
        assert (item.due_date, item.dias_restantes) == (None, None)
        assert item.urgencia == "sin_fecha"
        assert item.due_kind == "plazo"

    def test_los_campos_de_la_oportunidad_viajan_enteros(self) -> None:
        item = sp._pursuit_item(_pursuit_row(tender_deadline="2026-08-14"), date(2026, 8, 13))
        assert (item.pursuit_id, item.version, item.status) == (11, 2, "preparing")
        assert (item.responsible_user_id, item.responsible_name) == (3, "Dana")
        assert (item.tarea_id, item.tarea_texto, item.cartera_id) == (None, None, None)


class TestItemTarea:
    """Cada acción interna es su propio compromiso, con su propio vencimiento."""

    def test_hereda_la_oportunidad_y_lleva_su_vencimiento(self) -> None:
        item = sp._tarea_item(
            _tarea_row(),
            date(2026, 8, 13),
            tarea_id=41,
            tarea_texto="Pedir el certificado de solvencia",
            vence="2026-08-14",
        )
        assert item.kind == "tarea"
        assert (item.due_date, item.due_kind, item.dias_restantes) == (
            date(2026, 8, 14),
            "accion",
            1,
        )
        assert item.urgencia == "semana"
        assert (item.tarea_id, item.tarea_texto) == (41, "Pedir el certificado de solvencia")
        # La oportunidad a la que pertenece, para que la fila enlace a su ficha.
        assert (item.pursuit_id, item.licitacion_id, item.version) == (11, "EXP-1", 2)

    def test_sin_vencimiento_es_sin_fecha_y_no_hoy(self) -> None:
        """Una tarea sin fecha no es más urgente que una que vence mañana."""
        item = sp._tarea_item(
            _tarea_row(), date(2026, 8, 13), tarea_id=41, tarea_texto="Algo", vence=None
        )
        assert (item.due_date, item.dias_restantes, item.urgencia) == (None, None, "sin_fecha")
        assert item.due_kind == "accion"


class TestFusionDeTareas:
    HOY = date(2026, 8, 13)

    def test_una_fila_por_tarea_abierta(self) -> None:
        items = sp._agenda_tareas(
            [],
            [
                _tarea_row(tarea_id=41, tarea_vence="2026-08-14"),
                _tarea_row(tarea_id=42, tarea_texto="Maquetar oferta", tarea_vence="2026-08-20"),
            ],
            self.HOY,
        )
        assert [i.tarea_id for i in items] == [41, 42]
        assert [i.due_date for i in items] == [date(2026, 8, 14), date(2026, 8, 20)]

    def test_la_next_action_manual_de_un_pursuit_sin_tareas_emite_una_sin_id(self) -> None:
        """Existe como compromiso, pero no hay fila de ``pursuit_tasks`` que editar."""
        items = sp._agenda_tareas(
            [_pursuit_row(next_action="Confirmar visita", next_action_due="2026-08-15")],
            [],
            self.HOY,
        )
        assert len(items) == 1
        assert items[0].tarea_id is None
        assert items[0].tarea_texto == "Confirmar visita"
        assert (items[0].due_date, items[0].due_kind) == (date(2026, 8, 15), "accion")

    def test_un_pursuit_con_tareas_no_repite_su_next_action(self) -> None:
        """``next_action`` se deriva de la tarea más urgente (C6.1): repetirla
        contaría dos veces el mismo compromiso."""
        items = sp._agenda_tareas(
            [_pursuit_row(next_action="Pedir el certificado de solvencia")],
            [_tarea_row(tarea_vence="2026-08-14")],
            self.HOY,
        )
        assert [i.tarea_id for i in items] == [41]

    def test_un_pursuit_sin_next_action_y_sin_tareas_no_emite_nada(self) -> None:
        assert sp._agenda_tareas([_pursuit_row()], [], self.HOY) == []

    def test_la_tarea_de_otro_pursuit_no_tapa_la_next_action_del_primero(self) -> None:
        """El cruce es por ``pursuit_id``, no «hay alguna tarea en la agenda»."""
        items = sp._agenda_tareas(
            [_pursuit_row(pursuit_id=11, next_action="Confirmar visita")],
            [_tarea_row(pursuit_id=12, licitacion_id="EXP-2")],
            self.HOY,
        )
        assert sorted((i.pursuit_id, i.tarea_id) for i in items) == [(11, None), (12, 41)]


class TestItemContrato:
    """La fecha de un contrato propio es la que obliga a moverse."""

    HOY = date(2026, 8, 13)

    def test_con_ventana_y_sin_renovacion_la_fecha_es_el_inicio_de_la_ventana(self) -> None:
        item = sp._contrato_item(_contrato(), self.HOY)
        assert item.kind == "contrato"
        assert (item.due_date, item.due_kind) == (date(2026, 9, 30), "relicitacion")
        assert item.dias_restantes == 48
        assert item.urgencia == "despues"

    def test_con_la_renovacion_ya_preparada_la_fecha_pasa_a_ser_el_fin(self) -> None:
        """Ya hay oportunidad abierta: lo que queda por vigilar es el fin."""
        item = sp._contrato_item(_contrato(renovacion_pursuit_id=99), self.HOY)
        assert (item.due_date, item.due_kind) == (date(2027, 3, 31), "fin_contrato")
        assert item.renovacion_pursuit_id == 99

    def test_sin_ventana_pero_con_fin_la_fecha_es_el_fin(self) -> None:
        item = sp._contrato_item(
            _contrato(relicitacion_desde=None, relicitacion_hasta=None), self.HOY
        )
        assert (item.due_date, item.due_kind) == (date(2027, 3, 31), "fin_contrato")

    def test_sin_fecha_de_fin_no_se_inventa_ninguna(self) -> None:
        """La cartera no inventa fecha de fin y la agenda tampoco."""
        item = sp._contrato_item(
            _contrato(
                fecha_fin_efectiva=None,
                fecha_fin_origen=None,
                relicitacion_desde=None,
                relicitacion_hasta=None,
            ),
            self.HOY,
        )
        assert (item.due_date, item.dias_restantes, item.urgencia) == (None, None, "sin_fecha")
        assert item.due_kind == "fin_contrato"

    def test_lleva_los_campos_del_contrato_y_deja_vacios_los_del_pursuit_abierto(self) -> None:
        """``pursuit_id`` enlaza a la oportunidad ganada de origen, no a una abierta."""
        item = sp._contrato_item(_contrato(), self.HOY)
        assert (item.cartera_id, item.pursuit_id) == (77, 11)
        assert item.fecha_fin_efectiva == date(2027, 3, 31)
        assert (item.relicitacion_desde, item.relicitacion_hasta) == (
            date(2026, 9, 30),
            date(2026, 12, 31),
        )
        assert (item.prorrogas_aplicadas, item.fecha_fin_origen) == (1, "publicada")
        # Importe adjudicado, no presupuesto de licitación.
        assert item.importe_eur == 480_000.0
        assert (item.status, item.decision, item.next_action, item.version) == (
            None,
            None,
            None,
            None,
        )
        assert (item.organo, item.ccaa, item.url) == (
            "Junta",
            "Andalucía",
            "https://example.org/ctr-1",
        )


class TestAmbitoDeLosContratos:
    """El ámbito se aplica en Python, con el mismo criterio que el SQL."""

    HOY = date(2026, 8, 13)

    def _ids(self, contratos: list[ContratoCartera], **ambito: Any) -> list[str]:
        ambito.setdefault("tecnologias", [])
        ambito.setdefault("ccaas", [])
        return [i.licitacion_id for i in sp._agenda_contratos(contratos, self.HOY, **ambito)]

    def test_sin_ambito_entran_todos(self) -> None:
        assert self._ids([_contrato(), _contrato(licitacion_id="CTR-2", tecnologia="Oracle")]) == [
            "CTR-1",
            "CTR-2",
        ]

    def test_la_tecnologia_se_busca_en_el_csv_de_la_fila(self) -> None:
        """Un expediente multi-tecnología cuenta para las dos, como en SQL."""
        contratos = [
            _contrato(tecnologia="SAP,Oracle"),
            _contrato(licitacion_id="CTR-2", tecnologia="Salesforce"),
        ]
        assert self._ids(contratos, tecnologias=["Oracle"]) == ["CTR-1"]
        assert self._ids(contratos, tecnologias=["SAP", "Salesforce"]) == ["CTR-1", "CTR-2"]

    def test_varias_ccaa_son_un_or(self) -> None:
        contratos = [
            _contrato(ccaa="Andalucía"),
            _contrato(licitacion_id="CTR-2", ccaa="Galicia"),
            _contrato(licitacion_id="CTR-3", ccaa="Madrid"),
        ]
        assert self._ids(contratos, ccaas=["Galicia", "Madrid"]) == ["CTR-2", "CTR-3"]

    def test_las_dos_dimensiones_se_cruzan(self) -> None:
        contratos = [
            _contrato(ccaa="Galicia", tecnologia="SAP"),
            _contrato(licitacion_id="CTR-2", ccaa="Galicia", tecnologia="Oracle"),
        ]
        assert self._ids(contratos, tecnologias=["SAP"], ccaas=["Galicia"]) == ["CTR-1"]

    def test_un_contrato_sin_el_dato_no_se_esconde(self) -> None:
        """No saber la CCAA de un contrato propio no es motivo para ocultar que vence.

        Es la diferencia deliberada con pursuits y señales, donde el ``WHERE``
        de SQL sí deja fuera la fila sin el dato: aquel universo es el mercado
        y éste es lo que la organización ya tiene firmado.
        """
        contratos = [_contrato(ccaa=None, tecnologia=None)]
        assert self._ids(contratos, tecnologias=["SAP"], ccaas=["Galicia"]) == ["CTR-1"]

    def test_un_contrato_que_ya_termino_no_es_un_compromiso(self) -> None:
        """Vivo aquí es lo mismo que en ``resumen_cartera``: fin sin pasar.

        ``listar_cartera`` no filtra por fecha —nadie borra un contrato
        terminado— así que sin este corte uno que acabó hace años entraría con
        la ventana de relicitación abierta desde entonces: banda ``vencida``,
        miles de días de retraso y, por el orden de la agenda, por encima de
        todo lo que sí exige acción hoy. Contaría además en
        ``relicitaciones_abiertas``, que es el KPI que mide lo que se está
        dejando pasar.
        """
        terminado = _contrato(
            licitacion_id="CTR-VIEJO",
            fecha_fin_efectiva="2019-12-31",
            relicitacion_desde="2019-06-30",
            relicitacion_hasta="2019-09-30",
        )
        items = sp._agenda_contratos([_contrato(), terminado], self.HOY, tecnologias=[], ccaas=[])
        assert [item.licitacion_id for item in items] == ["CTR-1"]
        assert sp._agenda_kpis(items).relicitaciones_abiertas == 0

    def test_el_contrato_sin_fecha_de_fin_sigue_estando(self) -> None:
        """Sin fecha de fin no se puede afirmar que terminó, así que se queda.

        Es el mismo criterio del resumen: la cartera no inventa una fecha y el
        corte de vivos tampoco descarta por no tenerla.
        """
        sin_fin = _contrato(
            licitacion_id="CTR-SIN-FIN",
            fecha_fin_efectiva=None,
            relicitacion_desde=None,
            relicitacion_hasta=None,
        )
        items = sp._agenda_contratos([sin_fin], self.HOY, tecnologias=[], ccaas=[])
        assert [item.licitacion_id for item in items] == ["CTR-SIN-FIN"]
        assert items[0].urgencia == "sin_fecha"

    def test_el_contrato_que_vence_hoy_todavia_cuenta(self) -> None:
        """El corte es `fin < hoy`: el último día el contrato sigue vivo."""
        hoy_mismo = _contrato(
            licitacion_id="CTR-HOY",
            fecha_fin_efectiva=self.HOY.isoformat(),
            relicitacion_desde=None,
            relicitacion_hasta=None,
        )
        items = sp._agenda_contratos([hoy_mismo], self.HOY, tecnologias=[], ccaas=[])
        assert [item.licitacion_id for item in items] == ["CTR-HOY"]
        assert items[0].due_kind == "fin_contrato"
        assert items[0].dias_restantes == 0


# ── El ámbito que comparten las tres consultas ──────────────────────────────


class TestAmbitoSql:
    """``ambito_agenda_sql`` es el mismo filtro para pursuits, tareas y señales.

    Vive en un sitio justamente para que no diverja: si una consulta explotara
    el CSV de tecnologías y otra comparara por igualdad, el mismo ámbito daría
    universos distintos según el ``kind`` y los KPIs no cuadrarían con la lista.
    """

    def _sql(self, **ambito: Any) -> tuple[list[str], list[str]]:
        from db.repositories.base import ambito_agenda_sql

        ambito.setdefault("tecnologias", None)
        ambito.setdefault("ccaas", None)
        return ambito_agenda_sql("l", **ambito)

    def test_sin_ambito_no_se_anade_clausula(self) -> None:
        assert self._sql() == ([], [])
        assert self._sql(tecnologias=[], ccaas=[]) == ([], [])

    def test_los_valores_vacios_no_cuentan(self) -> None:
        """Un ``,,`` de más no puede convertirse en un filtro por cadena vacía."""
        assert self._sql(tecnologias=["", "  "], ccaas=[""]) == ([], [])

    def test_la_tecnologia_se_busca_en_el_csv_y_nunca_por_igualdad(self) -> None:
        """La igualdad dejaba fuera los expedientes multi-tecnología."""
        clauses, params = self._sql(tecnologias=["SAP"])
        assert params == ["SAP"]
        assert "l.tecnologia = " not in clauses[0]
        assert "string_to_array" in clauses[0]

    def test_varias_tecnologias_son_un_or_con_un_marcador_por_valor(self) -> None:
        clauses, params = self._sql(tecnologias=["SAP", "Oracle"])
        assert params == ["SAP", "Oracle"]
        assert clauses[0].count("%s") == 2

    def test_una_sola_ccaa_conserva_la_igualdad(self) -> None:
        """Para no cambiarle el plan a las consultas que ya existían."""
        assert self._sql(ccaas=["Galicia"]) == (["l.ccaa = %s"], ["Galicia"])

    def test_varias_ccaa_son_un_in(self) -> None:
        clauses, params = self._sql(ccaas=["Galicia", "Madrid"])
        assert clauses == ["l.ccaa IN (%s, %s)"]
        assert params == ["Galicia", "Madrid"]

    def test_los_valores_no_se_interpolan_nunca_en_el_sql(self) -> None:
        """Se interpolan marcadores; el valor viaja siempre por ``params``."""
        clauses, params = self._sql(tecnologias=["SAP'; DROP TABLE x--"], ccaas=["A", "B'--"])
        assert all("DROP TABLE" not in c for c in clauses)
        assert all("B'--" not in c for c in clauses)
        assert params == ["SAP'; DROP TABLE x--", "A", "B'--"]

    def test_el_alias_se_respeta(self) -> None:
        from db.repositories.base import ambito_agenda_sql

        clauses, _params = ambito_agenda_sql("lic", tecnologias=["SAP"], ccaas=["Galicia"])
        assert "lic.tecnologia" in clauses[0]
        assert clauses[1] == "lic.ccaa = %s"


# ── Orden ───────────────────────────────────────────────────────────────────


def _item(kind: str, *, dias: int | None, licitacion_id: str) -> Any:
    """Un item mínimo, sólo con lo que mira :func:`sp._agenda_orden`."""
    return sp.PipelineAgendaItem.model_validate(
        {
            "kind": kind,
            "urgencia": sp._urgencia(dias),
            "due_date": None,
            "dias_restantes": dias,
            "licitacion_id": licitacion_id,
            "titulo": None,
            "organo": None,
            "importe_eur": None,
            "ccaa": None,
            "tecnologia": None,
            "url": None,
            "pursuit_id": None,
            "status": None,
            "decision": None,
            "responsible_user_id": None,
            "responsible_name": None,
            "next_action": None,
            "next_action_due": None,
            "version": None,
            "rule_id": None,
            "rule_nombre": None,
            "adjudicatario": None,
            "riesgo_cambio": None,
        }
    )


class TestOrden:
    def test_sin_fecha_al_final_aunque_todo_lo_demas_este_vencido(self) -> None:
        items = [
            _item("pursuit", dias=None, licitacion_id="A"),
            _item("pursuit", dias=-30, licitacion_id="B"),
            _item("pursuit", dias=5, licitacion_id="C"),
        ]
        assert [i.licitacion_id for i in sorted(items, key=sp._agenda_orden)] == ["B", "C", "A"]

    def test_a_igual_dia_manda_la_clase_de_compromiso(self) -> None:
        """Primero el plazo externo, después lo que hay que hacer, después lo
        propio que vence y al final lo que todavía no es compromiso."""
        items = [
            _item("renovacion", dias=3, licitacion_id="A"),
            _item("senal", dias=3, licitacion_id="A"),
            _item("contrato", dias=3, licitacion_id="A"),
            _item("tarea", dias=3, licitacion_id="A"),
            _item("pursuit", dias=3, licitacion_id="A"),
        ]
        assert [i.kind for i in sorted(items, key=sp._agenda_orden)] == [
            "pursuit",
            "tarea",
            "contrato",
            "senal",
            "renovacion",
        ]

    def test_a_igual_dia_y_clase_desempata_el_expediente(self) -> None:
        items = [
            _item("tarea", dias=2, licitacion_id="EXP-9"),
            _item("tarea", dias=2, licitacion_id="EXP-1"),
        ]
        assert [i.licitacion_id for i in sorted(items, key=sp._agenda_orden)] == ["EXP-1", "EXP-9"]


# ── KPIs ────────────────────────────────────────────────────────────────────


class TestKpis:
    HOY = date(2026, 8, 13)

    def test_vence_semana_mide_pursuits_e_incluye_los_vencidos(self) -> None:
        """Un plazo pasado sigue exigiendo acción: no desaparece por llegar tarde."""
        vencido = sp._pursuit_item(
            _pursuit_row(tender_deadline="2026-08-10", importe_eur=50_000.0, decision="pending"),
            self.HOY,
        )
        lejano = sp._pursuit_item(
            _pursuit_row(
                licitacion_id="EXP-2",
                pursuit_id=12,
                tender_deadline="2026-12-01",
                next_action="Llamar",
            ),
            self.HOY,
        )
        senal = _item("senal", dias=1, licitacion_id="SEN-1")

        kpis = sp._agenda_kpis([vencido, lejano, senal])

        assert kpis.vence_semana == 1
        assert kpis.vence_semana_importe_eur == 50_000.0
        assert kpis.go_no_go_pendientes == 1
        assert kpis.senales_nuevas == 1

    def test_una_tarea_que_vence_no_cuenta_como_plazo_de_presentacion(self) -> None:
        """Los relojes no se suman: ``vence_semana`` son plazos, no acciones."""
        tarea = sp._tarea_item(
            _tarea_row(), self.HOY, tarea_id=41, tarea_texto="X", vence="2026-08-14"
        )
        kpis = sp._agenda_kpis([tarea])
        assert (kpis.vence_semana, kpis.vence_semana_importe_eur) == (0, 0.0)

    def test_acciones_hoy_cuenta_tareas_de_hoy_y_vencidas(self) -> None:
        tareas = [
            sp._tarea_item(_tarea_row(), self.HOY, tarea_id=1, tarea_texto="A", vence="2026-08-10"),
            sp._tarea_item(_tarea_row(), self.HOY, tarea_id=2, tarea_texto="B", vence="2026-08-13"),
            sp._tarea_item(_tarea_row(), self.HOY, tarea_id=3, tarea_texto="C", vence="2026-08-14"),
            sp._tarea_item(_tarea_row(), self.HOY, tarea_id=4, tarea_texto="D", vence=None),
        ]
        assert sp._agenda_kpis(tareas).acciones_hoy == 2

    def test_relicitaciones_abiertas_son_las_ventanas_ya_empezadas(self) -> None:
        """La que empieza dentro de un mes no está abierta; la de ayer sí."""
        abierta = sp._contrato_item(
            _contrato(relicitacion_desde="2026-08-12", licitacion_id="CTR-1"), self.HOY
        )
        futura = sp._contrato_item(
            _contrato(relicitacion_desde="2026-09-30", licitacion_id="CTR-2"), self.HOY
        )
        # Ventana abierta pero renovación ya preparada: deja de ser pendiente.
        preparada = sp._contrato_item(
            _contrato(
                relicitacion_desde="2026-08-12", licitacion_id="CTR-3", renovacion_pursuit_id=5
            ),
            self.HOY,
        )

        kpis = sp._agenda_kpis([abierta, futura, preparada])

        assert kpis.relicitaciones_abiertas == 1

    def test_sin_proxima_accion_no_cuenta_a_quien_tiene_una_tarea_abierta(self) -> None:
        """Un pursuit sin ``next_action`` **pero** con tarea sí tiene qué hacer.

        Es el caso que la versión anterior contaba de más: miraba sólo la
        columna ``next_action``, que un pursuit con tareas puede tener vacía
        mientras la tarea existe.
        """
        con_tarea = _pursuit_row(pursuit_id=11, licitacion_id="EXP-1")
        sin_nada = _pursuit_row(pursuit_id=12, licitacion_id="EXP-2")
        con_texto = _pursuit_row(pursuit_id=13, licitacion_id="EXP-3", next_action="Llamar")
        items = [sp._pursuit_item(row, self.HOY) for row in (con_tarea, sin_nada, con_texto)]
        items.extend(sp._agenda_tareas([con_tarea, sin_nada, con_texto], [_tarea_row()], self.HOY))

        kpis = sp._agenda_kpis(items)

        # Sólo `sin_nada`: el primero tiene tarea y el tercero, texto.
        assert kpis.sin_proxima_accion == 1


# ── Banda, hora y contadores: lo que la consola pinta sin recalcular ────────


class TestBanda:
    """``urgencia`` dice cuánto falta; ``banda``, en qué tramo va la fila.

    Coinciden casi siempre. Dejan de coincidir cuando el plazo de presentación
    ya no es algo que se pueda cumplir: o pasó sin oferta, o la oferta ya está
    entregada. Ninguna de las dos es una urgencia, y pintarlas en rojo arriba
    del todo enterraba lo que sí se puede hacer esta semana.
    """

    HOY = date(2026, 8, 13)

    def test_un_plazo_pasado_sin_presentar_es_un_cierre_pendiente(self) -> None:
        item = sp._pursuit_item(
            _pursuit_row(tender_deadline="2026-08-01", status="qualifying", decision="pending"),
            self.HOY,
        )
        # El reloj no cambia: el plazo venció. Lo que cambia es dónde se pinta.
        assert (item.urgencia, item.dias_restantes) == ("vencida", -12)
        assert item.banda == "plazo_pasado"

    @pytest.mark.parametrize("plazo", ["2026-08-01", "2026-08-20", None])
    def test_una_oferta_presentada_espera_resolucion_venza_cuando_venza(
        self, plazo: str | None
    ) -> None:
        item = sp._pursuit_item(_pursuit_row(tender_deadline=plazo, status="submitted"), self.HOY)
        assert item.banda == "en_resolucion"

    @pytest.mark.parametrize(
        ("plazo", "banda"),
        [
            ("2026-08-13", "hoy"),
            ("2026-08-16", "semana"),
            ("2026-09-01", "mes"),
            ("2026-12-01", "despues"),
            (None, "sin_fecha"),
        ],
    )
    def test_con_el_plazo_por_delante_la_banda_es_la_urgencia(
        self, plazo: str | None, banda: str
    ) -> None:
        item = sp._pursuit_item(_pursuit_row(tender_deadline=plazo), self.HOY)
        assert (item.banda, item.urgencia) == (banda, banda)

    def test_un_expediente_resuelto_sin_plazo_es_un_cierre_pendiente(self) -> None:
        """Sin fecha límite no hay plazo que medir, pero ya no hay nada que licitar.

        Caía en «Sin fecha» como una oportunidad viva a la que le faltaba el
        siguiente paso, y la franja la contaba en «Go/No-Go pendientes».
        """
        item = sp._pursuit_item(
            _pursuit_row(
                tender_deadline=None,
                status="identified",
                decision="pending",
                tender_estado="RES",
                adjudicatarios="Indra, Accenture",
            ),
            self.HOY,
        )
        # El reloj no cambia: sigue sin fecha. Lo que cambia es el tramo.
        assert (item.urgencia, item.dias_restantes) == ("sin_fecha", None)
        assert item.banda == "plazo_pasado"
        assert (item.expediente_cerrado, item.expediente_estado) == (True, "RES")
        assert item.adjudicatario == "Indra, Accenture"

    @pytest.mark.parametrize("estado", ["RES", "ADJ", "ANUL"])
    def test_un_estado_de_cierre_cierra_aunque_el_plazo_no_haya_pasado(self, estado: str) -> None:
        item = sp._pursuit_item(
            _pursuit_row(tender_deadline="2026-08-20", status="qualifying", tender_estado=estado),
            self.HOY,
        )
        assert (item.banda, item.urgencia) == ("plazo_pasado", "semana")

    def test_una_adjudicacion_publicada_cierra_aunque_el_estado_siga_abierto(self) -> None:
        """TED no mueve el estado del anuncio: la adjudicación llega aparte."""
        item = sp._pursuit_item(
            _pursuit_row(
                tender_deadline="2026-08-20",
                status="qualifying",
                tender_estado="PUB",
                adjudicatarios="Indra",
            ),
            self.HOY,
        )
        assert (item.banda, item.expediente_cerrado) == ("plazo_pasado", True)

    @pytest.mark.parametrize("estado", ["PUB", "EV", None])
    def test_un_expediente_abierto_no_cambia_de_tramo(self, estado: str | None) -> None:
        item = sp._pursuit_item(
            _pursuit_row(tender_deadline="2026-08-16", status="qualifying", tender_estado=estado),
            self.HOY,
        )
        assert (item.banda, item.expediente_cerrado, item.adjudicatario) == ("semana", False, None)

    def test_una_oferta_presentada_sobre_un_expediente_resuelto_sigue_esperando(self) -> None:
        """Lo pendiente es registrar el resultado, y la fila ya sabe quién ganó."""
        item = sp._pursuit_item(
            _pursuit_row(status="submitted", tender_estado="ADJ", adjudicatarios="Indra"),
            self.HOY,
        )
        assert item.banda == "en_resolucion"
        assert (item.expediente_cerrado, item.adjudicatario) == (True, "Indra")

    def test_una_tarea_vencida_sigue_siendo_vencida(self) -> None:
        """Llega tarde, pero todavía se puede hacer: eso sí es una urgencia."""
        item = sp._tarea_item(
            _tarea_row(), self.HOY, tarea_id=41, tarea_texto="X", vence="2026-08-10"
        )
        assert item.banda == "vencida"

    def test_el_contrato_lleva_la_banda_de_su_urgencia(self) -> None:
        item = sp._contrato_item(_contrato(), self.HOY)
        assert item.banda == item.urgencia == "despues"


class TestHoraDelPlazo:
    HOY = date(2026, 8, 13)

    def test_el_pursuit_lleva_la_hora_peninsular_de_su_plazo(self) -> None:
        """«Hoy» no distingue las 09:00 de la medianoche; la hora sí."""
        item = sp._pursuit_item(_pursuit_row(tender_deadline="2026-08-30T12:00:00+00:00"), self.HOY)
        assert (item.due_date, item.due_hora) == (date(2026, 8, 30), "14:00")

    def test_sin_hora_publicada_no_se_inventa(self) -> None:
        item = sp._pursuit_item(_pursuit_row(tender_deadline="2026-08-30"), self.HOY)
        assert item.due_hora is None

    def test_una_tarea_no_tiene_hora(self) -> None:
        item = sp._tarea_item(
            _tarea_row(), self.HOY, tarea_id=41, tarea_texto="X", vence="2026-08-14"
        )
        assert item.due_hora is None


class TestContadores:
    """Cada fila dice en qué contadores cuenta, y el contador es ese recuento.

    La franja de la agenda filtra la lista al pulsarla. Si el número y las filas
    salieran de dos reglas distintas —una aquí, otra en el navegador— un chip
    diría «7» y enseñaría cinco: por eso la pertenencia viaja en cada fila.
    """

    HOY = date(2026, 8, 13)

    def _viva(self, **overrides: Any) -> dict[str, Any]:
        campos: dict[str, Any] = {
            "tender_deadline": "2026-08-16",
            "status": "qualifying",
            "decision": "pending",
            "importe_eur": 200_000.0,
        }
        campos.update(overrides)
        return _pursuit_row(**campos)

    def _tarea(self, tarea_id: int, vence: str | None) -> Any:
        return sp._tarea_item(
            _tarea_row(), self.HOY, tarea_id=tarea_id, tarea_texto="X", vence=vence
        )

    def test_un_plazo_pasado_solo_cuenta_como_plazo_pasado(self) -> None:
        """Ni decisión pendiente ni «sin siguiente paso»: su paso es cerrarla.

        Era el ruido de la franja: cinco plazos pasados contaban a la vez como
        «plazos esta semana», «Go/No-Go pendientes» y «sin próxima acción».
        """
        [item] = sp._marcar([sp._pursuit_item(self._viva(tender_deadline="2026-08-01"), self.HOY)])
        assert item.cuenta_en == ["plazo_pasado"]

    def test_un_expediente_resuelto_solo_cuenta_como_cierre_pendiente(self) -> None:
        """Ni decisión pendiente ni «sin siguiente paso», aunque no tenga plazo."""
        fila = self._viva(tender_deadline=None, tender_estado="RES", adjudicatarios="Indra")
        [item] = sp._marcar([sp._pursuit_item(fila, self.HOY)])
        assert item.cuenta_en == ["plazo_pasado"]

    def test_una_oportunidad_viva_cuenta_en_cada_reloj_que_le_toca(self) -> None:
        [item] = sp._marcar([sp._pursuit_item(self._viva(), self.HOY)])
        assert set(item.cuenta_en) == {"plazo_semana", "go_no_go", "sin_paso"}

    def test_el_plazo_de_hoy_cuenta_en_la_semana(self) -> None:
        [item] = sp._marcar([sp._pursuit_item(self._viva(tender_deadline="2026-08-13"), self.HOY)])
        assert "plazo_semana" in item.cuenta_en

    def test_un_plazo_lejano_no_cuenta_en_la_semana(self) -> None:
        [item] = sp._marcar([sp._pursuit_item(self._viva(tender_deadline="2026-09-30"), self.HOY)])
        assert set(item.cuenta_en) == {"go_no_go", "sin_paso"}

    def test_una_oferta_presentada_no_cuenta_en_ninguno(self) -> None:
        """No queda plazo que cumplir ni decisión que tomar: queda esperar."""
        [item] = sp._marcar(
            [sp._pursuit_item(self._viva(status="submitted", decision="go"), self.HOY)]
        )
        assert item.cuenta_en == []

    def test_con_una_tarea_abierta_ya_tiene_siguiente_paso(self) -> None:
        row = self._viva()
        items = sp._marcar(
            [sp._pursuit_item(row, self.HOY), *sp._agenda_tareas([row], [_tarea_row()], self.HOY)]
        )
        assert "sin_paso" not in items[0].cuenta_en

    def test_la_tarea_de_hoy_o_vencida_cuenta_como_accion_vencida(self) -> None:
        tareas = sp._marcar(
            [
                self._tarea(1, "2026-08-10"),
                self._tarea(2, "2026-08-13"),
                self._tarea(3, "2026-08-14"),
                self._tarea(4, None),
            ]
        )
        assert [t.cuenta_en for t in tareas] == [["accion_vencida"], ["accion_vencida"], [], []]

    def test_cada_contador_es_el_numero_de_filas_que_lo_llevan(self) -> None:
        pasado = self._viva(pursuit_id=1, licitacion_id="EXP-1", tender_deadline="2026-08-01")
        viva = self._viva(pursuit_id=2, licitacion_id="EXP-2", importe_eur=300_000.0)
        hoy = self._viva(pursuit_id=3, licitacion_id="EXP-3", tender_deadline="2026-08-13")
        presentada = self._viva(pursuit_id=4, licitacion_id="EXP-4", status="submitted")
        rows = [pasado, viva, hoy, presentada]
        items = [sp._pursuit_item(row, self.HOY) for row in rows]
        tarea_de_hoy = _tarea_row(pursuit_id=3, licitacion_id="EXP-3", tarea_vence="2026-08-12")
        items.extend(sp._agenda_tareas(rows, [tarea_de_hoy], self.HOY))

        marcados = sp._marcar(items)
        contadores = sp._agenda_contadores(marcados)

        for nombre in ("plazo_semana", "accion_vencida", "go_no_go", "sin_paso", "plazo_pasado"):
            en_filas = sum(nombre in fila.cuenta_en for fila in marcados)
            assert getattr(contadores, nombre) == en_filas, nombre
        assert (contadores.plazo_pasado, contadores.plazo_semana) == (1, 2)
        assert (contadores.go_no_go, contadores.sin_paso, contadores.accion_vencida) == (2, 1, 1)
        # Solo lo que todavía se puede presentar está «en juego».
        assert contadores.plazo_semana_importe_eur == 500_000.0

    def test_la_oportunidad_dice_cuantas_tareas_abiertas_tiene(self) -> None:
        """Para no repetir en cada tarea de qué oportunidad es: se cuenta en ella."""
        con = self._viva(pursuit_id=1, licitacion_id="EXP-1")
        sin = self._viva(pursuit_id=2, licitacion_id="EXP-2")
        manual = self._viva(pursuit_id=3, licitacion_id="EXP-3", next_action="Llamar")
        rows = [con, sin, manual]
        items = [sp._pursuit_item(row, self.HOY) for row in rows]
        items.extend(
            sp._agenda_tareas(
                rows,
                [
                    _tarea_row(pursuit_id=1, licitacion_id="EXP-1", tarea_id=41),
                    _tarea_row(pursuit_id=1, licitacion_id="EXP-1", tarea_id=42),
                ],
                self.HOY,
            )
        )

        marcados = sp._marcar(items)

        assert [i.tareas_abiertas for i in marcados if i.kind == "pursuit"] == [2, 0, 1]
        assert {i.tareas_abiertas for i in marcados if i.kind == "tarea"} == {None}

    def test_los_kpis_de_siempre_no_cambian_de_significado(self) -> None:
        """``vence_semana`` sigue incluyendo lo vencido: es contrato publicado.

        La consola dejó de leerlo (lee ``contadores``), pero quien integre contra
        la API tiene que seguir recibiendo el mismo número con el mismo sentido.
        """
        marcados = sp._marcar(
            [sp._pursuit_item(self._viva(tender_deadline="2026-08-01"), self.HOY)]
        )
        assert sp._agenda_kpis(marcados).vence_semana == 1
        assert sp._agenda_contadores(marcados).plazo_semana == 0


class TestOrdenDeLaAgenda:
    """El orden completo: por banda, y dentro de ella por oportunidad."""

    HOY = date(2026, 8, 13)

    def _pursuit(self, pursuit_id: int, plazo: str | None, **overrides: Any) -> Any:
        return sp._pursuit_item(
            _pursuit_row(
                pursuit_id=pursuit_id,
                licitacion_id=f"EXP-{pursuit_id}",
                tender_deadline=plazo,
                **overrides,
            ),
            self.HOY,
        )

    def _tarea(self, pursuit_id: int, tarea_id: int, vence: str | None) -> Any:
        return sp._tarea_item(
            _tarea_row(pursuit_id=pursuit_id, licitacion_id=f"EXP-{pursuit_id}"),
            self.HOY,
            tarea_id=tarea_id,
            tarea_texto=f"Tarea {tarea_id}",
            vence=vence,
        )

    def test_el_plazo_pasado_va_detras_de_la_semana_y_delante_del_mes(self) -> None:
        """Primero lo que aún se puede hacer; después, lo que hay que cerrar."""
        pasado = self._pursuit(1, "2026-07-01", status="identified")
        semana = self._pursuit(2, "2026-08-16")
        mes = self._pursuit(3, "2026-09-01")
        ordenados = sp._ordenar_agenda([pasado, mes, semana])
        assert [i.pursuit_id for i in ordenados] == [2, 1, 3]

    def test_lo_presentado_va_al_final_delante_de_lo_sin_fecha(self) -> None:
        presentada = self._pursuit(1, "2026-08-01", status="submitted")
        lejana = self._pursuit(2, "2026-12-01")
        sin_fecha = self._pursuit(3, None)
        ordenados = sp._ordenar_agenda([sin_fecha, presentada, lejana])
        assert [i.pursuit_id for i in ordenados] == [2, 1, 3]

    def test_las_tareas_siguen_a_su_oportunidad_dentro_de_la_misma_banda(self) -> None:
        """Juntas se leen como un trabajo; sueltas, como cuatro títulos repetidos."""
        ordenados = sp._ordenar_agenda(
            [
                self._pursuit(1, "2026-08-18"),
                self._pursuit(2, "2026-08-19"),
                self._tarea(2, 21, "2026-08-15"),
                self._tarea(1, 11, "2026-08-17"),
                self._tarea(1, 12, "2026-08-16"),
            ]
        )
        assert [(i.kind, i.pursuit_id, i.tarea_id) for i in ordenados] == [
            # El grupo se coloca por su fila más próxima: la tarea del 15.
            ("pursuit", 2, None),
            ("tarea", 2, 21),
            ("pursuit", 1, None),
            ("tarea", 1, 12),
            ("tarea", 1, 11),
        ]

    def test_una_tarea_de_otra_banda_se_queda_en_la_suya(self) -> None:
        """La tarea de hoy no espera al plazo de dentro de tres semanas."""
        lejana = self._pursuit(1, "2026-09-05")
        semana = self._pursuit(2, "2026-08-16")
        ordenados = sp._ordenar_agenda([lejana, semana, self._tarea(1, 11, "2026-08-13")])
        assert [(i.kind, i.pursuit_id) for i in ordenados] == [
            ("tarea", 1),
            ("pursuit", 2),
            ("pursuit", 1),
        ]

    def test_sin_banda_declarada_ordena_por_la_urgencia(self) -> None:
        """Quien construye filas sin ``banda`` no se queda sin orden."""
        items = [
            _item("pursuit", dias=None, licitacion_id="A"),
            _item("pursuit", dias=-30, licitacion_id="B"),
            _item("pursuit", dias=5, licitacion_id="C"),
        ]
        assert [i.licitacion_id for i in sp._ordenar_agenda(items)] == ["B", "C", "A"]


# ── get_agenda: fusión con dependencias mockeadas ───────────────────────────


class _RepoStub:
    def __init__(self, rows: list[dict[str, Any]], truncado: bool = False) -> None:
        self._rows = rows
        self._truncado = truncado
        self.kwargs: dict[str, Any] = {}

    def agenda_rows(self, organization_id: int, **kwargs: Any) -> tuple[list[dict[str, Any]], bool]:
        self.kwargs = {"organization_id": organization_id, **kwargs}
        return self._rows, self._truncado

    def licitacion_ids(self, organization_id: int) -> set[str]:
        return {str(row["licitacion_id"]) for row in self._rows}


class _Dependencias:
    """Los dobles de una llamada a ``get_agenda``, para inspeccionarlos después."""

    def __init__(self, pursuits: _RepoStub, tareas: _RepoStub) -> None:
        self.pursuits = pursuits
        self.tareas = tareas
        self.reglas_consultadas: list[int] = []
        self.senales_kwargs: dict[str, Any] = {}
        self.renovaciones_kwargs: list[dict[str, Any]] = []
        self.carteras_pedidas: list[int] = []


@pytest.fixture()
def agenda_deps(monkeypatch: pytest.MonkeyPatch) -> _Dependencias:
    hoy = sp.hoy_peninsular()
    pursuits = _RepoStub([_pursuit_row(tender_deadline=(hoy + timedelta(days=3)).isoformat())])
    tareas = _RepoStub([_tarea_row(tarea_vence=(hoy + timedelta(days=2)).isoformat())])
    deps = _Dependencias(pursuits, tareas)

    monkeypatch.setattr(sp, "_repo", pursuits)
    monkeypatch.setattr(sp, "_tareas_repo", tareas)
    monkeypatch.setattr(sp, "alcance_resuelto", alcance_fijo(rol="member"))
    monkeypatch.setattr(
        sp,
        "list_rules",
        lambda user_key, organization_id=None: [
            WatchlistRule(id=5, nombre="SAP RRHH", keyword="SuccessFactors", active=True),
            WatchlistRule(id=6, nombre="Pausada", keyword="Oracle", active=False),
        ],
    )

    def _listar_cartera(organization_id: int) -> list[ContratoCartera]:
        deps.carteras_pedidas.append(organization_id)
        return [
            _contrato(
                licitacion_id="CTR-1",
                relicitacion_desde=(hoy + timedelta(days=10)).isoformat(),
                relicitacion_hasta=(hoy + timedelta(days=100)).isoformat(),
                fecha_fin_efectiva=(hoy + timedelta(days=190)).isoformat(),
            )
        ]

    monkeypatch.setattr(sp, "listar_cartera", _listar_cartera)

    def _signal_rows(criterios: Any, **kwargs: Any) -> list[dict[str, Any]]:
        deps.reglas_consultadas.append(criterios.rule_id)
        deps.senales_kwargs = kwargs
        return [
            {
                "id_externo": "SEN-1",
                "titulo": "Rollout SuccessFactors",
                "organo": "Osakidetza",
                "importe_eur": 1_200_000.0,
                "ccaa": "País Vasco",
                "tecnologia": "SAP",
                "fecha_limite": (hoy + timedelta(days=1)).isoformat(),
                "url": None,
            }
        ]

    monkeypatch.setattr(sp, "signal_rows", _signal_rows)

    def _renovaciones(**kwargs: Any) -> list[dict[str, Any]]:
        deps.renovaciones_kwargs.append(kwargs)
        return [
            # Con pursuit en la organización: debe quedar fuera de la agenda.
            {
                "licitacion_id": "EXP-1",
                "fecha_fin_efectiva": (hoy + timedelta(days=90)).isoformat(),
            },
            {
                "licitacion_id": "REN-1",
                "titulo": "Soporte SAP",
                "organo_contratacion": "SESCAM",
                "ccaa": None,
                "url": None,
                "empresa": "Competidor A",
                "importe_adjudicado": 2_000_000.0,
                "riesgo_cambio": 0.7,
                "fecha_fin_efectiva": (hoy + timedelta(days=120)).isoformat(),
            },
        ]

    monkeypatch.setattr(sp, "proximas_renovaciones", _renovaciones)
    return deps


def test_get_agenda_fusiona_los_cuatro_compromisos_propios(agenda_deps: _Dependencias) -> None:
    respuesta = sp.get_agenda(1, user_key="uk", organization_id=7)

    assert respuesta.organization_id == 7
    # Señal (1d); la oportunidad (3d) con su tarea (2d) detrás, colocadas por
    # la tarea, que es la fila más próxima del grupo; contrato (ventana a 10d).
    assert [item.kind for item in respuesta.items] == ["senal", "pursuit", "tarea", "contrato"]
    assert [item.due_kind for item in respuesta.items] == [
        "plazo",
        "plazo",
        "accion",
        "relicitacion",
    ]
    # Toda fila sale con su banda puesta: la consola no la deduce.
    assert [item.banda for item in respuesta.items] == ["semana", "semana", "semana", "mes"]
    assert respuesta.contadores.plazo_semana == 1
    # La regla pausada no cuenta: con cero activas la consola esconde el carril.
    assert respuesta.reglas_activas == 1
    assert respuesta.kpis.senales_nuevas == 1
    assert respuesta.pursuits_total == 1
    assert (respuesta.pursuits_truncados, respuesta.senales_truncadas) == (False, False)
    assert respuesta.tareas_truncadas is False
    assert agenda_deps.carteras_pedidas == [7]
    # La regla pausada no genera queries: solo la activa (id=5) consulta señales.
    assert agenda_deps.reglas_consultadas == [5]


def test_get_agenda_no_trae_el_mercado_salvo_que_se_pida(agenda_deps: _Dependencias) -> None:
    """Una renovación ajena no es un compromiso de la organización.

    Y no basta con filtrarla al final: sin ``incluir_mercado`` la consulta no
    se hace, que es lo que la sacó del camino por defecto.
    """
    respuesta = sp.get_agenda(1, user_key="uk", organization_id=7)

    assert "renovacion" not in {item.kind for item in respuesta.items}
    assert agenda_deps.renovaciones_kwargs == []


def test_get_agenda_con_mercado_anade_las_renovaciones_sin_pursuit(
    agenda_deps: _Dependencias,
) -> None:
    respuesta = sp.get_agenda(1, user_key="uk", organization_id=7, incluir_mercado=True)

    renovaciones = [item for item in respuesta.items if item.kind == "renovacion"]
    # `EXP-1` ya tiene pursuit en la organización: no se ofrece dos veces.
    assert [item.licitacion_id for item in renovaciones] == ["REN-1"]
    assert renovaciones[0].adjudicatario == "Competidor A"
    assert renovaciones[0].due_kind == "fin_contrato"
    assert respuesta.renovaciones_horizonte_meses == sp.AGENDA_RENOVACIONES_MESES


def test_get_agenda_solo_mios_limita_pursuits_y_tareas(agenda_deps: _Dependencias) -> None:
    """Los contratos no: son de la organización, no de una persona."""
    sp.get_agenda(1, user_key="uk", organization_id=7, solo_mios=True)

    assert agenda_deps.pursuits.kwargs["responsible_user_id"] == 1
    assert agenda_deps.tareas.kwargs["responsible_user_id"] == 1
    assert agenda_deps.carteras_pedidas == [7]


def test_get_agenda_sin_solo_mios_no_filtra_por_responsable(agenda_deps: _Dependencias) -> None:
    sp.get_agenda(1, user_key="uk", organization_id=7)

    assert agenda_deps.pursuits.kwargs["responsible_user_id"] is None
    assert agenda_deps.tareas.kwargs["responsible_user_id"] is None


@pytest.mark.parametrize(
    ("tecnologia", "ccaa", "tecnologias", "ccaas"),
    [
        ("SAP", "Galicia", ["SAP"], ["Galicia"]),
        ("SAP,Oracle", "Galicia,Madrid", ["SAP", "Oracle"], ["Galicia", "Madrid"]),
        (" SAP , Oracle ", " Galicia ,, Madrid ", ["SAP", "Oracle"], ["Galicia", "Madrid"]),
        (None, None, [], []),
        ("", ",", [], []),
    ],
)
def test_get_agenda_explota_el_ambito_en_listas(
    agenda_deps: _Dependencias,
    tecnologia: str | None,
    ccaa: str | None,
    tecnologias: list[str],
    ccaas: list[str],
) -> None:
    """El mismo ámbito llega a las tres consultas: si una lo leyera distinto,
    el mismo filtro daría universos distintos según el ``kind``."""
    sp.get_agenda(1, user_key="uk", organization_id=7, tecnologia=tecnologia, ccaa=ccaa)

    for repo in (agenda_deps.pursuits, agenda_deps.tareas):
        assert repo.kwargs["tecnologias"] == tecnologias
        assert repo.kwargs["ccaas"] == ccaas
    assert agenda_deps.senales_kwargs["tecnologias"] == tecnologias
    assert agenda_deps.senales_kwargs["ccaas"] == ccaas


def test_get_agenda_acota_los_contratos_con_el_mismo_ambito(agenda_deps: _Dependencias) -> None:
    """El contrato de la cartera es de Andalucía: pedir Galicia lo deja fuera."""
    respuesta = sp.get_agenda(1, user_key="uk", organization_id=7, ccaa="Galicia")

    assert "contrato" not in {item.kind for item in respuesta.items}


def test_get_agenda_con_varias_ccaa_consulta_el_mercado_una_vez_por_region(
    agenda_deps: _Dependencias,
) -> None:
    """``proximas_renovaciones`` filtra por **una** CCAA; la unión se reordena."""
    sp.get_agenda(
        1,
        user_key="uk",
        organization_id=7,
        ccaa="Galicia,Madrid",
        tecnologia="SAP,Oracle",
        incluir_mercado=True,
    )

    assert [k["ccaa"] for k in agenda_deps.renovaciones_kwargs] == ["Galicia", "Madrid"]
    assert agenda_deps.renovaciones_kwargs[0]["tecnologias"] == ["SAP", "Oracle"]


def test_get_agenda_declara_el_corte_de_tareas(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un tope alcanzado se declara; presentar el corte como el total es mentir."""
    monkeypatch.setattr(sp, "_repo", _RepoStub([]))
    monkeypatch.setattr(sp, "_tareas_repo", _RepoStub([_tarea_row()], truncado=True))
    monkeypatch.setattr(sp, "alcance_resuelto", alcance_fijo(rol="member"))
    monkeypatch.setattr(sp, "listar_cartera", lambda organization_id: [])
    monkeypatch.setattr(sp, "list_rules", lambda *a, **k: [])

    respuesta = sp.get_agenda(1, user_key="uk", organization_id=7)

    assert respuesta.tareas_truncadas is True
    assert respuesta.pursuits_truncados is False
    assert sp.AGENDA_TAREAS_MAX >= 1
    assert respuesta.reglas_activas == 0


def test_get_agenda_la_senal_lleva_la_hora_de_su_plazo(
    agenda_deps: _Dependencias, monkeypatch: pytest.MonkeyPatch
) -> None:
    hoy = sp.hoy_peninsular()
    plazo = f"{(hoy + timedelta(days=1)).isoformat()}T10:00:00+00:00"
    monkeypatch.setattr(
        sp,
        "signal_rows",
        lambda criterios, **kwargs: [{"id_externo": "SEN-1", "fecha_limite": plazo}],
    )

    respuesta = sp.get_agenda(1, user_key="uk", organization_id=7)

    [senal] = [item for item in respuesta.items if item.kind == "senal"]
    # Las 10:00 UTC son las 11:00 o las 12:00 peninsulares, según la época.
    assert senal.due_hora in {"11:00", "12:00"}
    assert senal.banda == "semana"


def test_update_normaliza_next_action_y_serializa_fecha() -> None:
    current = {
        "status": "preparing",
        "decision": "go",
        "decision_reason": "encaja",
        "outcome": "pending",
        "next_action": None,
        "next_action_due": None,
        "submitted_at": None,
        "closed_at": None,
        "version": 1,
    }
    changes = sp._normalize_and_validate_update(
        current,
        {"next_action": "  Subir oferta  ", "next_action_due": date(2026, 8, 20)},
        organization_id=7,
    )
    assert changes["next_action"] == "Subir oferta"
    # TEXT ISO en BD: comparable en el diff y serializable en el evento JSON.
    assert changes["next_action_due"] == "2026-08-20"


def test_get_agenda_cuenta_los_dias_desde_el_hoy_peninsular(
    agenda_deps: _Dependencias, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pasada la medianoche peninsular, el plazo de hoy es «hoy» y no «1 d».

    La agenda medía contra el día UTC: durante las dos primeras horas del día
    (una en invierno) todo plazo salía un día más lejos de lo que estaba.
    """
    monkeypatch.setattr(sp, "hoy_peninsular", lambda: date(2026, 10, 15))
    agenda_deps.pursuits._rows[:] = [_pursuit_row(tender_deadline="2026-10-15")]
    agenda_deps.tareas._rows[:] = []

    respuesta = sp.get_agenda(1, user_key="uk", organization_id=7)

    [oportunidad] = [item for item in respuesta.items if item.kind == "pursuit"]
    assert (oportunidad.dias_restantes, oportunidad.banda) == (0, "hoy")


# ── Decidir desde cualquier fase: el GO salta a preparación ─────────────────


class TestSaltoConGo:
    """Con el GO tomado, las fases anteriores ya no tienen nada que frenar.

    El embudo era lineal sin excepción: de «Identificada» a «Preparando oferta»
    hacían falta tres movimientos y un motivo, y un equipo pequeño no los daba
    —de catorce oportunidades, dos con decisión registrada—. Las fases previas
    existen para llegar a la decisión; una vez tomada, se puede ir directo.
    """

    def _actual(self, **overrides: Any) -> dict[str, Any]:
        actual: dict[str, Any] = {
            "status": "identified",
            "decision": "pending",
            "decision_reason": None,
            "outcome": "pending",
            "next_action": None,
            "next_action_due": None,
            "submitted_at": None,
            "closed_at": None,
            "version": 1,
        }
        actual.update(overrides)
        return actual

    @pytest.mark.parametrize("fase", ["identified", "qualifying", "go_no_go"])
    def test_el_go_lleva_a_preparacion_desde_cualquier_fase_anterior(self, fase: str) -> None:
        cambios = sp._normalize_and_validate_update(
            self._actual(status=fase),
            {"status": "preparing", "decision": "go", "decision_reason": "Encaja"},
            organization_id=7,
        )
        assert (cambios["status"], cambios["decision"]) == ("preparing", "go")
        assert cambios["decision_at"] is not None

    def test_un_go_ya_registrado_tambien_deja_saltar(self) -> None:
        """El GO pudo anotarse antes sin mover la fase: lo que cuenta es tenerlo."""
        cambios = sp._normalize_and_validate_update(
            self._actual(decision="go", decision_reason="Encaja"),
            {"status": "preparing"},
            organization_id=7,
        )
        assert cambios["status"] == "preparing"

    def test_sin_go_el_salto_sigue_siendo_una_transicion_no_permitida(self) -> None:
        with pytest.raises(sp.PursuitTransitionError, match="identified -> preparing"):
            sp._normalize_and_validate_update(
                self._actual(), {"status": "preparing"}, organization_id=7
            )

    def test_el_go_no_deja_saltarse_la_presentacion(self) -> None:
        """Solo se salta lo que precede a la decisión, no lo que la sigue."""
        with pytest.raises(sp.PursuitTransitionError, match="identified -> submitted"):
            sp._normalize_and_validate_update(
                self._actual(),
                {"status": "submitted", "decision": "go", "decision_reason": "Encaja"},
                organization_id=7,
            )

    def test_el_go_sigue_exigiendo_motivo(self) -> None:
        with pytest.raises(sp.PursuitValidationError, match="motivo"):
            sp._normalize_and_validate_update(
                self._actual(), {"status": "preparing", "decision": "go"}, organization_id=7
            )

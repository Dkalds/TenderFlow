"""El ciclo de vida de una oportunidad, como máquina de estados.

``tests/test_pursuits_rules.py`` comprueba cada guarda con el caso que la
dispara. Aquí Hypothesis encadena parches arbitrarios —los que acepta el
contrato ``PursuitUpdate``, ``null`` incluido— y tras cada uno que el servicio
acepta se comprueba que la oportunidad sigue siendo coherente. Lo que busca es
la **secuencia** que ninguna guarda mira por separado: un estado al que no se
llega con un parche, pero sí con tres.

No abre base de datos: ``_normalize_and_validate_update`` es la función que
decide qué cambia, y es pura salvo por el responsable (que valida contra la
organización y por eso queda fuera de los parches generados).

Los invariantes están escritos **sin leer** ``_TRANSITIONS``: si reutilizaran la
tabla del servicio, un error en la tabla pasaría el test.

Casos de uso: CU-05 y CU-06 (``docs/casos-de-uso.md``).
"""

from __future__ import annotations

from typing import Any

from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from services.pursuits import (
    MOTIVOS_PERDIDA,
    PursuitValidationError,
    _normalize_and_validate_update,
)
from shared.dto import PursuitUpdate

#: El embudo, en su orden. Escrito aquí a mano, no importado del servicio.
_EMBUDO = ("identified", "qualifying", "go_no_go", "preparing", "submitted")
_TERMINALES = {"won": "won", "lost": "lost", "withdrawn": "cancelled"}
_ESTADOS = (*_EMBUDO, *_TERMINALES)
_DECISIONES = ("pending", "go", "no_go")
_RESULTADOS = ("pending", "won", "lost", "cancelled")

_textos = st.sampled_from([None, "", "   ", "Motivo escrito"])

#: Un parche como los que el contrato admite: cualquier subconjunto de campos,
#: cada uno con un valor válido para su tipo o ``null``.
_parches = st.fixed_dictionaries(
    {},
    optional={
        "status": st.sampled_from([None, *_ESTADOS]),
        "decision": st.sampled_from([None, *_DECISIONES]),
        "decision_reason": _textos,
        "outcome": st.sampled_from([None, *_RESULTADOS]),
        "awarded_amount_eur": st.sampled_from([None, 0.0, 125_000.0]),
        "outcome_reason": _textos,
        "outcome_reason_code": st.sampled_from([None, *MOTIVOS_PERDIDA]),
        "offer_price_eur": st.sampled_from([None, 99_000.0]),
        "next_action": _textos,
    },
)


def _oportunidad_nueva() -> dict[str, Any]:
    return {
        "status": "identified",
        "decision": "pending",
        "decision_reason": None,
        "decision_at": None,
        "outcome": "pending",
        "outcome_reason": None,
        "outcome_reason_code": None,
        "awarded_amount_eur": None,
        "offer_price_eur": None,
        "submitted_at": None,
        "closed_at": None,
        "next_action": None,
        "next_action_due": None,
        "responsible_user_id": 1,
        "version": 1,
    }


def _en_blanco(valor: object) -> bool:
    return not str(valor or "").strip()


class CicloDeVidaDeLaOportunidad(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.actual = _oportunidad_nueva()
        self.recorrido: list[str] = ["identified"]
        self.presentada_en: object = None
        self.cerrada_en: object = None

    # ── Pasos ───────────────────────────────────────────────────────────────

    def _aplicar(self, parche: dict[str, Any]) -> bool:
        """Pasa el parche por el contrato y el servicio. ``True`` si se aceptó."""
        pedido = PursuitUpdate.model_validate(parche).model_dump(exclude_unset=True)
        try:
            cambios = _normalize_and_validate_update(dict(self.actual), pedido, 1)
        except PursuitValidationError:
            return False
        self.actual.update(cambios)
        if self.actual["status"] != self.recorrido[-1]:
            self.recorrido.append(str(self.actual["status"]))
        return True

    @rule(parche=_parches)
    def parche_cualquiera(self, parche: dict[str, Any]) -> None:
        self._aplicar(parche)

    @precondition(lambda self: self.actual["status"] in ("identified", "qualifying", "go_no_go"))
    @rule()
    def decidir_go_y_preparar(self) -> None:
        """El camino que recorre la consola: sin él, casi ningún ejemplo pasa de la decisión."""
        assert self._aplicar(
            {"decision": "go", "decision_reason": "Encaja", "status": "preparing"}
        ) or (self.actual["status"] == "go_no_go" and self.actual["decision"] == "no_go")

    @precondition(lambda self: self.actual["status"] == "preparing")
    @rule()
    def presentar(self) -> None:
        assert self._aplicar({"status": "submitted"})

    @precondition(lambda self: self.actual["status"] == "submitted")
    @rule(importe=st.sampled_from([0.0, 80_000.0]))
    def ganar(self, importe: float) -> None:
        assert self._aplicar({"status": "won", "awarded_amount_eur": importe})

    @precondition(lambda self: self.actual["status"] == "submitted")
    @rule(motivo=st.sampled_from(MOTIVOS_PERDIDA))
    def perder(self, motivo: str) -> None:
        assert self._aplicar({"status": "lost", "outcome_reason_code": motivo})

    @precondition(lambda self: self.actual["status"] in _EMBUDO)
    @rule()
    def retirar(self) -> None:
        """De cualquier fase abierta se puede salir: nadie queda atrapado en el embudo."""
        assert self._aplicar({"status": "withdrawn"}), self.actual

    # ── Invariantes ─────────────────────────────────────────────────────────

    @invariant()
    def los_campos_de_estado_son_valores_del_contrato(self) -> None:
        assert self.actual["status"] in _ESTADOS, self.actual
        assert self.actual["decision"] in _DECISIONES, self.actual
        assert self.actual["outcome"] in _RESULTADOS, self.actual

    @invariant()
    def el_resultado_corresponde_al_estado(self) -> None:
        esperado = _TERMINALES.get(str(self.actual["status"]), "pending")
        assert self.actual["outcome"] == esperado, self.actual

    @invariant()
    def no_hay_oferta_sin_go(self) -> None:
        if self.actual["status"] in ("preparing", "submitted", "won", "lost"):
            assert self.actual["decision"] == "go", self.actual

    @invariant()
    def toda_decision_tiene_motivo(self) -> None:
        if self.actual["decision"] != "pending":
            assert not _en_blanco(self.actual["decision_reason"]), self.actual

    @invariant()
    def un_no_go_no_sigue_hacia_la_oferta(self) -> None:
        if self.actual["decision"] == "no_go":
            assert self.actual["status"] in ("go_no_go", "withdrawn"), self.actual

    @invariant()
    def las_fechas_acompanan_al_estado(self) -> None:
        estado = self.actual["status"]
        if estado in ("submitted", "won", "lost"):
            assert self.actual["submitted_at"] is not None, self.actual
        assert (self.actual["closed_at"] is not None) == (estado in _TERMINALES), self.actual

    @invariant()
    def las_fechas_selladas_no_se_reescriben(self) -> None:
        for campo, atributo in (("submitted_at", "presentada_en"), ("closed_at", "cerrada_en")):
            sellada = getattr(self, atributo)
            if sellada is None:
                setattr(self, atributo, self.actual[campo])
            else:
                assert self.actual[campo] == sellada, (campo, self.actual)

    @invariant()
    def un_cierre_dice_cuanto_o_por_que(self) -> None:
        if self.actual["status"] == "won":
            assert self.actual["awarded_amount_eur"] is not None or not _en_blanco(
                self.actual["outcome_reason"]
            ), self.actual

    @invariant()
    def una_perdida_conserva_su_motivo(self) -> None:
        if self.actual["status"] == "lost":
            assert not _en_blanco(self.actual["outcome_reason_code"]), self.actual

    @invariant()
    def el_embudo_solo_avanza(self) -> None:
        """Cada cambio de fase es un paso adelante, el atajo del GO, un cierre o una retirada."""
        for previo, siguiente in zip(self.recorrido, self.recorrido[1:], strict=False):
            assert previo not in _TERMINALES, self.recorrido
            if siguiente == "withdrawn":
                continue
            if siguiente in ("won", "lost"):
                assert previo == "submitted", self.recorrido
                continue
            avance = _EMBUDO.index(siguiente) - _EMBUDO.index(previo)
            atajo = siguiente == "preparing" and previo in ("identified", "qualifying")
            assert avance == 1 or atajo, self.recorrido


CicloDeVidaDeLaOportunidad.TestCase.settings = settings(
    max_examples=120, stateful_step_count=14, deadline=None
)
TestCicloDeVidaDeLaOportunidad = CicloDeVidaDeLaOportunidad.TestCase

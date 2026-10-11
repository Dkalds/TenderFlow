"""Las reglas de alerta como máquina de estados contra Postgres.

Dos cosas que los tests de ejemplo no pueden agotar:

1. **El ciclo de vida.** Hypothesis crea, edita y borra reglas de dos personas
   en cualquier orden, y tras cada paso el listado de cada una tiene que ser
   exactamente el modelo: ni reglas ajenas, ni reglas borradas, ni una edición
   aplicada a la regla de al lado.
2. **Qué casa.** Para cada regla viva, lo que devuelve el SQL (``count_matches``
   y ``list_matches``) se compara con un oráculo escrito aquí en Python sobre el
   mismo corpus. El oráculo no comparte código con el predicado: si ``LIKE``
   interpreta un carácter que el usuario escribió como texto, discrepan.

El corpus lleva a propósito los caracteres que un ``LIKE`` trata como comodín o
escape (``%``, ``_``, ``\\``), importes nulos y expedientes multi-tecnología.
"""

from __future__ import annotations

from dataclasses import dataclass

from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    Bundle,
    RuleBasedStateMachine,
    consumes,
    invariant,
    rule,
    run_state_machine_as_test,
)

from services.watchlist_rules import (
    WatchlistRule,
    count_matches,
    create_rule,
    delete_rule,
    list_matches,
    list_rules,
    update_rule,
)


@dataclass(frozen=True)
class _Expediente:
    id_externo: str
    titulo: str
    descripcion: str | None
    cpv: str | None
    importe: float | None
    ccaa: str | None
    tecnologia: str | None


_CORPUS = (
    _Expediente("C-01", "Implantación SAP S/4HANA", None, "72000000", 400_000.0, "Madrid", "SAP"),
    _Expediente(
        "C-02",
        "Soporte sap_core y erp",
        "Mantenimiento",
        "72500000",
        30_000.0,
        "Madrid",
        "SAP,ORACLE",
    ),
    _Expediente("C-03", "Mejora del 100% de la red", None, "32400000", None, "Galicia", None),
    _Expediente(
        "C-04",
        "Migración de la ruta C:\\datos",
        "Copia 100 % fiel",
        "72300000",
        80_000.0,
        None,
        " ORACLE , SALESFORCE",
    ),
    _Expediente("C-05", "Sapiencia: formación", "curso de erp", "80500000", 5_000.0, "Galicia", ""),
    _Expediente("C-06", "Obra de cubierta", None, None, 900_000.0, "Madrid", None),
    _Expediente(
        "C-07", "Licencias a_b y a%b", "sAp", "48000000", 100_000.0, "Cataluña", "SALESFORCE"
    ),
)


def _casa(regla: WatchlistRule, fila: _Expediente) -> bool:
    """Lo que la regla significa para quien la escribe. Sin SQL y sin comodines."""
    if regla.keyword:
        aguja = regla.keyword.lower()
        if aguja not in fila.titulo.lower() and aguja not in (fila.descripcion or "").lower():
            return False
    if regla.cpv and not (fila.cpv or "").startswith(regla.cpv):
        return False
    if regla.min_importe is not None and (fila.importe is None or fila.importe < regla.min_importe):
        return False
    if regla.ccaa and fila.ccaa != regla.ccaa:
        return False
    if regla.tecnologia:
        codigos = [codigo.strip() for codigo in (fila.tecnologia or "").split(",")]
        if regla.tecnologia not in codigos:
            return False
    return True


_reglas = st.builds(
    WatchlistRule,
    nombre=st.sampled_from([None, "Mi regla"]),
    keyword=st.sampled_from(
        [None, "", "sap", "SAP", "erp", "100%", "%", "_", "a_b", "a%b", "\\", "C:\\", "s/4", "zzz"]
    ),
    cpv=st.sampled_from([None, "", "72", "725", "7_", "%", "80500000", "9"]),
    min_importe=st.sampled_from([None, 0.0, 30_000.0, 100_000.0, 1_000_000.0]),
    ccaa=st.sampled_from([None, "", "Madrid", "Galicia", "madrid"]),
    tecnologia=st.sampled_from([None, "SAP", "ORACLE", "SALESFORCE", "SA"]),
    frequency=st.sampled_from(["immediate", "daily", "weekly"]),
    active=st.booleans(),
)

_PERSONAS = ("ana", "berta")


def _comparable(regla: WatchlistRule) -> dict[str, object]:
    return regla.model_dump(exclude={"id", "organization_id", "visibility"})


def test_las_reglas_de_alerta_se_comportan_como_su_modelo(tmp_db):
    """CU-04 — crear, editar y borrar en cualquier orden, y que case lo que la regla dice."""
    db_mod, _ = tmp_db
    from db.users import create_user

    with db_mod.connect() as conn:
        for fila in _CORPUS:
            conn.execute(
                "INSERT INTO licitaciones (id_externo, titulo, descripcion, cpv, importe, ccaa, "
                " tecnologia, fuente, fecha_publicacion, fecha_extraccion) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, 'placsp', '2026-09-01', CURRENT_TIMESTAMP)",
                (
                    fila.id_externo,
                    fila.titulo,
                    fila.descripcion,
                    fila.cpv,
                    fila.importe,
                    fila.ccaa,
                    fila.tecnologia,
                ),
            )
    ids = {
        nombre: create_user(email=f"{nombre}-reglas@example.test", password_hash="test-hash")
        for nombre in _PERSONAS
    }

    class ReglasDeAlerta(RuleBasedStateMachine):
        vivas = Bundle("vivas")

        def __init__(self) -> None:
            super().__init__()
            # La base sobrevive entre ejemplos: cada uno empieza sin reglas.
            with db_mod.connect() as conn:
                conn.execute("DELETE FROM watchlist_rules")
            self.modelo: dict[str, dict[int, WatchlistRule]] = {p: {} for p in _PERSONAS}

        @rule(target=vivas, persona=st.sampled_from(_PERSONAS), regla=_reglas)
        def crear(self, persona: str, regla: WatchlistRule) -> tuple[str, int]:
            rid = create_rule(persona, regla, user_id=ids[persona])
            assert rid > 0
            self.modelo[persona][rid] = regla
            return persona, rid

        @rule(viva=vivas, regla=_reglas)
        def editar(self, viva: tuple[str, int], regla: WatchlistRule) -> None:
            persona, rid = viva
            assert update_rule(persona, rid, regla, user_id=ids[persona]) is True
            self.modelo[persona][rid] = regla

        @rule(viva=vivas, regla=_reglas)
        def editar_la_de_otra_no_hace_nada(
            self, viva: tuple[str, int], regla: WatchlistRule
        ) -> None:
            persona, rid = viva
            (otra,) = (p for p in _PERSONAS if p != persona)
            assert update_rule(otra, rid, regla, user_id=ids[otra]) is False
            assert delete_rule(otra, rid, user_id=ids[otra]) is False

        @rule(viva=consumes(vivas))
        def borrar(self, viva: tuple[str, int]) -> None:
            persona, rid = viva
            assert delete_rule(persona, rid, user_id=ids[persona]) is True
            del self.modelo[persona][rid]
            # Borrada, ya no existe ni para su dueña.
            assert delete_rule(persona, rid, user_id=ids[persona]) is False

        @invariant()
        def cada_persona_ve_exactamente_sus_reglas(self) -> None:
            for persona in _PERSONAS:
                listado = list_rules(persona, user_id=ids[persona])
                assert {r.id: _comparable(r) for r in listado} == {
                    rid: _comparable(regla) for rid, regla in self.modelo[persona].items()
                }
                # Más recientes primero: el orden es parte del contrato del listado.
                assert [r.id for r in listado] == sorted(self.modelo[persona], reverse=True)

        @invariant()
        def lo_que_casa_es_lo_que_la_regla_dice(self) -> None:
            for reglas in self.modelo.values():
                for regla in reglas.values():
                    esperadas = {f.id_externo for f in _CORPUS if _casa(regla, f)}
                    encontradas = {str(m["id_externo"]) for m in list_matches(regla, limit=50)}
                    assert encontradas == esperadas, _comparable(regla)
                    assert count_matches(regla) == len(esperadas), _comparable(regla)

    run_state_machine_as_test(
        ReglasDeAlerta,
        settings=settings(max_examples=25, stateful_step_count=10, deadline=None),
    )

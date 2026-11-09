"""Los admitidos de un acuerdo marco, en su pieza pura (CU-36).

La fuente publica una fila por adjudicatario y lote; el marco se lee por
empresas. El recorrido por la API está en ``tests/test_escenario_marcos.py``.
"""

from __future__ import annotations

from db.repositories.marcos import FilaAdmitido
from services.marcos import agrupar_admitidos
from services.pursuit_awards import IdentidadFiscal

NIF_PROPIO = "B11223344"  # pragma: allowlist secret -- NIF de prueba
PROPIA = IdentidadFiscal(nifs=frozenset({NIF_PROPIO}))


def _fila(
    nombre: str, nif: str | None, lote: str | None = None, empresa_id: int | None = None
) -> FilaAdmitido:
    return FilaAdmitido(nombre=nombre, nif=nif, empresa_id=empresa_id, lote_numero=lote)


def test_una_empresa_en_tres_lotes_cuenta_una_vez() -> None:
    admitidos, _ = agrupar_admitidos(
        [
            _fila("Acme SL", "A28000001", "1"),
            _fila("Acme SL", "a-28000001", "3"),
            _fila("ACME, S.L.", "A28000001", "2"),
            _fila("Beta SA", "A28000002", "1"),
        ],
        PROPIA,
    )

    assert [(a.nombre, a.lotes) for a in admitidos] == [
        ("Acme SL", ["1", "2", "3"]),
        ("Beta SA", ["1"]),
    ]


def test_la_organizacion_admitida_va_la_primera() -> None:
    admitidos, admitida = agrupar_admitidos(
        [_fila("Acme SL", "A28000001"), _fila("Zeta Mi Empresa SL", NIF_PROPIO)], PROPIA
    )

    assert admitida is True
    assert admitidos[0].es_tu_organizacion is True
    assert admitidos[0].nombre == "Zeta Mi Empresa SL"
    assert admitidos[1].es_tu_organizacion is False


def test_sin_nif_declarado_no_se_afirma_nada() -> None:
    _, admitida = agrupar_admitidos([_fila("Acme SL", "A28000001")], IdentidadFiscal())

    assert admitida is None


def test_no_esta_solo_se_afirma_si_todos_los_admitidos_estan_identificados() -> None:
    identificados = [_fila("Acme SL", "A28000001"), _fila("Beta SA", None, empresa_id=7)]
    assert agrupar_admitidos(identificados, PROPIA)[1] is False

    # Uno sin NIF ni empresa resuelta podría ser la organización: no se sabe.
    con_hueco = [*identificados, _fila("Empresa sin NIF publicado", None)]
    admitidos, admitida = agrupar_admitidos(con_hueco, PROPIA)
    assert admitida is None
    assert len(admitidos) == 3


def test_la_empresa_del_maestro_tambien_reconoce_a_la_organizacion() -> None:
    por_maestro = IdentidadFiscal(nifs=frozenset({NIF_PROPIO}), empresa_ids=frozenset({42}))

    _, admitida = agrupar_admitidos([_fila("Mi Empresa SL", None, empresa_id=42)], por_maestro)

    assert admitida is True


def test_un_marco_sin_adjudicar_no_tiene_admitidos_ni_respuesta() -> None:
    assert agrupar_admitidos([], PROPIA) == ([], None)

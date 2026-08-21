"""Referencia pública de licitación: ida y vuelta, y fallo cerrado ante basura.

Estos tests existen porque la superficie pública tiene dos propiedades que no
se pueden romper sin romper el SEO:

1. **La URL de un expediente no puede cambiar.** Si ``codificar_ref`` deja de
   ser determinista, cada despliegue reescribe todas las URLs indexadas y
   Google se encuentra un sitio nuevo lleno de 404.
2. **Una referencia inventada tiene que dar 404, nunca 500.** El endpoint es
   anónimo y ``scripts/fuzz_api_contract.py`` mantiene ``KNOWN_5XX`` a cero:
   una excepción al decodificar sería un fallo de CI, no solo un bug.
"""

from __future__ import annotations

import pytest

from shared.public_ref import codificar_ref, decodificar_ref

pytestmark = pytest.mark.unit


# `PA-S 2026/000058` es un id real de PLACSP, el mismo que usa
# `tests/test_ask_route.py` para el caso de las barras. Los espacios y la barra
# son justamente lo que hace inviable meter el id crudo en una URL.
IDS_REALES = [
    "PA-S 2026/000058",
    "2026-MULTILOTE-0001",
    "EXP/2024/123/A",
    "Contratación de servicios · Ñandú",
    "a" * 300,
]


@pytest.mark.parametrize("id_externo", IDS_REALES)
def test_ida_y_vuelta_conserva_el_id_exacto(id_externo: str) -> None:
    assert decodificar_ref(codificar_ref(id_externo)) == id_externo


@pytest.mark.parametrize("id_externo", IDS_REALES)
def test_la_ref_es_segura_en_una_url(id_externo: str) -> None:
    ref = codificar_ref(id_externo)
    # base64url: sin barras, espacios, signos de suma ni relleno. Cualquiera de
    # ellos rompería el segmento de ruta o sobreviviría re-codificado.
    assert not set(ref) & set("/+= ")
    assert ref.isascii()


def test_la_ref_es_determinista() -> None:
    """Una URL indexada no puede depender de cuándo se generó."""
    assert codificar_ref("PA-S 2026/000058") == codificar_ref("PA-S 2026/000058")


@pytest.mark.parametrize(
    "basura",
    [
        "",
        "!!!",
        "a",  # longitud imposible en base64
        "x" * 600,  # por encima del tope
        "../../etc/passwd",
        "%2F%2E%2E",
        "AAAA",  # decodifica a NUL: Postgres lo rechazaría
        "<script>",
    ],
)
def test_entrada_invalida_devuelve_none_sin_lanzar(basura: str) -> None:
    assert decodificar_ref(basura) is None


def test_no_se_acepta_el_id_crudo_como_ref() -> None:
    """Evita que alguien "arregle" el endpoint aceptando el id sin codificar.

    Sería una regresión silenciosa: funcionaría en desarrollo con ids simples y
    fallaría en producción justo con los expedientes que tienen barras.
    """
    assert decodificar_ref("PA-S 2026/000058") is None

"""El HTML de los correos: marca, contraste WCAG, idioma y plurales.

Sin SMTP ni base de datos: se renderiza cada correo con datos en memoria y se
mira el HTML resultante.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from unittest.mock import patch

import pytest

from services import email_html
from services.email_digest import BloqueDigest, render_digest, render_evento
from services.email_html import BLANCO, OXIDO, PAPEL, SECUNDARIO, TINTA, abrir_documento, contar
from services.informes import InformeSemanal, Vencimiento, render_html
from services.solicitudes_acceso import _cuerpo_acceso

_NARANJA_CLARO = "#F39349"


def _luminancia(hex_color: str) -> float:
    canales = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lineales = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canales]
    return 0.2126 * lineales[0] + 0.7152 * lineales[1] + 0.0722 * lineales[2]


def _contraste(a: str, b: str) -> float:
    claro, oscuro = sorted((_luminancia(a), _luminancia(b)), reverse=True)
    return (claro + 0.05) / (oscuro + 0.05)


@pytest.mark.parametrize(
    ("texto", "fondo"),
    [
        (TINTA, BLANCO),
        (OXIDO, BLANCO),
        (SECUNDARIO, BLANCO),
        (BLANCO, OXIDO),
        (TINTA, PAPEL),
    ],
)
def test_todo_texto_cumple_aa(texto: str, fondo: str) -> None:
    assert _contraste(texto, fondo) >= 4.5


def test_el_naranja_claro_no_sirve_para_texto() -> None:
    """Por eso no está en la paleta del correo."""
    assert _contraste(_NARANJA_CLARO, BLANCO) < 4.5
    paleta = {v.upper() for k, v in vars(email_html).items() if k.isupper() and isinstance(v, str)}
    assert _NARANJA_CLARO not in paleta


def test_contar_concuerda() -> None:
    assert contar(1, "solicitud", "solicitudes") == "1 solicitud"
    assert contar(3, "solicitud", "solicitudes") == "3 solicitudes"
    assert contar(0, "licitación nueva", "licitaciones nuevas") == "0 licitaciones nuevas"


def test_abrir_documento_declara_idioma_y_esquema_claro() -> None:
    cabeza = abrir_documento()
    assert cabeza.startswith('<!DOCTYPE html><html lang="es">')
    assert '<meta name="color-scheme" content="light">' in cabeza
    assert '<meta name="supported-color-schemes" content="light">' in cabeza


_COLORES_FUERA_DE_MARCA = ("#1d4ed8", "#1a5276", "#0e7490", "#1f2733", "#55606e", "#8a93a0")


def _comprobar_html(html: str) -> None:
    assert '<html lang="es">' in html
    assert '<meta name="color-scheme" content="light">' in html
    assert html.endswith("</body></html>")
    for color in (*_COLORES_FUERA_DE_MARCA, "#e5e8ec", "#777", "#555", _NARANJA_CLARO):
        assert color.lower() not in html.lower()
    # Cuerpo y tablas a 14 px como mínimo; 12 px queda para el pie legal.
    tamanos = {int(t) for t in re.findall(r"font-size:(\d+)px", html)}
    assert tamanos <= {12, 14, 15}


def _lic(i: int) -> dict[str, object]:
    return {
        "id_externo": f"L-{i}",
        "titulo": f"Licitación <{i}>",
        "organo_contratacion": "Ayuntamiento",
        "importe": 1000.0,
        "fecha_limite": "2026-10-15",
    }


def test_digest_con_marca_y_plural_concordado() -> None:
    texto, html = render_digest(
        bloques=[BloqueDigest(etiqueta="SAP", licitaciones=[_lic(1)])],
        frecuencia="daily",
        base_url="https://app.example",
        baja_url="https://app.example/baja?k=a&t=b",
    )
    _comprobar_html(html)
    assert texto.startswith("1 licitación nueva de hoy")
    assert "(es)" not in texto and "(s)" not in texto
    assert f"color:{OXIDO}" in html
    assert "&lt;1&gt;" in html and "<1>" not in html

    texto_varias, _ = render_digest(
        bloques=[BloqueDigest(etiqueta="SAP", licitaciones=[_lic(1), _lic(2)])],
        frecuencia="daily",
        base_url=None,
        baja_url=None,
    )
    assert texto_varias.startswith("2 licitaciones nuevas de hoy")


def test_evento_con_marca() -> None:
    _, html = render_evento(
        titulo="Te han asignado <x>", cuerpo="Cuerpo", licitacion_id="L-1", base_url="https://a"
    )
    _comprobar_html(html)
    assert "&lt;x&gt;" in html


def test_informe_tutea_y_tabla_accesible() -> None:
    informe = InformeSemanal(
        organization_id=1,
        organizacion="ACME <SA>",
        generado_en=datetime(2026, 9, 14, 7, 30, tzinfo=UTC),
        desde=date(2026, 9, 7),
        hasta=date(2026, 9, 13),
        abiertas_por_estado={"en_estudio": 2},
        vencimientos=[Vencimiento("L-1", "Título <b>", "2026-09-16", 2)],
    )
    html = render_html(informe, url_baja="https://x.test/baja?a=1&b=2")
    _comprobar_html(html)
    assert html.startswith("<!DOCTYPE html>")
    assert "si abres este correo ni en qué haces clic" in html
    assert "abrís" not in html and "hacéis" not in html
    assert html.count("<thead>") == 2
    assert html.count("<th scope='col'") == 2 + 5
    assert "Título &lt;b&gt;" in html
    assert "a=1&amp;b=2" in html


def test_correo_de_acceso_con_boton_de_marca() -> None:
    texto, html = _cuerpo_acceso("<script>", "https://x.example/login", "ana@empresa.example")
    _comprobar_html(html)
    assert f"background:{OXIDO};color:{BLANCO}" in html
    assert "&lt;script&gt;" in html and "<script>" not in html
    assert "https://x.example/login" in texto


@pytest.mark.parametrize(("pendientes", "esperado"), [(1, "1 solicitud "), (4, "4 solicitudes ")])
def test_aviso_al_operador_concuerda(pendientes: int, esperado: str) -> None:
    from services.solicitudes_acceso import avisar_operador_de_solicitud

    with (
        patch("services.solicitudes_acceso._dentro_de_la_ventana_de_aviso", return_value=True),
        patch("services.solicitudes_acceso.notify") as notify,
    ):
        assert avisar_operador_de_solicitud(
            solicitud_id=1, empresa=None, origen=None, pendientes=pendientes
        )
    mensaje = notify.call_args.args[2]
    assert esperado in mensaje
    assert "(es)" not in mensaje

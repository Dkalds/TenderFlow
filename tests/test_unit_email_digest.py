"""El digest de watchlist es un correo de producto, no una alerta de operación.

Funciones puras de ``services/email_digest.py``: sin SMTP ni base de datos.
"""

from __future__ import annotations

from services.email_digest import (
    BloqueDigest,
    asunto_digest,
    enlace_ficha,
    etiqueta_de_regla,
    render_digest,
    token_de_baja,
    url_de_baja_alertas,
    verificar_token_de_baja,
)

_LIC = {
    "id_externo": "PA-S 2026/000058",
    "titulo": "Implantación de SAP S/4HANA <corporativo>",
    "organo_contratacion": "Ayuntamiento de Prueba",
    "importe": 250000.0,
    "fecha_limite": "2026-10-15T12:00:00+00:00",
    "ccaa": "Madrid",
    "tecnologia": "SAP",
    "url": "https://contrataciondelestado.es/x",
}


def test_etiqueta_prefiere_el_nombre_de_la_regla() -> None:
    assert (
        etiqueta_de_regla(nombre="SAP Madrid", keyword="sap", cpv=None, min_importe=None, ccaa=None)
        == "SAP Madrid"
    )


def test_etiqueta_sin_nombre_describe_los_criterios() -> None:
    etiqueta = etiqueta_de_regla(
        nombre=None, keyword="sap", cpv="72", min_importe=100000, ccaa="Madrid"
    )
    assert "«sap»" in etiqueta
    assert "CPV 72" in etiqueta
    assert "100.000 €" in etiqueta
    assert "Madrid" in etiqueta


def test_asunto_sin_prefijo_de_severidad() -> None:
    asunto = asunto_digest("daily", 3)
    assert asunto.startswith("TenderFlow")
    assert "[INFO]" not in asunto
    assert "3 licitaciones nuevas de hoy" in asunto
    assert "1 licitación nueva" in asunto_digest("immediate", 1)


def test_enlace_ficha_apunta_a_la_consola_cuando_hay_sitio() -> None:
    assert (
        enlace_ficha(_LIC, "https://app.example")
        == "https://app.example/detalle?lic=PA-S%202026%2F000058"
    )
    assert enlace_ficha(_LIC, None) == "https://contrataciondelestado.es/x"


def test_render_incluye_datos_y_escapa_html() -> None:
    texto, html = render_digest(
        bloques=[BloqueDigest(etiqueta="SAP Madrid", licitaciones=[_LIC])],
        frecuencia="daily",
        base_url="https://app.example",
        baja_url="https://app.example/api/v1/watchlist/rules/baja?k=abc&t=kid.sig",
    )
    assert "Implantación de SAP S/4HANA <corporativo>" in texto
    assert "Ayuntamiento de Prueba" in texto
    assert "250.000 €" in texto
    assert "2026-10-15" in texto
    assert "https://app.example/detalle?lic=PA-S%202026%2F000058" in texto
    assert "Dejar de recibir estos correos" in texto
    # El título con `<corporativo>` no puede llegar al HTML sin escapar.
    assert "&lt;corporativo&gt;" in html
    assert "<corporativo>" not in html
    assert 'href="https://app.example/detalle?lic=PA-S%202026%2F000058"' in html
    assert "k=abc&amp;t=kid.sig" in html


def test_render_recorta_por_bloque_y_declara_el_resto() -> None:
    lics = [{**_LIC, "id_externo": f"L-{i}", "titulo": f"Licitación {i}"} for i in range(12)]
    texto, html = render_digest(
        bloques=[BloqueDigest(etiqueta="Todo", licitaciones=lics)],
        frecuencia="weekly",
        base_url=None,
        baja_url=None,
    )
    assert "Licitación 9" in texto
    assert "Licitación 10" not in texto
    assert "y 2 más" in texto
    assert "y 2 más" in html


def test_token_de_baja_verifica_y_rechaza_manipulaciones() -> None:
    token = token_de_baja("clave-de-prueba-a")
    assert token is not None
    assert verificar_token_de_baja("clave-de-prueba-a", token)
    assert not verificar_token_de_baja("clave-de-prueba-b", token)
    assert not verificar_token_de_baja("clave-de-prueba-a", token + "x")
    assert token_de_baja("") is None


def test_url_de_baja_lleva_user_key_y_firma() -> None:
    url = url_de_baja_alertas("clave-de-prueba-a", "https://app.example")
    assert url is not None
    assert url.startswith("https://app.example/api/v1/watchlist/rules/baja?")
    assert "k=clave-de-prueba-a" in url
    assert "t=" in url
    assert url_de_baja_alertas("clave-de-prueba-a", None) is None

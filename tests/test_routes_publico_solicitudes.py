"""Tests de ``POST /api/v1/publico/solicitudes-acceso``.

Es el único endpoint público de escritura de la API, así que lo que se fija
aquí no es tanto el camino feliz como los que impiden que se convierta en un
problema: nunca un 5xx (``scripts/fuzz_api_contract.py`` mantiene ``KNOWN_5XX``
a cero), nada guardado sin consentimiento explícito, y el campo trampa
respondiendo como si todo hubiera ido bien para no enseñarle al bot dónde está.
"""

from __future__ import annotations

import pytest

RUTA = "/api/v1/publico/solicitudes-acceso"
FORM = {"Content-Type": "application/x-www-form-urlencoded"}


def _contar() -> int:
    from db.solicitudes_acceso import contar_pendientes

    return contar_pendientes()


def test_envio_valido_redirige_y_persiste(client):
    antes = _contar()

    r = client.post(
        RUTA,
        content="email=ana%40empresa.example&empresa=Empresa&consentimiento=si&origen=landing",
        headers=FORM,
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert r.headers["location"] == "/solicitud-recibida"
    assert _contar() == antes + 1


def test_sin_consentimiento_no_guarda(client):
    """Sin la casilla marcada no hay base para guardar un dato de contacto."""
    antes = _contar()

    r = client.post(RUTA, content="email=b%40e.example", headers=FORM, follow_redirects=False)

    assert r.status_code == 303
    assert "estado=error" in r.headers["location"]
    assert _contar() == antes


@pytest.mark.parametrize("email", ["", "noesunemail", "sin@arroba", "a@b", "@dominio.example"])
def test_email_invalido_no_guarda(client, email):
    antes = _contar()

    r = client.post(
        RUTA,
        content=f"email={email}&consentimiento=si",
        headers=FORM,
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert "estado=error" in r.headers["location"]
    assert _contar() == antes


def test_honeypot_finge_exito_pero_no_guarda(client):
    """Un bot que rellena el campo trampa recibe el mismo 303 de éxito.

    Devolver un error le diría exactamente qué campo evitar la próxima vez.
    """
    antes = _contar()

    r = client.post(
        RUTA,
        content="email=bot%40spam.example&consentimiento=si&website=http%3A%2F%2Fspam",
        headers=FORM,
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert r.headers["location"] == "/solicitud-recibida"
    assert _contar() == antes


def test_json_no_es_un_formulario(client):
    """El endpoint sirve a un `<form>` HTML; nada más entra."""
    antes = _contar()

    r = client.post(RUTA, json={"email": "x@y.example"}, follow_redirects=False)

    assert r.status_code == 303
    assert "estado=error" in r.headers["location"]
    assert _contar() == antes


def test_cuerpo_basura_no_da_5xx(client):
    """Entrada de internet, salida limpia: el fuzzer del contrato exige 0 5xx."""
    r = client.post(RUTA, content=b"\xff\xfe%%%=&&&", headers=FORM, follow_redirects=False)

    assert r.status_code < 500


def test_campos_largos_se_recortan_sin_romper(client):
    antes = _contar()

    r = client.post(
        RUTA,
        content="email=larga%40e.example&consentimiento=si&empresa=" + "x" * 5000,
        headers=FORM,
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert _contar() == antes + 1

    from db.solicitudes_acceso import listar_solicitudes

    guardada = listar_solicitudes(limit=1)[0]
    assert guardada["empresa"] is not None
    assert len(guardada["empresa"]) <= 200


def test_no_requiere_autenticacion(client):
    """La superficie pública no exige sesión: si la exigiera, el CTA moriría."""
    r = client.post(
        RUTA,
        content="email=anon%40e.example&consentimiento=si",
        headers=FORM,
        follow_redirects=False,
    )

    assert r.status_code != 401
    assert r.status_code != 403

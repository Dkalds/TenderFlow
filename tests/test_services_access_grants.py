"""Regla de las concesiones de acceso: qué no se puede conceder por dominio.

El formulario de solicitud es público y anónimo. Una solicitud enviada desde
una cuenta de Gmail y un clic en «Conceder dominio» dejaban entrar a cualquier
cuenta de Gmail: lo que el administrador aprueba es a una persona, no a un
proveedor de correo entero.
"""

from __future__ import annotations

import pytest

from db.access_grants import ConcesionInvalida
from services.access_grants import DOMINIOS_DE_CORREO_PUBLICO, validar_concesion

#: La lista que se decidió, escrita otra vez aquí a propósito: que alguien
#: quite un dominio de la constante tiene que romper un test, no pasar
#: desapercibido porque el test lee la misma constante que comprueba.
_PROVEEDORES_PUBLICOS = (
    "gmail.com",
    "googlemail.com",
    "outlook.com",
    "outlook.es",
    "hotmail.com",
    "hotmail.es",
    "live.com",
    "msn.com",
    "yahoo.com",
    "yahoo.es",
    "icloud.com",
    "me.com",
    "proton.me",
    "protonmail.com",
    "gmx.com",
    "gmx.es",
    "aol.com",
    "zoho.com",
    "yandex.com",
    "mail.com",
    "telefonica.net",
    "movistar.es",
    "orange.es",
    "ono.com",
)


def test_la_lista_es_la_que_se_decidio():
    assert frozenset(_PROVEEDORES_PUBLICOS) == DOMINIOS_DE_CORREO_PUBLICO


@pytest.mark.parametrize("dominio", _PROVEEDORES_PUBLICOS)
def test_el_dominio_de_un_proveedor_publico_no_se_concede(dominio):
    with pytest.raises(ConcesionInvalida) as rechazo:
        validar_concesion("domain", dominio)

    # El mensaje llega tal cual al administrador (422): dice qué dominio es y
    # qué hacer en su lugar.
    mensaje = str(rechazo.value)
    assert dominio in mensaje
    assert "email" in mensaje.lower()


@pytest.mark.parametrize("dominio", _PROVEEDORES_PUBLICOS)
def test_el_email_de_esos_mismos_proveedores_si_se_concede(dominio):
    validar_concesion("email", f"quien-sea@{dominio}")


@pytest.mark.parametrize(
    "dominio",
    [
        "empresa.example",
        # Parecerse a un proveedor público no es serlo: la lista es exacta.
        "gmail.com.empresa.example",
        "migmail.com",
    ],
)
def test_el_dominio_de_una_empresa_se_concede(dominio):
    validar_concesion("domain", dominio)

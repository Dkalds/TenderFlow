"""La ficha de la oportunidad lee las puntuaciones del acta y la fila propia se confirma por PATCH.

Contra Postgres y la API con sesión real (``tests/escenarios.py``): lo que se
prueba es que la confirmación llega al ledger con su actor, que se lee de vuelta
en la ficha, y que un PATCH que solo la lleva no toca la oportunidad (ni su
versión). Sin endpoint nuevo: es el ``PATCH /pursuits/{id}`` de siempre.
"""

from __future__ import annotations

from typing import Any, cast

from db.database import connect
from db.repositories.documentos import TIPO_ACTA
from db.repositories.puntuaciones_acta import PuntuacionesActaRepository, PuntuacionNueva
from services.normalization import normalize_company
from tests.escenarios import Sesion, abrir_sesion, sembrar_licitacion

_LIC = "EXP-ESC-ACTA"
_AHORA = "2026-11-01T10:00:00+00:00"

_ASAP = "ASAP GLOBAL SOLUTION S.L."
_ADELANTE = "ADELANTE SERVICIOS INFORMÁTICOS S.L."
_ASAP_N = normalize_company(_ASAP)
_ADELANTE_N = normalize_company(_ADELANTE)


def _abrir_oportunidad(sesion: Sesion, licitacion_id: str = _LIC) -> int:
    creada = sesion.post(
        "/pursuits",
        json={"licitacion_id": licitacion_id, "organization_id": sesion.organization_id},
    )
    assert creada.status_code == 201, creada.text
    return int(creada.json()["id"])


def _fila(
    documento_id: int, licitador: str, criterio: str | None, puntos: float
) -> PuntuacionNueva:
    return cast(
        "PuntuacionNueva",
        {
            "lote_numero": "1",
            "licitador_nombre": licitador,
            "licitador_normalizado": normalize_company(licitador),
            "criterio": criterio,
            "puntos": puntos,
            "puntos_max": None
            if criterio is None
            else (65.0 if criterio == "Oferta económica" else 30.0),
            "es_precio": None if criterio is None else criterio == "Oferta económica",
            "excluida": False,
            "documento_id": documento_id,
            "pagina": 2,
            "cita": f"{licitador} {criterio or 'total'}",
        },
    )


def _sembrar_adjudicacion(licitacion_id: str) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO adjudicaciones "
            "(licitacion_id, nombre, nif, importe_adjudicado, fecha_extraccion) "
            "VALUES (%s, %s, %s, %s, %s)",
            (licitacion_id, _ASAP, None, 100_000.0, _AHORA),
        )


def _sembrar_acta(licitacion_id: str, *, leida: bool = True) -> None:
    """La adjudicación, el documento ``acta`` y, si ``leida``, su lectura (lote 1, dos licitadores)."""
    _sembrar_adjudicacion(licitacion_id)
    with connect() as c:
        documento_id = int(
            c.execute(
                "INSERT INTO documentos (licitacion_id, tipo, uri) VALUES (%s, %s, %s) "
                "RETURNING id",
                (licitacion_id, TIPO_ACTA, "https://placsp.example/acta-mesa.pdf"),
            ).fetchone()[0]
        )
    if not leida:
        return
    filas = [
        _fila(documento_id, _ASAP, "Informe técnico", 30),
        _fila(documento_id, _ASAP, "Oferta económica", 65),
        _fila(documento_id, _ASAP, None, 100),
        _fila(documento_id, _ADELANTE, "Informe técnico", 28),
        _fila(documento_id, _ADELANTE, "Oferta económica", 44.54),
        _fila(documento_id, _ADELANTE, None, 72.54),
    ]
    PuntuacionesActaRepository().guardar(
        licitacion_id,
        status="ok",
        extraction_version="acta-puntuaciones-v1",
        model="modelo-de-prueba",
        documentos_leidos=1,
        error_detail=None,
        filas=filas,
    )


def _lote_1(detalle: dict[str, Any]) -> dict[str, Any]:
    puntuaciones = detalle["adjudicacion"]["puntuaciones"]
    assert puntuaciones["estado"] == "ok"
    lote: dict[str, Any] = puntuaciones["lotes"][0]
    return lote


def _licitador(lote: dict[str, Any], indice: int | None) -> str:
    assert indice is not None
    return str(lote["filas"][indice]["licitador_normalizado"])


def test_patch_fila_acta_anota_el_ledger_y_se_lee_confirmada(client, api_db):
    sembrar_licitacion(_LIC, "Soporte y mantenimiento")
    sesion = abrir_sesion("fila-acta@example.com", client)
    pid = _abrir_oportunidad(sesion)
    _sembrar_acta(_LIC)

    # Antes de confirmar: el adjudicatario publicado es la ganadora y no hay propuesta
    # (el nombre de la organización no casa con ningún licitador).
    antes = _lote_1(sesion.get(f"/pursuits/{pid}").json())
    assert _licitador(antes, antes["fila_ganadora"]) == _ASAP_N
    assert antes["ganadora_es_mayor_puntuacion"] is False
    assert antes["fila_propia"] is None
    assert antes["fila_propia_confirmada"] is False
    assert antes["diferencia"] == []

    ref = {"lote_numero": "1", "licitador_normalizado": _ADELANTE_N}
    respuesta = sesion.patch(f"/pursuits/{pid}", json={"fila_acta": ref})
    assert respuesta.status_code == 200, respuesta.text

    lote = _lote_1(respuesta.json())
    assert lote["fila_propia_confirmada"] is True
    assert _licitador(lote, lote["fila_propia"]) == _ADELANTE_N
    # Se perdió casi todo en la oferta económica (-20,46 de 65) y poco en lo técnico (-2).
    assert lote["motivo_sugerido"] == "precio"
    por_criterio = {d["criterio"]: d for d in lote["diferencia"]}
    assert por_criterio["Oferta económica"]["diferencia"] == -20.46
    assert por_criterio[None]["diferencia"] == -27.46

    # Queda en el ledger con quien la confirmó, y se lee igual en un GET posterior.
    detalle = sesion.get(f"/pursuits/{pid}").json()
    eventos = [e for e in detalle["events"] if e["event_type"] == "fila_acta_confirmada"]
    assert len(eventos) == 1
    assert eventos[0]["payload"] == ref
    assert eventos[0]["actor_user_id"] == sesion.user_id
    assert _lote_1(detalle)["fila_propia_confirmada"] is True

    # Una confirmación posterior del mismo lote manda sobre la anterior.
    otra = sesion.patch(
        f"/pursuits/{pid}",
        json={"fila_acta": {"lote_numero": "1", "licitador_normalizado": _ASAP_N}},
    )
    assert otra.status_code == 200, otra.text
    lote = _lote_1(otra.json())
    assert _licitador(lote, lote["fila_propia"]) == _ASAP_N
    assert lote["diferencia"] == []
    assert lote["motivo_sugerido"] is None


def test_patch_fila_acta_inexistente_es_422(client, api_db):
    sembrar_licitacion(_LIC, "Soporte y mantenimiento")
    sesion = abrir_sesion("fila-inexistente@example.com", client)
    pid = _abrir_oportunidad(sesion)
    _sembrar_acta(_LIC)
    antes = sesion.get(f"/pursuits/{pid}").json()

    # Ni el licitador ni el lote están en el acta leída.
    for ref in (
        {"lote_numero": "1", "licitador_normalizado": "NADIE S.L."},
        {"lote_numero": "7", "licitador_normalizado": _ADELANTE_N},
    ):
        respuesta = sesion.patch(
            f"/pursuits/{pid}", json={"fila_acta": ref, "next_action": "Llamar al órgano"}
        )
        assert respuesta.status_code == 422, respuesta.text
        assert "acta" in respuesta.json()["detail"]

    # Y no se aplicó nada, tampoco lo otro que iba en el mismo PATCH.
    despues = sesion.get(f"/pursuits/{pid}").json()
    assert despues["version"] == antes["version"]
    assert despues["next_action"] is None
    assert [e["event_type"] for e in despues["events"]] == [
        e["event_type"] for e in antes["events"]
    ]


def test_patch_solo_fila_acta_no_sube_la_version(client, api_db):
    sembrar_licitacion(_LIC, "Soporte y mantenimiento")
    sesion = abrir_sesion("fila-version@example.com", client)
    pid = _abrir_oportunidad(sesion)
    _sembrar_acta(_LIC)
    version = sesion.get(f"/pursuits/{pid}").json()["version"]
    ref = {"lote_numero": "1", "licitador_normalizado": _ADELANTE_N}

    solo_la_fila = sesion.patch(f"/pursuits/{pid}", json={"fila_acta": ref})
    assert solo_la_fila.status_code == 200, solo_la_fila.text
    assert solo_la_fila.json()["version"] == version
    tipos = [e["event_type"] for e in solo_la_fila.json()["events"]]
    assert "pursuit.updated" not in tipos
    assert tipos.count("fila_acta_confirmada") == 1

    # Con otro cambio en el mismo PATCH sí hay actualización, y la fila no pasa por las columnas.
    con_cambio = sesion.patch(
        f"/pursuits/{pid}", json={"fila_acta": ref, "next_action": "Pedir vista del expediente"}
    )
    assert con_cambio.status_code == 200, con_cambio.text
    assert con_cambio.json()["version"] == version + 1
    assert con_cambio.json()["next_action"] == "Pedir vista del expediente"
    assert _lote_1(con_cambio.json())["fila_propia_confirmada"] is True


def test_repetir_el_patch_con_la_misma_clave_no_anota_otra_fila(client, api_db):
    sembrar_licitacion(_LIC, "Soporte y mantenimiento")
    sesion = abrir_sesion("fila-idempotente@example.com", client)
    pid = _abrir_oportunidad(sesion)
    _sembrar_acta(_LIC)
    ref = {"lote_numero": "1", "licitador_normalizado": _ADELANTE_N}

    # Solo la fila, y la fila con otro cambio: en los dos caminos un reintento no duplica.
    for clave, cuerpo in (
        ("reintento-solo-fila", {"fila_acta": ref}),
        ("reintento-con-cambio", {"fila_acta": ref, "next_action": "Pedir vista"}),
    ):
        for _ in range(2):
            respuesta = sesion.client.patch(
                f"/api/v1/pursuits/{pid}",
                json=cuerpo,
                headers={**sesion.cab, "X-Idempotency-Key": clave},
            )
            assert respuesta.status_code == 200, respuesta.text

    tipos = [e["event_type"] for e in sesion.get(f"/pursuits/{pid}").json()["events"]]
    assert tipos.count("fila_acta_confirmada") == 2
    assert tipos.count("pursuit.updated") == 1


def test_la_ficha_distingue_acta_sin_leer_de_expediente_sin_acta(client, api_db):
    sembrar_licitacion("EXP-ESC-ACTA-PENDIENTE", "Con acta, sin leer")
    sembrar_licitacion("EXP-ESC-SIN-ACTA", "Sin acta")
    sesion = abrir_sesion("fila-estados@example.com", client)
    pendiente = _abrir_oportunidad(sesion, "EXP-ESC-ACTA-PENDIENTE")
    sin_acta = _abrir_oportunidad(sesion, "EXP-ESC-SIN-ACTA")
    _sembrar_acta("EXP-ESC-ACTA-PENDIENTE", leida=False)
    _sembrar_adjudicacion("EXP-ESC-SIN-ACTA")

    con_acta = sesion.get(f"/pursuits/{pendiente}").json()["adjudicacion"]["puntuaciones"]
    assert con_acta == {"estado": "pendiente", "lotes": []}
    assert sesion.get(f"/pursuits/{sin_acta}").json()["adjudicacion"]["puntuaciones"] is None

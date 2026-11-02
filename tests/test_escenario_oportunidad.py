"""Escenarios de la oportunidad: del expediente a la cartera.

Cada test es un recorrido completo por la API con sesión real. Ver
``tests/escenarios.py`` y ``docs/casos-de-uso.md``.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from db.database import connect
from db.repositories.documentos import TIPO_ACTA, DocumentosRepository
from services.normalization import normalize_company
from services.puntuaciones_acta import extraer_puntuaciones
from tests.escenarios import abrir_sesion, sembrar_licitacion


def _abrir_oportunidad(sesion, licitacion_id: str) -> dict:
    creada = sesion.post(
        "/pursuits",
        json={"licitacion_id": licitacion_id, "organization_id": sesion.organization_id},
    )
    assert creada.status_code == 201, creada.text
    return creada.json()


def _mover(sesion, pursuit_id: int, **cambios):
    return sesion.patch(f"/pursuits/{pursuit_id}", json=cambios)


def test_cu05_cu06_cu07_oportunidad_ganada_de_punta_a_punta(client, api_db):
    """CU-05, CU-06, CU-07 — abrir, decidir con la matriz, preparar, presentar y ganar.

    El recorrido que da sentido al producto: un expediente se convierte en
    oportunidad, se puntúa, se decide GO, se prepara con tareas, se presenta, se
    gana y aparece en la cartera con su importe.
    """
    sembrar_licitacion("EXP-ESC-GANADA", "Migración a S/4HANA")
    sesion = abrir_sesion("ganadora@example.com", client)

    # CU-05 — abrir la oportunidad desde el expediente.
    oportunidad = _abrir_oportunidad(sesion, "EXP-ESC-GANADA")
    pid = oportunidad["id"]
    assert oportunidad["status"] == "identified"
    assert oportunidad["decision"] == "pending"
    assert oportunidad["tender_title"] == "Migración a S/4HANA"

    # Abrirla dos veces no la duplica: la consola puede reintentar.
    repetida = sesion.post(
        "/pursuits",
        json={"licitacion_id": "EXP-ESC-GANADA", "organization_id": sesion.organization_id},
    )
    assert repetida.status_code in (200, 201, 409), repetida.text
    listado = sesion.get("/pursuits", params={"organization_id": sesion.organization_id}).json()
    assert listado["total"] == 1

    # CU-06 — la matriz go/no-go: sin puntuar no recomienda; puntuada, sí.
    vacia = sesion.get(f"/pursuits/{pid}/go-no-go").json()
    assert vacia["criterios_puntuados"] == 0
    assert vacia["completa"] is False
    for criterio in ("encaje", "capacidad", "competencia", "rentabilidad", "riesgo"):
        puntuada = sesion.put(
            f"/pursuits/{pid}/go-no-go",
            json={"criterio": criterio, "puntuacion": 5, "motivo": "Referencia directa"},
        )
        assert puntuada.status_code == 200, puntuada.text
    matriz = puntuada.json()
    assert matriz["completa"] is True
    assert matriz["total"] == 5
    assert matriz["recomendacion"] == "go"

    # Preparar la oferta sin decisión no se puede: la regla vive en el servidor.
    sin_decidir = _mover(sesion, pid, status="preparing")
    assert sin_decidir.status_code == 409, sin_decidir.text
    # Un GO sin motivo tampoco.
    sin_motivo = _mover(sesion, pid, decision="go")
    assert sin_motivo.status_code == 422, sin_motivo.text

    # Con GO y motivo, el atajo lleva de «identificada» a «preparando» de una vez.
    preparando = _mover(
        sesion, pid, decision="go", decision_reason="Encaje total", status="preparing"
    )
    assert preparando.status_code == 200, preparando.text
    assert preparando.json()["status"] == "preparing"
    assert sesion.get(f"/pursuits/{pid}/go-no-go").json()["discrepa"] is False

    # CU-07 — tareas de la preparación.
    tarea = sesion.post(
        f"/pursuits/{pid}/tasks", json={"titulo": "Redactar memoria técnica", "vence": "2026-12-20"}
    )
    assert tarea.status_code == 201, tarea.text
    tid = tarea.json()["id"]
    assert tarea.json()["estado"] == "pendiente"
    hecha = sesion.patch(f"/pursuits/{pid}/tasks/{tid}", json={"estado": "hecha"})
    assert hecha.status_code == 200, hecha.text
    tareas = sesion.get(f"/pursuits/{pid}/tasks").json()
    assert {t["id"]: t["estado"] for t in tareas}[tid] == "hecha"

    # Ganar sin haber presentado no se puede.
    sin_presentar = _mover(sesion, pid, status="won", awarded_amount_eur=240_000)
    assert sin_presentar.status_code == 409, sin_presentar.text

    presentada = _mover(sesion, pid, status="submitted", offer_price_eur=240_000)
    assert presentada.status_code == 200, presentada.text
    assert presentada.json()["submitted_at"] is not None

    ganada = _mover(sesion, pid, status="won", awarded_amount_eur=240_000)
    assert ganada.status_code == 200, ganada.text
    cuerpo = ganada.json()
    assert (cuerpo["status"], cuerpo["outcome"]) == ("won", "won")
    assert cuerpo["closed_at"] is not None

    # Un estado terminal no se reabre.
    reabierta = _mover(sesion, pid, status="preparing")
    assert reabierta.status_code == 409, reabierta.text

    # El historial cuenta el recorrido entero, y el embudo lo refleja.
    detalle = sesion.get(f"/pursuits/{pid}").json()
    assert len(detalle["events"]) >= 4
    metricas = sesion.get("/pursuits/metrics").json()
    assert metricas["pursuits_identified"] == 1
    assert metricas["pursuits_won"] == 1
    assert metricas["awarded_amount_eur"] == 240_000

    # La ganada pasa sola a la cartera, con su importe.
    cartera = sesion.get("/pursuits/cartera").json()
    assert [c["pursuit_id"] for c in cartera] == [pid]
    assert cartera[0]["importe_adjudicado"] == 240_000
    assert cartera[0]["licitacion_id"] == "EXP-ESC-GANADA"


def test_cu08_cartera_fecha_de_fin_y_renovacion(client, api_db):
    """CU-08 — del contrato ganado a la oportunidad de su relicitación."""
    sembrar_licitacion("EXP-ESC-CONTRATO", "Soporte SAP 2026")
    sembrar_licitacion("EXP-ESC-RELICITA", "Soporte SAP 2028")
    sesion = abrir_sesion("cartera@example.com", client)
    pid = _abrir_oportunidad(sesion, "EXP-ESC-CONTRATO")["id"]
    assert (
        _mover(
            sesion, pid, decision="go", decision_reason="Cliente actual", status="preparing"
        ).status_code
        == 200
    )
    assert _mover(sesion, pid, status="submitted").status_code == 200
    assert _mover(sesion, pid, status="won", awarded_amount_eur=90_000).status_code == 200

    (contrato,) = sesion.get("/pursuits/cartera").json()
    cid = contrato["id"]
    assert contrato["renovacion_pursuit_id"] is None

    # La fuente no publicó fin: se pone a mano y queda dicho de dónde sale.
    con_fin = sesion.patch(f"/pursuits/cartera/{cid}", json={"fecha_fin": "2028-06-30"})
    assert con_fin.status_code == 200, con_fin.text
    assert con_fin.json()["fecha_fin_efectiva"].startswith("2028-06-30")
    assert con_fin.json()["fecha_fin_origen"] == "manual"

    resumen = sesion.get("/pursuits/cartera/resumen").json()
    assert resumen["contratos_vivos"] == 1
    assert resumen["importe_en_ejecucion_eur"] == 90_000

    # El mismo expediente no es su propia relicitación.
    misma = sesion.post(
        f"/pursuits/cartera/{cid}/renovacion", json={"licitacion_id": "EXP-ESC-CONTRATO"}
    )
    assert misma.status_code == 422, misma.text

    renovacion = sesion.post(
        f"/pursuits/cartera/{cid}/renovacion", json={"licitacion_id": "EXP-ESC-RELICITA"}
    )
    assert renovacion.status_code in (200, 201), renovacion.text
    assert renovacion.json()["creada"] is True
    nueva = renovacion.json()["renovacion_pursuit_id"]

    # Prepararla otra vez devuelve la misma, no una segunda.
    otra_vez = sesion.post(
        f"/pursuits/cartera/{cid}/renovacion", json={"licitacion_id": "EXP-ESC-RELICITA"}
    )
    assert otra_vez.json() == {**renovacion.json(), "creada": False}

    abiertas = sesion.get("/pursuits").json()
    assert {p["id"]: p["licitacion_id"] for p in abiertas["items"]}[nueva] == "EXP-ESC-RELICITA"
    (contrato,) = sesion.get("/pursuits/cartera").json()
    assert contrato["renovacion_pursuit_id"] == nueva


def test_cu05_oportunidad_perdida_exige_motivo_y_alimenta_el_reparto(client, api_db):
    """CU-05 — perder exige decir por qué, y el motivo llega a las métricas."""
    sembrar_licitacion("EXP-ESC-PERDIDA", "Licencias y soporte")
    sesion = abrir_sesion("perdedora@example.com", client)
    pid = _abrir_oportunidad(sesion, "EXP-ESC-PERDIDA")["id"]
    assert (
        _mover(sesion, pid, decision="go", decision_reason="Vale", status="preparing").status_code
        == 200
    )
    assert _mover(sesion, pid, status="submitted").status_code == 200

    sin_codigo = _mover(sesion, pid, status="lost")
    assert sin_codigo.status_code == 422, sin_codigo.text
    assert sesion.get(f"/pursuits/{pid}").json()["status"] == "submitted"

    perdida = _mover(sesion, pid, status="lost", outcome_reason_code="precio")
    assert perdida.status_code == 200, perdida.text
    assert perdida.json()["outcome"] == "lost"

    # Ya cerrada, el motivo se puede corregir pero no borrar.
    borrado = sesion.patch(f"/pursuits/{pid}", json={"outcome_reason_code": None})
    assert borrado.status_code == 422, borrado.text
    corregido = _mover(sesion, pid, outcome_reason_code="solvencia")
    assert corregido.status_code == 200, corregido.text
    assert sesion.get(f"/pursuits/{pid}").json()["outcome_reason_code"] == "solvencia"

    metricas = sesion.get("/pursuits/metrics").json()
    assert metricas["pursuits_lost"] == 1
    assert metricas["win_rate"] == 0
    assert sesion.get("/pursuits/cartera").json() == []


def test_cu06_no_go_cierra_la_oportunidad_sin_pasar_por_la_oferta(client, api_db):
    """CU-06 — un NO-GO no puede seguir hacia la oferta: solo se retira."""
    sembrar_licitacion("EXP-ESC-NOGO", "Obra civil con algo de software")
    sesion = abrir_sesion("descarta@example.com", client)
    pid = _abrir_oportunidad(sesion, "EXP-ESC-NOGO")["id"]

    for criterio in ("encaje", "capacidad"):
        assert (
            sesion.put(
                f"/pursuits/{pid}/go-no-go", json={"criterio": criterio, "puntuacion": 1}
            ).status_code
            == 200
        )
    assert sesion.get(f"/pursuits/{pid}/go-no-go").json()["recomendacion"] == "no_go"

    # NO-GO y seguir preparando se contradicen.
    contradiccion = _mover(
        sesion, pid, decision="no_go", decision_reason="Fuera de foco", status="preparing"
    )
    assert contradiccion.status_code == 409, contradiccion.text

    retirada = _mover(
        sesion, pid, decision="no_go", decision_reason="Fuera de foco", status="withdrawn"
    )
    assert retirada.status_code == 200, retirada.text
    assert (retirada.json()["status"], retirada.json()["outcome"]) == ("withdrawn", "cancelled")


def test_cu05_un_null_en_un_campo_de_estado_no_toca_nada(client, api_db):
    """CU-05 — ``null`` en estado, decisión o resultado es «no tocar», no un 500.

    Regresión: ``{"decision": null}`` sobre una oportunidad con motivo escrito
    pasaba las guardas y reventaba en el UPDATE (columna NOT NULL).
    """
    sembrar_licitacion("EXP-ESC-NULL", "Expediente cualquiera")
    sesion = abrir_sesion("nulos@example.com", client)
    pid = _abrir_oportunidad(sesion, "EXP-ESC-NULL")["id"]
    assert _mover(sesion, pid, decision_reason="Lo estamos mirando").status_code == 200

    for campo in ("decision", "status", "outcome"):
        respuesta = sesion.patch(f"/pursuits/{pid}", json={campo: None})
        assert respuesta.status_code == 200, (campo, respuesta.text)

    detalle = sesion.get(f"/pursuits/{pid}").json()
    assert (detalle["status"], detalle["decision"], detalle["outcome"]) == (
        "identified",
        "pending",
        "pending",
    )
    assert detalle["decision_reason"] == "Lo estamos mirando"


# El acta de la mesa del expediente de ``test_cu05_perdida_con_puntuaciones_del_acta``:
# la ganadora saca más en los dos criterios y pierde la nuestra, sobre todo en precio.
_GANADORA = "Ganadora SL"
_NUESTRA = "Nuestra Empresa SL"
_FILA_GANADORA = f"{_GANADORA} 33 65 98"
_FILA_NUESTRA = f"{_NUESTRA} 31 44,54 75,54"
_PAGINAS_ACTA = [
    "ACTA DE LA MESA DE CONTRATACIÓN\nLOTE 1. Servicio de soporte y mantenimiento\n"
    "Se reúne la mesa para valorar las ofertas admitidas.",
    "VALORACIÓN DE LOS CRITERIOS DE ADJUDICACIÓN\nLOTE 1\n"
    "Licitador Informe técnico (sobre 35 puntos) Oferta económica (sobre 65 puntos) Total\n"
    f"{_FILA_GANADORA}\n{_FILA_NUESTRA}\n"
    "La puntuación total máxima es de 100 puntos.",
]


def _sembrar_acta_de_la_mesa(licitacion_id: str) -> int:
    """La adjudicación a la ganadora y el acta ``extracted`` con dos páginas; devuelve su id."""
    with connect() as c:
        c.execute(
            "INSERT INTO adjudicaciones "
            "(licitacion_id, nombre, nif, importe_adjudicado, fecha_extraccion) "
            "VALUES (%s, %s, %s, %s, %s)",
            (licitacion_id, _GANADORA, None, 240_000.0, "2026-11-01T10:00:00+00:00"),
        )
        documento_id = int(
            c.execute(
                "INSERT INTO documentos (licitacion_id, tipo, uri) VALUES (%s, %s, %s) "
                "RETURNING id",
                (licitacion_id, TIPO_ACTA, "https://placsp.example/acta-mesa.pdf"),
            ).fetchone()[0]
        )
    DocumentosRepository().mark_extracted(
        documento_id, texto="\n".join(_PAGINAS_ACTA), sha256="acta-escenario", pages=_PAGINAS_ACTA
    )
    return documento_id


def _lo_que_lee_el_modelo(documento_id: int) -> str:
    """El JSON que un modelo leería de la tabla de la página 2; las citas son filas del acta."""

    def fila(licitador: str, cita: str, tecnico: float, economica: float, total: float):
        return {
            "licitador": licitador,
            "criterios": [
                {"nombre": "Informe técnico", "puntos": tecnico, "maximo": 35},
                {"nombre": "Oferta económica", "puntos": economica, "maximo": 65},
            ],
            "total": total,
            "excluida": False,
            "cita": cita,
            "pagina": 2,
            "documento_id": documento_id,
        }

    return json.dumps(
        {
            "lotes": [
                {
                    "lote": "LOTE 1",
                    "filas": [
                        fila(_GANADORA, _FILA_GANADORA, 33, 65, 98),
                        fila(_NUESTRA, _FILA_NUESTRA, 31, 44.54, 75.54),
                    ],
                }
            ]
        }
    )


def test_cu05_perdida_con_puntuaciones_del_acta(client, api_db):
    """CU-05 — perder con el acta delante: la nota frente a la ganadora y el motivo propuesto.

    El recorrido del post-mortem: la mesa publicó acta con puntuaciones, el job las
    lee (con el modelo sustituido por un doble cuyas citas son texto del acta), la
    ficha de la oportunidad enseña la tabla sin adivinar cuál es nuestra empresa, la
    persona la marca, la diferencia por criterio propone «precio» y el cierre como
    perdida lleva ese motivo.
    """
    sembrar_licitacion("EXP-ESC-ACTA-PERDIDA", "Soporte y mantenimiento de aplicaciones")
    sesion = abrir_sesion("perdida-acta@example.com", client)
    pid = _abrir_oportunidad(sesion, "EXP-ESC-ACTA-PERDIDA")["id"]
    documento_id = _sembrar_acta_de_la_mesa("EXP-ESC-ACTA-PERDIDA")
    assert (
        _mover(sesion, pid, decision="go", decision_reason="Vale", status="preparing").status_code
        == 200
    )
    assert _mover(sesion, pid, status="submitted", offer_price_eur=250_000).status_code == 200

    # Con el acta publicada y sin leer, la ficha lo dice en vez de callar.
    antes = sesion.get(f"/pursuits/{pid}").json()["adjudicacion"]["puntuaciones"]
    assert antes == {"estado": "pendiente", "lotes": []}

    # El job: no descarga nada (ya está extraída) y el modelo devuelve la tabla.
    with (
        patch(
            "services.rag.fact_sheet.ensure_documents_ready",
            return_value={"attempted": 0, "extracted": 0, "error": 0, "sin_texto": 0},
        ),
        patch(
            "services.rag.fact_sheet._llamar_modelo",
            return_value=_lo_que_lee_el_modelo(documento_id),
        ),
    ):
        assert extraer_puntuaciones("EXP-ESC-ACTA-PERDIDA", model="modelo-de-prueba") == "ok"

    puntuaciones = sesion.get(f"/pursuits/{pid}").json()["adjudicacion"]["puntuaciones"]
    assert puntuaciones["estado"] == "ok"
    (lote,) = puntuaciones["lotes"]
    assert lote["lote_numero"] == "1"
    # Por total descendente: la ganadora publicada primero, y sin fila propia que adivinar.
    assert [f["licitador"] for f in lote["filas"]] == [_GANADORA, _NUESTRA]
    assert lote["fila_ganadora"] == 0
    assert lote["ganadora_es_mayor_puntuacion"] is False
    assert lote["fila_propia"] is None
    assert lote["fila_propia_confirmada"] is False
    assert lote["diferencia"] == []
    assert lote["motivo_sugerido"] is None

    # La persona marca su fila: llega la diferencia por criterio y el motivo propuesto.
    ref = {"lote_numero": "1", "licitador_normalizado": normalize_company(_NUESTRA)}
    confirmada = sesion.patch(f"/pursuits/{pid}", json={"fila_acta": ref})
    assert confirmada.status_code == 200, confirmada.text
    for detalle in (confirmada.json(), sesion.get(f"/pursuits/{pid}").json()):
        (lote,) = detalle["adjudicacion"]["puntuaciones"]["lotes"]
        assert lote["fila_propia_confirmada"] is True
        assert lote["filas"][lote["fila_propia"]]["licitador"] == _NUESTRA
        assert lote["motivo_sugerido"] == "precio"
        por_criterio = {d["criterio"]: d["diferencia"] for d in lote["diferencia"]}
        assert por_criterio == {"Informe técnico": -2, "Oferta económica": -20.46, None: -22.46}

    # El cierre como perdida con el motivo propuesto, y la tabla sigue en la ficha cerrada.
    perdida = _mover(sesion, pid, status="lost", outcome_reason_code=lote["motivo_sugerido"])
    assert perdida.status_code == 200, perdida.text
    assert (perdida.json()["status"], perdida.json()["outcome"]) == ("lost", "lost")
    cerrada = sesion.get(f"/pursuits/{pid}").json()
    assert cerrada["outcome_reason_code"] == "precio"
    assert cerrada["adjudicacion"]["puntuaciones"]["lotes"][0]["fila_propia_confirmada"] is True

"""Escenarios de la oportunidad: del expediente a la cartera.

Cada test es un recorrido completo por la API con sesión real. Ver
``tests/escenarios.py`` y ``docs/casos-de-uso.md``.
"""

from __future__ import annotations

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

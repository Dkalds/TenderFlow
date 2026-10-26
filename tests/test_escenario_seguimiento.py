"""Escenarios de búsqueda, seguimiento y alertas.

Recorridos completos por la API con sesión real. Ver ``tests/escenarios.py`` y
``docs/casos-de-uso.md``.
"""

from __future__ import annotations

import json

from tests.escenarios import abrir_sesion, sembrar_licitacion


def _sembrar_mercado() -> None:
    """Dos expedientes de software, ya clasificados, y una obra sin tecnología."""
    sembrar_licitacion(
        "EXP-SEG-SAP",
        "Implantación SAP S/4HANA",
        cpv="72000000",
        importe=400_000.0,
        ccaa="Madrid",
        tecnologia="SAP",
    )
    sembrar_licitacion(
        "EXP-SEG-ORACLE",
        "Mantenimiento Oracle",
        cpv="72500000",
        importe=30_000.0,
        ccaa="Madrid",
        tecnologia="Oracle",
    )
    sembrar_licitacion(
        "EXP-SEG-OBRA", "Reforma de cubierta", cpv="45000000", importe=900_000.0, ccaa="Galicia"
    )


def test_cu02_buscar_filtrar_y_abrir_la_ficha(client, api_db):
    """CU-02 — de la búsqueda a la ficha del expediente."""
    _sembrar_mercado()
    sesion = abrir_sesion("busca@example.com", client)

    # El universo de la búsqueda es lo clasificado: la obra sin tecnología no entra.
    todo = sesion.post("/licitaciones/search", json={"with_total": True})
    assert todo.status_code == 200, todo.text
    assert todo.json()["total"] == 2
    assert {i["id_externo"] for i in todo.json()["items"]} == {"EXP-SEG-SAP", "EXP-SEG-ORACLE"}

    por_texto = sesion.post("/licitaciones/search", json={"q": "SAP", "with_total": True}).json()
    assert [i["id_externo"] for i in por_texto["items"]] == ["EXP-SEG-SAP"]

    por_ambito = sesion.post(
        "/licitaciones/search",
        json={"ccaa": ["Madrid"], "importe_min": 100_000, "with_total": True},
    ).json()
    assert [i["id_externo"] for i in por_ambito["items"]] == ["EXP-SEG-SAP"]

    # Un filtro que no casa con nada devuelve cero, no un error.
    nada = sesion.post("/licitaciones/search", json={"q": "zzzinexistente", "with_total": True})
    assert nada.status_code == 200
    assert nada.json()["items"] == []

    ficha = sesion.get("/licitaciones/EXP-SEG-SAP")
    assert ficha.status_code == 200, ficha.text
    assert ficha.json()["titulo"] == "Implantación SAP S/4HANA"
    assert sesion.get("/licitaciones/EXP-NO-EXISTE").status_code == 404


def test_cu03_seguir_un_expediente_anotarlo_y_dejar_de_seguirlo(client, api_db):
    """CU-03 — el favorito con su nota, y la lista privada de cada persona."""
    _sembrar_mercado()
    sesion = abrir_sesion("sigue@example.com", client)

    assert sesion.get("/watchlist/items").json()["items"] == []
    seguido = sesion.post("/watchlist/items", json={"id_externo": "EXP-SEG-SAP"})
    assert seguido.status_code == 201, seguido.text

    nota = sesion.put("/watchlist/items/EXP-SEG-SAP/nota", json={"nota": "Llamar al cliente"})
    assert nota.status_code == 200, nota.text

    (item,) = sesion.get("/watchlist/items").json()["items"]
    assert item["id_externo"] == "EXP-SEG-SAP"
    assert item["titulo"] == "Implantación SAP S/4HANA"
    assert item["nota"] == "Llamar al cliente"

    # Otra persona no ve lo que sigue la primera.
    otra = abrir_sesion("otra-sigue@example.com")
    assert otra.get("/watchlist/items").json()["items"] == []

    assert sesion.delete("/watchlist/items/EXP-SEG-SAP").status_code == 204
    assert sesion.get("/watchlist/items").json()["items"] == []


def test_cu04_regla_de_alerta_de_la_vista_previa_a_los_avisos(client, api_db):
    """CU-04 — probar una regla, guardarla, ver qué casa, afinarla y borrarla."""
    _sembrar_mercado()
    sesion = abrir_sesion("alertas@example.com", client)

    # La vista previa cuenta antes de guardar nada.
    previa = sesion.post("/watchlist/rules/preview", json={"cpv": "72"})
    assert previa.status_code == 200, previa.text
    assert previa.json()["total"] == 2
    assert sesion.get("/watchlist/rules").json()["items"] == []

    creada = sesion.post(
        "/watchlist/rules", json={"nombre": "Software", "cpv": "72", "frequency": "daily"}
    )
    assert creada.status_code == 201, creada.text
    rid = creada.json()["id"]

    # Lo que la regla casa es lo que la vista previa prometió.
    casan = sesion.get(f"/watchlist/rules/{rid}/matches").json()
    assert casan["total"] == previa.json()["total"]
    assert {m["id_externo"] for m in casan["items"]} == {"EXP-SEG-SAP", "EXP-SEG-ORACLE"}
    (regla,) = sesion.get("/watchlist/rules").json()["items"]
    assert regla["match_count"] == 2

    # Afinarla estrecha el resultado.
    afinada = sesion.put(f"/watchlist/rules/{rid}", json={"cpv": "72", "min_importe": 100_000})
    assert afinada.status_code == 200, afinada.text
    casan = sesion.get(f"/watchlist/rules/{rid}/matches").json()
    assert [m["id_externo"] for m in casan["items"]] == ["EXP-SEG-SAP"]

    # Un expediente nuevo que casa aparece sin tocar la regla.
    sembrar_licitacion("EXP-SEG-NUEVO", "Evolutivo SAP BW", cpv="72200000", importe=150_000.0)
    casan = sesion.get(f"/watchlist/rules/{rid}/matches").json()
    assert {m["id_externo"] for m in casan["items"]} == {"EXP-SEG-SAP", "EXP-SEG-NUEVO"}

    assert sesion.delete(f"/watchlist/rules/{rid}").status_code == 200
    assert sesion.get("/watchlist/rules").json()["items"] == []
    assert sesion.get(f"/watchlist/rules/{rid}/matches").status_code == 404


def test_cu04_alerta_por_defecto_al_guardar_el_ambito(client, api_db):
    """CU-04 — guardar las tecnologías de la organización deja una alerta editable."""
    _sembrar_mercado()
    sesion = abrir_sesion("ambito@example.com", client)
    ajustes = f"/organizations/{sesion.organization_id}/settings"
    assert sesion.get("/watchlist/rules").json()["items"] == []

    guardado = sesion.put(ajustes, json={"tecnologias": ["SAP"], "ccaas": ["Madrid"]})
    assert guardado.status_code == 200, guardado.text

    # La alerta aparece en Mi Watchlist, diaria y con el correo de quien guardó.
    (regla,) = sesion.get("/watchlist/rules").json()["items"]
    assert (regla["tecnologia"], regla["ccaa"]) == ("SAP", "Madrid")
    assert regla["frequency"] == "daily"
    assert regla["email"] == "ambito@example.com"
    casan = sesion.get(f"/watchlist/rules/{regla['id']}/matches").json()
    assert [m["id_externo"] for m in casan["items"]] == ["EXP-SEG-SAP"]

    # Se edita como cualquier otra, y volver a guardar el ámbito no la duplica.
    editada = sesion.put(
        f"/watchlist/rules/{regla['id']}",
        json={"nombre": "SAP en Madrid", "tecnologia": "SAP", "frequency": "weekly"},
    )
    assert editada.status_code == 200, editada.text
    assert sesion.put(ajustes, json={"tecnologias": ["SAP", "ORACLE"]}).status_code == 200
    (regla,) = sesion.get("/watchlist/rules").json()["items"]
    assert (regla["nombre"], regla["frequency"]) == ("SAP en Madrid", "weekly")

    # Borrarla es la baja: no vuelve al guardar otra vez.
    assert sesion.delete(f"/watchlist/rules/{regla['id']}").status_code == 200
    assert sesion.put(ajustes, json={"tecnologias": ["SAP"]}).status_code == 200
    assert sesion.get("/watchlist/rules").json()["items"] == []


def test_cu09_vista_guardada_sobrevive_y_se_borra(client, api_db):
    """CU-09 — guardar un ámbito con nombre, recuperarlo tal cual y borrarlo."""
    sesion = abrir_sesion("vistas@example.com", client)
    ambito = {"ccaa": ["Madrid"], "tecnologia": ["SAP"], "importe_min": 100000}

    guardada = sesion.post(
        "/saved-filters", json={"name": "Madrid SAP", "filters_json": json.dumps(ambito)}
    )
    assert guardada.status_code == 201, guardada.text

    (vista,) = sesion.get("/saved-filters").json()["items"]
    assert vista["name"] == "Madrid SAP"
    assert json.loads(vista["filters_json"]) == ambito

    # Es privada: otra persona no la encuentra.
    otra = abrir_sesion("otra-vistas@example.com")
    assert otra.get("/saved-filters").json()["items"] == []

    assert sesion.delete(f"/saved-filters/{vista['id']}").status_code == 200
    assert sesion.get("/saved-filters").json()["items"] == []


def test_cu10_descartar_del_radar_y_deshacerlo(client, api_db):
    """CU-10 — lo descartado deja de proponerse hasta que se restaura."""
    _sembrar_mercado()
    sesion = abrir_sesion("radar@example.com", client)

    assert sesion.get("/radar/dismissals").json()["ids"] == []
    descartada = sesion.post(
        "/radar/dismissals", json={"id_externo": "EXP-SEG-OBRA", "score": 12, "banda": "Descarte"}
    )
    assert descartada.status_code == 201, descartada.text
    assert descartada.json()["ids"] == ["EXP-SEG-OBRA"]

    # Descartar dos veces no duplica.
    assert sesion.post("/radar/dismissals", json={"id_externo": "EXP-SEG-OBRA"}).status_code == 201
    assert sesion.get("/radar/dismissals").json()["ids"] == ["EXP-SEG-OBRA"]

    assert sesion.delete("/radar/dismissals/EXP-SEG-OBRA").status_code == 204
    assert sesion.get("/radar/dismissals").json()["ids"] == []


def test_cu23_el_investigador_entiende_la_frase_y_ensena_donde_casa(client, api_db):
    """CU-23 — de una frase escrita como se habla a la ficha del expediente."""
    sembrar_licitacion(
        "EXP-INV-MADRID",
        "Mantenimiento evolutivo de SAP S/4HANA",
        ccaa="Madrid",
        tecnologia="SAP",
        descripcion="Soporte y evolutivos del ERP SAP de la consejería",
    )
    sembrar_licitacion(
        "EXP-INV-GALICIA", "Mantenimiento de SAP para el servicio de salud", ccaa="Galicia"
    )
    sembrar_licitacion("EXP-INV-ORACLE", "Licencias Oracle Database", ccaa="Madrid")
    sesion = abrir_sesion("investiga@example.com", client)

    respuesta = sesion.post("/search/semantic", json={"q": "mantenimiento de SAP en Madrid"})
    assert respuesta.status_code == 200, respuesta.text
    datos = respuesta.json()

    # Dice qué entendió: el lugar sale de la frase y deja de ser un término.
    assert datos["interpretacion"]["ccaa"] == ["Madrid"]
    assert datos["interpretacion"]["terminos"] == ["mantenimiento", "sap"]

    # Y devuelve el que cumple las dos cosas, con lo que casó resaltado.
    (acierto,) = datos["hits"]
    assert acierto["id_externo"] == "EXP-INV-MADRID"
    assert acierto["coincide_en"] == ["anuncio"]
    resaltado = [t["texto"] for t in acierto["titulo_tramos"] if t["resaltado"]]
    assert resaltado == ["Mantenimiento", "SAP"]

    # Sin el lugar, la misma pregunta trae también el de Galicia.
    amplia = sesion.post("/search/semantic", json={"q": "mantenimiento de SAP"}).json()
    assert {h["id_externo"] for h in amplia["hits"]} == {"EXP-INV-MADRID", "EXP-INV-GALICIA"}

    # Una pregunta sin respuesta no es un error: cero resultados y lo entendido.
    vacia = sesion.post("/search/semantic", json={"q": "zzzqqq inexistente"})
    assert vacia.status_code == 200
    assert vacia.json()["hits"] == []
    assert vacia.json()["interpretacion"]["terminos"] == ["zzzqqq", "inexistente"]

    # Del resultado se llega a la ficha.
    ficha = sesion.get(f"/licitaciones/{acierto['id_externo']}")
    assert ficha.status_code == 200, ficha.text
    assert ficha.json()["titulo"] == acierto["titulo"]


def test_cu17_el_perfil_reordena_el_radar_como_prometio_la_vista_previa(client, api_db):
    """CU-17 — probar un perfil, guardarlo, y que el Radar quede como la vista previa dijo."""
    for id_externo, titulo, tecnologia, importe in (
        ("EXP-PF-SAP", "Implantación SAP S/4HANA", "SAP", 900_000.0),
        ("EXP-PF-ORACLE", "Migración de bases de datos Oracle", "ORACLE", 60_000.0),
        ("EXP-PF-NET", "Desarrollo a medida en .NET", "MICROSOFT", 200_000.0),
    ):
        sembrar_licitacion(id_externo, titulo, estado="PUB", tecnologia=tecnologia, importe=importe)
    sesion = abrir_sesion("perfil-radar@example.com", client)

    def radar() -> list[tuple[str, int]]:
        cuerpo = sesion.get("/analytics/scoring").json()
        return [(o["id_externo"], o["score"]) for o in cuerpo["opportunities"]]

    de_fabrica = radar()
    assert de_fabrica[0][0] == "EXP-PF-SAP"  # sin perfil manda el importe

    perfil = {
        "weights": {"afinidad": 80, "importe": 10, "plazo": 10},
        "afinidad_keywords": ["oracle"],
    }

    # La vista previa no guarda nada: enseña cómo quedaría y cuánto se mueve cada uno.
    previa = sesion.post("/me/profile/preview", json=perfil)
    assert previa.status_code == 200, previa.text
    prometido = previa.json()["opportunities"]
    assert prometido[0]["id_externo"] == "EXP-PF-ORACLE"
    assert (prometido[0]["posicion"], prometido[0]["posicion_actual"]) == (1, 3)
    assert {o["id_externo"]: o["score_actual"] for o in prometido} == dict(de_fabrica)
    assert radar() == de_fabrica
    assert sesion.get("/me/profile").json()["weights"] is None

    # Guardado, el Radar es exactamente lo que la vista previa prometió.
    assert sesion.put("/me/profile", json=perfil).status_code == 200
    assert radar() == [(o["id_externo"], o["score"]) for o in prometido]
    assert sesion.get("/me/profile").json()["afinidad_keywords"] == ["oracle"]

    # Unos pesos que no suman cien no se guardan, y el perfil sigue como estaba.
    invalido = sesion.put(
        "/me/profile", json={"weights": {"afinidad": 10, "importe": 10, "plazo": 10}}
    )
    assert invalido.status_code == 422, invalido.text
    assert sesion.get("/me/profile").json()["weights"] == perfil["weights"]

    # Borrarlo devuelve el Radar a como venía.
    assert sesion.delete("/me/profile").status_code == 200
    assert radar() == de_fabrica

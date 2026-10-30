"""Tools de dominio del MCP contra Postgres (leen por ``DATABASE_URL``, no por el rol del MCP)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from db.consulta_libre import JSONValue
from db.database import DocumentoReferencia
from db.repositories.documentos import DocumentosRepository
from db.upsert import (
    Adjudicacion,
    Licitacion,
    Lote,
    replace_adjudicaciones,
    replace_lotes,
    upsert_licitaciones,
)
from mcp_server.tools import ErrorHerramienta
from mcp_server.tools.dominio import buscar_en_pliegos, buscar_licitaciones, ficha_licitacion

ID = "EXP-MCP-1"


def _dict(valor: JSONValue) -> dict[str, JSONValue]:
    assert isinstance(valor, dict)
    return valor


def _lista(valor: JSONValue) -> list[JSONValue]:
    assert isinstance(valor, list)
    return valor


@pytest.fixture()
def licitacion_con_lote_y_adjudicacion(tmp_db: Any) -> str:
    upsert_licitaciones(
        [
            Licitacion(
                id_externo=ID,
                titulo="Soporte SAP S/4HANA",
                organo_contratacion="Consejería de Hacienda",
                importe=640_000.0,
                estado="ADJ",
                ccaa="Madrid",
                fecha_publicacion="2026-03-01",
                tecnologia="SAP",
            ),
            Licitacion(
                id_externo="EXP-MCP-2",
                titulo="Licencias Oracle",
                importe=10_000.0,
                estado="PUB",
                ccaa="Galicia",
                fecha_publicacion="2025-01-15",
                tecnologia="ORACLE",
            ),
            Licitacion(id_externo="EXP-MCP-SINTEC", titulo="Soporte SAP sin tecnología"),
        ]
    )
    mapa = replace_lotes(ID, [Lote(licitacion_id=ID, numero="1", titulo="Lote uno")])
    replace_adjudicaciones(
        ID,
        [
            Adjudicacion(
                licitacion_id=ID,
                nombre="ALFA CONSULTORÍA SA",
                importe_adjudicado=500_000.0,
                lote_id=mapa["1"],
            )
        ],
    )
    return ID


@pytest.fixture()
def pliego_con_chunks(
    licitacion_con_lote_y_adjudicacion: str, monkeypatch: pytest.MonkeyPatch
) -> str:
    monkeypatch.setattr("services.embeddings.embeddings_available", lambda: False)
    repo = DocumentosRepository()
    repo.upsert_meta(ID, [DocumentoReferencia(tipo="legal", uri="https://x/pcap.pdf")])
    doc = repo.list_pendientes()[0]
    repo.mark_extracted(doc["id"], texto="pliego", sha256="h", filename="PCAP.pdf")
    repo.replace_chunks(
        doc["id"],
        [
            "Plazo de ejecución de veinticuatro meses",
            "Solvencia económica: volumen anual de negocios",
        ],
        [[0.1] * 384, [0.2] * 384],
        paginas=[1, 7],
    )
    return ID


def test_tool_buscar_licitaciones_limite_maximo(tmp_db: Any) -> None:
    with pytest.raises(ValidationError):
        buscar_licitaciones("x", limite=51)
    with pytest.raises(ValidationError):
        buscar_licitaciones("x", limite=0)


@pytest.mark.parametrize("fecha", ["2026-13-01", "01/03/2026", "2026-3-1", "ayer"])
def test_tool_buscar_licitaciones_rechaza_fechas_mal_formadas(tmp_db: Any, fecha: str) -> None:
    with pytest.raises(ValidationError):
        buscar_licitaciones("x", desde=fecha)


def test_tool_buscar_licitaciones_encuentra_y_filtra(
    licitacion_con_lote_y_adjudicacion: str,
) -> None:
    res = buscar_licitaciones("sap")
    assert res["total"] == 1  # la fila sin tecnología no entra (search_advanced)
    resultados = res["resultados"]
    assert isinstance(resultados, list)
    assert [_dict(r)["id_externo"] for r in resultados] == [ID]
    json.dumps(res)

    assert buscar_licitaciones("", ccaa=["Galicia"])["total"] == 1
    assert buscar_licitaciones("", estado=["ADJ"], importe_min=600_000)["total"] == 1
    assert buscar_licitaciones("", importe_max=5_000)["total"] == 0
    assert buscar_licitaciones("", desde="2026-01-01")["total"] == 1
    assert buscar_licitaciones("", hasta="2025-12-31")["total"] == 1
    assert buscar_licitaciones("", tecnologia=["ORACLE"])["total"] == 1


def test_tool_buscar_licitaciones_pagina_con_desplazamiento(
    licitacion_con_lote_y_adjudicacion: str,
) -> None:
    def ids(res: dict[str, JSONValue]) -> list[str]:
        filas = res["resultados"]
        assert isinstance(filas, list)
        return [str(_dict(r)["id_externo"]) for r in filas]

    primera = buscar_licitaciones("", limite=1)
    segunda = buscar_licitaciones("", limite=1, desplazamiento=1)
    assert primera["total"] == segunda["total"] == 2
    assert len(ids(primera)) == len(ids(segunda)) == 1
    assert ids(primera) != ids(segunda)
    assert ids(buscar_licitaciones("", desplazamiento=2)) == []
    with pytest.raises(ValidationError):
        buscar_licitaciones("", desplazamiento=-1)


def test_tool_ficha_inexistente(tmp_db: Any) -> None:
    with pytest.raises(ErrorHerramienta) as e:
        ficha_licitacion("NO-EXISTE")
    assert "No existe la licitación" in e.value.mensaje
    assert "buscar_licitaciones" in (e.value.pista or "")


def test_tool_ficha_serializa_a_json(licitacion_con_lote_y_adjudicacion: str) -> None:
    ficha = ficha_licitacion(licitacion_con_lote_y_adjudicacion)
    json.dumps(ficha)
    assert _dict(ficha["licitacion"])["titulo"] == "Soporte SAP S/4HANA"
    assert len(_lista(ficha["lotes"])) == 1
    assert len(_lista(ficha["adjudicaciones"])) == 1


def test_tool_buscar_en_pliegos_con_expediente(pliego_con_chunks: str) -> None:
    res = buscar_en_pliegos("solvencia económica", id_externo=pliego_con_chunks)
    json.dumps(res)
    fragmentos = res["fragmentos"]
    assert isinstance(fragmentos, list)
    primero = fragmentos[0]
    assert isinstance(primero, dict)
    assert "Solvencia" in str(primero["texto"])
    assert primero["pagina"] == 7
    assert primero["documento"] == "PCAP.pdf"


@pytest.mark.parametrize("limite", [0, 21])
def test_tool_buscar_en_pliegos_limite_fuera_de_rango(tmp_db: Any, limite: int) -> None:
    with pytest.raises(ValidationError):
        buscar_en_pliegos("x", limite=limite)


def test_tool_buscar_en_pliegos_sin_resultados_explica(tmp_db: Any) -> None:
    res = buscar_en_pliegos("nada", id_externo="NO-EXISTE")
    assert res["fragmentos"] == []
    assert "aviso" in res


def test_tool_buscar_en_pliegos_no_recorta_el_fragmento_a_1000(
    licitacion_con_lote_y_adjudicacion: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("services.embeddings.embeddings_available", lambda: False)
    repo = DocumentosRepository()
    repo.upsert_meta(ID, [DocumentoReferencia(tipo="legal", uri="https://x/largo.pdf")])
    doc = repo.list_pendientes()[0]
    repo.mark_extracted(doc["id"], texto="pliego", sha256="h2", filename="LARGO.pdf")
    repo.replace_chunks(doc["id"], ["penalidades " * 400], [[0.1] * 384])

    res = buscar_en_pliegos("penalidades", id_externo=ID)
    (fragmento,) = _lista(res["fragmentos"])
    texto = str(_dict(fragmento)["texto"])
    assert len(texto) == 1_500
    assert "…[+" not in texto


def test_tool_buscar_licitaciones_rechaza_desde_posterior_a_hasta(tmp_db: Any) -> None:
    with pytest.raises(ValidationError, match="posterior"):
        buscar_licitaciones("x", desde="2026-05-01", hasta="2026-01-01")


def test_tool_buscar_en_pliegos_aviso_sugiere_reintentar(tmp_db: Any) -> None:
    sin_id = buscar_en_pliegos("palabras que no existen en ninguna parte")
    assert "otras palabras clave" in str(sin_id["aviso"])
    con_id = buscar_en_pliegos("nada", id_externo="NO-EXISTE")
    assert "otras palabras clave" not in str(con_id["aviso"])


def test_tool_buscar_licitaciones_sin_resultados_remite_a_sql(
    licitacion_con_lote_y_adjudicacion: str,
) -> None:
    vacio = buscar_licitaciones("", importe_max=5_000)
    assert vacio["total"] == 0
    assert "consultar_sql" in str(vacio["aviso"])
    assert "aviso" not in buscar_licitaciones("sap")

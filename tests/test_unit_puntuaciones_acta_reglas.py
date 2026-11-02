"""Reglas puras de las puntuaciones del acta (``services/puntuaciones_acta_reglas``).

Sin BD ni red. El texto del acta es real: ``tests/fixtures/actas/astillero_1611_2026.json``
guarda las páginas 2-4 del acta de la mesa del exp. 1611/2026 del Ayuntamiento de
Astillero (dos lotes). La 2 y la 3 traen la tabla de puntuaciones; la 4 no.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.normalization import normalize_company
from services.puntuaciones_acta_reglas import (
    CriterioActa,
    CriterioCalculo,
    FilaActa,
    FilaCalculo,
    LoteActa,
    RespuestaActa,
    diferencia,
    es_precio_de,
    fila_ganadora,
    fila_propia,
    filas_validadas,
    motivo_sugerido,
    normalizar_lote,
    prioridad_de_acta,
    seleccionar_paginas,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "actas" / "astillero_1611_2026.json"

#: Criterios del pliego del expediente de Astillero (la descripción es la del acta).
_PLIEGO = [
    {"lote_numero": "1", "descripcion": "Oferta económica", "es_precio": True},
    {"lote_numero": "1", "descripcion": "Informe técnico", "es_precio": False},
    {"lote_numero": "1", "descripcion": "Tiempo de respuesta", "es_precio": False},
    {"lote_numero": "2", "descripcion": "Oferta económica", "es_precio": True},
    {"lote_numero": "2", "descripcion": "Informe técnico", "es_precio": False},
    {"lote_numero": "2", "descripcion": "Tiempo de respuesta", "es_precio": False},
    {"lote_numero": "2", "descripcion": "Capacidad adicional", "es_precio": False},
]


def _paginas() -> list[dict[str, object]]:
    paginas: list[dict[str, object]] = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return paginas


def _texto(paginas: list[dict[str, object]], numero: int) -> str:
    return str(next(p["texto"] for p in paginas if p["page_number"] == numero))


# --- normalizar_lote ---------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "esperado"),
    [
        ("Lote 1", "1"),
        ("LOTE Nº 1", "1"),
        ("lote n.º 2", "2"),
        ("1", "1"),
        (None, None),
        ("", None),
        ("Único", None),
        # Una cifra con texto detrás podría ser otro lote: mejor sin lote que con el equivocado.
        ("Lote 1 y 2", None),
        # El descriptor que el acta pone tras el número no cambia de lote...
        ("LOTE 1: Servicio de limpieza", "1"),
        ("Lote 1 - Suministro", "1"),
        ("Lote 1\u2013Suministro", "1"),
        ("Lote 1 (Servicio)", "1"),
        ("Lote 1.", "1"),
        ("Lote nº 2: Correo electrónico", "2"),
        # ...y los ceros a la izquierda tampoco: el pliego guarda «1».
        ("Lote 01", "1"),
        ("01", "1"),
        # Lo que no es un solo número de lote sigue sin lote.
        ("Lote 1.5", None),
        ("Lotes 1-2", None),
        ("1-2", None),
        ("Lote A", None),
    ],
)
def test_normalizar_lote(raw: str | None, esperado: str | None) -> None:
    assert normalizar_lote(raw) == esperado


# --- el JSON del modelo ------------------------------------------------------


def test_respuesta_acepta_coma_decimal() -> None:
    r = RespuestaActa.model_validate(
        {
            "lotes": [
                {
                    "lote": "1",
                    "filas": [
                        {
                            "licitador": "A",
                            "criterios": [{"nombre": "Precio", "puntos": "18,50", "maximo": "65"}],
                            "total": "n/d",
                            "cita": "x",
                            "pagina": 1,
                            "documento_id": 1,
                        }
                    ],
                }
            ]
        }
    )
    c = r.lotes[0].filas[0].criterios[0]
    assert (c.puntos, c.maximo, r.lotes[0].filas[0].total) == (18.5, 65.0, None)


def test_respuesta_acepta_excluida_null() -> None:
    # Un null del modelo no puede invalidar la respuesta entera: no excluida.
    fila = {"licitador": "A", "excluida": None, "cita": "x", "pagina": 1, "documento_id": 1}
    r = RespuestaActa.model_validate({"lotes": [{"lote": "1", "filas": [fila]}]})
    assert r.lotes[0].filas[0].excluida is False


def test_respuesta_acepta_lote_numerico_y_campos_de_mas() -> None:
    r = RespuestaActa.model_validate({"lotes": [{"lote": 2, "comentario": "x", "filas": []}]})
    assert r.lotes[0].lote == "2"


# --- es_precio_de ------------------------------------------------------------


def test_es_precio_por_criterio_del_pliego() -> None:
    # La descripción casa por fold_text (sin tildes ni mayúsculas) y manda el es_precio del pliego.
    assert es_precio_de("OFERTA ECONOMICA (sobre 65 puntos)", _PLIEGO, "1") is True
    assert es_precio_de("Informe técnico", _PLIEGO, "1") is False
    # El pliego manda aunque el nombre huela a precio.
    pliego = [{"lote_numero": None, "descripcion": "Baja de plazo", "es_precio": False}]
    assert es_precio_de("Baja de plazo", pliego, None) is False


def test_es_precio_el_lote_manda_sobre_el_expediente_y_los_otros_lotes_no_cuentan() -> None:
    pliego = [
        {"lote_numero": None, "descripcion": "Mejoras", "es_precio": False},
        {"lote_numero": "1", "descripcion": "Mejoras", "es_precio": True},
        {"lote_numero": "2", "descripcion": "Plazo de entrega", "es_precio": True},
    ]
    assert es_precio_de("Mejoras", pliego, "1") is True
    assert es_precio_de("Mejoras", pliego, "3") is False  # solo el criterio del expediente
    assert es_precio_de("Plazo de entrega", pliego, "1") is None  # es del lote 2


def test_es_precio_un_texto_muy_corto_no_casa_por_contencion() -> None:
    """«de» o «ec» están dentro de casi cualquier criterio: no son un criterio."""
    # Descripción del pliego de 2 letras: contenida en «plazo de entrega», no lo identifica.
    pliego_corto = [{"lote_numero": None, "descripcion": "de", "es_precio": False}]
    assert es_precio_de("Plazo de entrega", pliego_corto, None) is None
    # Nombre del acta de 2 letras: contenido en «oferta económica», tampoco.
    assert es_precio_de("ec", _PLIEGO, "1") is None
    # Justo en el mínimo (6, como ``_MIN_NOMBRE_CRITERIO``) sí casa.
    pliego_justo = [{"lote_numero": None, "descripcion": "Mejoras", "es_precio": False}]
    assert es_precio_de("Mejoras técnicas", pliego_justo, None) is False


def test_es_precio_por_nombre() -> None:
    assert es_precio_de("Oferta económica (sobre 65 puntos)", [], "1") is True
    assert es_precio_de("Precio", [], None) is True
    assert es_precio_de("Baja sobre el tipo de licitación", [], None) is True


def test_es_precio_desconocido() -> None:
    # Sin pliego que lo diga y sin nombre que lo delate no se inventa: spec §5, «si tampoco, NULL».
    assert es_precio_de("Mejoras", [], "1") is None
    assert es_precio_de("Informe técnico", [], "1") is None
    assert es_precio_de("Mejoras", _PLIEGO, "1") is None


# --- seleccionar_paginas -----------------------------------------------------


def test_seleccionar_paginas_del_acta_real() -> None:
    paginas = _paginas()
    elegidas = seleccionar_paginas(paginas, ["Oferta económica", "Informe técnico"])
    # Salen las dos tablas; la 4 («No habiendo más asuntos…») no tiene ninguna señal.
    assert [p["page_number"] for p in elegidas] == [2, 3]
    assert "44,54" in str(elegidas[0]["texto"])


def test_seleccionar_paginas_sin_nombres_de_criterio_sigue_viendo_la_tabla() -> None:
    # «(sobre 30 \npuntos)» con salto de línea en medio: se plegan los blancos antes de buscar.
    assert [p["page_number"] for p in seleccionar_paginas(_paginas(), [])] == [2, 3]


def test_seleccionar_paginas_respeta_el_tope_y_el_orden() -> None:
    relleno = "Puntuación total, sobre 30 puntos. "
    paginas: list[dict[str, object]] = [
        {"documento_id": 2, "page_number": n, "texto": relleno} for n in range(15, 0, -1)
    ]
    # La que más puntúa está al final y tiene que sobrevivir al recorte.
    paginas.append({"documento_id": 1, "page_number": 9, "texto": relleno + "Oferta económica"})
    elegidas = seleccionar_paginas(paginas, ["Oferta económica"])
    claves = [(p["documento_id"], p["page_number"]) for p in elegidas]
    assert len(claves) == 12
    assert claves == sorted(claves, key=lambda k: (int(str(k[0])), int(str(k[1]))))
    assert (1, 9) in claves


# --- prioridad_de_acta -------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "esperada"),
    [
        ("Acta del órgano de asistencia", 0),
        ("ACTA_MESA_2026.pdf", 0),
        ("Actas de apertura.pdf", 0),
        ("Informe de valoración", 0),
        ("Informe de criterios AUTOMÁTICOS.pdf", 0),
        # Resoluciones: dicen a quién y no cuántos puntos sacó cada uno.
        ("Adjudicación definitiva 0027", 1),
        ("Adjudicación provisional 0027", 1),
        ("Propuesta de adjudicación.pdf", 1),
        # «acta» pegada a una letra por delante no es la palabra.
        ("Informe exactas.pdf", 1),
        ("", 1),
        (None, 1),
    ],
)
def test_prioridad_de_acta_por_nombre_de_fichero(filename: str | None, esperada: int) -> None:
    assert prioridad_de_acta({"id": 1, "filename": filename}) == esperada


def test_prioridad_de_acta_sin_nombre_de_fichero() -> None:
    assert prioridad_de_acta({"id": 1}) == 1


def test_prioridad_de_acta_deja_fuera_las_resoluciones_del_expediente_real() -> None:
    """Los 6 documentos de acta del exp. 13: con el tope de 3 no entra ninguna adjudicación."""
    from lxml import etree

    from scraper.codice_parser import parse_document_references

    fixture = (
        Path(__file__).parent / "fixtures" / "placsp" / "13_criterios_sin_escala_deducible.xml"
    )
    entry = etree.parse(str(fixture)).getroot()
    documentos = [
        {"id": i, "filename": ref.filename}
        for i, ref in enumerate(parse_document_references(entry), start=1)
        if ref.tipo == "acta"
    ]
    assert len(documentos) == 6

    # El orden de ``ensure_documents_ready``: estable, así que dentro de cada
    # prioridad manda el orden de la lista (el de ``list_by_licitacion``).
    elegidos = sorted(documentos, key=prioridad_de_acta)[:3]

    assert [d["filename"] for d in elegidos] == [
        "Acta del órgano de asistencia",
        "Informe de valoración",
        "Acta del órgano de asistencia",
    ]


# --- filas_validadas ---------------------------------------------------------

_CITA_ADELANTE = "ADELANTE SERVICIOS \nINFORMÁTICOS S.L. 28 5 44,54 77,54"
_CITA_ASAP = "ASAP GLOBAL SOLUTION S.L. 30 5 65 100"
_CITA_IT_DIGITAL = "IT DIGITAL S.L. excluida   0"
_CITA_POLARIS = "POLARIS INFORMÁTICA Y \nCOMUNICACIONES S.A. 30 5 50,91 85,91"
_CITA_SOLUCIONES = "SOLUCIONES \nINFORMATICAS DIG \nSL\n8 5 0 48,18 61,18"
_CITA_TH_WORK = "TH WORK 3000 SL 7 5 5 80 97"


def _criterios(*valores: tuple[str, str, str]) -> list[dict[str, str]]:
    return [{"nombre": n, "puntos": p, "maximo": m} for n, p, m in valores]


def _respuesta_del_acta_real() -> RespuestaActa:
    """Lo que un modelo leería de las tablas de las páginas 2 y 3, escrito a mano."""
    lote1 = [
        ("Informe técnico", "30"),
        ("Tiempo de respuesta", "5"),
        ("Oferta económica", "65"),
    ]
    lote2 = [
        ("Informe técnico", "10"),
        ("Tiempo de respuesta", "5"),
        ("Capacidad adicional", "5"),
        ("Oferta económica", "80"),
    ]

    def fila(
        licitador: str,
        cita: str,
        pagina: int,
        puntos: list[str],
        total: str,
        maximos: list[tuple[str, str]],
        *,
        excluida: bool = False,
    ) -> dict[str, object]:
        return {
            "licitador": licitador,
            "criterios": _criterios(
                *[(n, p, m) for (n, m), p in zip(maximos, puntos, strict=True)]
            ),
            "total": total,
            "excluida": excluida,
            "cita": cita,
            "pagina": pagina,
            "documento_id": 1,
        }

    return RespuestaActa.model_validate(
        {
            "lotes": [
                {
                    "lote": "LOTE 1",
                    "filas": [
                        fila(
                            "ADELANTE SERVICIOS INFORMÁTICOS S.L.",
                            _CITA_ADELANTE,
                            2,
                            ["28", "5", "44,54"],
                            "77,54",
                            lote1,
                        ),
                        fila(
                            "ASAP GLOBAL SOLUTION S.L.",
                            _CITA_ASAP,
                            2,
                            ["30", "5", "65"],
                            "100",
                            lote1,
                        ),
                        fila("IT DIGITAL S.L.", _CITA_IT_DIGITAL, 2, [], "0", [], excluida=True),
                        fila(
                            "POLARIS INFORMÁTICA Y COMUNICACIONES S.A.",
                            _CITA_POLARIS,
                            2,
                            ["30", "5", "50,91"],
                            "85,91",
                            lote1,
                        ),
                    ],
                },
                {
                    "lote": "Lote 2",
                    "filas": [
                        fila(
                            "SOLUCIONES INFORMATICAS DIG SL",
                            _CITA_SOLUCIONES,
                            3,
                            ["8", "5", "0", "48,18"],
                            "61,18",
                            lote2,
                        ),
                        fila(
                            "TH WORK 3000 SL", _CITA_TH_WORK, 3, ["7", "5", "5", "80"], "97", lote2
                        ),
                    ],
                },
            ]
        }
    )


def test_filas_validadas_acta_real() -> None:
    paginas = _paginas()
    respuesta = _respuesta_del_acta_real()
    # Lo que hace real la validación: cada cita escrita a mano está tal cual en su página.
    for lote in respuesta.lotes:
        for f in lote.filas:
            assert f.cita in _texto(paginas, f.pagina)

    filas = filas_validadas(respuesta, paginas, _PLIEGO)

    por_licitador: dict[tuple[str | None, str], dict[str | None, dict[str, object]]] = {}
    for f in filas:
        por_licitador.setdefault((f["lote_numero"], f["licitador_normalizado"]), {})[
            f["criterio"]
        ] = dict(f)

    # Lote 1: 4 filas (3 criterios y el total) por 3 licitadores y 1 la excluida. Lote 2: 5 por 2.
    assert len(filas) == 4 * 3 + 1 + 5 * 2
    assert set(por_licitador) == {
        ("1", "ADELANTE SERVICIOS INFORMATICOS"),
        ("1", "ASAP GLOBAL SOLUTION"),
        ("1", "IT DIGITAL"),
        ("1", "POLARIS INFORMATICA Y COMUNICACIONES"),
        ("2", "SOLUCIONES INFORMATICAS DIG"),
        ("2", "TH WORK 3000"),
    }
    # licitador_normalizado sale de normalize_company, no del modelo.
    assert normalize_company("ASAP GLOBAL SOLUTION S.L.") == "ASAP GLOBAL SOLUTION"

    asap = por_licitador[("1", "ASAP GLOBAL SOLUTION")]
    assert {k: (v["puntos"], v["puntos_max"], v["es_precio"]) for k, v in asap.items()} == {
        "Informe técnico": (30.0, 30.0, False),
        "Tiempo de respuesta": (5.0, 5.0, False),
        "Oferta económica": (65.0, 65.0, True),
        None: (100.0, None, None),
    }
    assert asap[None]["licitador_nombre"] == "ASAP GLOBAL SOLUTION S.L."
    assert all(
        (v["documento_id"], v["pagina"], v["cita"], v["excluida"]) == (1, 2, _CITA_ASAP, False)
        for v in asap.values()
    )

    # El nombre con salto de línea del PDF se guarda en una línea.
    adelante = por_licitador[("1", "ADELANTE SERVICIOS INFORMATICOS")]
    assert adelante[None]["licitador_nombre"] == "ADELANTE SERVICIOS INFORMÁTICOS S.L."
    assert adelante["Oferta económica"]["puntos"] == 44.54

    # La excluida no trae criterios: solo su total (0) con excluida=True.
    it_digital = por_licitador[("1", "IT DIGITAL")]
    assert list(it_digital) == [None]
    assert it_digital[None]["puntos"] == 0.0
    assert it_digital[None]["excluida"] is True

    th_work = por_licitador[("2", "TH WORK 3000")]
    assert {k: (v["puntos"], v["es_precio"]) for k, v in th_work.items()} == {
        "Informe técnico": (7.0, False),
        "Tiempo de respuesta": (5.0, False),
        "Capacidad adicional": (5.0, False),
        "Oferta económica": (80.0, True),
        None: (97.0, None),
    }
    assert {v["pagina"] for v in th_work.values()} == {3}


def test_filas_validadas_descarta_cita_inventada() -> None:
    paginas = _paginas()
    respuesta = _respuesta_del_acta_real()
    respuesta.lotes[0].filas[1].cita = "ASAP GLOBAL SOLUTION S.L. 30 5 70 105"  # no está en el acta
    filas = filas_validadas(respuesta, paginas, _PLIEGO)
    assert "ASAP GLOBAL SOLUTION" not in {f["licitador_normalizado"] for f in filas}
    assert "ADELANTE SERVICIOS INFORMATICOS" in {f["licitador_normalizado"] for f in filas}


@pytest.mark.parametrize("cita", ["", "   ", "x" * 700])
def test_filas_validadas_descarta_citas_inservibles(cita: str) -> None:
    respuesta = _respuesta_del_acta_real()
    respuesta.lotes[0].filas[1].cita = cita
    filas = filas_validadas(respuesta, _paginas(), _PLIEGO)
    assert "ASAP GLOBAL SOLUTION" not in {f["licitador_normalizado"] for f in filas}


def test_filas_validadas_corrige_la_pagina_de_la_cita() -> None:
    respuesta = _respuesta_del_acta_real()
    respuesta.lotes[1].filas[1].pagina = 2  # TH WORK 3000 está en la 3
    filas = filas_validadas(respuesta, _paginas(), _PLIEGO)
    th_work = [f for f in filas if f["licitador_normalizado"] == "TH WORK 3000"]
    assert th_work
    assert {f["pagina"] for f in th_work} == {3}


def test_filas_validadas_descarta_licitador_sin_nombre_normalizable() -> None:
    respuesta = _respuesta_del_acta_real()
    respuesta.lotes[0].filas[1].licitador = "S.L."
    filas = filas_validadas(respuesta, _paginas(), _PLIEGO)
    assert all(f["licitador_nombre"] != "S.L." for f in filas)
    assert "ASAP GLOBAL SOLUTION" not in {f["licitador_normalizado"] for f in filas}


def test_filas_validadas_deduplica() -> None:
    respuesta = _respuesta_del_acta_real()
    # La misma fila dos veces (dos actas del mismo expediente, o el modelo repitiéndose) y un
    # criterio repetido dentro de otra: la BD tiene un índice único y rechazaría la escritura.
    respuesta.lotes[0].filas.append(respuesta.lotes[0].filas[1].model_copy(deep=True))
    respuesta.lotes[0].filas[0].criterios.append(
        respuesta.lotes[0].filas[0].criterios[0].model_copy()
    )
    filas = filas_validadas(respuesta, _paginas(), _PLIEGO)
    claves = [(f["lote_numero"], f["licitador_normalizado"], f["criterio"]) for f in filas]
    assert len(claves) == len(set(claves))
    assert len(filas) == 4 * 3 + 1 + 5 * 2


def _th_work_del_lote_1() -> FilaActa:
    """TH WORK 3000 también concursó al lote 1 (página 2 del acta)."""
    return FilaActa(
        licitador="TH WORK 3000 SL",
        criterios=[
            CriterioActa(nombre="Informe técnico", puntos=30, maximo=30),
            CriterioActa(nombre="Tiempo de respuesta", puntos=5, maximo=5),
            CriterioActa(nombre="Oferta económica", puntos=61.5, maximo=65),
        ],
        total=96.5,
        cita="TH WORK 3000 SL 30 5 61,5 96,5",
        pagina=2,
        documento_id=1,
    )


def test_filas_validadas_lotes_con_descriptor_no_se_funden() -> None:
    paginas = _paginas()
    respuesta = _respuesta_del_acta_real()
    # Etiquetas como las escribe un acta: «LOTE N: descripción». Con el mismo licitador en los dos.
    respuesta.lotes[0].lote = "LOTE 1: Servicio de desarrollo web"
    respuesta.lotes[1].lote = "LOTE 2: Gestión del correo electrónico"
    respuesta.lotes[0].filas.append(_th_work_del_lote_1())
    assert _th_work_del_lote_1().cita in _texto(paginas, 2)

    filas = filas_validadas(respuesta, paginas, _PLIEGO)

    assert {f["lote_numero"] for f in filas} == {"1", "2"}
    th_work = {
        (f["lote_numero"], f["criterio"]): f["puntos"]
        for f in filas
        if f["licitador_normalizado"] == "TH WORK 3000"
    }
    assert th_work[("1", None)] == 96.5
    assert th_work[("2", None)] == 97.0  # la ganadora del lote 2 no se pierde
    assert th_work[("2", "Oferta económica")] == 80.0
    assert th_work[("1", "Oferta económica")] == 61.5
    assert len(filas) == 4 * 3 + 1 + 5 * 2 + 4


def test_filas_validadas_lote_sin_numero_en_respuesta_multilote_se_descarta() -> None:
    respuesta = _respuesta_del_acta_real()
    respuesta.lotes[0].lote = "Lote primero"  # no hay número que verificar
    filas = filas_validadas(respuesta, _paginas(), _PLIEGO)
    assert {f["lote_numero"] for f in filas} == {"2"}
    assert {f["licitador_normalizado"] for f in filas} == {
        "SOLUCIONES INFORMATICAS DIG",
        "TH WORK 3000",
    }


def test_filas_validadas_lote_sin_etiqueta_junto_a_otro_con_numero_se_descarta() -> None:
    respuesta = _respuesta_del_acta_real()
    respuesta.lotes[0].lote = None  # sin etiqueta: en una respuesta multilote no se sabe de cuál es
    respuesta.lotes[1].lote = "Lote 2"
    filas = filas_validadas(respuesta, _paginas(), _PLIEGO)
    assert {f["lote_numero"] for f in filas} == {"2"}
    assert len(filas) == 5 * 2


def test_filas_validadas_dos_lotes_sin_etiqueta_no_dejan_nada() -> None:
    respuesta = _respuesta_del_acta_real()
    respuesta.lotes[0].lote = None
    respuesta.lotes[1].lote = ""
    assert filas_validadas(respuesta, _paginas(), _PLIEGO) == []


@pytest.mark.parametrize("etiqueta", ["Único", None, ""])
def test_filas_validadas_lote_unico_sin_numero_queda_sin_lote(etiqueta: str | None) -> None:
    # Con un solo lote no hay otro con quien fundirse: «Único» o sin etiqueta se guarda sin lote.
    respuesta = _respuesta_del_acta_real()
    respuesta.lotes = [LoteActa(lote=etiqueta, filas=respuesta.lotes[0].filas)]
    filas = filas_validadas(respuesta, _paginas(), _PLIEGO)
    assert filas
    assert {f["lote_numero"] for f in filas} == {None}


# --- fila ganadora y fila propia ---------------------------------------------


def _crit(
    nombre: str, puntos: float | None, maximo: float | None, es_precio: bool | None
) -> CriterioCalculo:
    return CriterioCalculo(
        nombre=nombre,
        puntos=puntos,
        maximo=maximo,
        es_precio=es_precio,
        documento_id=1,
        pagina=2,
        cita="x",
    )


def _fila(
    licitador: str,
    total: float | None,
    criterios: tuple[CriterioCalculo, ...] = (),
    *,
    excluida: bool = False,
) -> FilaCalculo:
    return FilaCalculo(
        licitador=licitador,
        licitador_normalizado=normalize_company(licitador) or "",
        total=total,
        excluida=excluida,
        criterios=criterios,
    )


def test_fila_ganadora_por_nombre_adjudicatario() -> None:
    filas = [_fila("MEJOR S.L.", 95), _fila("ADJUDICATARIA S.L.", 80), _fila("OTRA S.L.", 70)]
    assert fila_ganadora(filas, {"ADJUDICATARIA"}) == (1, False)


def test_fila_ganadora_varias_coincidencias_manda_el_mayor_total() -> None:
    # Dos nombres publicados para el lote que casan con dos filas (una UTE y una de sus socias).
    filas = [
        _fila("ADJ S.L.", 50),
        _fila("OTRA S.L.", 90),
        _fila("ADJ NORTE S.L.", 80),
        _fila("ADJ SUR S.L.", None),
    ]
    assert fila_ganadora(filas, {"ADJ", "ADJ NORTE", "ADJ SUR"}) == (2, False)
    assert fila_ganadora(
        [_fila("ADJ S.L.", None), _fila("ADJ NORTE S.L.", 10)], {"ADJ", "ADJ NORTE"}
    ) == (1, False)
    # Sin totales, la primera.
    assert fila_ganadora(
        [_fila("ADJ S.L.", None), _fila("ADJ NORTE S.L.", None)], {"ADJ", "ADJ NORTE"}
    ) == (0, False)


def test_fila_ganadora_por_mayor_total_sin_excluidas() -> None:
    filas = [
        _fila("EXCLUIDA S.L.", 100, excluida=True),
        _fila("UNA S.L.", 70),
        _fila("OTRA S.L.", 85),
        _fila("SIN TOTAL S.L.", None),
    ]
    assert fila_ganadora(filas, {"NADIE QUE CASE"}) == (2, True)
    assert fila_ganadora(filas, set()) == (2, True)


def test_fila_ganadora_sin_totales() -> None:
    assert fila_ganadora([], {"X"}) == (None, False)
    assert fila_ganadora([_fila("UNA S.L.", None), _fila("OTRA S.L.", None)], set()) == (
        None,
        False,
    )
    # Una excluida con total tampoco cuenta como la de mayor puntuación.
    assert fila_ganadora([_fila("UNA S.L.", 90, excluida=True)], set()) == (None, False)


def test_fila_propia_exacta() -> None:
    filas = [_fila("UNA S.L.", 70), _fila("MI EMPRESA S.L.", 60)]
    assert fila_propia(filas, {"MI EMPRESA"}) == 1


def test_fila_propia_ambigua() -> None:
    # Dos nombres de la organización y los dos están en el lote: no se elige.
    filas = [_fila("MI EMPRESA S.L.", 70), _fila("MI EMPRESA NORTE S.L.", 60)]
    assert fila_propia(filas, {"MI EMPRESA", "MI EMPRESA NORTE"}) is None


def test_fila_propia_ninguna() -> None:
    assert fila_propia([_fila("UNA S.L.", 70)], {"MI EMPRESA"}) is None
    assert fila_propia([], {"MI EMPRESA"}) is None
    assert fila_propia([_fila("UNA S.L.", 70)], set()) is None


def test_fila_propia_no_casa_una_ute_que_la_contiene() -> None:
    filas = [_fila("UTE MI EMPRESA - OTRA", 70)]
    assert fila_propia(filas, {"MI EMPRESA"}) is None


# --- diferencia y motivo -----------------------------------------------------


def _par_precio() -> tuple[FilaCalculo, FilaCalculo]:
    propia = _fila(
        "MI EMPRESA S.L.",
        68,
        (_crit("Precio", 40, 65, True), _crit("Técnica", 28, 30, False)),
    )
    ganadora = _fila(
        "GANADORA S.L.",
        88.5,
        (_crit("Precio", 58.5, 65, True), _crit("Técnica", 30, 30, False)),
    )
    return propia, ganadora


def test_diferencia_por_criterio_y_total() -> None:
    propia, ganadora = _par_precio()
    d = diferencia(propia, ganadora)
    assert [(x.criterio, x.diferencia, x.maximo, x.es_precio) for x in d] == [
        ("Precio", -18.5, 65, True),
        ("Técnica", -2, 30, False),
        (None, -20.5, None, None),
    ]


def test_diferencia_sin_ruido_de_coma_flotante() -> None:
    propia = _fila("A", 78.13, (_crit("Precio", 43.13, 65, True),))
    ganadora = _fila("B", 85.91, (_crit("Precio", 50.91, 65, True),))
    assert [x.diferencia for x in diferencia(propia, ganadora)] == [-7.78, -7.78]


def test_diferencia_solo_con_lo_que_hay_en_las_dos_filas() -> None:
    propia = _fila("A", None, (_crit("Precio", 40, 65, True), _crit("Mejoras", 3, 5, None)))
    ganadora = _fila("B", 90, (_crit("PRECIO", 58, 65, True), _crit("Plazo", 5, 5, None)))
    # «Mejoras» no está en la ganadora, «Plazo» no está en la propia y no hay total propio.
    assert [(x.criterio, x.diferencia) for x in diferencia(propia, ganadora)] == [("Precio", -18)]
    assert diferencia(_fila("A", None), _fila("B", None)) == []


def test_motivo_precio() -> None:
    propia, ganadora = _par_precio()
    assert motivo_sugerido(propia, ganadora, propia_es_ganadora=False) == "precio"


def test_motivo_tecnica() -> None:
    propia = _fila("A", 0, (_crit("Precio", 55, 65, True), _crit("Técnica", 20, 30, False)))
    ganadora = _fila("B", 0, (_crit("Precio", 58, 65, True), _crit("Técnica", 30, 30, False)))
    assert motivo_sugerido(propia, ganadora, propia_es_ganadora=False) == "tecnica"


def test_motivo_empate_de_perdidas_es_tecnica() -> None:
    propia = _fila("A", 0, (_crit("Precio", 55, 65, True), _crit("Técnica", 25, 30, False)))
    ganadora = _fila("B", 0, (_crit("Precio", 60, 65, True), _crit("Técnica", 30, 30, False)))
    assert motivo_sugerido(propia, ganadora, propia_es_ganadora=False) == "tecnica"


def test_motivo_sin_perdidas() -> None:
    # Gana en todo pero no es la adjudicataria: la causa no está en los puntos.
    propia = _fila("A", 0, (_crit("Precio", 65, 65, True), _crit("Técnica", 30, 30, False)))
    ganadora = _fila("B", 0, (_crit("Precio", 60, 65, True), _crit("Técnica", 30, 30, False)))
    assert motivo_sugerido(propia, ganadora, propia_es_ganadora=False) is None


def test_motivo_sin_es_precio() -> None:
    propia = _fila("A", 0, (_crit("Criterio 1", 10, 65, None), _crit("Criterio 2", 20, 30, None)))
    ganadora = _fila("B", 0, (_crit("Criterio 1", 60, 65, None), _crit("Criterio 2", 30, 30, None)))
    assert motivo_sugerido(propia, ganadora, propia_es_ganadora=False) is None


def test_motivo_propia_ganadora() -> None:
    propia, ganadora = _par_precio()
    assert motivo_sugerido(propia, ganadora, propia_es_ganadora=True) is None


def test_motivo_propia_excluida() -> None:
    propia, ganadora = _par_precio()
    excluida = _fila("MI EMPRESA S.L.", 0, propia.criterios, excluida=True)
    assert motivo_sugerido(excluida, ganadora, propia_es_ganadora=False) is None

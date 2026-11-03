"""Job que lee las puntuaciones del acta (``services/puntuaciones_acta``).

Sin BD ni red: los repositorios, ``ensure_documents_ready``, ``_llamar_modelo`` y
la cola están sustituidos. El texto del acta es real
(``tests/fixtures/actas/astillero_1611_2026.json``, expediente 1611/2026 del
Ayuntamiento de Astillero); el modelo es un doble que devuelve el JSON que
leería de la tabla de la página 2, con citas que son subcadenas literales de
esa página.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

import pytest

from config.settings import settings
from services.jobs import TIPO_PUNTUACIONES_ACTA, TIPOS_A_DEMANDA, Job
from services.puntuaciones_acta import (
    _MAX_ACTAS,
    _PREGUNTA_ACTA,
    EXTRACTION_VERSION,
    encolar_pendientes,
    extraer_puntuaciones,
)
from services.puntuaciones_acta_reglas import prioridad_de_acta

_FIXTURE = Path(__file__).parent / "fixtures" / "actas" / "astillero_1611_2026.json"
_LIC = "EXP-1611"
_MODELO = "modelo-de-prueba"

_CITA_ADELANTE = "ADELANTE SERVICIOS \nINFORMÁTICOS S.L. 28 5 44,54 77,54"
_CITA_ASAP = "ASAP GLOBAL SOLUTION S.L. 30 5 65 100"

_CRITERIOS_PLIEGO = [
    {"lote_numero": "1", "descripcion": "Oferta económica", "es_precio": True},
    {"lote_numero": "1", "descripcion": "Informe técnico", "es_precio": False},
]

_ENSURE_OK = {"attempted": 1, "extracted": 1, "error": 0, "sin_texto": 0}


def _paginas() -> list[dict[str, Any]]:
    paginas: list[dict[str, Any]] = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return paginas


def _fila(licitador: str, cita: str, puntos: list[str], total: str) -> dict[str, Any]:
    nombres = [("Informe técnico", "30"), ("Tiempo de respuesta", "5"), ("Oferta económica", "65")]
    return {
        "licitador": licitador,
        "criterios": [
            {"nombre": n, "puntos": p, "maximo": m}
            for (n, m), p in zip(nombres, puntos, strict=True)
        ],
        "total": total,
        "excluida": False,
        "cita": cita,
        "pagina": 2,
        "documento_id": 1,
    }


def _respuesta(*, cita_asap: str = _CITA_ASAP) -> str:
    """El JSON que un modelo leería de la tabla del lote 1 (dos de sus licitadores)."""
    return json.dumps(
        {
            "lotes": [
                {
                    "lote": "LOTE 1",
                    "filas": [
                        _fila(
                            "ADELANTE SERVICIOS INFORMÁTICOS S.L.",
                            _CITA_ADELANTE,
                            ["28", "5", "44,54"],
                            "77,54",
                        ),
                        _fila("ASAP GLOBAL SOLUTION S.L.", cita_asap, ["30", "5", "65"], "100"),
                    ],
                }
            ]
        }
    )


@dataclass
class _Entorno:
    repo: MagicMock
    paginas_repo: MagicMock
    ensure: MagicMock
    llamar: MagicMock


@pytest.fixture
def entorno() -> Iterator[_Entorno]:
    with (
        patch("services.puntuaciones_acta.PuntuacionesActaRepository") as repo_cls,
        patch("services.puntuaciones_acta.DocumentosRepository") as docs_cls,
        patch("services.puntuaciones_acta.CondicionesOficialesRepository") as condiciones_cls,
        patch(
            "services.rag.fact_sheet.ensure_documents_ready", return_value=dict(_ENSURE_OK)
        ) as ensure,
        patch("services.rag.fact_sheet._llamar_modelo", return_value=_respuesta()) as llamar,
    ):
        docs_cls.return_value.list_pages_by_licitacion.return_value = _paginas()
        docs_cls.return_value.list_by_licitacion.return_value = []
        condiciones_cls.return_value.get.return_value = {"criterios": _CRITERIOS_PLIEGO}
        repo_cls.return_value.get_extraccion.return_value = None  # sin lectura previa
        yield _Entorno(
            repo=repo_cls.return_value,
            paginas_repo=docs_cls.return_value,
            ensure=ensure,
            llamar=llamar,
        )


def _guardado(entorno: _Entorno) -> dict[str, Any]:
    """Los argumentos de la única llamada a ``guardar``."""
    entorno.repo.guardar.assert_called_once()
    (licitacion,), kwargs = entorno.repo.guardar.call_args
    assert licitacion == _LIC
    return dict(kwargs)


# --- encolar_pendientes ------------------------------------------------------


def test_encolar_escribe_sin_acta_sin_job() -> None:
    with (
        patch("services.puntuaciones_acta.PuntuacionesActaRepository") as repo_cls,
        patch("services.puntuaciones_acta.enqueue") as enqueue,
    ):
        repo = repo_cls.return_value
        repo.expedientes_pendientes.return_value = [{"licitacion_id": _LIC, "tiene_acta": False}]

        assert encolar_pendientes() == 1

    enqueue.assert_not_called()
    repo.guardar.assert_called_once_with(
        _LIC,
        status="sin_acta",
        extraction_version=EXTRACTION_VERSION,
        model=None,
        documentos_leidos=0,
        error_detail=None,
        filas=[],
    )


def test_encolar_encola_con_acta() -> None:
    with (
        patch("services.puntuaciones_acta.PuntuacionesActaRepository") as repo_cls,
        patch("services.puntuaciones_acta.enqueue") as enqueue,
    ):
        repo = repo_cls.return_value
        repo.expedientes_pendientes.return_value = [{"licitacion_id": _LIC, "tiene_acta": True}]

        assert encolar_pendientes() == 1

    repo.guardar.assert_not_called()
    enqueue.assert_called_once_with(
        TIPO_PUNTUACIONES_ACTA,
        {"licitacion_id": _LIC, "model": settings.PLIEGO_FACTS_MODEL},
        organization_id=None,
    )


def test_encolar_respeta_el_limite_y_cuenta_las_dos_salidas() -> None:
    with (
        patch("services.puntuaciones_acta.PuntuacionesActaRepository") as repo_cls,
        patch("services.puntuaciones_acta.enqueue") as enqueue,
    ):
        repo = repo_cls.return_value
        repo.expedientes_pendientes.return_value = [
            {"licitacion_id": "A", "tiene_acta": True},
            {"licitacion_id": "B", "tiene_acta": False},
            {"licitacion_id": "C", "tiene_acta": True},
        ]

        assert encolar_pendientes(limit=3) == 3

    repo.expedientes_pendientes.assert_called_once_with(
        extraction_version=EXTRACTION_VERSION, limit=3
    )
    assert [c.args[1]["licitacion_id"] for c in enqueue.call_args_list] == ["A", "C"]
    assert [c.args[0] for c in repo.guardar.call_args_list] == ["B"]


def test_encolar_sin_pendientes_no_hace_nada() -> None:
    with (
        patch("services.puntuaciones_acta.PuntuacionesActaRepository") as repo_cls,
        patch("services.puntuaciones_acta.enqueue") as enqueue,
    ):
        repo_cls.return_value.expedientes_pendientes.return_value = []

        assert encolar_pendientes() == 0

    enqueue.assert_not_called()
    repo_cls.return_value.guardar.assert_not_called()


# --- extraer_puntuaciones ----------------------------------------------------


def test_extraer_ok_guarda_filas_con_cita(entorno: _Entorno) -> None:
    assert extraer_puntuaciones(_LIC, model=_MODELO) == "ok"

    guardado = _guardado(entorno)
    assert guardado["status"] == "ok"
    assert guardado["extraction_version"] == EXTRACTION_VERSION
    assert guardado["model"] == _MODELO
    assert guardado["documentos_leidos"] == 1
    assert guardado["error_detail"] is None
    filas = guardado["filas"]
    # Dos licitadores x (3 criterios + el total).
    assert len(filas) == 8
    assert {f["licitador_normalizado"] for f in filas} == {
        "ADELANTE SERVICIOS INFORMATICOS",
        "ASAP GLOBAL SOLUTION",
    }
    assert all(
        f["lote_numero"] == "1" and f["pagina"] == 2 and f["documento_id"] == 1 for f in filas
    )
    asap = {f["criterio"]: f for f in filas if f["licitador_normalizado"] == "ASAP GLOBAL SOLUTION"}
    assert asap["Oferta económica"]["puntos"] == 65.0
    assert asap["Oferta económica"]["es_precio"] is True  # el criterio viene del pliego
    assert asap[None]["puntos"] == 100.0
    assert asap[None]["cita"] == _CITA_ASAP


def test_extraer_descarga_solo_las_actas_y_pide_al_modelo_las_paginas_con_tabla(
    entorno: _Entorno,
) -> None:
    extraer_puntuaciones(_LIC, model=_MODELO)

    entorno.ensure.assert_called_once_with(
        _LIC, tipos=frozenset({"acta"}), max_documentos=_MAX_ACTAS, orden=prioridad_de_acta
    )
    entorno.paginas_repo.list_pages_by_licitacion.assert_called_once_with(
        _LIC, tipos=frozenset({"acta"})
    )
    entorno.llamar.assert_called_once()
    (pregunta, seleccionadas), kwargs = entorno.llamar.call_args
    assert pregunta == _PREGUNTA_ACTA
    # La página 4 («No habiendo más asuntos…») no tiene ninguna señal y no viaja.
    assert [p["page_number"] for p in seleccionadas] == [2, 3]
    assert kwargs["licitacion_id"] == _LIC
    assert kwargs["model"] == _MODELO
    assert kwargs["keywords"] == ("puntuación", "total")
    assert kwargs["max_tokens"] == 4000
    assert isinstance(kwargs["stop"], threading.Event)


def test_extraer_una_cita_inventada_tira_solo_su_fila(entorno: _Entorno) -> None:
    entorno.llamar.return_value = _respuesta(cita_asap="ASAP GLOBAL SOLUTION S.L. 30 5 70 105")

    assert extraer_puntuaciones(_LIC, model=_MODELO) == "ok"
    assert {f["licitador_normalizado"] for f in _guardado(entorno)["filas"]} == {
        "ADELANTE SERVICIOS INFORMATICOS"
    }


def test_extraer_con_todas_las_citas_inventadas_es_sin_tabla_sin_excepcion(
    entorno: _Entorno,
) -> None:
    inventada = json.loads(_respuesta())
    for fila in inventada["lotes"][0]["filas"]:
        fila["cita"] = "XXXX SOLUCIONES S.L. 99 99 99 99"
    entorno.llamar.return_value = json.dumps(inventada)

    assert extraer_puntuaciones(_LIC, model=_MODELO) == "sin_tabla"

    guardado = _guardado(entorno)
    assert guardado["status"] == "sin_tabla"
    assert guardado["filas"] == []
    assert guardado["model"] == _MODELO
    assert guardado["documentos_leidos"] == 1
    assert "cita" in guardado["error_detail"]


def test_extraer_respuesta_sin_lotes_es_sin_tabla(entorno: _Entorno) -> None:
    entorno.llamar.return_value = '```json\n{"lotes": []}\n```'

    assert extraer_puntuaciones(_LIC, model=_MODELO) == "sin_tabla"

    guardado = _guardado(entorno)
    assert guardado["status"] == "sin_tabla"
    assert guardado["filas"] == []


def test_extraer_sin_paginas_con_senales_no_llama_al_llm(entorno: _Entorno) -> None:
    entorno.paginas_repo.list_pages_by_licitacion.return_value = [
        {"documento_id": 1, "page_number": 1, "texto": "Se abre la sesión a las diez."}
    ]

    assert extraer_puntuaciones(_LIC, model=_MODELO) == "sin_tabla"

    entorno.llamar.assert_not_called()
    guardado = _guardado(entorno)
    assert guardado["status"] == "sin_tabla"
    assert guardado["filas"] == []
    assert guardado["model"] is None  # no se llamó a ningún modelo
    assert guardado["documentos_leidos"] == 1
    assert "señales" in guardado["error_detail"]


def _previa(**cambios: Any) -> dict[str, Any]:
    """La fila de ``acta_extracciones`` de una lectura anterior que acabó en ``sin_tabla``."""
    previa: dict[str, Any] = {
        "licitacion_id": _LIC,
        "status": "sin_tabla",
        "extraction_version": EXTRACTION_VERSION,
        "model": "modelo-de-la-pasada-anterior",
        "documentos_leidos": 1,  # el fixture trae las páginas de un solo documento
        "error_detail": "El modelo no encontró una tabla de puntuaciones por licitador en el acta",
        "extracted_at": datetime.now(UTC),
    }
    return {**previa, **cambios}


def test_extraer_relectura_sin_actas_nuevas_no_llama_al_llm(entorno: _Entorno) -> None:
    """Un sin_tabla reencolado por actas aún ``pending`` no repite la misma pregunta al modelo."""
    previa = _previa()
    entorno.repo.get_extraccion.return_value = previa

    assert extraer_puntuaciones(_LIC, model=_MODELO) == "sin_tabla"

    entorno.llamar.assert_not_called()
    guardado = _guardado(entorno)
    assert guardado["status"] == "sin_tabla"
    assert guardado["filas"] == []
    # Conserva lo de la lectura que sí llegó al modelo, no el modelo de esta pasada.
    assert guardado["model"] == previa["model"]
    assert guardado["error_detail"] == previa["error_detail"]
    assert guardado["documentos_leidos"] == 1
    assert guardado["extraction_version"] == EXTRACTION_VERSION


@pytest.mark.parametrize(
    "cambios",
    [
        # Se leyó un acta que la lectura anterior no tenía.
        {"documentos_leidos": 0},
        # La pregunta o las reglas cambiaron: lo leído antes ya no vale.
        {"extraction_version": "acta-puntuaciones-v0"},
        # Solo un sin_tabla es definitivo hasta que haya algo nuevo.
        {"status": "error"},
        {"status": "ok"},
    ],
)
def test_extraer_relectura_con_algo_nuevo_vuelve_a_llamar_al_llm(
    entorno: _Entorno, cambios: dict[str, Any]
) -> None:
    entorno.repo.get_extraccion.return_value = _previa(**cambios)

    assert extraer_puntuaciones(_LIC, model=_MODELO) == "ok"

    entorno.llamar.assert_called_once()
    assert _guardado(entorno)["model"] == _MODELO


def test_extraer_relectura_tras_un_sin_tabla_que_no_llego_al_modelo_llama_si_ahora_hay_senales(
    entorno: _Entorno,
) -> None:
    """Un sin_tabla «sin señales» (model None) no frena la lectura cuando ya hay señales."""
    entorno.repo.get_extraccion.return_value = _previa(
        model=None, error_detail="Ninguna página del acta tiene las señales de una tabla"
    )

    assert extraer_puntuaciones(_LIC, model=_MODELO) == "ok"

    entorno.llamar.assert_called_once()


def _acta(status: str, *, sin_publicar: bool = False, tipo: str = "acta") -> dict[str, Any]:
    """Un documento tal como lo devuelve ``DocumentosRepository.list_by_licitacion``."""
    return {"id": 1, "tipo": tipo, "status": status, "sin_publicar": sin_publicar}


def _sin_paginas(entorno: _Entorno, *documentos: dict[str, Any]) -> None:
    """La descarga no intenta nada (todo a cero) y los documentos están como se dice."""
    entorno.ensure.return_value = {**_ENSURE_OK, "attempted": 0, "extracted": 0}
    entorno.paginas_repo.list_pages_by_licitacion.return_value = []
    entorno.paginas_repo.list_by_licitacion.return_value = list(documentos)


@pytest.mark.parametrize(
    "recuento",
    [
        # La pasada que descarga el PDF escaneado...
        {"attempted": 1, "extracted": 0, "sin_texto": 1},
        # ...y las siguientes, con la fila ya en sin_texto: el recuento sale a cero.
        {"attempted": 0, "extracted": 0, "sin_texto": 0},
    ],
)
def test_extraer_acta_escaneada_es_sin_tabla(entorno: _Entorno, recuento: dict[str, int]) -> None:
    _sin_paginas(entorno, _acta("sin_texto"))
    entorno.ensure.return_value = {**_ENSURE_OK, **recuento}

    assert extraer_puntuaciones(_LIC, model=_MODELO) == "sin_tabla"

    entorno.llamar.assert_not_called()
    guardado = _guardado(entorno)
    assert guardado["status"] == "sin_tabla"
    assert guardado["error_detail"] == "El acta no tiene texto extraíble (escaneada); falta OCR"
    assert guardado["documentos_leidos"] == 0
    assert guardado["model"] is None


def test_extraer_acta_en_formato_no_soportado_es_sin_tabla(entorno: _Entorno) -> None:
    # ``unsupported`` ni siquiera cuenta como ``sin_texto`` en el recuento de la descarga.
    _sin_paginas(entorno, _acta("unsupported"))
    entorno.ensure.return_value = {**_ENSURE_OK, "extracted": 0, "unsupported": 1}

    assert extraer_puntuaciones(_LIC, model=_MODELO) == "sin_tabla"

    entorno.llamar.assert_not_called()
    guardado = _guardado(entorno)
    assert guardado["status"] == "sin_tabla"
    assert "formato no soportado" in guardado["error_detail"]
    assert guardado["model"] is None


def test_extraer_escaneada_y_no_soportada_dice_escaneada(entorno: _Entorno) -> None:
    _sin_paginas(entorno, _acta("unsupported"), _acta("sin_texto"))

    assert extraer_puntuaciones(_LIC, model=_MODELO) == "sin_tabla"

    assert "escaneada" in _guardado(entorno)["error_detail"]


@pytest.mark.parametrize("pendiente", ["pending", "downloaded", "error"])
def test_extraer_escaneada_con_otra_acta_por_resolver_sigue_siendo_error(
    entorno: _Entorno, pendiente: str
) -> None:
    """Una acta escaneada y otra que aún puede leerse: no se da el expediente por vacío."""
    _sin_paginas(entorno, _acta("sin_texto"), _acta(pendiente))

    with pytest.raises(RuntimeError, match="descargar"):
        extraer_puntuaciones(_LIC, model=_MODELO)

    assert _guardado(entorno)["status"] == "error"


def test_extraer_ignora_lo_que_no_es_acta_ni_esta_publicado(entorno: _Entorno) -> None:
    # Un pliego escaneado o un acta anunciada y sin publicar no deciden por la lectura del acta.
    _sin_paginas(entorno, _acta("sin_texto", tipo="legal"), _acta("pending", sin_publicar=True))

    with pytest.raises(RuntimeError, match="descargar"):
        extraer_puntuaciones(_LIC, model=_MODELO)

    assert _guardado(entorno)["status"] == "error"

    entorno.repo.guardar.reset_mock()
    _sin_paginas(entorno, _acta("sin_texto"), _acta("pending", sin_publicar=True))

    assert extraer_puntuaciones(_LIC, model=_MODELO) == "sin_tabla"


def test_extraer_descarga_fallida_lanza_y_deja_error(entorno: _Entorno) -> None:
    entorno.ensure.return_value = {**_ENSURE_OK, "extracted": 0, "error": 1}
    entorno.paginas_repo.list_pages_by_licitacion.return_value = []

    with pytest.raises(RuntimeError, match="descargar"):
        extraer_puntuaciones(_LIC, model=_MODELO)

    entorno.llamar.assert_not_called()
    guardado = _guardado(entorno)
    assert guardado["status"] == "error"
    assert guardado["filas"] == []
    assert guardado["model"] == _MODELO
    assert guardado["extraction_version"] == EXTRACTION_VERSION
    assert "descargar" in guardado["error_detail"]


def test_extraer_llm_vacio_lanza_y_deja_error(entorno: _Entorno) -> None:
    entorno.llamar.side_effect = ValueError("El modelo m devolvió una respuesta vacía")

    with pytest.raises(ValueError, match="respuesta vacía"):
        extraer_puntuaciones(_LIC, model=_MODELO)

    guardado = _guardado(entorno)
    assert guardado["status"] == "error"
    assert guardado["filas"] == []
    assert "respuesta vacía" in guardado["error_detail"]


def test_extraer_json_ilegible_lanza_y_deja_error(entorno: _Entorno) -> None:
    entorno.llamar.return_value = "No encuentro ninguna tabla."

    with pytest.raises(ValueError, match="objeto JSON"):
        extraer_puntuaciones(_LIC, model=_MODELO)

    assert _guardado(entorno)["status"] == "error"


def test_extraer_error_detail_se_trunca_a_500(entorno: _Entorno) -> None:
    entorno.llamar.side_effect = RuntimeError("x" * 900)

    with pytest.raises(RuntimeError):
        extraer_puntuaciones(_LIC, model=_MODELO)

    assert len(_guardado(entorno)["error_detail"]) == 500


@pytest.mark.parametrize("modo", ["devuelve_texto", "vacio_como_el_cliente_real"])
def test_extraer_tope_de_tiempo(entorno: _Entorno, modo: str) -> None:
    """Al vencer el tope, ``stop`` se activa: el job falla por tiempo, no por el texto."""

    def _modelo_lento(*_: object, stop: threading.Event, **__: object) -> str:
        assert stop.wait(5), "el tope no activó la señal de parada"
        if modo == "vacio_como_el_cliente_real":
            # ``stream_llm_response`` termina sin tokens con ``stop`` activo y
            # ``_llamar_modelo`` lo convierte en «respuesta vacía».
            raise ValueError("respuesta vacía")
        return _respuesta()

    entorno.llamar.side_effect = _modelo_lento

    with (
        patch("services.puntuaciones_acta._TOPE_LLM_SEGUNDOS", 0.05),
        pytest.raises(TimeoutError),
    ):
        extraer_puntuaciones(_LIC, model=_MODELO)

    guardado = _guardado(entorno)
    assert guardado["status"] == "error"
    assert guardado["filas"] == []


class _TimerFalso:
    """Registra su vida: ni arranca un hilo ni dispara nada."""

    instancias: ClassVar[list[_TimerFalso]] = []

    def __init__(self, intervalo: float, funcion: Any) -> None:
        self.intervalo = intervalo
        self.funcion = funcion
        self.daemon = False
        self.arrancado = False
        self.cancelado = False
        _TimerFalso.instancias.append(self)

    def start(self) -> None:
        self.arrancado = True

    def cancel(self) -> None:
        self.cancelado = True


@pytest.mark.parametrize("falla", [False, True])
def test_el_temporizador_del_tope_se_cancela_siempre(entorno: _Entorno, falla: bool) -> None:
    _TimerFalso.instancias = []
    if falla:
        entorno.llamar.side_effect = RuntimeError("proveedor caído")

    with patch("services.puntuaciones_acta.threading.Timer", _TimerFalso):
        if falla:
            with pytest.raises(RuntimeError):
                extraer_puntuaciones(_LIC, model=_MODELO)
        else:
            extraer_puntuaciones(_LIC, model=_MODELO)

    (timer,) = _TimerFalso.instancias
    assert timer.arrancado and timer.cancelado
    assert timer.intervalo == 300
    assert timer.daemon  # un job colgado no debe retener el apagado del proceso


# --- la pregunta y el modelo -------------------------------------------------


def test_la_pregunta_cabe_en_el_cliente_y_pide_lo_acordado() -> None:
    from llm.client import MAX_INTERNAL_QUESTION_LEN, _validate_request

    assert len(_PREGUNTA_ACTA) <= MAX_INTERNAL_QUESTION_LEN
    _validate_request(_PREGUNTA_ACTA, [], settings.PLIEGO_FACTS_MODEL, mode="extraction")
    for exigido in (
        "excluida",
        "cita",
        "literal",
        "300",
        "pagina",
        "documento_id",
        '{"lotes": []}',
    ):
        assert exigido in _PREGUNTA_ACTA


def test_llamar_modelo_pasa_stop_al_cliente_y_sin_el_usa_la_del_tope() -> None:
    from services.rag.fact_sheet import _llamar_modelo

    pagina = [{"documento_id": 1, "page_number": 2, "texto": "t"}]
    parada = threading.Event()
    with patch("services.rag.fact_sheet.stream_llm_response", return_value=iter(["{}"])) as stream:
        _llamar_modelo(
            "p",
            pagina,
            licitacion_id=_LIC,
            model=_MODELO,
            keywords=("a",),
            max_tokens=1,
            stop=parada,
        )
        assert stream.call_args.kwargs["stop"] is parada
    with patch("services.rag.fact_sheet.stream_llm_response", return_value=iter(["{}"])) as stream:
        _llamar_modelo(
            "p", pagina, licitacion_id=_LIC, model=_MODELO, keywords=("a",), max_tokens=1
        )
        # Sin la de quien llama, la llamada lleva la suya: la del tope total.
        propia = stream.call_args.kwargs["stop"]
        assert isinstance(propia, threading.Event) and not propia.is_set()


# --- cola y worker -----------------------------------------------------------


def _job(payload: dict[str, object]) -> Job:
    ahora = datetime.now(UTC)
    return Job(
        id=1,
        tipo=TIPO_PUNTUACIONES_ACTA,
        payload=payload,
        organization_id=None,
        estado="running",
        intentos=1,
        run_after=ahora,
        locked_by="test",
        locked_at=ahora,
        resultado=None,
        error_detail=None,
        created_at=ahora,
        updated_at=ahora,
    )


def test_el_tipo_esta_declarado_a_demanda_y_deduplicado_por_expediente() -> None:
    declarado = TIPOS_A_DEMANDA[TIPO_PUNTUACIONES_ACTA]
    assert declarado.handler == "scheduler.worker:ejecutar_puntuaciones_acta"
    assert declarado.clave_dedupe == "licitacion_id"


def test_worker_devuelve_el_estado(entorno: _Entorno) -> None:
    from scheduler.worker import ejecutar_puntuaciones_acta

    resultado = ejecutar_puntuaciones_acta(_job({"licitacion_id": _LIC, "model": _MODELO}))

    assert resultado == {"licitacion_id": _LIC, "status": "ok"}
    assert _guardado(entorno)["model"] == _MODELO


def test_worker_lanza_si_queda_en_error(entorno: _Entorno) -> None:
    """La cola reintenta solo lo que lanza: un ``error`` guardado en silencio no se reintentaría."""
    from scheduler.worker import ejecutar_puntuaciones_acta

    entorno.llamar.side_effect = ValueError("respuesta vacía")

    with pytest.raises(ValueError, match="respuesta vacía"):
        ejecutar_puntuaciones_acta(_job({"licitacion_id": _LIC, "model": _MODELO}))

    assert _guardado(entorno)["status"] == "error"

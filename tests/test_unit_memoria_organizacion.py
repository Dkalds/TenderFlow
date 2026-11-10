"""Memoria de la organización (ADR-040): la lógica que no necesita base de datos.

Lo que aquí se fija es lo que decide **qué** se indexa y **qué** se cita; que el
SQL no cruce organizaciones lo prueban ``tests/test_rls_tenant_scope_integration.py``
y el escenario de ``tests/test_escenario_adjuntos.py``.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, ClassVar
from unittest.mock import patch

import pytest

import services.memoria_organizacion as memoria
import services.pursuit_attachments as adjuntos

# ── Dobles ──────────────────────────────────────────────────────────────────


class _Repo:
    """Lo justo de ``PursuitAttachmentsRepository`` que usan los dos servicios."""

    def __init__(self, fila: dict[str, Any] | None = None, *, indexables: int = 0) -> None:
        self.fila = fila
        self.indexables = indexables
        self.guardado: dict[str, Any] | None = None
        self.sin_texto: list[tuple[str, str]] = []
        self.busquedas: list[str] = []
        self.permiso_al_guardar = True

    def get(self, attachment_id: int, *, organization_id: int) -> dict[str, Any] | None:
        return self.fila

    def contar_indexables(self, organization_id: int) -> int:
        return self.indexables

    def set_indexable(
        self, attachment_id: int, *, organization_id: int, indexable: bool
    ) -> dict[str, Any] | None:
        if self.fila is None:
            return None
        self.fila = {
            **self.fila,
            "indexable": indexable,
            "index_status": "pending" if indexable else None,
        }
        return self.fila

    def delete(self, attachment_id: int, *, organization_id: int) -> str | None:
        return None if self.fila is None else str(self.fila["blob_key"])

    def reemplazar_fragmentos(self, attachment_id: int, **kwargs: Any) -> int | None:
        if not self.permiso_al_guardar:
            return None
        self.guardado = kwargs
        return len(kwargs["fragmentos"])

    def marcar_sin_texto(
        self, attachment_id: int, *, organization_id: int, estado: str, error: str
    ) -> bool:
        self.sin_texto.append((estado, error))
        return True

    def buscar_por_palabras(self, organization_id: int, terminos: Any, **_: Any) -> list[Any]:
        self.busquedas.append("palabras")
        return []

    def buscar_por_significado(self, organization_id: int, embedding: Any, **_: Any) -> list[Any]:
        self.busquedas.append("significado")
        return []


class _Almacen:
    enabled = True

    def __init__(self, contenido: bytes | None = b"binario") -> None:
        self.contenido = contenido

    def get(self, key: str) -> bytes | None:
        return self.contenido


def _adjunto(**campos: Any) -> dict[str, Any]:
    return {
        "id": 11,
        "pursuit_id": 42,
        "organization_id": 7,
        # Compuesta y no literal: una cadena con pinta de clave la marca gitleaks.
        "blob_key": "/".join(("adjuntos", "7", "42", "abc")),
        "filename": "Propuesta.pdf",
        "content_type": "application/pdf",
        "size_bytes": 1024,
        "indexable": True,
        "index_status": "pending",
        **campos,
    }


def _fila_cita(**campos: Any) -> dict[str, Any]:
    return {
        "attachment_id": 11,
        "chunk_index": 0,
        "page_number": 3,
        "texto": "Migramos el ERP de la Diputación a SAP S/4HANA en nueve meses.",
        "filename": "Propuesta.pdf",
        "pursuit_id": 42,
        "licitacion_id": "EXP-1",
        "licitacion_titulo": "Implantación de SAP",
        "score": 0.0,
        "n_terminos": 0,
        "cobertura": 0,
        "extracto": None,
        **campos,
    }


@pytest.fixture
def sin_motor_masivo(monkeypatch: pytest.MonkeyPatch) -> None:
    """El proceso de la API: sin motor para embeber un documento entero."""
    import services.embeddings as emb

    monkeypatch.setattr(emb, "embeddings_masivos_disponibles", lambda: False)
    monkeypatch.setattr(emb, "embeddings_available", lambda: False)


def _indexar(repo: _Repo, extraer: Any, *, almacen: _Almacen | None = None, **kwargs: Any) -> Any:
    with (
        patch.object(memoria, "_repo", return_value=repo),
        patch("shared.object_store.get_object_store", return_value=almacen or _Almacen()),
    ):
        return memoria.indexar(11, 7, extraer=extraer, **kwargs)


# ── Qué se puede indexar ────────────────────────────────────────────────────


def test_solo_es_indexable_lo_que_se_adjunta_y_se_sabe_leer() -> None:
    from scraper.document_fetcher import supported_content_types

    assert set(adjuntos.TIPOS_PERMITIDOS) >= memoria.TIPOS_INDEXABLES
    assert supported_content_types() >= memoria.TIPOS_INDEXABLES


def test_los_topes_salen_del_entorno_y_cero_apaga(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEMORIA_ORG_MAX_DOCUMENTOS", raising=False)
    monkeypatch.delenv("MEMORIA_ORG_MAX_BYTES_POR_DOCUMENTO", raising=False)
    por_defecto = memoria.politica_indexado()
    assert (por_defecto.max_documentos, por_defecto.max_bytes) == (5, 5 * 1024 * 1024)
    assert por_defecto.disponible

    monkeypatch.setenv("MEMORIA_ORG_MAX_DOCUMENTOS", "0")
    monkeypatch.setenv("MEMORIA_ORG_MAX_BYTES_POR_DOCUMENTO", "2048")
    apagado = memoria.politica_indexado()
    assert (apagado.max_documentos, apagado.max_bytes) == (0, 2048)
    assert not apagado.disponible


def test_la_cuota_de_adjuntos_es_configurable_y_conserva_su_valor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PURSUIT_ATTACHMENT_MAX_BYTES_POR_ORGANIZACION", raising=False)
    assert adjuntos.max_bytes_por_organizacion() == adjuntos.MAX_BYTES_POR_ORGANIZACION

    monkeypatch.setenv("PURSUIT_ATTACHMENT_MAX_BYTES_POR_ORGANIZACION", "1000")
    assert adjuntos.max_bytes_por_organizacion() == 1000


# ── Fragmentos y páginas ────────────────────────────────────────────────────


def test_cada_fragmento_hereda_la_pagina_en_la_que_empieza() -> None:
    paginas = ["uno " * 500, "dos " * 500, "tres " * 20]

    fragmentos, numeros = memoria.fragmentar(paginas)

    assert len(fragmentos) == len(numeros) > 2
    assert numeros[0] == 1
    assert numeros == sorted(n for n in numeros if n is not None)
    for texto, numero in zip(fragmentos, numeros, strict=True):
        # La segunda palabra: el solape puede empezar un fragmento a media palabra.
        assert texto.split()[1] == {1: "uno", 2: "dos", 3: "tres"}[numero or 0]


def test_un_documento_sin_texto_no_da_fragmentos() -> None:
    assert memoria.fragmentar(["", "  \n "]) == ([], [])


# ── Indexado ────────────────────────────────────────────────────────────────


def test_indexar_guarda_fragmentos_sin_vectores_si_no_hay_motor(sin_motor_masivo: None) -> None:
    repo = _Repo(_adjunto())

    resultado = _indexar(repo, lambda contenido, tipo: ["Primera página.", "Segunda página."])

    assert resultado["estado"] == "indexed"
    assert resultado["con_embeddings"] is False
    assert repo.guardado is not None
    assert repo.guardado["embeddings"] is None
    assert repo.guardado["organization_id"] == 7
    assert repo.guardado["paginas"] == [1]


def test_indexar_embebe_cuando_el_proceso_tiene_motor(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.embeddings as emb

    monkeypatch.setattr(emb, "embeddings_masivos_disponibles", lambda: True)
    monkeypatch.setattr(emb, "encode_texts", lambda textos: [[0.1] * 3 for _ in textos])
    repo = _Repo(_adjunto())

    resultado = _indexar(repo, lambda contenido, tipo: ["Texto de la propuesta."])

    assert resultado["con_embeddings"] is True
    assert repo.guardado is not None
    assert len(repo.guardado["embeddings"]) == len(repo.guardado["fragmentos"])


@pytest.mark.parametrize("fila", [None, _adjunto(indexable=False)])
def test_sin_permiso_no_se_lee_el_binario(fila: dict[str, Any] | None) -> None:
    def _extraer(contenido: bytes, tipo: str) -> list[str]:
        raise AssertionError("no debe extraerse un adjunto sin permiso")

    repo = _Repo(fila)

    assert _indexar(repo, _extraer)["estado"] == "sin_permiso"
    assert repo.guardado is None


def test_un_adjunto_ya_indexado_no_se_repite() -> None:
    def _extraer(contenido: bytes, tipo: str) -> list[str]:
        raise AssertionError("un job duplicado no repite el trabajo")

    resultado = _indexar(_Repo(_adjunto(index_status="indexed")), _extraer)

    assert resultado == {"attachment_id": 11, "estado": "indexed", "repetido": True}


def test_si_el_permiso_se_retira_mientras_tanto_no_queda_indexado(sin_motor_masivo: None) -> None:
    repo = _Repo(_adjunto())
    repo.permiso_al_guardar = False

    assert _indexar(repo, lambda c, t: ["Texto."])["estado"] == "sin_permiso"


@pytest.mark.parametrize("estado", ["unsupported", "sin_texto", "error"])
def test_lo_que_no_se_puede_leer_queda_con_su_estado_y_no_falla_el_job(estado: Any) -> None:
    def _extraer(contenido: bytes, tipo: str) -> list[str]:
        raise memoria.TextoNoExtraible(estado, "motivo legible")

    repo = _Repo(_adjunto())

    assert _indexar(repo, _extraer)["estado"] == estado
    assert repo.sin_texto == [(estado, "motivo legible")]


def test_un_documento_vacio_queda_sin_texto(sin_motor_masivo: None) -> None:
    repo = _Repo(_adjunto())

    assert _indexar(repo, lambda c, t: ["   "])["estado"] == "sin_texto"
    assert repo.guardado is None


def test_sin_binario_en_el_almacen_queda_en_error() -> None:
    repo = _Repo(_adjunto())

    resultado = _indexar(repo, lambda c, t: ["Texto."], almacen=_Almacen(None))

    assert resultado["estado"] == "error"


def test_un_fallo_reintentable_se_propaga_y_solo_el_ultimo_intento_marca_error() -> None:
    def _extraer(contenido: bytes, tipo: str) -> list[str]:
        raise ConnectionError("el almacén no responde")

    repo = _Repo(_adjunto())
    with pytest.raises(ConnectionError):
        _indexar(repo, _extraer)
    assert repo.sin_texto == []

    with pytest.raises(ConnectionError):
        _indexar(repo, _extraer, ultimo_intento=True)
    assert [estado for estado, _ in repo.sin_texto] == ["error"]


def test_el_handler_del_worker_traduce_los_fallos_del_extractor() -> None:
    """`services/` no importa de `scraper/`: el worker le pasa el extractor hecho."""
    import scheduler.worker as worker
    from scraper.document_fetcher import PdfSinTextoError, UnsupportedDocumentError

    casos = [
        (PdfSinTextoError("escaneado"), "sin_texto"),
        (UnsupportedDocumentError("xlsx", content_type="application/x"), "unsupported"),
    ]
    for excepcion, estado in casos:
        with (
            patch("scraper.document_fetcher.extraer_paginas", side_effect=excepcion),
            pytest.raises(memoria.TextoNoExtraible) as recogida,
        ):
            worker._paginas_de_adjunto(b"x", "application/pdf")
        assert recogida.value.estado == estado


def test_el_handler_no_indexa_un_job_sin_organizacion() -> None:
    import scheduler.worker as worker
    from services.jobs import JobSinReintento

    class _Job:
        organization_id = None
        payload: ClassVar[dict[str, int]] = {"attachment_id": 11}
        intentos = 1

    with pytest.raises(JobSinReintento):
        worker.ejecutar_indexado_adjunto(_Job())  # type: ignore[arg-type]


def test_el_tipo_de_job_esta_declarado_con_cuota_y_dedupe() -> None:
    from services import jobs

    declarado = jobs.TIPOS_A_DEMANDA[jobs.TIPO_INDEXADO_ADJUNTO]
    assert declarado.clave_dedupe == "attachment_id"
    assert declarado.handler == "scheduler.worker:ejecutar_indexado_adjunto"
    assert jobs.TIPO_INDEXADO_ADJUNTO in jobs.TIPOS_CON_CUOTA


# ── Qué se cita ─────────────────────────────────────────────────────────────


def test_los_terminos_son_palabras_de_tres_letras_sin_repetir() -> None:
    assert memoria.terminos_de("¿Qué experiencia en SAP y en sap S/4HANA?") == [
        "qué",
        "experiencia",
        "sap",
        "4hana",
    ]


def test_por_significado_solo_se_cita_lo_que_pasa_el_umbral() -> None:
    cerca = _fila_cita(score=memoria.UMBRAL_SIGNIFICADO + 0.1)
    lejos = _fila_cita(attachment_id=12, score=memoria.UMBRAL_SIGNIFICADO - 0.1)

    elegidas = memoria.seleccionar([cerca, lejos], [])

    assert [c.attachment_id for c in elegidas] == [11]


def test_por_palabras_hace_falta_cobertura_y_una_sola_palabra_basta_si_es_la_unica() -> None:
    una_de_tres = _fila_cita(cobertura=1, n_terminos=3)
    dos_de_tres = _fila_cita(attachment_id=12, cobertura=2, n_terminos=3)
    la_unica = _fila_cita(attachment_id=13, cobertura=1, n_terminos=1)
    sin_terminos = _fila_cita(attachment_id=14, cobertura=0, n_terminos=0)

    elegidas = memoria.seleccionar([], [una_de_tres, dos_de_tres, la_unica, sin_terminos])

    assert [c.attachment_id for c in elegidas] == [12, 13]


def test_la_cita_es_un_extracto_literal_con_su_origen() -> None:
    fila = _fila_cita(cobertura=2, n_terminos=2, extracto="el ERP de la Diputación a SAP")

    (cita,) = memoria.seleccionar([], [fila])

    assert cita.cita == "el ERP de la Diputación a SAP"
    assert cita.cita in fila["texto"]
    assert (cita.filename, cita.page_number) == ("Propuesta.pdf", 3)
    assert (cita.pursuit_id, cita.licitacion_id) == (42, "EXP-1")
    assert cita.licitacion_titulo == "Implantación de SAP"
    assert "organization_id" not in cita.model_dump()
    assert "blob_key" not in cita.model_dump()


def test_una_cita_por_pagina_y_un_tope_por_pregunta() -> None:
    misma_pagina = [_fila_cita(chunk_index=i, score=0.9) for i in range(3)]
    otras = [_fila_cita(attachment_id=20 + i, score=0.8) for i in range(5)]

    elegidas = memoria.seleccionar(misma_pagina + otras, [])

    assert len(elegidas) == memoria.MAX_CITAS
    assert [c.attachment_id for c in elegidas] == [11, 20, 21]


def test_un_fragmento_largo_se_recorta_sin_partir_palabras() -> None:
    from services.rag.citas import MAX_CITA_CHARS

    (cita,) = memoria.seleccionar([_fila_cita(texto="palabra " * 200, score=0.9)], [])

    assert len(cita.cita) <= MAX_CITA_CHARS + 1
    assert cita.cita.endswith("palabra…")


def test_sin_documentos_indexables_no_se_busca_ni_se_codifica(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(memoria, "_vectores", lambda consultas: pytest.fail("no debe codificar"))
    repo = _Repo(indexables=0)

    with patch.object(memoria, "_repo", return_value=repo):
        assert memoria.citas(7, ["¿experiencia en SAP?", "plan de trabajo"]) == [[], []]
    assert repo.busquedas == []


def test_con_el_indexado_apagado_no_se_consulta_nada(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORIA_ORG_MAX_DOCUMENTOS", "0")

    with patch.object(memoria, "_repo", side_effect=AssertionError("no debe abrir el repo")):
        assert memoria.citas(7, ["¿experiencia en SAP?"]) == [[]]


def test_sin_motor_se_busca_solo_por_palabras(sin_motor_masivo: None) -> None:
    repo = _Repo(indexables=1)

    with patch.object(memoria, "_repo", return_value=repo):
        memoria.citas(7, ["¿experiencia en SAP?"])

    assert repo.busquedas == ["palabras"]


# ── El permiso por fichero ──────────────────────────────────────────────────


@contextmanager
def _alcance(user_id: Any, organization_id: Any = None, *, write: bool = False):
    yield 7, "owner"


def _marcar(repo: _Repo, *, indexable: bool, encolar: Any = None) -> tuple[Any, list[Any]]:
    auditados: list[Any] = []
    with (
        patch.object(adjuntos, "alcance_resuelto", _alcance),
        patch.object(adjuntos, "PursuitAttachmentsRepository", return_value=repo),
        patch.object(adjuntos, "_encolar_indexado", encolar or (lambda *a: 1)),
        patch("db.audit.log_event", side_effect=lambda **k: auditados.append(k)),
    ):
        return adjuntos.marcar_indexable(1, 11, indexable=indexable), auditados


def test_activar_deja_pendiente_encola_y_queda_en_el_rastro() -> None:
    encolados: list[tuple[int, int]] = []
    repo = _Repo(_adjunto(indexable=False, index_status=None))

    fila, auditados = _marcar(repo, indexable=True, encolar=lambda a, o: encolados.append((a, o)))

    assert fila["index_status"] == "pending"
    assert encolados == [(11, 7)]
    (evento,) = auditados
    assert evento["event_type"] == "pursuit_attachment.indexing_changed"
    assert evento["resource"] == "org:7"
    assert evento["detail"] == {
        "attachment_id": 11,
        "pursuit_id": 42,
        "indexable": True,
        "motivo": "permiso",
    }


def test_repetir_el_mismo_valor_no_encola_ni_audita() -> None:
    repo = _Repo(_adjunto(indexable=True, index_status="indexed"))

    _, auditados = _marcar(
        repo, indexable=True, encolar=lambda *a: pytest.fail("no debe volver a encolar")
    )

    assert auditados == []


def test_desactivar_queda_en_el_rastro() -> None:
    repo = _Repo(_adjunto(indexable=True, index_status="indexed"))

    fila, auditados = _marcar(repo, indexable=False)

    assert fila["indexable"] is False
    assert [e["detail"]["indexable"] for e in auditados] == [False]


@pytest.mark.parametrize(
    ("campos", "indexables", "mensaje"),
    [
        ({"content_type": "image/png"}, 0, "no se puede extraer texto"),
        ({"size_bytes": 6 * 1024 * 1024}, 0, "supera el tope"),
        ({}, 5, "su tope"),
    ],
)
def test_no_se_activa_lo_que_no_cabe_en_la_politica(
    campos: dict[str, Any], indexables: int, mensaje: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MEMORIA_ORG_MAX_DOCUMENTOS", raising=False)
    monkeypatch.delenv("MEMORIA_ORG_MAX_BYTES_POR_DOCUMENTO", raising=False)
    repo = _Repo(_adjunto(indexable=False, index_status=None, **campos), indexables=indexables)

    with pytest.raises(adjuntos.IndexadoRechazado, match=mensaje):
        _marcar(repo, indexable=True)
    assert repo.fila is not None
    assert repo.fila["indexable"] is False


def test_con_el_indexado_apagado_no_se_activa_pero_si_se_desactiva(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEMORIA_ORG_MAX_DOCUMENTOS", "0")

    with pytest.raises(adjuntos.IndexadoRechazado, match="no está activado"):
        _marcar(_Repo(_adjunto(indexable=False)), indexable=True)

    fila, _ = _marcar(_Repo(_adjunto(indexable=True)), indexable=False)
    assert fila["indexable"] is False


def test_si_no_se_puede_encolar_el_permiso_se_deshace() -> None:
    def _cola_llena(*_: Any) -> int:
        raise RuntimeError("cola llena")

    repo = _Repo(_adjunto(indexable=False, index_status=None))

    with pytest.raises(adjuntos.IndexadoRechazado, match="cola de indexado"):
        _marcar(repo, indexable=True, encolar=_cola_llena)
    assert repo.fila is not None
    assert repo.fila["indexable"] is False


def test_retirar_un_adjunto_indexado_queda_en_el_rastro() -> None:
    auditados: list[Any] = []
    repo = _Repo(_adjunto(indexable=True, index_status="indexed"))
    with (
        patch.object(adjuntos, "alcance_resuelto", _alcance),
        patch.object(adjuntos, "PursuitAttachmentsRepository", return_value=repo),
        patch("db.audit.log_event", side_effect=lambda **k: auditados.append(k)),
    ):
        assert adjuntos.borrar(1, 11) is True

    (evento,) = auditados
    assert evento["detail"]["indexable"] is False
    assert evento["detail"]["motivo"] == "adjunto_retirado"


# ── Dónde se enseñan ────────────────────────────────────────────────────────


def _cita() -> memoria.CitaOrganizacion:
    return memoria.CitaOrganizacion(
        attachment_id=11,
        filename="Propuesta.pdf",
        page_number=3,
        cita="Migramos el ERP en nueve meses.",
        pursuit_id=42,
        licitacion_id="EXP-1",
    )


def test_el_guion_recibe_las_citas_en_una_copia_y_el_cacheado_no_cambia() -> None:
    """El guion de la caché es de todas las organizaciones: no puede llevarse las de una."""
    from services.rag.guion_oferta import (
        GuionCriterio,
        GuionOferta,
        PuntoGuion,
        con_citas_de_organizacion,
    )

    cacheado = GuionOferta(
        licitacion_id="EXP-1",
        criterios=[
            GuionCriterio(criterio="Plan de trabajo", puntos=[PuntoGuion(texto="Cronograma.")]),
            GuionCriterio(criterio="Equipo", puntos=[PuntoGuion(texto="Perfiles.")]),
        ],
    )
    pedidas: list[Any] = []

    def _citas(organization_id: int, consultas: Any) -> list[list[memoria.CitaOrganizacion]]:
        pedidas.append((organization_id, list(consultas)))
        return [[_cita()], []]

    with patch.object(memoria, "citas", _citas):
        propio = con_citas_de_organizacion(cacheado, 7)

    assert pedidas == [(7, ["Plan de trabajo", "Equipo"])]
    assert [len(c.citas_organizacion) for c in propio.criterios] == [1, 0]
    assert all(c.citas_organizacion == [] for c in cacheado.criterios)
    # Los puntos, que sí salen del modelo, no cambian: D33.
    assert [c.puntos for c in propio.criterios] == [c.puntos for c in cacheado.criterios]


def test_si_la_busqueda_falla_el_guion_sale_sin_citas_propias() -> None:
    from services.rag.guion_oferta import GuionCriterio, GuionOferta, con_citas_de_organizacion

    guion = GuionOferta(licitacion_id="EXP-1", criterios=[GuionCriterio(criterio="Equipo")])

    with patch.object(memoria, "citas", side_effect=RuntimeError("bd caída")):
        assert con_citas_de_organizacion(guion, 7) is guion


@pytest.mark.parametrize(
    ("principal", "esperada"),
    [
        ({"organization_id": 7, "auth_method": "session"}, 7),
        ({"organization_id": 7, "auth_method": "api_key", "scopes": "ask:read"}, None),
        ({"organization_id": 7, "auth_method": "api_key", "scopes": "ask:read,pursuits:read"}, 7),
        ({"organization_id": 7, "auth_method": "api_key", "scopes": ["*"]}, 7),
        ({"auth_method": "session"}, None),
    ],
)
def test_que_principal_puede_recibir_citas_de_documentos_propios(
    principal: dict[str, Any], esperada: int | None
) -> None:
    from api.routes.ask import _organizacion_para_citas

    assert _organizacion_para_citas(principal) == esperada  # type: ignore[arg-type]


def test_las_citas_propias_de_ask_no_rompen_la_pregunta_si_fallan() -> None:
    from api.routes.ask import _fuentes_organizacion

    with patch.object(memoria, "citas", side_effect=RuntimeError("bd caída")):
        assert _fuentes_organizacion("¿experiencia en SAP?", 7) == []

    with patch.object(memoria, "citas", return_value=[[_cita()]]):
        (fuente,) = _fuentes_organizacion("¿experiencia en SAP?", 7)
    assert fuente["filename"] == "Propuesta.pdf"
    assert fuente["licitacion_id"] == "EXP-1"

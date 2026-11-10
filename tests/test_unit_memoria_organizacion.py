"""Memoria de la organización (ADR-040): la lógica que no necesita base de datos.

Lo que aquí se fija es lo que decide **qué** se indexa y **qué** se cita; que el
SQL no cruce organizaciones lo prueban ``tests/test_rls_tenant_scope_integration.py``
y el escenario de ``tests/test_escenario_adjuntos.py``.
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
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
        #: ``(indexable, actor, motivo)`` de cada cambio de permiso pedido.
        self.permisos: list[tuple[bool, int | None, str]] = []
        self.retirados: list[tuple[int, int | None]] = []

    def get(self, attachment_id: int, *, organization_id: int) -> dict[str, Any] | None:
        return self.fila

    def contar_indexables(self, organization_id: int) -> int:
        return self.indexables

    def set_indexable(
        self,
        attachment_id: int,
        *,
        organization_id: int,
        indexable: bool,
        actor_user_id: int | None = None,
        motivo: str = "permiso",
    ) -> dict[str, Any] | None:
        if self.fila is None:
            return None
        self.permisos.append((indexable, actor_user_id, motivo))
        self.fila = {
            **self.fila,
            "indexable": indexable,
            "index_status": "pending" if indexable else None,
        }
        return self.fila

    def delete(
        self, attachment_id: int, *, organization_id: int, actor_user_id: int | None = None
    ) -> str | None:
        self.retirados.append((attachment_id, actor_user_id))
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


@pytest.fixture(autouse=True)
def _sin_conexion_agrupada(monkeypatch: pytest.MonkeyPatch) -> None:
    """`citas` agrupa sus lecturas en una conexión; aquí el repositorio es un doble."""
    import db.connection as conexion

    monkeypatch.setattr(conexion, "lecturas_agrupadas", nullcontext)


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


def test_cada_tipo_indexable_se_lee_sin_los_extras_que_la_api_no_trae(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # El adjunto lo extrae el consumidor de la cola de la API, cuya imagen no
    # trae python-docx ni odfpy: un tipo indexable que los necesitara quedaría
    # `unsupported` para siempre. DOCX y ODT se leen con la biblioteca estándar.
    import sys

    from scraper.document_fetcher import ExtractorAusenteError, extraer_paginas

    monkeypatch.setitem(sys.modules, "docx", None)
    monkeypatch.setitem(sys.modules, "odf", None)
    for tipo in memoria.TIPOS_INDEXABLES:
        try:
            extraer_paginas(b"", tipo)
        except ExtractorAusenteError:
            pytest.fail(f"{tipo} necesita un extra que la imagen de la API no trae")
        except Exception:
            pass


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
    # Sin deduplicar: quitar y volver a dar el permiso mientras un job corre
    # tiene que encolar otro, o el adjunto se queda «pendiente» sin trabajo.
    assert declarado.clave_dedupe is None
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


def _marcar(repo: _Repo, *, indexable: bool, encolar: Any = None) -> Any:
    with (
        patch.object(adjuntos, "alcance_resuelto", _alcance),
        patch.object(adjuntos, "PursuitAttachmentsRepository", return_value=repo),
        patch.object(adjuntos, "_encolar_indexado", encolar or (lambda *a: 1)),
    ):
        return adjuntos.marcar_indexable(1, 11, indexable=indexable)


def test_activar_deja_pendiente_encola_y_pide_el_rastro_con_su_autor() -> None:
    """El evento lo escribe el repositorio en su transacción (ADR-039 §3): aquí
    se fija que el servicio le dice quién fue. El rastro de verdad lo comprueba
    el escenario de CU-37."""
    encolados: list[tuple[int, int]] = []
    repo = _Repo(_adjunto(indexable=False, index_status=None))

    fila = _marcar(repo, indexable=True, encolar=lambda a, o: encolados.append((a, o)))

    assert fila["index_status"] == "pending"
    assert encolados == [(11, 7)]
    assert repo.permisos == [(True, 1, "permiso")]


def test_repetir_el_mismo_valor_no_vuelve_a_encolar() -> None:
    repo = _Repo(_adjunto(indexable=True, index_status="indexed"))

    _marcar(repo, indexable=True, encolar=lambda *a: pytest.fail("no debe volver a encolar"))


def test_desactivar_pide_el_rastro_y_no_encola() -> None:
    repo = _Repo(_adjunto(indexable=True, index_status="indexed"))

    fila = _marcar(repo, indexable=False, encolar=lambda *a: pytest.fail("no debe encolar"))

    assert fila["indexable"] is False
    assert repo.permisos == [(False, 1, "permiso")]


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
    assert repo.permisos == []


def test_con_el_indexado_apagado_no_se_activa_pero_si_se_desactiva(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEMORIA_ORG_MAX_DOCUMENTOS", "0")

    with pytest.raises(adjuntos.IndexadoRechazado, match="no está activado"):
        _marcar(_Repo(_adjunto(indexable=False)), indexable=True)

    assert _marcar(_Repo(_adjunto(indexable=True)), indexable=False)["indexable"] is False


def test_si_la_cola_no_acepta_el_permiso_se_deshace_y_es_un_fallo_del_servicio() -> None:
    def _cola_caida(*_: Any) -> int:
        raise RuntimeError("la cola no responde")

    repo = _Repo(_adjunto(indexable=False, index_status=None))

    with pytest.raises(adjuntos.IndexadoNoDisponible, match="cola de indexado"):
        _marcar(repo, indexable=True, encolar=_cola_caida)
    assert repo.fila is not None
    assert repo.fila["indexable"] is False
    # Las dos vueltas quedan en el rastro, y la segunda dice por qué.
    assert repo.permisos == [(True, 1, "permiso"), (False, 1, "cola_no_disponible")]


def test_si_la_organizacion_agoto_su_cupo_de_jobs_se_dice_con_su_mensaje() -> None:
    from services.jobs import CuotaDeJobsExcedida

    def _sin_cupo(*_: Any) -> int:
        raise CuotaDeJobsExcedida("Tu organización ya tiene 20 trabajos de este tipo en cola.")

    repo = _Repo(_adjunto(indexable=False, index_status=None))

    with pytest.raises(adjuntos.IndexadoRechazado, match="20 trabajos"):
        _marcar(repo, indexable=True, encolar=_sin_cupo)
    assert repo.fila is not None
    assert repo.fila["indexable"] is False


def test_el_indexado_se_encola_sin_deduplicar() -> None:
    pedidos: list[dict[str, Any]] = []

    def _enqueue(tipo: str, payload: dict[str, Any], **kwargs: Any) -> int:
        pedidos.append({"tipo": tipo, "payload": payload, **kwargs})
        return 1

    with patch("services.jobs.enqueue", _enqueue):
        adjuntos._encolar_indexado(11, 7)

    assert pedidos == [
        {
            "tipo": "indexado_adjunto",
            "payload": {"attachment_id": 11},
            "organization_id": 7,
            "deduplicar": False,
        }
    ]


def test_retirar_un_adjunto_le_dice_al_repositorio_quien_fue() -> None:
    repo = _Repo(_adjunto(indexable=True, index_status="indexed"))
    with (
        patch.object(adjuntos, "alcance_resuelto", _alcance),
        patch.object(adjuntos, "PursuitAttachmentsRepository", return_value=repo),
    ):
        assert adjuntos.borrar(1, 11) is True

    assert repo.retirados == [(11, 1)]


def test_un_job_que_llega_con_el_indexado_apagado_no_guarda_texto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _extraer(contenido: bytes, tipo: str) -> list[str]:
        raise AssertionError("apagado: no se lee el documento")

    monkeypatch.setenv("MEMORIA_ORG_MAX_DOCUMENTOS", "0")
    repo = _Repo(_adjunto())

    assert _indexar(repo, _extraer)["estado"] == "apagado"
    assert repo.guardado is None
    assert [estado for estado, _ in repo.sin_texto] == ["error"]


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


def test_si_la_busqueda_falla_el_guion_sale_sin_citas_propias_y_lo_dice() -> None:
    from services.rag.guion_oferta import GuionCriterio, GuionOferta, con_citas_de_organizacion

    guion = GuionOferta(licitacion_id="EXP-1", criterios=[GuionCriterio(criterio="Equipo")])

    with patch.object(memoria, "citas", side_effect=RuntimeError("bd caída")):
        resultado = con_citas_de_organizacion(guion, 7)

    # Sale el guion, sin citas propias, y dice que no se pudieron consultar.
    assert resultado.criterios == guion.criterios
    assert resultado.citas_organizacion_fallidas is True
    assert guion.citas_organizacion_fallidas is False


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
    from api.scopes import organizacion_para_citas

    assert organizacion_para_citas(principal) == esperada


def test_las_citas_propias_de_ask_no_rompen_la_pregunta_si_fallan_y_se_distinguen() -> None:
    from api.routes.ask import _fuentes_organizacion

    with patch.object(memoria, "citas", side_effect=RuntimeError("bd caída")):
        # `None`, no una lista vacía: no pudo consultar, que no es «no hay nada».
        assert _fuentes_organizacion("¿experiencia en SAP?", 7) is None

    with patch.object(memoria, "citas", return_value=[[_cita()]]):
        (fuente,) = _fuentes_organizacion("¿experiencia en SAP?", 7)
    assert fuente["filename"] == "Propuesta.pdf"
    assert fuente["licitacion_id"] == "EXP-1"

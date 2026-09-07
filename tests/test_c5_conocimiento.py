"""Conocimiento: citas, versión de embeddings, caché y voto (C5).

Cuatro huecos que el plan complementario mide:

- ``/ask`` no cita: los fragmentos entran al prompt con su documento y su
  página, y la respuesta sale como texto libre (hecho 20).
- El voto del asistente es un evento de telemetría que no llega a ninguna tabla
  (hecho 21).
- ``EMBEDDING_VERSION`` no lo lee ningún módulo y ``documento_chunks`` no guarda
  modelo ni versión: cambiar de modelo no tiene camino (hecho 6).
- No hay caché de respuestas del LLM: la misma pregunta sobre el mismo pliego se
  paga cada vez.
"""

from __future__ import annotations

import inspect
from typing import Any, ClassVar

import pytest


class TestMarcadoresDeCita:
    """C5.3 — emisor y lector tienen que coincidir literalmente."""

    def test_ida_y_vuelta_entre_el_prompt_y_el_extractor(self) -> None:
        """El test que impide que las dos mitades se separen en silencio.

        Si el bloque de contexto imprime una forma y el extractor espera otra,
        **todas** las citas se descartan como inventadas y la respuesta parece
        infundada aunque el modelo haya hecho justo lo que se le pidió.
        """
        from llm.prompts import marcador_de_chunk
        from services.rag.citas import extraer_marcadores

        chunk = {"documento_id": 12, "page_number": 3}
        marcador = marcador_de_chunk(chunk)
        assert marcador == "[doc:12 p.3]"
        assert extraer_marcadores(f"El plazo es de 24 meses {marcador}.") == [(12, 3)]

    def test_ida_y_vuelta_sin_pagina(self) -> None:
        from llm.prompts import marcador_de_chunk
        from services.rag.citas import extraer_marcadores

        marcador = marcador_de_chunk({"documento_id": 7})
        assert marcador == "[doc:7]"
        assert extraer_marcadores(f"…{marcador}") == [(7, None)]

    def test_un_chunk_sin_documento_no_produce_marcador(self) -> None:
        """Un marcador sin documento sería incitar al modelo a inventarse uno."""
        from llm.prompts import marcador_de_chunk

        assert marcador_de_chunk({"tipo": "ficha estructurada verificada"}) == ""

    def test_el_prompt_de_licitacion_pide_el_marcador(self) -> None:
        from llm.prompts import build_system_prompt

        prompt = build_system_prompt("licitacion", has_corpus_context=True)
        assert "[doc:N p.M]" in prompt
        assert "No inventes marcadores" in prompt

    def test_los_marcadores_no_se_repiten(self) -> None:
        from services.rag.citas import extraer_marcadores

        texto = "Uno [doc:1 p.2]. Dos [doc:1 p.2]. Tres [doc:1]."
        assert extraer_marcadores(texto) == [(1, 2), (1, None)]


class TestValidacionDeCitas:
    """C5.3 / D29 — se valida contra lo enviado, no contra lo que el modelo diga."""

    CHUNKS: ClassVar[list[dict[str, Any]]] = [
        {
            "documento_id": 5,
            "page_number": 2,
            "texto": "El plazo de ejecución es de 24 meses.",
            "tipo": "legal",
            "filename": "pcap.pdf",
        },
        {
            "documento_id": 5,
            "page_number": 9,
            "texto": "La solvencia técnica exige tres proyectos.",
            "tipo": "legal",
            "filename": "pcap.pdf",
        },
    ]

    def test_una_cita_de_un_documento_ausente_se_descarta(self) -> None:
        from services.rag.citas import validar

        validas, invalidas = validar("Dice tal cosa [doc:99 p.1].", self.CHUNKS)
        assert validas == []
        assert invalidas == [(99, 1)]

    def test_la_cita_valida_trae_pagina_y_extracto(self) -> None:
        from services.rag.citas import validar

        validas, _ = validar("Son 24 meses [doc:5 p.2].", self.CHUNKS)
        assert len(validas) == 1
        assert validas[0].documento_id == 5
        assert validas[0].page_number == 2
        assert "24 meses" in validas[0].cita
        assert validas[0].filename == "pcap.pdf"

    def test_una_pagina_equivocada_no_tira_la_cita_entera(self) -> None:
        """El documento sí estaba; perder la cita castigaría al lector."""
        from services.rag.citas import validar

        validas, invalidas = validar("Algo [doc:5 p.404].", self.CHUNKS)
        assert invalidas == []
        assert len(validas) == 1
        assert validas[0].page_number == 2, "cae al primer chunk de ese documento"

    def test_sin_citas_el_evento_lo_declara(self) -> None:
        """`sin_fuentes` es la señal que la UI necesita para pintar distinto."""
        from services.rag.citas import evento_sources

        evento = evento_sources("Creo que son 24 meses.", self.CHUNKS)
        assert evento["sin_fuentes"] is True
        assert evento["sources"] == []

    def test_el_evento_cuenta_las_inventadas(self) -> None:
        """Es la métrica que dice si el prompt funciona; después no se reconstruye."""
        from services.rag.citas import evento_sources

        evento = evento_sources("Uno [doc:5 p.2] y dos [doc:88].", self.CHUNKS)
        assert evento["sin_fuentes"] is False
        assert evento["descartadas"] == 1
        assert len(evento["sources"]) == 1

    def test_no_se_reescribe_la_respuesta(self) -> None:
        """Borrar una cita inventada dejaría la afirmación con aspecto de fundada."""
        import services.rag.citas as mod

        fuente = inspect.getsource(mod)
        assert "def evento_sources" in fuente
        assert "sub(" not in fuente.split("def evento_sources")[1], (
            "el módulo no debe reescribir el texto de la respuesta"
        )


class TestCitasEnLaRuta:
    """C5.3 — el evento es aditivo al stream y solo en modo licitación."""

    def test_el_stream_admite_un_evento_de_cierre(self) -> None:
        import api.routes.ask as mod

        assert "post_event" in inspect.signature(mod._stream_sse).parameters

    def test_solo_se_emite_en_modo_licitacion(self) -> None:
        import api.routes.ask as mod

        fuente = inspect.getsource(mod._stream_ask)
        assert 'if mode == "licitacion":' in fuente

    def test_una_respuesta_degradada_no_emite_sources(self) -> None:
        """No hay respuesta que citar: `sin_fuentes` ahí sería una afirmación falsa."""
        import api.routes.ask as mod

        fuente = inspect.getsource(mod._stream_sse)
        cuerpo_degradado = fuente.split('if kind == "degraded":')[1]
        assert "post_event" not in cuerpo_degradado


class TestPaginaDelChunk:
    """C5.3 — sin página, una cita a un pliego de 200 páginas no es referencia."""

    def test_los_offsets_apuntan_al_chunk_que_dicen(self) -> None:
        from services.rag.chunking import chunk_text, chunk_text_with_offsets

        texto = " ".join(f"palabra{i}" for i in range(600))
        con_offsets = chunk_text_with_offsets(texto)
        assert [c for c, _ in con_offsets] == chunk_text(texto), (
            "las dos funciones deben trocear igual"
        )
        for chunk, offset in con_offsets:
            assert texto.strip()[offset : offset + len(chunk)] == chunk

    def test_el_solape_no_colapsa_los_offsets(self) -> None:
        """Buscar desde cero devolvería siempre la primera aparición."""
        from services.rag.chunking import chunk_text_with_offsets

        texto = " ".join(f"palabra{i}" for i in range(900))
        offsets = [off for _, off in chunk_text_with_offsets(texto)]
        assert offsets == sorted(offsets)
        assert len(set(offsets)) == len(offsets)

    def test_la_pagina_es_la_ultima_que_empieza_antes(self) -> None:
        from services.rag.chunking import pagina_de_offset

        inicios = [(0, 1), (1000, 2), (2500, 3)]
        assert pagina_de_offset(0, inicios) == 1
        assert pagina_de_offset(999, inicios) == 1
        assert pagina_de_offset(1000, inicios) == 2
        assert pagina_de_offset(9999, inicios) == 3

    def test_sin_paginas_no_se_inventa_una(self) -> None:
        from services.rag.chunking import pagina_de_offset

        assert pagina_de_offset(50, []) is None
        assert pagina_de_offset(10, [(100, 1)]) is None, "no cae a la primera «por si acaso»"


class TestVersionDeEmbeddings:
    """C5.7 — `EMBEDDING_VERSION` deja de ser una variable que nadie lee."""

    def test_el_job_escribe_modelo_y_version(self) -> None:
        import scheduler.jobs.documentos_embeddings as mod

        fuente = inspect.getsource(mod._embeber_documentos)
        assert "embedding_model=settings.EMBEDDING_MODEL" in fuente
        assert "embedding_version=settings.EMBEDDING_VERSION" in fuente

    def test_el_retrieval_pide_la_version_vigente(self) -> None:
        import services.rag.context as mod

        fuente = inspect.getsource(mod._select_chunks_pgvector)
        assert "embedding_version=settings.EMBEDDING_VERSION" in fuente

    def test_la_busqueda_cae_a_la_version_anterior(self) -> None:
        """Filtrar sin caída deja sin retrieval a todo el corpus durante la migración."""
        from db.repositories.documentos import DocumentosRepository

        fuente = inspect.getsource(DocumentosRepository.search_chunks_by_embedding)
        assert "if filas:" in fuente
        assert "return filas" in fuente

    def test_nunca_se_mezclan_dos_versiones_en_la_misma_consulta(self) -> None:
        """Dos modelos no comparten geometría: el orden no significaría nada."""
        from db.repositories.documentos import DocumentosRepository

        fuente = inspect.getsource(DocumentosRepository.search_chunks_by_embedding)
        assert "OR dc.embedding_version" not in fuente
        assert "IN (" not in fuente

    def test_el_reembedding_va_detras_de_los_documentos_sin_indice(self) -> None:
        import scheduler.jobs.documentos_embeddings as mod

        fuente = inspect.getsource(mod._run_embed_phase)
        pos_nuevos = fuente.index("_embeber_documentos(repo, candidatos")
        pos_obsoletos = fuente.index("_embeber_documentos(repo, obsoletos")
        assert pos_nuevos < pos_obsoletos

    def test_el_historico_no_se_rellena_con_la_version_de_hoy(self) -> None:
        """Rellenarlo afirmaría de qué modelo salió, que es lo que no consta."""
        from pathlib import Path

        migracion = (
            Path(__file__).resolve().parent.parent
            / "db"
            / "alembic"
            / "versions"
            / "v119_documento_chunks_version_pagina.py"
        ).read_text(encoding="utf-8")
        assert "UPDATE documento_chunks" not in migracion

    def test_la_variable_ya_no_es_letra_muerta(self) -> None:
        """El hecho 6 del plan, convertido en gate."""
        from pathlib import Path

        raiz = Path(__file__).resolve().parent.parent
        usos = [
            ruta
            for ruta in (*raiz.glob("services/**/*.py"), *raiz.glob("scheduler/**/*.py"))
            if "EMBEDDING_VERSION" in ruta.read_text(encoding="utf-8")
        ]
        assert usos, "config/settings.py no puede declarar variables que nadie lee"


class TestCacheDeRespuestas:
    """C5.5 — la misma pregunta sobre el mismo pliego no se paga dos veces."""

    def test_la_version_del_prompt_sale_del_prompt(self) -> None:
        """Un número a mano funciona hasta el día que alguien olvida subirlo."""
        from llm.prompts import prompt_version

        antes = prompt_version("licitacion")
        assert len(antes) == 8
        assert prompt_version("resumen") != antes

    def test_cambiar_el_prompt_cambia_la_clave(self, monkeypatch) -> None:
        import llm.prompts as prompts
        from shared.cache import llm_cache_key

        def clave() -> str:
            return llm_cache_key(
                modo="licitacion",
                modelo="m",
                prompt_version=prompts.prompt_version("licitacion"),
                contexto="ctx",
            )

        original = clave()
        monkeypatch.setattr(prompts, "_SYSTEM_LICITACION", prompts._SYSTEM_LICITACION + " extra.")
        assert clave() != original

    def test_la_clave_distingue_modo_modelo_y_contexto(self) -> None:
        from shared.cache import llm_cache_key

        base = {
            "modo": "licitacion",
            "modelo": "m1",
            "prompt_version": "abc12345",
            "contexto": "ctx",
        }
        claves = {
            llm_cache_key(**base),
            llm_cache_key(**{**base, "modo": "general"}),
            llm_cache_key(**{**base, "modelo": "m2"}),
            llm_cache_key(**{**base, "contexto": "otro"}),
        }
        assert len(claves) == 4

    def test_la_huella_del_contexto_incluye_el_historial(self) -> None:
        """La misma última pregunta en dos conversaciones es otra pregunta."""
        from api.routes.ask import _huella_contexto

        docs = [{"id_externo": "EXP-1", "chunks": [{"documento_id": 1, "chunk_index": 0}]}]
        a = _huella_contexto("¿y el plazo?", [], docs)
        b = _huella_contexto(
            "¿y el plazo?", [{"role": "user", "content": "resume los criterios"}], docs
        )
        assert a != b

    def test_la_huella_cambia_si_cambian_los_fragmentos(self) -> None:
        from api.routes.ask import _huella_contexto

        uno = [{"id_externo": "EXP-1", "chunks": [{"documento_id": 1, "chunk_index": 0}]}]
        dos = [{"id_externo": "EXP-1", "chunks": [{"documento_id": 1, "chunk_index": 4}]}]
        assert _huella_contexto("q", [], uno) != _huella_contexto("q", [], dos)

    def test_force_salta_la_cache(self) -> None:
        import api.routes.ask as mod

        assert "force" in mod.AskRequest.model_fields
        assert "not request.force" in inspect.getsource(mod._stream_ask)

    def test_no_se_cachea_una_respuesta_degradada(self) -> None:
        """Cachearla la convertiría en la respuesta oficial durante 24 h."""
        import api.routes.ask as mod

        fuente = inspect.getsource(mod._stream_ask)
        assert 'texto = "".join(partes).strip()' in fuente
        assert "if texto:" in fuente

    def test_el_ttl_es_de_un_dia(self) -> None:
        from shared.cache import LLM_CACHE_TTL_SECONDS

        assert LLM_CACHE_TTL_SECONDS == 24 * 3600

    def test_la_metrica_cuenta_hit_y_miss(self) -> None:
        """Un hit sin su miss no permite calcular la ratio, que es la métrica."""
        from observability.runtime_metrics import llm_cache_hit_total

        assert llm_cache_hit_total is not None
        fuente = inspect.getsource(__import__("api.routes.ask", fromlist=["x"]))
        assert 'resultado=("hit" if cacheado is not None else "miss")' in fuente


class TestFeedbackDelAsistente:
    """C5.4 — el voto deja de morir como evento de telemetría."""

    def test_el_hash_lleva_sal_del_servidor(self) -> None:
        """Sin sal, «¿cuál es el plazo?» se revierte con un diccionario."""
        import db.repositories.asistente_feedback as mod

        fuente = inspect.getsource(mod.hash_pregunta)
        assert "hmac.new" in fuente
        assert "SIGNING_KEY" in fuente

    def test_el_hash_normaliza_espacios_y_mayusculas(self) -> None:
        from db.repositories.asistente_feedback import hash_pregunta

        assert hash_pregunta("¿Cuál es el   PLAZO?") == hash_pregunta("¿cuál es el plazo?")

    def test_el_motivo_es_una_lista_cerrada(self) -> None:
        """Un campo libre sería la vía por la que la pregunta acaba en la tabla."""
        from db.repositories.asistente_feedback import MOTIVOS

        assert "otro" in MOTIVOS
        assert len(MOTIVOS) <= 8

    def test_el_texto_solo_con_opt_in(self) -> None:
        import db.repositories.asistente_feedback as mod

        fuente = inspect.getsource(mod.registrar)
        assert "if texto_opt_in else None" in fuente

    @pytest.mark.parametrize(
        "ruta",
        [
            "/api/v1/feedback/asistente",
            "/api/v1/feedback/asistente/resumen",
            "/api/v1/feedback/asistente/peores",
        ],
    )
    def test_las_rutas_existen(self, ruta: str) -> None:
        from api.app import app

        assert ruta in {r.path for r in app.routes if hasattr(r, "path")}

    def test_el_panel_exige_admin(self) -> None:
        """Las preguntas agrupadas son datos de operación, no de producto."""
        import api.routes.feedback as mod

        for fn in (mod.asistente_feedback_resumen, mod.asistente_feedback_peores):
            assert "require_admin" in inspect.getsource(fn)

    def test_el_voto_no_devuelve_error_si_la_tabla_falla(self) -> None:
        """Quien vota nos hace un favor; un 500 convierte su cortesía en un error."""
        import api.routes.feedback as mod

        fuente = inspect.getsource(mod.submit_asistente_feedback)
        assert "registrado=fila_id is not None" in fuente

    def test_el_borrado_rgpd_borra_la_fila_entera(self) -> None:
        import db.repositories.asistente_feedback as mod

        fuente = inspect.getsource(mod.borrar_de_usuario)
        assert "DELETE FROM asistente_feedback" in fuente

"""Stream C5 del plan complementario 2026-09: caché del LLM y trazabilidad.

Sin BD y sin proveedor: se sustituye ``stream_llm_response`` por un doble que
cuenta llamadas, que es exactamente la magnitud que la aceptación mide («la
segunda pregunta idéntica no consume presupuesto»).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# C5.5 — Caché de respuestas del LLM
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _cache_limpia() -> Any:
    """Cada test arranca con la caché vacía: si no, el orden decide el resultado."""
    from llm.cache import NAMESPACE
    from shared.cache import reset_cache

    reset_cache(NAMESPACE)
    yield
    reset_cache(NAMESPACE)


def _docs() -> list[dict[str, Any]]:
    return [{"id_externo": "placsp:1", "titulo": "Servicio SAP", "chunks": []}]


class TestClaveDeCache:
    def test_la_misma_pregunta_da_la_misma_clave(self) -> None:
        from llm.cache import clave

        a = clave(modo="licitacion", modelo="m", pregunta="¿Cuál es el plazo?", docs=_docs())
        b = clave(modo="licitacion", modelo="m", pregunta="  ¿Cuál es el plazo?  ", docs=_docs())

        assert a == b, "el espaciado no cambia la pregunta"

    @pytest.mark.parametrize(
        "cambio",
        [
            {"modo": "general"},
            {"modelo": "otro"},
            {"pregunta": "¿Y el importe?"},
        ],
    )
    def test_lo_que_cambia_la_respuesta_cambia_la_clave(self, cambio: dict[str, Any]) -> None:
        from llm.cache import clave

        base = {
            "modo": "licitacion",
            "modelo": "m",
            "pregunta": "¿Cuál es el plazo?",
            "docs": _docs(),
        }
        assert clave(**base) != clave(**{**base, **cambio})

    def test_el_estado_de_los_documentos_entra_en_la_clave(self) -> None:
        """Un pliego que pasa a extraído cambia el contexto, luego la respuesta."""
        from llm.cache import clave

        antes = clave(modo="licitacion", modelo="m", pregunta="p", docs=_docs())
        docs = _docs()
        docs[0]["chunks"] = [{"documento_id": 7, "texto": "..."}]
        despues = clave(modo="licitacion", modelo="m", pregunta="p", docs=docs)

        assert antes != despues

    def test_editar_un_prompt_invalida_lo_cacheado(self) -> None:
        """Sin esto la caché serviría respuestas de un prompt que ya no existe.

        La versión es un hash del contenido, no un contador: no hay nada que
        acordarse de subir en el PR que edita el prompt.
        """
        from llm.cache import clave

        antes = clave(modo="general", modelo="m", pregunta="p", docs=_docs())
        with patch("llm.prompts.PROMPT_VERSION", "otra-version"):
            despues = clave(modo="general", modelo="m", pregunta="p", docs=_docs())

        assert antes != despues

    def test_el_usuario_no_entra_en_la_clave(self) -> None:
        """Decisión explícita: el contexto es público, así que se comparte.

        Es de donde sale el ahorro. Si algún día entrara dato privado en el
        contexto, hay que rehacerla — y este test es el que debería fallar.
        """
        import inspect

        import llm.cache as mod

        firma = inspect.signature(mod.clave).parameters
        assert not ({"user", "user_id", "user_key", "usuario"} & set(firma))


class TestLecturaYEscritura:
    def test_un_texto_vacio_no_deja_entrada(self) -> None:
        """Cachear un degradado lo volvería permanente durante 24 h."""
        from llm.cache import guardar, leer

        guardar("k", "   ")

        assert leer("k", modo="general") is None

    def test_lo_guardado_se_recupera(self) -> None:
        from llm.cache import guardar, leer

        guardar("k", "respuesta")

        assert leer("k", modo="general") == "respuesta"

    def test_un_backend_roto_no_tumba_la_pregunta(self) -> None:
        """La caché es una optimización: su fallo no puede ser el del endpoint."""
        from llm.cache import guardar, leer

        with patch("shared.cache.get_cache", side_effect=RuntimeError("redis caído")):
            assert leer("k", modo="general") is None
            guardar("k", "texto")  # no lanza


class TestAskUsaLaCache:
    """Aceptación de C5.5: la segunda pregunta idéntica no llama al proveedor.

    Se ejercita ``_stream_ask`` y no el endpoint entero: lo que se mide es
    cuántas veces se llama al proveedor, y eso no necesita ni BD ni sesión. La
    autenticación de ``/ask`` ya la cubre ``tests/test_ask_route.py``.
    """

    @staticmethod
    def _peticion(**extra: Any) -> Any:
        from api.routes.ask import AskRequest

        campos: dict[str, Any] = {
            "question": "¿Cuál es el plazo de presentación?",
            "model": "deepseek-ai/deepseek-v4-flash-0731",
        }
        campos.update(extra)
        return AskRequest(**campos)

    @staticmethod
    async def _texto(peticion: Any) -> str:
        from api.routes.ask import _stream_ask

        generador = await _stream_ask(peticion, None, None)
        return "".join([evento async for evento in generador])

    def _correr(self, peticiones: list[Any]) -> tuple[list[str], list[dict[str, Any]]]:
        import asyncio

        llamadas: list[dict[str, Any]] = []

        def _fake_stream(**kwargs: Any) -> Any:
            llamadas.append(kwargs)
            return iter(["El plazo ", "vence el 30."])

        async def _run_db(func: Any, *args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        with (
            patch("llm.client.stream_llm_response", _fake_stream),
            patch("api.routes.ask.run_db", _run_db),
            patch("api.routes.ask._prepare_ask_context", return_value=(_docs(), "general")),
        ):
            salidas = [asyncio.run(self._texto(p)) for p in peticiones]
        return salidas, llamadas

    def test_la_segunda_pregunta_identica_no_consume_presupuesto(self) -> None:
        salidas, llamadas = self._correr([self._peticion(), self._peticion()])

        assert len(llamadas) == 1, "la segunda respuesta tenía que salir de caché"
        assert "El plazo " in salidas[1] and "vence el 30." in salidas[1]

    def test_force_salta_la_cache(self) -> None:
        _, llamadas = self._correr([self._peticion(), self._peticion(force=True)])

        assert len(llamadas) == 2

    def test_una_pregunta_distinta_si_llama_al_proveedor(self) -> None:
        _, llamadas = self._correr(
            [self._peticion(), self._peticion(question="¿Y el importe base?")]
        )

        assert len(llamadas) == 2

    def test_ask_meta_dice_si_la_respuesta_venia_de_cache(self) -> None:
        """Sin esta marca, «¿por qué respondió al instante?» no tiene respuesta."""
        salidas, _ = self._correr([self._peticion(), self._peticion()])

        assert '"cached": false' in salidas[0]
        assert '"cached": true' in salidas[1]


def test_las_metricas_de_cache_estan_declaradas() -> None:
    """`llm_cache_hit_total` en /metrics es parte de la aceptación de C5.5."""
    from observability import runtime_metrics

    assert hasattr(runtime_metrics, "llm_cache_hit_total")
    assert hasattr(runtime_metrics, "llm_cache_miss_total")


# ---------------------------------------------------------------------------
# C5.4 — Feedback del asistente persistido
# ---------------------------------------------------------------------------


class TestFeedbackDelAsistente:
    def test_la_huella_agrega_variantes_de_la_misma_pregunta(self) -> None:
        """«esta pregunta falla siempre» es la señal; repartida en veinte huellas,
        no se ve ninguna."""
        from db.repositories.asistente_feedback import hash_pregunta

        assert hash_pregunta("¿Cuál es el plazo?") == hash_pregunta(
            "  cual  es el plazo?  ".replace("cual", "¿Cuál")
        )
        assert hash_pregunta("¿Cuál es el plazo?") != hash_pregunta("¿Cuál es el importe?")

    def test_la_huella_no_es_reversible(self) -> None:
        from db.repositories.asistente_feedback import hash_pregunta

        huella = hash_pregunta("El proyecto de ACME por 2 millones")
        assert "ACME" not in huella
        assert len(huella) == 64 and all(c in "0123456789abcdef" for c in huella)

    def test_el_motivo_es_vocabulario_cerrado(self) -> None:
        """Un campo de texto libre en un formulario de queja acaba con el nombre
        del cliente dentro. La fila no puede llevar PII, y eso no se consigue
        pidiéndolo en la interfaz."""
        from db.repositories.asistente_feedback import MOTIVOS

        assert set(MOTIVOS) == {"incorrecta", "incompleta", "sin_fuentes", "lenta", "otro"}

    def test_la_fila_no_tiene_columna_de_usuario(self) -> None:
        """Con ella, el conjunto pasa a ser un registro de qué preguntó cada cual."""
        import importlib.util
        from pathlib import Path

        ruta = (
            Path(__file__).resolve().parents[1]
            / "db"
            / "alembic"
            / "versions"
            / "v120_asistente_feedback.py"
        )
        fuente = ruta.read_text(encoding="utf-8")
        cuerpo = fuente[fuente.index("def upgrade()") :]
        for prohibida in ("user_id", "user_key", "email", "ip", "session"):
            assert f'"{prohibida}"' not in cuerpo, f"v120 declara una columna {prohibida}"

        spec = importlib.util.spec_from_file_location("v120", ruta)
        assert spec is not None and spec.loader is not None
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        assert modulo.VOTOS == ("up", "down")

    def test_el_texto_de_la_pregunta_solo_viaja_con_opt_in(self) -> None:
        """Sin marcar, se guarda la huella y nada más."""
        import inspect

        from db.repositories.asistente_feedback import AsistenteFeedbackRepository

        fuente = inspect.getsource(AsistenteFeedbackRepository.registrar)
        assert "pregunta.strip() if compartir_pregunta else None" in fuente
        firma = inspect.signature(AsistenteFeedbackRepository.registrar)
        assert firma.parameters["compartir_pregunta"].default is False

    def test_un_voto_invalido_no_escribe(self) -> None:
        from unittest.mock import patch as _patch

        from db.repositories.asistente_feedback import AsistenteFeedbackRepository

        with _patch("db.repositories.asistente_feedback.connect") as conectar:
            assert (
                AsistenteFeedbackRepository().registrar(
                    pregunta="p", modo="general", modelo="m", voto="quizas"
                )
                is None
            )
            assert not conectar.called, "ni siquiera abre conexión"

    def test_las_rutas_del_panel_existen(self) -> None:
        from api.app import app

        rutas = {r.path for r in app.routes if hasattr(r, "path")}
        assert "/api/v1/feedback/asistente" in rutas
        assert "/api/v1/feedback/asistente/stats" in rutas

    def test_sin_votos_el_porcentaje_es_none_y_no_cero(self) -> None:
        """Un 0 % de satisfacción sin un solo voto asusta y no significa nada."""
        from api.routes.feedback import AsistenteFeedbackResumen

        assert AsistenteFeedbackResumen().pct_positivos is None


# ---------------------------------------------------------------------------
# C5.7 — Versión de embeddings y re-embedding
# ---------------------------------------------------------------------------


class TestVersionDeEmbeddings:
    def test_la_firma_incluye_el_modelo_y_no_solo_la_version(self) -> None:
        """El modelo es lo que define el espacio vectorial.

        Dos vectores de modelos distintos tienen distancias que no son
        comparables, y `<=>` las ordena igual sin quejarse.
        """
        from services.embeddings import embedding_signature

        modelo, version = embedding_signature()
        assert modelo and version
        assert "MiniLM" in modelo or "mpnet" in modelo

    def test_los_chunks_se_escriben_etiquetados(self) -> None:
        import inspect

        from db.repositories.documentos import DocumentosRepository

        fuente = inspect.getsource(DocumentosRepository.replace_chunks)
        assert "embedding_signature()" in fuente
        assert "embedding_model" in fuente and "embedding_version" in fuente

    def test_el_retrieval_prefiere_la_version_vigente_y_cae_a_la_anterior(self) -> None:
        """Cambiar de modelo no puede dejar la ficha sin responder.

        Un retrieval con vectores viejos es peor que uno actual y mejor que
        ninguno; el job de re-embebido lo corrige por detrás.
        """
        import inspect

        from db.repositories.documentos import DocumentosRepository

        fuente = inspect.getsource(DocumentosRepository.search_chunks_by_embedding)
        assert "dc.embedding_model = %s AND dc.embedding_version = %s" in fuente
        assert "if filas:" in fuente and "return filas" in fuente
        assert "documento_chunks_fallback_version_embedding" in fuente

    def test_las_filas_sin_etiqueta_cuentan_como_pendientes(self) -> None:
        """«No consta con qué modelo» no es lo mismo que «está al día»."""
        import inspect

        from db.repositories.documentos import DocumentosRepository

        fuente = inspect.getsource(DocumentosRepository.pendientes_por_version_embedding)
        assert "sin_etiqueta" in fuente
        assert '"pendientes": total - al_dia' in fuente

    def test_la_variable_de_entorno_dejo_de_ser_decorativa(self) -> None:
        """`EMBEDDING_VERSION` llevaba desde el alta del RAG sin un solo lector."""
        import inspect

        import services.embeddings as mod

        assert "EMBEDDING_VERSION" in inspect.getsource(mod.embedding_signature)


# ---------------------------------------------------------------------------
# C5.3 — Citas estructuradas en /ask (D29)
# ---------------------------------------------------------------------------


class TestCitasEstructuradas:
    def test_solo_se_cita_lo_que_se_puede_abrir(self) -> None:
        """Una cita sin `documento_id` es una nota al pie decorativa."""
        from api.routes.ask import _citas

        citas = _citas(
            [
                {
                    "id_externo": "placsp:1",
                    "chunks": [
                        {"documento_id": 7, "page_number": 12, "texto": "El plazo es de 30 días"},
                        {"texto": "fragmento sin documento"},
                    ],
                }
            ]
        )

        assert len(citas) == 1
        assert citas[0]["documento_id"] == 7
        assert citas[0]["page_number"] == 12
        assert citas[0]["cita"].startswith("El plazo")

    def test_la_cita_se_recorta(self) -> None:
        """El evento es una referencia, no una copia del pliego."""
        from api.routes.ask import _CITA_CHARS, _citas

        citas = _citas([{"chunks": [{"documento_id": 1, "texto": "x" * 5000}]}])

        assert len(citas[0]["cita"]) == _CITA_CHARS

    def test_un_fragmento_sin_pagina_no_se_inventa_una(self) -> None:
        from api.routes.ask import _citas

        citas = _citas([{"chunks": [{"documento_id": 3, "texto": "algo"}]}])

        assert citas[0]["page_number"] is None

    def test_la_cabecera_del_fragmento_dice_pagina_y_no_dos_numeros(self) -> None:
        """Antes se pegaban `documento_id` y `page_number` en un solo campo.

        Como la página nunca se rellenaba, el prompt acababa diciendo
        «documento/página 41» con 41 = id del documento: el modelo citaba una
        página que no existía.
        """
        from llm.prompts import _doc_block

        bloque = _doc_block(
            {
                "id_externo": "x",
                "titulo": "t",
                "chunks": [
                    {"tipo": "legal", "filename": "pcap.pdf", "documento_id": 41, "texto": "c"}
                ],
            },
            [],
        )

        assert "pág." not in bloque, "sin página conocida no se escribe ninguna"
        assert "41" not in bloque

    def test_el_prompt_de_licitacion_exige_referencia_por_afirmacion(self) -> None:
        from llm.prompts import build_system_prompt

        prompt = build_system_prompt("licitacion", has_corpus_context=True)

        assert "CADA afirmación" in prompt
        assert "No inventes números de página" in prompt

    def test_la_pagina_se_resuelve_en_una_sola_consulta(self) -> None:
        """Doce viajes a BD dentro de una petición de chat se notan."""
        import inspect

        from db.repositories.documentos import DocumentosRepository

        fuente = inspect.getsource(DocumentosRepository.paginas_de_fragmentos)
        assert fuente.count("c.execute(") == 1
        assert "WITH frag(idx, documento_id, fragmento) AS (VALUES" in fuente
        # Un fragmento a caballo entre dos páginas se cita donde empieza.
        assert "MIN(dp.page_number)" in fuente

    def test_no_poder_numerar_una_cita_no_rompe_la_respuesta(self) -> None:
        import inspect

        import services.rag.context as mod

        fuente = inspect.getsource(mod._anotar_paginas)
        assert "except Exception:" in fuente and "return" in fuente

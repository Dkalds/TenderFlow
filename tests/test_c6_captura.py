"""Colaboración y captura: la oportunidad como espacio de trabajo (C6).

El stream cubre lo que el plan pedía y que el producto no tenía:

- una oportunidad con **una** `next_action` y **una** fecha, cuando preparar una
  oferta son cinco o diez acciones con responsables distintos (C6.1);
- `decision` sin el porqué, así que dos meses después nadie puede responder «¿en
  qué nos equivocamos al decidir?» (C6.4);
- `bajas/referencia` respondiendo por el mercado y nadie por la baja propia
  (C6.5);
- favoritos sin motivo y comentarios sin destinatario (C6.6, C6.2);
- un tablero que no se podía sacar del producto (C6.7).
"""

from __future__ import annotations

import inspect
from typing import Any, ClassVar

import pytest


class TestPlantillaGoNoGo:
    """C6.4 / D30 — cinco criterios fijos, pesos por organización."""

    def test_los_cinco_criterios_de_la_decision(self) -> None:
        from services.go_no_go_template import CRITERIOS

        assert CRITERIOS == ("encaje", "capacidad", "competencia", "rentabilidad", "riesgo")

    def test_el_riesgo_puntua_invertido(self) -> None:
        """5 = poco riesgo, para que la suma tenga una sola dirección."""
        from services.go_no_go_template import CRITERIO_INVERTIDO, ETIQUETAS

        assert CRITERIO_INVERTIDO == "riesgo"
        assert "riesgo bajo" in ETIQUETAS["riesgo"]

    def test_solo_se_promedian_los_criterios_puntuados(self) -> None:
        """Contar los ausentes como cero haría que media ficha dijera «no go»."""
        from services.go_no_go_template import calcular

        resultado = calcular({"encaje": 5, "capacidad": 5})
        assert resultado.total == 5.0
        assert resultado.criterios_puntuados == 2
        assert resultado.completa is False
        assert resultado.recomendacion == "go"

    def test_una_ficha_vacia_no_recomienda_nada(self) -> None:
        from services.go_no_go_template import calcular

        resultado = calcular({})
        assert resultado.recomendacion == "sin_datos"
        assert resultado.completa is False

    def test_los_pesos_mueven_el_resultado(self) -> None:
        from services.go_no_go_template import calcular

        puntuaciones = {"encaje": 5, "rentabilidad": 1}
        neutral = calcular(puntuaciones)
        sesgado = calcular(puntuaciones, {"encaje": 9, "rentabilidad": 1})
        assert neutral.total == 3.0
        assert sesgado.total > neutral.total

    def test_un_criterio_sin_peso_usa_el_default_y_no_cero(self) -> None:
        """«No configurado» y «no cuenta» son cosas distintas."""
        from services.go_no_go_template import PESO_DEFECTO, normalizar_pesos

        pesos = normalizar_pesos({"encaje": 4})
        assert pesos["encaje"] == 4
        assert pesos["riesgo"] == PESO_DEFECTO

    def test_todos_los_pesos_a_cero_no_deja_el_total_indefinido(self) -> None:
        from services.go_no_go_template import calcular

        resultado = calcular({"encaje": 4}, dict.fromkeys(["encaje", "riesgo"], 0.0))
        assert resultado.total == 4.0

    def test_la_puntuacion_fuera_de_rango_se_descarta(self) -> None:
        from services.go_no_go_template import calcular

        assert calcular({"encaje": 9, "capacidad": 3}).criterios_puntuados == 1

    def test_la_discrepancia_se_señala_pero_no_bloquea(self) -> None:
        """Una plantilla que bloquea se rellena para pasarla."""
        from services.go_no_go_template import calcular, discrepa

        flojo = calcular(dict.fromkeys(("encaje", "capacidad"), 1))
        assert flojo.recomendacion == "no_go"
        assert discrepa("go", flojo) is True
        assert discrepa("no_go", flojo) is False

    def test_sin_decision_no_hay_discrepancia(self) -> None:
        from services.go_no_go_template import calcular, discrepa

        assert discrepa(None, calcular({"encaje": 5})) is False

    def test_puntuar_no_es_decidir(self) -> None:
        """Reservarlo a owner/admin lo convertiría en un trámite de aprobación."""
        import services.go_no_go_puntuacion as mod

        assert "_ROLES_PESOS" in inspect.getsource(mod.set_weights)
        assert "_ROLES_PESOS" not in inspect.getsource(mod.set_score)


class TestMenciones:
    """C6.2 — el comentario guarda ids, no el nombre resuelto."""

    MIEMBROS: ClassVar[list[dict[str, Any]]] = [
        {"id": 1, "display_name": "Ana Ruiz"},
        {"id": 2, "display_name": "Marta Sanz"},
        {"id": 3, "display_name": "Ana Prieto"},
    ]

    def test_una_mencion_simple_resuelve(self) -> None:
        from services.pursuit_menciones import resolver

        assert resolver("aviso a @{Marta Sanz}", self.MIEMBROS).user_ids == [2]

    def test_un_nombre_ambiguo_no_resuelve_a_nadie(self) -> None:
        """Elegir la primera notificaría a la persona equivocada."""
        from services.pursuit_menciones import resolver

        r = resolver("@Ana ¿lo miras?", self.MIEMBROS)
        assert r.user_ids == []
        assert r.ambiguos == ["Ana"]

    def test_las_tildes_y_las_mayusculas_no_importan(self) -> None:
        from services.pursuit_menciones import resolver

        assert resolver("@{MARTA SÁNZ}", self.MIEMBROS).user_ids == [2]

    def test_los_espacios_internos_si_importan(self) -> None:
        """«AnaRuiz» no es «Ana Ruiz»: resolverlo sería adivinar."""
        from services.pursuit_menciones import resolver

        r = resolver("@AnaRuiz", self.MIEMBROS)
        assert r.user_ids == []
        assert r.sin_resolver == ["AnaRuiz"]

    def test_alguien_de_fuera_no_se_puede_mencionar(self) -> None:
        """El filtro es la entrada, no una comprobación posterior."""
        from services.pursuit_menciones import resolver

        assert resolver("@{Luis Gomez}", self.MIEMBROS).user_ids == []

    def test_la_misma_persona_no_se_repite(self) -> None:
        from services.pursuit_menciones import resolver

        assert resolver("@{Ana Ruiz} y otra vez @{Ana Ruiz}", self.MIEMBROS).user_ids == [1]

    def test_solo_se_resuelve_al_crear(self) -> None:
        """Un reintento idempotente no re-resuelve: el nombre pudo cambiar."""
        import services.pursuit_comments as mod

        fuente = inspect.getsource(mod.add_comment)
        assert "if created:" in fuente

    def test_solo_miembros_activos(self) -> None:
        import services.pursuit_comments as mod

        assert '"active"' in inspect.getsource(mod._resolver_menciones)

    def test_un_fallo_de_mencion_no_tumba_el_comentario(self) -> None:
        import db.repositories.pursuit_comments as mod

        fuente = inspect.getsource(mod.PursuitCommentRepository.guardar_menciones)
        assert "except Exception:" in fuente
        assert "return 0" in fuente


class TestMiBaja:
    """C6.5 — la otra mitad de `bajas/referencia`."""

    def test_la_baja_propia_es_sobre_el_presupuesto(self) -> None:
        from services.pursuit_bajas import baja_propia_pct

        assert baja_propia_pct(100_000, 80_000) == 20.0

    def test_una_baja_negativa_no_se_esconde(self) -> None:
        """Ofertar por encima del presupuesto es raro pero real."""
        from services.pursuit_bajas import baja_propia_pct

        assert baja_propia_pct(100_000, 110_000) == -10.0

    def test_sin_presupuesto_no_hay_baja(self) -> None:
        from services.pursuit_bajas import baja_propia_pct

        assert baja_propia_pct(0, 10) is None
        assert baja_propia_pct(None, 10) is None
        assert baja_propia_pct(100, None) is None

    def test_se_agrupa_por_cpv4_y_por_organo(self) -> None:
        from services.pursuit_bajas import agrupar

        ofertas = [
            {
                "cpv": "72220000",
                "organo_contratacion": "Ayuntamiento de X",
                "presupuesto": 100.0,
                "offer_price_eur": 80.0,
            }
        ]
        segmentos = {(s.segmento, s.clave) for s in agrupar(ofertas, {})}
        assert ("cpv4", "7222") in segmentos
        assert ("organo", "Ayuntamiento de X") in segmentos

    def test_por_debajo_de_cinco_ofertas_lo_declara(self) -> None:
        """Se devuelve igual, con su `n`: no saberlo es lo que engaña."""
        from services.pursuit_bajas import MIN_OFERTAS_POR_SEGMENTO, agrupar

        ofertas = [
            {
                "cpv": "72220000",
                "organo_contratacion": "",
                "presupuesto": 100.0,
                "offer_price_eur": 80.0,
            }
        ] * 2
        segmento = agrupar(ofertas, {})[0]
        assert segmento.n == 2
        assert segmento.suficiente is False
        assert MIN_OFERTAS_POR_SEGMENTO == 5

    def test_sin_referencia_no_hay_delta(self) -> None:
        """Restar contra un hueco daría un número que parece comparación."""
        from services.pursuit_bajas import agrupar

        ofertas = [
            {
                "cpv": "72220000",
                "organo_contratacion": "",
                "presupuesto": 100.0,
                "offer_price_eur": 80.0,
            }
        ]
        assert agrupar(ofertas, {})[0].delta_pct is None

    def test_el_delta_compara_contra_el_mercado(self) -> None:
        from services.pursuit_bajas import agrupar

        ofertas = [
            {
                "cpv": "72220000",
                "organo_contratacion": "",
                "presupuesto": 100.0,
                "offer_price_eur": 80.0,
            }
        ]
        referencias = {("cpv4", "7222"): {"baja_media_pct": 15.0, "contratos": 40}}
        segmento = agrupar(ofertas, referencias)[0]
        assert segmento.baja_mercado_pct == 15.0
        assert segmento.delta_pct == 5.0

    def test_solo_importes_de_base_declarada(self) -> None:
        """Mezclar bases devolvería una baja del 21 % que es el IVA (C1.1)."""
        from db.repositories.pursuits import PursuitRepository

        fuente = inspect.getsource(PursuitRepository.ofertas_presentadas)
        assert "importe_base_sin_iva" in fuente
        assert "l.importe_tipo = 'sin_iva'" in fuente


class TestTareas:
    """C6.1 — `next_action` pasa a derivarse, no a desaparecer."""

    def test_next_action_no_se_retira(self) -> None:
        import services.pursuit_tasks as mod

        assert "set_next_action_derivada" in inspect.getsource(mod._sincronizar_next_action)

    def test_la_derivada_no_toca_la_version_ni_el_ledger(self) -> None:
        """Si lo hiciera, cerrar una tarea daría conflicto de concurrencia.

        Se mira el **cuerpo** y no el docstring: el docstring explica justo esas
        tres cosas, así que buscarlas en la fuente entera siempre acertaría.
        """
        from db.repositories.pursuits import PursuitRepository

        fuente = inspect.getsource(PursuitRepository.set_next_action_derivada)
        cuerpo = fuente.split('"""')[-1]
        for prohibido in ("version", "pursuit_events", "updated_by_user_id"):
            assert prohibido not in cuerpo, f"la derivada no puede tocar {prohibido}"

    def test_la_agenda_ordena_los_sin_fecha_al_final(self) -> None:
        from db.repositories.pursuit_tasks import PursuitTasksRepository

        assert "t.vence IS NULL, t.vence" in inspect.getsource(PursuitTasksRepository.agenda)

    def test_vaciar_un_campo_necesita_su_propia_bandera(self) -> None:
        """`None` ya significa «no tocar»."""
        from db.repositories.pursuit_tasks import PursuitTasksRepository

        firma = inspect.signature(PursuitTasksRepository.update).parameters
        assert "limpiar_responsable" in firma
        assert "limpiar_vence" in firma

    def test_el_responsable_debe_ser_miembro_activo(self) -> None:
        import services.pursuit_tasks as mod

        assert "require_active_member" in inspect.getsource(mod.create_task)

    def test_la_pertenencia_se_comprueba_en_el_insert(self) -> None:
        """Un SELECT previo dejaría ventana entre comprobar y escribir."""
        from db.repositories.pursuit_tasks import PursuitTasksRepository

        fuente = inspect.getsource(PursuitTasksRepository.create)
        assert "FROM pursuits p WHERE p.id = %s AND p.organization_id = %s" in fuente

    def test_borrar_una_cuenta_no_borra_su_tarea(self) -> None:
        from db.repositories.pursuit_tasks import PursuitTasksRepository

        fuente = inspect.getsource(PursuitTasksRepository.anonymize_user_references)
        assert "responsable_user_id = NULL" in fuente
        assert "DELETE" not in fuente

    def test_un_fallo_al_derivar_no_pierde_la_tarea(self) -> None:
        import services.pursuit_tasks as mod

        assert "except Exception:" in inspect.getsource(mod._sincronizar_next_action)


class TestNotaDelFavorito:
    """C6.6 — la nota es personal aunque el favorito sea de la organización."""

    def test_la_nota_se_filtra_por_persona_y_no_por_organizacion(self) -> None:
        from db.repositories.watchlist import WatchlistRepository

        fuente = inspect.getsource(WatchlistRepository.set_nota)
        assert "WHERE user_key = %s AND id_externo = %s" in fuente
        assert "organization_id" not in fuente.split('"""')[2]

    def test_la_nota_viaja_en_el_listado(self) -> None:
        from shared.dto import WatchlistFavoriteItem

        assert "nota" in WatchlistFavoriteItem.model_fields

    def test_la_ruta_existe(self) -> None:
        from api.app import app

        rutas = {r.path for r in app.routes if hasattr(r, "path")}
        # `:path` en el patrón: los identificadores de PLACSP llevan barras.
        assert "/api/v1/watchlist/items/{id_externo:path}/nota" in rutas


class TestExportDelPipeline:
    """C6.7 — el tablero se puede sacar del producto."""

    def test_declara_organizacion_y_fecha(self) -> None:
        from services.exports import PURSUIT_COLUMNS

        assert "organizacion_id" in PURSUIT_COLUMNS
        assert "exportado_en" in PURSUIT_COLUMNS

    def test_van_como_columnas_y_no_como_preambulo(self) -> None:
        """Una línea antes de las cabeceras rompe a pandas y a Excel."""
        from db.repositories.pursuits import PursuitRepository

        fuente = inspect.getsource(PursuitRepository.export_rows)
        assert "%s AS organizacion_id, %s AS exportado_en" in fuente

    def test_el_pdf_queda_fuera(self) -> None:
        """Su maquetación es del corpus público, con otras columnas."""
        import api.routes.exports as mod

        fuente = inspect.getsource(mod._download_pursuits)
        assert 'if format == "pdf":' in fuente
        assert "HTTP_400_BAD_REQUEST" in fuente

    def test_la_sanitizacion_de_formulas_es_la_de_siempre(self) -> None:
        """El texto lo escribe el equipo: es cuando nadie sospecha del fichero."""
        import inspect as _inspect

        from services.exports import generate_csv

        assert "sanitize_spreadsheet_record" in _inspect.getsource(generate_csv)

    @pytest.mark.parametrize(
        "peligroso", ["=1+1", "+1+1", "-1+1", "@SUM(A1)", "\t=cmd|' /C calc'!A0"]
    )
    def test_una_formula_en_el_motivo_de_la_decision_no_se_ejecuta(self, peligroso: str) -> None:
        from shared.export_safety import sanitize_spreadsheet_record

        limpio = sanitize_spreadsheet_record({"decision_reason": peligroso})
        assert not str(limpio["decision_reason"]).lstrip().startswith(("=", "+", "-", "@"))

    def test_el_recurso_es_un_parametro_del_export(self) -> None:
        import api.routes.exports as mod

        assert "recurso" in inspect.signature(mod.download_export).parameters


class TestOrdenDeRutas:
    """Las rutas estáticas bajo `/pursuits` no pueden quedar ensombrecidas.

    FastAPI resuelve por orden de declaración: `/pursuits/mi-baja` declarada
    después de `/pursuits/{pursuit_id}` entra por el detalle con
    `pursuit_id="mi-baja"` y devuelve un 422 que no dice nada. Pasó al escribir
    C6 y este test es lo que impide que vuelva a pasar.
    """

    @pytest.mark.parametrize(
        "estatica",
        [
            "/api/v1/pursuits/mi-baja",
            "/api/v1/pursuits/tasks/agenda",
            "/api/v1/pursuits/adjuntos/{attachment_id}",
            "/api/v1/pursuits/adjuntos/{attachment_id}/enlace",
            "/api/v1/pursuits/adjuntos/{attachment_id}/descargar",
            "/api/v1/pursuits/adjuntos/{attachment_id}/indexable",
        ],
    )
    def test_la_estatica_va_antes_que_la_parametrica(self, estatica: str) -> None:
        from api.app import app

        rutas = [getattr(r, "path", "") for r in app.routes]
        assert estatica in rutas, f"{estatica} no está registrada"
        assert rutas.index(estatica) < rutas.index("/api/v1/pursuits/{pursuit_id}")

    def test_las_rutas_de_tareas_y_go_no_go_existen(self) -> None:
        from api.app import app

        rutas = {r.path for r in app.routes if hasattr(r, "path")}
        for ruta in (
            "/api/v1/pursuits/{pursuit_id}/tasks",
            "/api/v1/pursuits/{pursuit_id}/tasks/{task_id}",
            "/api/v1/pursuits/{pursuit_id}/go-no-go",
            "/api/v1/organizations/go-no-go/weights",
        ):
            assert ruta in rutas, f"falta {ruta}"


class TestAdjuntosPropios:
    """C6.3 — la propuesta del equipo vive en el producto, no en el disco de alguien.

    El ítem estuvo bloqueado hasta que `master` trajo el almacén de objetos de
    v2 S8.1. Lo que se prueba aquí es lo que el plan pide como criterio: límite
    de tamaño y de tipos, un enlace caducado que devuelve 403, y que el RAG no
    indexe adjuntos propios salvo opt-in por adjunto.
    """

    # ── Límite de tipos ──────────────────────────────────────────────────

    def test_el_tipo_va_por_lista_blanca(self) -> None:
        """Una lista negra es una carrera que se pierde: basta un formato nuevo."""
        from services.pursuit_attachments import TIPOS_PERMITIDOS, AttachmentTypeRejected, validar

        assert "application/x-msdownload" not in TIPOS_PERMITIDOS
        assert "image/svg+xml" not in TIPOS_PERMITIDOS, "SVG es XML con scripts"
        assert "text/html" not in TIPOS_PERMITIDOS
        with pytest.raises(AttachmentTypeRejected):
            validar(filename="a.exe", content_type="application/x-msdownload", size_bytes=10)

    def test_el_tipo_y_la_extension_tienen_que_concordar(self) -> None:
        """Confiar solo en el `Content-Type` es confiar en quien sube el fichero."""
        from services.pursuit_attachments import AttachmentTypeRejected, validar

        with pytest.raises(AttachmentTypeRejected):
            validar(filename="propuesta.exe", content_type="application/pdf", size_bytes=10)
        nombre, tipo = validar(
            filename="propuesta.pdf", content_type="application/pdf", size_bytes=10
        )
        assert (nombre, tipo) == ("propuesta.pdf", "application/pdf")

    def test_el_content_type_con_parametros_se_normaliza(self) -> None:
        from services.pursuit_attachments import validar

        _, tipo = validar(
            filename="notas.txt", content_type="text/plain; charset=utf-8", size_bytes=5
        )
        assert tipo == "text/plain"

    # ── Límite de tamaño ─────────────────────────────────────────────────

    def test_el_tope_por_fichero_se_aplica(self) -> None:
        from services.pursuit_attachments import MAX_BYTES, AttachmentTooLarge, validar

        with pytest.raises(AttachmentTooLarge):
            validar(filename="grande.pdf", content_type="application/pdf", size_bytes=MAX_BYTES + 1)

    def test_un_fichero_vacio_no_es_un_adjunto(self) -> None:
        from services.pursuit_attachments import AttachmentError, validar

        with pytest.raises(AttachmentError):
            validar(filename="vacio.pdf", content_type="application/pdf", size_bytes=0)

    def test_el_tope_tambien_vive_en_la_base(self) -> None:
        """Una ruta nueva que olvide validar choca contra el CHECK de v127."""
        import inspect as _inspect

        from db.alembic.versions import v127_pursuit_attachments as mig

        fuente = _inspect.getsource(mig.upgrade)
        assert "ck_pursuit_attachments_size" in fuente
        assert "26214400" in fuente, "25 MiB, el mismo MAX_BYTES del servicio"

    # ── Nombre de fichero ────────────────────────────────────────────────

    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("../../etc/passwd", "passwd"),
            ("C:\\Users\\yo\\propuesta.pdf", "propuesta.pdf"),
            ("informe final.pdf", "informe final.pdf"),
            ("licitación (2).pdf", "licitación (2).pdf"),
            ('mal"nombre.pdf', "mal_nombre.pdf"),
            ("", "adjunto"),
        ],
    )
    def test_el_nombre_se_sanea(self, entrada: str, esperado: str) -> None:
        """Viaja en `Content-Disposition`: no puede llevar rutas ni comillas."""
        from services.pursuit_attachments import sanear_nombre

        assert sanear_nombre(entrada) == esperado

    # ── Clave del objeto ─────────────────────────────────────────────────

    def test_la_clave_lleva_la_organizacion_y_la_huella(self) -> None:
        """El prefijo por organización es lo que permite una supresión sin BD."""
        from services.pursuit_attachments import blob_key

        clave = blob_key(organization_id=7, pursuit_id=42, sha256="a" * 64)
        assert clave.endswith("/7/42/" + "a" * 64)

    def test_los_adjuntos_no_comparten_prefijo_con_los_pliegos(self) -> None:
        """Un pliego lo purga la retención a los 24 meses; una propuesta no."""
        from services.pursuit_attachments import attachments_prefix
        from shared.object_store import blob_prefix

        assert attachments_prefix() != blob_prefix()

    # ── Enlace firmado y caducidad ───────────────────────────────────────

    def test_un_enlace_vigente_verifica(self) -> None:
        from urllib.parse import parse_qs, urlsplit

        from services.pursuit_attachments import firmar_descarga, verificar_descarga

        enlace = firmar_descarga(99)
        query = parse_qs(urlsplit(enlace.path).query)
        assert verificar_descarga(99, exp=int(query["exp"][0]), token=query["t"][0])

    def test_un_enlace_caducado_no_verifica(self) -> None:
        """El criterio del plan: un enlace caducado devuelve 403."""
        from urllib.parse import parse_qs, urlsplit

        from services.pursuit_attachments import firmar_descarga, verificar_descarga

        enlace = firmar_descarga(99, ttl=-1)
        query = parse_qs(urlsplit(enlace.path).query)
        assert not verificar_descarga(99, exp=int(query["exp"][0]), token=query["t"][0])

    def test_estirar_la_caducidad_invalida_la_firma(self) -> None:
        """La caducidad va DENTRO de lo firmado; suelta, se editaría en la URL."""
        from urllib.parse import parse_qs, urlsplit

        from services.pursuit_attachments import firmar_descarga, verificar_descarga

        enlace = firmar_descarga(99)
        query = parse_qs(urlsplit(enlace.path).query)
        estirado = int(query["exp"][0]) + 86400
        assert not verificar_descarga(99, exp=estirado, token=query["t"][0])

    def test_la_firma_de_un_adjunto_no_vale_para_otro(self) -> None:
        from urllib.parse import parse_qs, urlsplit

        from services.pursuit_attachments import firmar_descarga, verificar_descarga

        enlace = firmar_descarga(99)
        query = parse_qs(urlsplit(enlace.path).query)
        assert not verificar_descarga(100, exp=int(query["exp"][0]), token=query["t"][0])

    def test_la_descarga_responde_403_y_no_410_al_caducar(self) -> None:
        """410 diría que el fichero ya no está, y sigue ahí: caducó el permiso."""
        import api.routes.pursuits as mod

        fuente = inspect.getsource(mod.get_adjunto_descarga)
        assert "status_code=403" in fuente
        # Contra el código, no contra el texto: el docstring nombra el 410 justo
        # para explicar por qué no se usa, y buscar la cadena suelta lo confunde
        # con una respuesta declarada.
        assert "status_code=410" not in fuente
        assert "410: {" not in fuente
        assert "403: {" in fuente

    def test_la_descarga_sigue_exigiendo_sesion(self) -> None:
        """La firma acota qué y hasta cuándo; no sustituye a autenticarse."""
        import api.routes.pursuits as mod

        firma = inspect.signature(mod.get_adjunto_descarga).parameters
        assert "ctx" in firma, "un enlace reenviado no puede abrir nada por sí solo"

    # ── El RAG no los indexa ─────────────────────────────────────────────

    def test_el_opt_in_del_rag_nace_apagado(self) -> None:
        import inspect as _inspect

        from db.alembic.versions import v127_pursuit_attachments as mig

        fuente = _inspect.getsource(mig.upgrade)
        assert '"indexable"' in fuente
        assert 'sa.text("false")' in fuente

    def test_ningun_camino_de_indexacion_mira_la_tabla(self) -> None:
        """La garantía es estructural: el RAG lee `documentos`, no adjuntos propios."""
        import inspect as _inspect

        import scheduler.jobs.documentos_embeddings as job
        import services.embeddings as emb

        for modulo in (job, emb):
            assert "pursuit_attachments" not in _inspect.getsource(modulo), (
                f"{modulo.__name__} no puede alcanzar los adjuntos propios sin opt-in"
            )

    def test_el_opt_in_es_por_adjunto_y_no_por_organizacion(self) -> None:
        from db.repositories.pursuit_attachments import PursuitAttachmentsRepository

        firma = inspect.signature(PursuitAttachmentsRepository.set_indexable).parameters
        assert {"attachment_id", "organization_id", "indexable"} <= set(firma)

    # ── Almacén y frontera de organización ───────────────────────────────

    def test_sin_bucket_no_se_acepta_la_subida(self) -> None:
        """`NullObjectStore.put` no lanza: aceptar sería prometer una descarga."""
        import api.routes.pursuits as mod

        fuente = inspect.getsource(mod.post_pursuit_adjunto)
        assert "AttachmentStoreUnavailable" in fuente
        assert "status_code=503" in fuente

    def test_la_pertenencia_se_comprueba_en_el_insert(self) -> None:
        from db.repositories.pursuit_attachments import PursuitAttachmentsRepository

        fuente = inspect.getsource(PursuitAttachmentsRepository.create)
        assert "FROM pursuits p WHERE p.id = %s AND p.organization_id = %s" in fuente

    def test_toda_lectura_lleva_la_organizacion(self) -> None:
        from db.repositories.pursuit_attachments import PursuitAttachmentsRepository

        for metodo in ("get", "list_for_pursuit", "delete", "set_indexable"):
            fuente = inspect.getsource(getattr(PursuitAttachmentsRepository, metodo))
            assert "organization_id = %s" in fuente, f"{metodo} sin frontera de organización"

    def test_un_rechazo_no_deja_bytes_en_el_bucket(self) -> None:
        """Si el pursuit no era suyo, el objeto recién escrito se borra."""
        import services.pursuit_attachments as mod

        fuente = inspect.getsource(mod.subir)
        assert "almacen.delete(clave)" in fuente

    def test_primero_la_fila_y_despues_el_binario_al_borrar(self) -> None:
        """Al revés quedaría una fila apuntando a un objeto que ya no existe."""
        import services.pursuit_attachments as mod

        fuente = inspect.getsource(mod.borrar)
        assert fuente.index("PursuitAttachmentsRepository().delete") < fuente.index(
            "get_object_store().delete"
        )

    # ── GDPR: dato corporativo ───────────────────────────────────────────

    def test_borrar_la_organizacion_purga_sus_adjuntos(self) -> None:
        import services.organizations as mod

        fuente = inspect.getsource(mod.borrar_organizacion)
        assert "purgar_organizacion" in fuente
        assert fuente.index("purgar_organizacion") < fuente.index("_repo.borrar")

    def test_la_advertencia_de_borrado_cuenta_los_adjuntos(self) -> None:
        from db.repositories.organizations import OrganizationRepository

        fuente = inspect.getsource(OrganizationRepository.contar_dato_corporativo)
        assert "pursuit_attachments" in fuente

    def test_el_dto_no_publica_la_clave_del_objeto(self) -> None:
        """La `blob_key` es una coordenada del bucket, no del contrato."""
        from api.routes.pursuits import PursuitAttachmentOut

        assert "blob_key" not in PursuitAttachmentOut.model_fields

    def test_subir_no_necesita_python_multipart(self) -> None:
        """D31 no pre-autoriza esa dependencia; el cuerpo crudo evita añadirla."""
        import api.routes.pursuits as mod

        fuente = inspect.getsource(mod.post_pursuit_adjunto)
        assert "UploadFile" not in fuente
        assert "await request.body()" in fuente

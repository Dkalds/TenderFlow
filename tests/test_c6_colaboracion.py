"""Stream C6 del plan complementario 2026-09: la oportunidad como espacio de trabajo.

Sin BD: se comprueban las reglas que viven en el código —permisos, orden,
derivación de la próxima acción y el orden de declaración de las rutas—, no el
resultado de una consulta.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# C6.1 — Tareas de la oportunidad
# ---------------------------------------------------------------------------


class TestAislamientoEntreOrganizaciones:
    """«Una tarea de otra organización no es visible» es la aceptación del punto."""

    def test_toda_consulta_lleva_la_organizacion_en_el_where(self) -> None:
        """Un id de oportunidad se puede enumerar: sin esta condición bastaría
        con acertar un número para leer —o cerrar— las tareas de otro equipo."""
        import db.repositories.pursuit_tasks as mod

        metodos = [
            mod.PursuitTaskRepository.crear,
            mod.PursuitTaskRepository.listar,
            mod.PursuitTaskRepository.agenda,
            mod.PursuitTaskRepository.actualizar,
            mod.PursuitTaskRepository.proxima_pendiente,
            mod.PursuitTaskRepository.vencen_en,
            mod.PursuitTaskRepository.sincronizar_next_action,
        ]
        for metodo in metodos:
            fuente = inspect.getsource(metodo)
            assert "organization_id" in fuente, f"{metodo.__name__} no acota por organización"

    def test_crear_comprueba_la_pertenencia_en_el_mismo_insert(self) -> None:
        """Comprobarlo antes, en una consulta aparte, deja una ventana entre el
        permiso y la escritura."""
        import db.repositories.pursuit_tasks as mod

        fuente = inspect.getsource(mod.PursuitTaskRepository.crear)
        assert "INSERT INTO pursuit_tasks" in fuente
        assert "FROM pursuits p WHERE p.id = %s AND p.organization_id = %s" in fuente

    def test_el_servicio_resuelve_la_organizacion_activa(self) -> None:
        import services.pursuit_tasks as mod

        for fn in (mod.list_tasks, mod.add_task, mod.update_task, mod.agenda):
            assert "resolve_organization" in inspect.getsource(fn)


class TestOrdenDeLasTareas:
    def test_las_sin_fecha_van_al_final(self) -> None:
        """Postgres ordena los NULL primero en ASC: sin `NULLS LAST`, lo primero
        que se ve sería lo que menos corre prisa."""
        import db.repositories.pursuit_tasks as mod

        for metodo in (
            mod.PursuitTaskRepository.listar,
            mod.PursuitTaskRepository.agenda,
            mod.PursuitTaskRepository.proxima_pendiente,
        ):
            assert "NULLS LAST" in inspect.getsource(metodo)

    def test_las_pendientes_van_antes_que_las_cerradas(self) -> None:
        import db.repositories.pursuit_tasks as mod

        fuente = inspect.getsource(mod.PursuitTaskRepository.listar)
        assert "CASE estado WHEN 'pendiente' THEN 0 ELSE 1 END" in fuente


class TestProximaAccionDerivada:
    def test_next_action_se_sincroniza_tras_cada_cambio(self) -> None:
        """Un campo que hay que mantener a mano se desincroniza, y el tablero
        acaba enseñando una acción terminada hace semanas."""
        import services.pursuit_tasks as mod

        for fn in (mod.add_task, mod.update_task):
            assert "sincronizar_next_action" in inspect.getsource(fn)

    def test_sin_tareas_pendientes_next_action_queda_vacia(self) -> None:
        """Dejar la última sería enseñar algo falso."""
        import db.repositories.pursuit_tasks as mod

        fuente = inspect.getsource(mod.PursuitTaskRepository.sincronizar_next_action)
        assert '(proxima or {}).get("titulo")' in fuente


class TestActualizacionParcial:
    def test_desasignar_una_tarea_es_expresable(self) -> None:
        """Con `is not None` no habría forma de decir «quitale el responsable»."""
        import services.pursuit_tasks as mod

        fuente = inspect.getsource(mod.update_task)
        assert "model_fields_set" in fuente
        assert 'tocar_responsable="responsable_user_id" in enviados' in fuente
        assert 'tocar_vence="vence" in enviados' in fuente

    def test_un_estado_fuera_del_vocabulario_no_escribe(self) -> None:
        from unittest.mock import patch as _patch

        from db.repositories.pursuit_tasks import ESTADOS, PursuitTaskRepository

        with _patch("db.repositories.pursuit_tasks.connect") as conectar:
            assert (
                PursuitTaskRepository().actualizar(task_id=1, organization_id=1, estado="terminada")
                is None
            )
            assert not conectar.called
        assert ESTADOS == ("pendiente", "hecha", "cancelada")

    def test_cancelada_no_es_borrar(self) -> None:
        """«Ya no hace falta» dice que alguien lo evaluó; el hueco de una fila
        borrada es indistinguible de «nadie se acordó»."""
        import db.repositories.pursuit_tasks as mod

        fuente = inspect.getsource(mod)
        assert "DELETE FROM pursuit_tasks" not in fuente


class TestRutas:
    def test_las_rutas_existen(self) -> None:
        from api.app import app

        rutas = {r.path for r in app.routes if hasattr(r, "path")}
        for ruta in (
            "/api/v1/pursuits/{pursuit_id}/tasks",
            "/api/v1/pursuits/{pursuit_id}/tasks/{task_id}",
            "/api/v1/pursuits/tasks/agenda",
        ):
            assert ruta in rutas, f"falta {ruta}"

    def test_las_rutas_literales_se_declaran_antes_que_la_parametrica(self) -> None:
        """FastAPI resuelve por orden de declaración.

        Una ruta literal bajo `/pursuits/` declarada después de
        `/pursuits/{pursuit_id}` **nunca se alcanza**: la petición entra por la
        paramétrica con el valor «tasks» y muere en un 422 que no explica nada.
        Es un fallo que ningún test de la ruta detecta, porque la ruta existe.
        """
        from api.app import app

        orden = [getattr(r, "path", "") for r in app.routes]
        parametrica = orden.index("/api/v1/pursuits/{pursuit_id}")
        for literal in ("/api/v1/pursuits/agenda", "/api/v1/pursuits/tasks/agenda"):
            assert orden.index(literal) < parametrica, (
                f"{literal} se declara después de la paramétrica y no se alcanza nunca"
            )


class TestCalendario:
    def test_las_tareas_con_fecha_entran_en_el_ics(self) -> None:
        import api.routes.exports as mod

        assert "_eventos_de_tareas" in inspect.getsource(mod._eventos_calendario)

    def test_solo_las_pendientes(self) -> None:
        """Una tarea hecha en el calendario del mes que viene es ruido."""
        import api.routes.exports as mod

        fuente = inspect.getsource(mod._eventos_de_tareas)
        # `agenda` ya filtra por `estado = 'pendiente'`.
        assert ".agenda(" in fuente

    def test_un_fallo_de_tareas_no_deja_sin_plazos_al_calendario(self) -> None:
        import api.routes.exports as mod

        fuente = inspect.getsource(mod._eventos_de_tareas)
        assert "except Exception:" in fuente and "return []" in fuente

    def test_las_tareas_sin_fecha_no_son_eventos(self) -> None:
        import api.routes.exports as mod

        fuente = inspect.getsource(mod._eventos_de_tareas)
        assert 'if not tarea.get("vence"):' in fuente


def test_el_titulo_de_una_tarea_es_corto_a_proposito() -> None:
    """Una tarea es una acción («pedir el aval»); lo que no cabe es un comentario."""
    from shared.dto import PURSUIT_TASK_TITULO_MAX_CHARS, PursuitTaskCreate

    assert PURSUIT_TASK_TITULO_MAX_CHARS == 200
    with pytest.raises(ValueError):
        PursuitTaskCreate(titulo="x" * 201)


def test_una_tarea_puede_no_tener_responsable_ni_fecha() -> None:
    """Existir antes de saber quién la hará es un estado legítimo."""
    from shared.dto import PursuitTaskCreate

    tarea = PursuitTaskCreate(titulo="Pedir la clasificación")

    assert tarea.responsable_user_id is None
    assert tarea.vence is None


def test_el_dto_de_update_distingue_ausente_de_nulo() -> None:
    from shared.dto import PursuitTaskUpdate

    solo_estado = PursuitTaskUpdate(estado="hecha")
    desasignar: Any = PursuitTaskUpdate.model_validate({"responsable_user_id": None})

    assert "responsable_user_id" not in solo_estado.model_fields_set
    assert "responsable_user_id" in desasignar.model_fields_set


# ---------------------------------------------------------------------------
# C6.7 — Exportar el pipeline
# ---------------------------------------------------------------------------


class TestExportDelPipeline:
    def test_una_formula_no_se_ejecuta_al_abrir_el_fichero(self) -> None:
        """Aquí el texto lo escribe el propio equipo: una fórmula no llega por
        casualidad desde una fuente pública, alguien la pudo escribir a propósito
        en el motivo de una decisión."""
        from services.exports import PURSUIT_COLUMNS, generate_csv, pursuit_rows

        filas = pursuit_rows(
            [{"licitacion_id": "placsp:1", "decision_reason": "=cmd|' /c calc'!A0"}],
            organizacion="ACME",
            exportado_en="2026-09-07",
        )
        filas[0]["titulo"] = '=HYPERLINK("http://malo","click")'
        csv = generate_csv(filas, columns=[*PURSUIT_COLUMNS])

        texto = csv.decode("utf-8")
        # Neutralizada, no borrada: el texto original se sigue leyendo, pero la
        # hoja de cálculo lo trata como texto porque empieza por apóstrofo.
        assert "'=HYPERLINK" in texto
        # Ningún campo empieza por un carácter que Excel interprete como fórmula.
        for campo in texto.split(";"):
            assert not campo.lstrip('"').startswith(("=", "+", "@")), campo

    def test_el_fichero_declara_organizacion_y_fecha(self) -> None:
        """Van como columnas y no como comentario antes de la cabecera: un `# …`
        inicial rompe `pd.read_csv` por defecto y la importación de Excel."""
        from services.exports import PURSUIT_COLUMNS, generate_csv, pursuit_rows

        filas = pursuit_rows(
            [{"licitacion_id": "placsp:1"}], organizacion="ACME", exportado_en="2026-09-07"
        )
        cabecera = generate_csv(filas, columns=PURSUIT_COLUMNS).decode("utf-8").splitlines()[0]

        assert PURSUIT_COLUMNS[0] == "organizacion"
        assert "organizacion" in cabecera and "exportado_en" in cabecera

    def test_la_procedencia_va_en_cada_fila(self) -> None:
        """Un CSV se corta, se pega y se filtra: la procedencia tiene que
        sobrevivir a eso."""
        from services.exports import pursuit_rows

        filas = pursuit_rows(
            [{"licitacion_id": "a"}, {"licitacion_id": "b"}],
            organizacion="ACME",
            exportado_en="2026-09-07",
        )

        assert all(f["organizacion"] == "ACME" for f in filas)
        assert all(f["exportado_en"] == "2026-09-07" for f in filas)

    def test_el_nombre_del_fichero_no_dice_licitaciones(self) -> None:
        from services.exports import get_export_filename

        assert get_export_filename("csv", prefix="pipeline").startswith("pipeline_")

    def test_el_pdf_del_pipeline_se_rechaza_en_vez_de_entregar_otra_cosa(self) -> None:
        """El PDF está maquetado para el corpus público: tiene otras columnas y
        otro público."""
        import inspect

        import api.routes.exports as mod

        fuente = inspect.getsource(mod.download_export)
        assert 'if recurso == "pursuits":' in fuente
        assert "El export del pipeline no tiene formato PDF" in fuente

    def test_el_nombre_de_la_organizacion_se_lee_como_el_resto_del_espacio(self) -> None:
        """No hay razón para que el export resuelva el nombre de una
        organización que quien lo pide no ve."""
        import inspect

        import api.routes.exports as mod

        assert "get_for_user" in inspect.getsource(mod._nombre_organizacion)


# ---------------------------------------------------------------------------
# C6.6 — Notas en seguimientos
# ---------------------------------------------------------------------------


class TestNotasEnFavoritos:
    def test_la_nota_no_se_muestra_a_otra_persona_aunque_el_favorito_sea_compartido(
        self,
    ) -> None:
        """Es la aceptación del punto, y se resuelve en la proyección.

        Una segunda columna de visibilidad sería un segundo sitio donde
        equivocarse; el `CASE` lo deja imposible de leer mal.
        """
        import db.repositories.watchlist as mod

        # La proyección vive en `_proyeccion_nota` desde que se hizo tolerante a
        # que `v123` no esté aplicada todavía (`db/columnas.py`); la regla es la
        # misma y sigue estando en un solo sitio.
        fuente = inspect.getsource(mod._proyeccion_nota)
        assert "CASE WHEN wi.user_key = %s THEN wi.nota END AS nota" in fuente

    def test_nadie_edita_la_nota_de_otra_persona(self) -> None:
        """`remove_item` acepta borrar un favorito compartido; esto no."""
        import db.repositories.watchlist as mod

        fuente = inspect.getsource(mod.WatchlistRepository.set_note)
        assert "AND user_key = %s" in fuente
        assert "visibility" not in fuente

    def test_una_nota_vacia_borra_en_vez_de_guardar_espacios(self) -> None:
        import db.repositories.watchlist as mod

        fuente = inspect.getsource(mod.WatchlistRepository.set_note)
        assert '(nota or "").strip() or None' in fuente

    def test_el_contrato_es_tipado(self) -> None:
        from shared.dto import (
            WATCHLIST_NOTA_MAX_CHARS,
            WatchlistFavoriteItem,
            WatchlistNotaBody,
        )

        assert "nota" in WatchlistFavoriteItem.model_fields
        assert WATCHLIST_NOTA_MAX_CHARS == 500
        with pytest.raises(ValueError):
            WatchlistNotaBody(nota="x" * 501)

    def test_el_export_rgpd_arrastra_la_nota(self) -> None:
        """Es dato personal del usuario: sale en su export y se va con él."""
        import db.repositories.watchlist as mod

        exportar = inspect.getsource(mod.WatchlistRepository.export_items_by_user_key)
        assert "SELECT * FROM watchlist_items" in exportar
        anonimizar = inspect.getsource(mod.WatchlistRepository.anonymize_items_by_user_key)
        assert "DELETE FROM watchlist_items" in anonimizar

    def test_la_ruta_existe_y_convive_con_el_delete(self) -> None:
        from api.app import app

        metodos = {
            metodo
            for r in app.routes
            if getattr(r, "path", "") == "/api/v1/watchlist/items/{id_externo:path}"
            for metodo in (getattr(r, "methods", None) or set())
        }
        assert {"PUT", "DELETE"} <= metodos


# ---------------------------------------------------------------------------
# C6.5 — Mi baja frente al mercado
# ---------------------------------------------------------------------------


class TestBajaPropia:
    def test_solo_entra_la_base_sin_iva_declarada(self) -> None:
        """Comparar una oferta sin IVA con un presupuesto que lo lleva produce
        una baja del 21 % que no existió, y este número se usa para decidir el
        precio de la siguiente oferta."""
        import db.repositories.pursuits as mod

        fuente = inspect.getsource(mod.PursuitRepository.baja_propia_por_segmento)
        assert "BASE_DECLARADA_SQL" in fuente
        assert "l.importe_base_sin_iva > 0" in fuente

    def test_solo_cuenta_lo_presentado(self) -> None:
        """Una oferta que se preparó y no se presentó no es una baja: es un borrador."""
        import db.repositories.pursuits as mod

        fuente = inspect.getsource(mod.PursuitRepository.baja_propia_por_segmento)
        assert "p.submitted_at IS NOT NULL" in fuente
        assert "p.offer_price_eur IS NOT NULL" in fuente

    def test_un_segmento_con_pocas_ofertas_no_se_publica(self) -> None:
        """Con menos de cinco, un expediente agresivo convierte «bajamos un 4 %»
        en «bajamos un 22 %» y alguien planifica con eso."""
        import db.repositories.pursuits as mod

        assert mod.PursuitRepository.MIN_OFERTAS_POR_SEGMENTO == 5
        fuente = inspect.getsource(mod.PursuitRepository.baja_propia_por_segmento)
        assert "HAVING COUNT(*) >= " in fuente

    def test_la_consulta_esta_acotada_a_la_organizacion(self) -> None:
        import db.repositories.pursuits as mod

        fuente = inspect.getsource(mod.PursuitRepository.baja_propia_por_segmento)
        assert "WHERE p.organization_id = %s" in fuente

    def test_el_cpv_se_agrupa_a_cuatro_digitos(self) -> None:
        import db.repositories.pursuits as mod

        fuente = inspect.getsource(mod.PursuitRepository.baja_propia_por_segmento)
        assert "LEFT(l.cpv, 4)" in fuente

    def test_la_respuesta_declara_n_y_base(self) -> None:
        """Una media sin `n` no se puede interpretar ni comparar con la del mercado."""
        from shared.dto import BajaPropiaResult, BajaPropiaSegmento

        assert "n" in BajaPropiaSegmento.model_fields
        vacio = BajaPropiaResult(organization_id=1, segmento="cpv", min_ofertas=5)
        assert vacio.base == "sin_iva"
        assert vacio.items == []

    def test_un_decimal_ilegible_es_none_y_no_cero(self) -> None:
        """Un `0.0` por error de conversión sería una baja nula que nadie hizo."""
        from services.pursuits import _a_float

        assert _a_float(None) is None
        assert _a_float("no-es-un-numero") is None
        assert _a_float("12.5") == 12.5

    def test_la_ruta_se_declara_antes_que_la_parametrica(self) -> None:
        from api.app import app

        orden = [getattr(r, "path", "") for r in app.routes]
        assert orden.index("/api/v1/pursuits/baja-propia") < orden.index(
            "/api/v1/pursuits/{pursuit_id}"
        )


# ---------------------------------------------------------------------------
# C6.2 — Menciones en comentarios
# ---------------------------------------------------------------------------


def _miembros() -> list[dict[str, Any]]:
    return [
        {"user_id": 1, "status": "active", "display_name": "Ana Pérez", "email": "ana@acme.es"},
        {"user_id": 2, "status": "active", "display_name": "Bruno Gil", "email": "bruno@acme.es"},
        {"user_id": 3, "status": "invited", "display_name": "Clara Ruiz", "email": "clara@acme.es"},
        {"user_id": 4, "status": "revoked", "display_name": "Diego Paz", "email": "diego@acme.es"},
    ]


class TestParseoDeMenciones:
    def test_resuelve_por_nombre_visible_y_por_email(self) -> None:
        from services.menciones import resolver

        assert resolver("@Ana Pérez ¿lo tenemos?", _miembros()) == [1]
        assert resolver("gracias @bruno", _miembros()) == [2]

    def test_los_acentos_y_las_mayusculas_no_cambian_a_quien_se_menciona(self) -> None:
        from services.menciones import resolver

        assert resolver("@ana perez mirá esto", _miembros()) == [1]

    def test_lo_ambiguo_no_resuelve(self) -> None:
        """Elegir una de las dos Anas es peor que no elegir: la mención llega a
        quien no era y la destinataria no se entera."""
        from services.menciones import resolver

        dos_anas = [
            {"user_id": 1, "status": "active", "display_name": "Ana", "email": "ana@acme.es"},
            {"user_id": 9, "status": "active", "display_name": "Ana", "email": "ana2@acme.es"},
        ]

        assert resolver("@ana ¿lo miras?", dos_anas) == []

    def test_el_nombre_mas_largo_gana_al_mas_corto(self) -> None:
        from services.menciones import resolver

        equipo = [
            {"user_id": 1, "status": "active", "display_name": "Ana", "email": "a@acme.es"},
            {"user_id": 2, "status": "active", "display_name": "Ana María", "email": "am@acme.es"},
        ]

        assert resolver("@Ana María revisa el pliego", equipo) == [2]

    def test_no_se_menciona_a_quien_no_esta_activo(self) -> None:
        """Un `invited` todavía no ha entrado y un `revoked` ya no está."""
        from services.menciones import resolver

        assert resolver("@clara @diego", _miembros()) == []

    def test_una_arroba_que_no_es_nadie_no_menciona(self) -> None:
        from services.menciones import resolver

        assert resolver("nos vemos @mañana en la reunión", _miembros()) == []

    def test_no_se_repite_a_la_misma_persona(self) -> None:
        from services.menciones import resolver

        assert resolver("@ana @Ana Pérez @ana", _miembros()) == [1]


class TestNotificacionDeMenciones:
    def test_va_al_outbox_y_no_a_un_envio_directo(self) -> None:
        """El despachador decide el canal según las preferencias de cada persona
        (C2.7); escribir un correo aquí saltaría esa decisión."""
        from unittest.mock import patch as _patch

        from services.menciones import notificar

        with _patch("db.events.append_event") as evento:
            enviados = notificar(
                mencionados=[2, 3],
                autor_user_id=1,
                organization_id=7,
                pursuit_id=11,
                comment_id=99,
            )

        assert enviados == 2
        tipos = {llamada.args[0] for llamada in evento.call_args_list}
        assert tipos == {"pursuit.mentioned"}
        assert all(c.args[1] == 11 for c in evento.call_args_list)

    def test_mencionarse_a_uno_mismo_no_notifica(self) -> None:
        """Es una forma de escribir, no una petición de atención."""
        from unittest.mock import patch as _patch

        from services.menciones import notificar

        with _patch("db.events.append_event") as evento:
            enviados = notificar(
                mencionados=[1], autor_user_id=1, organization_id=7, pursuit_id=1, comment_id=1
            )

        assert enviados == 0
        assert not evento.called

    def test_un_fallo_del_outbox_no_tumba_el_comentario(self) -> None:
        from unittest.mock import patch as _patch

        from services.menciones import notificar

        with _patch("db.events.append_event", side_effect=RuntimeError("bd caída")):
            assert (
                notificar(
                    mencionados=[2], autor_user_id=1, organization_id=7, pursuit_id=1, comment_id=1
                )
                == 0
            )


class TestPersistenciaDeMenciones:
    def test_se_guardan_los_ids_y_no_el_texto_resuelto(self) -> None:
        """Si alguien cambia su nombre visible, la mención sigue apuntando a la
        misma persona."""
        import db.repositories.pursuit_comments as mod

        fuente = inspect.getsource(mod.PursuitCommentRepository.create)
        assert "mentions_json" in fuente
        assert "json.dumps(mentions" in fuente

    def test_un_reintento_idempotente_no_vuelve_a_avisar(self) -> None:
        import services.pursuit_comments as mod

        fuente = inspect.getsource(mod.add_comment)
        assert "if created and mencionados:" in fuente

    def test_una_fila_corrupta_no_rompe_el_hilo(self) -> None:
        from services.pursuit_comments import _menciones

        assert _menciones(None) == []
        assert _menciones("no-es-json") == []
        assert _menciones("[1, 2]") == [1, 2]

    def test_el_contrato_expone_las_menciones(self) -> None:
        from shared.dto import PursuitCommentOut

        assert "mentions" in PursuitCommentOut.model_fields


# ---------------------------------------------------------------------------
# C6.4 — Plantilla de go/no-go ponderada (D30)
# ---------------------------------------------------------------------------


class TestPlantillaGoNoGo:
    def test_los_cinco_criterios_son_los_de_d30(self) -> None:
        """Cerrados a propósito: un formulario que cada equipo amplía deja de
        poder compararse consigo mismo el trimestre siguiente."""
        from services.gonogo import CRITERIOS

        assert CRITERIOS == (
            "encaje_estrategico",
            "capacidad",
            "competencia",
            "rentabilidad",
            "riesgo",
        )

    def test_los_pesos_tienen_que_sumar_cien(self) -> None:
        """Sin eso el total deja de ser «sobre 100» y dos equipos —o el mismo
        antes y después— dejan de poder compararse."""
        from services.gonogo import PESOS_POR_DEFECTO, GoNoGoError, validar_pesos

        assert sum(PESOS_POR_DEFECTO.values()) == 100
        with pytest.raises(GoNoGoError, match="suman"):
            validar_pesos({**PESOS_POR_DEFECTO, "riesgo": 10})

    def test_media_plantilla_rellenada_no_puntua(self) -> None:
        """Un total con tres criterios de cinco parece comparable y no lo es."""
        from services.gonogo import GoNoGoError, validar_puntuaciones

        with pytest.raises(GoNoGoError, match="Faltan"):
            validar_puntuaciones({"capacidad": 3, "riesgo": 4})

    def test_la_escala_va_de_uno_a_cinco(self) -> None:
        from services.gonogo import CRITERIOS, GoNoGoError, validar_puntuaciones

        with pytest.raises(GoNoGoError, match="entre"):
            validar_puntuaciones({**{c: 3 for c in CRITERIOS}, "riesgo": 6})

    def test_todo_unos_no_da_cero(self) -> None:
        """«0 sobre 100» a quien puntuó todo con unos le dice que no puntuó."""
        from services.gonogo import CRITERIOS, PESOS_POR_DEFECTO, total_ponderado

        assert total_ponderado({c: 1 for c in CRITERIOS}, PESOS_POR_DEFECTO) == 20.0
        assert total_ponderado({c: 5 for c in CRITERIOS}, PESOS_POR_DEFECTO) == 100.0

    def test_unos_ajustes_corruptos_no_dejan_sin_plantilla(self) -> None:
        from services.gonogo import PESOS_POR_DEFECTO, UMBRAL_POR_DEFECTO, ajustes_de

        assert ajustes_de({}) == (PESOS_POR_DEFECTO, UMBRAL_POR_DEFECTO)
        assert ajustes_de({"gonogo": "no-es-un-dict"}) == (PESOS_POR_DEFECTO, UMBRAL_POR_DEFECTO)
        assert ajustes_de({"gonogo": {"pesos": {"capacidad": 100}}})[0] == PESOS_POR_DEFECTO

    def test_el_total_se_congela_y_no_se_recalcula(self) -> None:
        """Recalcularlo al leer haría que cambiar un peso reescribiera decisiones
        ya tomadas: expedientes rechazados por bajos aparecerían por encima."""
        import db.repositories.pursuits as mod

        fuente = inspect.getsource(mod.PursuitRepository.guardar_gonogo)
        assert "UPDATE pursuits SET gonogo_json = %s, gonogo_total = %s" in fuente
        assert "AND organization_id = %s" in fuente

    def test_solo_owner_o_admin_cambian_la_plantilla(self) -> None:
        """Quien la toca cambia el criterio con el que se juzga al equipo entero."""
        import services.gonogo as mod

        assert set(mod.ROLES_QUE_EDITAN) == {"owner", "admin"}
        fuente = inspect.getsource(mod.guardar_ajustes)
        assert "ROLES_QUE_EDITAN" in fuente
        assert "log_event(" in fuente and '"antes"' in fuente and '"despues"' in fuente

    def test_la_metrica_de_producto_cuenta_los_go_bajos(self) -> None:
        import scripts.product_status as mod

        fuente = inspect.getsource(mod._imprimir_gonogo)
        assert "go_bajo_umbral" in fuente
        # Cero puntuados no es «cero problemas».
        assert "sin puntuar" in fuente

    def test_las_rutas_existen(self) -> None:
        from api.app import app

        rutas = {r.path for r in app.routes if hasattr(r, "path")}
        assert "/api/v1/organizations/gonogo" in rutas
        assert "/api/v1/pursuits/{pursuit_id}/gonogo" in rutas

    def test_el_riesgo_se_puntua_al_derecho(self) -> None:
        """Invertir uno solo de los cinco es la forma más rápida de que alguien
        rellene el formulario al revés sin darse cuenta."""
        from services.gonogo import PESOS_POR_DEFECTO, total_ponderado

        base = {
            "encaje_estrategico": 3,
            "capacidad": 3,
            "competencia": 3,
            "rentabilidad": 3,
            "riesgo": 1,
        }
        mejor = {**base, "riesgo": 5}

        assert total_ponderado(mejor, PESOS_POR_DEFECTO) > total_ponderado(base, PESOS_POR_DEFECTO)

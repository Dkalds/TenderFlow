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

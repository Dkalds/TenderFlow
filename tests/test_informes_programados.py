"""Informes programados por organización (T6, v132).

Los criterios de aceptación del ítem, uno por bloque:

1. **Render con fixture**, y el informe declara universo, ventana y fecha del
   dato (ADR-014). Sin eso es un PDF con cifras que alguien llevará a un comité
   creyendo que dicen otra cosa.
2. **Opt-out por usuario y sin seguimiento de aperturas.** Lo segundo se
   comprueba sobre el HTML: ni una imagen, que es como se cuela un píxel.
3. **Una organización sin oportunidades no recibe correo** y queda en
   `ops_events`.

Y tres cosas que el ítem no pide pero rompen en producción si no se fijan:

4. **Idempotencia.** El paso corre en cada pasada de la pipeline —cada cuatro
   horas—, no una vez al día. Sin la marca de ventana, el informe saldría una
   vez por pasada durante toda la semana.
5. **El adjunto llega de verdad.** El transporte no admitía adjuntos hasta
   ahora; un `multipart/alternative` con el PDF colgando al lado enseñaría el
   texto plano *y* el HTML en vez de elegir.
6. **El paso está en la secuencia canónica** y es advisory: un ESP caído no
   puede tumbar la ingesta.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from html import escape
from typing import Any
from unittest.mock import patch

import pytest

from shared.dto import ReportScheduleOut

AHORA = datetime(2026, 9, 14, 7, 30, tzinfo=UTC)  # lunes


# ── Utilidades de semilla ───────────────────────────────────────────────────


def _organizacion(db_mod: Any, correo: str, nombre: str = "Equipo") -> tuple[int, int]:
    from db.repositories.organizations import OrganizationRepository
    from db.users import create_user

    user_id = create_user(email=correo, password_hash="x")  # pragma: allowlist secret
    org_id = int(OrganizationRepository().create_organization(nombre, user_id)["id"])
    return user_id, org_id


def _pursuit(
    db_mod: Any,
    organization_id: int,
    user_id: int,
    *,
    id_externo: str,
    status: str = "preparing",
    outcome: str = "pending",
    identified_at: str = "2026-09-10T00:00:00+00:00",
    closed_at: str | None = None,
    fecha_limite: str | None = None,
) -> int:
    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_limite, fecha_extraccion) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (id_externo) DO UPDATE SET "
            "fecha_limite = EXCLUDED.fecha_limite",
            (id_externo, f"Expediente {id_externo}", fecha_limite, "2026-09-01T00:00:00+00:00"),
        )
        fila = c.execute(
            "INSERT INTO pursuits (licitacion_id, organization_id, responsible_user_id, "
            " status, outcome, identified_at, closed_at, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                id_externo,
                organization_id,
                user_id,
                status,
                outcome,
                identified_at,
                closed_at,
                "2026-09-01T00:00:00+00:00",
                "2026-09-01T00:00:00+00:00",
            ),
        ).fetchone()
    return int(fila[0])


# ── 1. Render y declaración de universo (ADR-014) ───────────────────────────


def test_el_informe_cuenta_el_embudo_los_cierres_y_los_vencimientos(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    from services.informes import construir

    user_id, org_id = _organizacion(db_mod, "informe@example.test", "ACME")
    _pursuit(db_mod, org_id, user_id, id_externo="INF-1", status="preparing")
    _pursuit(db_mod, org_id, user_id, id_externo="INF-2", status="qualifying")
    _pursuit(
        db_mod,
        org_id,
        user_id,
        id_externo="INF-3",
        status="won",
        outcome="won",
        closed_at="2026-09-12T00:00:00+00:00",
    )
    _pursuit(
        db_mod,
        org_id,
        user_id,
        id_externo="INF-4",
        status="lost",
        outcome="lost",
        closed_at="2026-09-12T00:00:00+00:00",
    )
    # Cerrada hace un mes: fuera de la ventana, no cuenta como cierre de esta
    # semana. Es la clase de fila que hace que el informe diga «tres ganadas»
    # todas las semanas.
    _pursuit(
        db_mod,
        org_id,
        user_id,
        id_externo="INF-5",
        status="won",
        outcome="won",
        identified_at="2026-07-01T00:00:00+00:00",
        closed_at="2026-08-01T00:00:00+00:00",
    )

    informe = construir(org_id, organizacion="ACME", ahora=AHORA)

    assert informe.abiertas == 2
    assert informe.abiertas_por_estado == {"preparing": 1, "qualifying": 1}
    assert informe.ganadas == 1
    assert informe.perdidas == 1
    # Las cuatro identificadas dentro de la ventana; la de julio queda fuera.
    assert informe.nuevas == 4
    assert informe.vacio is False


def test_el_informe_declara_universo_ventana_y_fecha_del_dato(tmp_db: Any) -> None:
    """ADR-014: cifras sin universo son cifras que alguien leerá mal."""
    db_mod, _ = tmp_db
    from services.informes import construir, render_html, render_pdf

    user_id, org_id = _organizacion(db_mod, "universo@example.test")
    _pursuit(db_mod, org_id, user_id, id_externo="UNI-1")

    informe = construir(org_id, organizacion="ACME", ahora=AHORA)
    assert str(org_id) in informe.universo
    # Siete fechas, no ocho. Los dos extremos son inclusivos, así que
    # `hasta - 7` abarcaba del 07 al 14 —ocho días— y lo cerrado el lunes
    # anterior contaba en dos informes seguidos.
    assert informe.ventana.startswith("Del 2026-09-08 al 2026-09-14")
    assert informe.fecha_dato == "2026-09-14 07:30 UTC"

    html = render_html(informe)
    for trozo in (informe.universo, informe.ventana, informe.fecha_dato):
        assert trozo in html

    pdf = render_pdf(informe)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 500


def test_solo_entran_los_vencimientos_del_horizonte_y_de_la_organizacion(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    from services.informes import DIAS_VENCIMIENTO, construir

    user_id, org_id = _organizacion(db_mod, "plazos@example.test")
    otro_user, otra_org = _organizacion(db_mod, "plazos-otro@example.test", "Otra")

    dentro = (AHORA + timedelta(days=3)).date().isoformat()
    fuera = (AHORA + timedelta(days=DIAS_VENCIMIENTO + 5)).date().isoformat()
    _pursuit(db_mod, org_id, user_id, id_externo="PLZ-1", fecha_limite=dentro)
    _pursuit(db_mod, org_id, user_id, id_externo="PLZ-2", fecha_limite=fuera)
    _pursuit(db_mod, otra_org, otro_user, id_externo="PLZ-3", fecha_limite=dentro)

    informe = construir(org_id, ahora=AHORA)

    assert [v.licitacion_id for v in informe.vencimientos] == ["PLZ-1"]
    assert informe.vencimientos[0].dias == 3


# ── 2. Privacidad: opt-out y sin seguimiento ────────────────────────────────


def test_el_html_no_lleva_ninguna_imagen(tmp_db: Any) -> None:
    """Sin píxel de seguimiento, y la forma de comprobarlo es que no hay `<img`.

    Misma regla que `web/src/lib/analytics.ts`: no se mide quién abre el correo.
    Un test sobre la ausencia de una etiqueta es tosco, pero es exactamente lo
    que impide que alguien añada «una imagen de cabecera» y de paso un píxel.
    """
    db_mod, _ = tmp_db
    from services.informes import construir, render_html

    user_id, org_id = _organizacion(db_mod, "privacidad@example.test")
    _pursuit(db_mod, org_id, user_id, id_externo="PRI-1")

    html = render_html(construir(org_id, ahora=AHORA), url_baja="https://x.test/baja")
    assert "<img" not in html.lower()
    assert "https://x.test/baja" in html


def test_quien_apago_el_informe_no_lo_recibe(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    from db.repositories import notification_preferences as prefs
    from db.repositories.organizations import OrganizationRepository
    from scheduler.jobs.informes_programados import TIPO_AVISO, _destinatarios

    _owner_id, org_id = _organizacion(db_mod, "recibe@example.test")
    admin_id, _ = _organizacion(db_mod, "apagado@example.test", "Suya")
    OrganizationRepository().add_membership(org_id, admin_id, "admin")

    prefs.guardar(admin_id, tipo=TIPO_AVISO, canal="email", frecuencia="off")

    correos = {c for _, c in _destinatarios({"organization_id": org_id, "destinatarios": None})}
    assert correos == {"recibe@example.test"}


def test_una_lista_explicita_sustituye_a_los_administradores(tmp_db: Any) -> None:
    """Y no se le consulta preferencia: pueden no ser cuentas de la aplicación."""
    db_mod, _ = tmp_db
    from scheduler.jobs.informes_programados import _destinatarios

    _owner, org_id = _organizacion(db_mod, "lista@example.test")
    destinos = _destinatarios(
        {"organization_id": org_id, "destinatarios": ["direccion@acme.test", " "]}
    )
    assert destinos == [(None, "direccion@acme.test")]


# ── 3. Una organización vacía no recibe correo ──────────────────────────────


def test_sin_oportunidades_no_se_envia_y_queda_en_ops_events(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    from db.repositories import report_schedules
    from scheduler.jobs.informes_programados import ejecutar

    _owner, org_id = _organizacion(db_mod, "vacia@example.test")
    report_schedules.guardar(
        org_id, activo=True, dia_semana=0, hora_utc=7, destinatarios=["a@b.test"]
    )

    with (
        patch("observability.mailer.enviar") as enviar,
        patch("observability.ops_events.record_event") as evento,
    ):
        resumen = ejecutar(AHORA)

    assert resumen.vacios == 1 and resumen.enviados == 0
    enviar.assert_not_called()
    assert evento.call_args.args[0] == "informe_semanal_vacio"

    # Y la ventana queda sellada: sin esto se recalcularía en cada pasada.
    fila = report_schedules.get(org_id)
    assert fila is not None and fila["ultimo_estado"] == "vacio"


# ── 4. Idempotencia de la ventana ───────────────────────────────────────────


def test_dos_pasadas_dentro_de_la_misma_ventana_envian_una_vez(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    from db.repositories import report_schedules
    from observability.mailer import ResultadoEnvio
    from scheduler.jobs.informes_programados import ejecutar

    user_id, org_id = _organizacion(db_mod, "idempotente@example.test")
    _pursuit(db_mod, org_id, user_id, id_externo="IDE-1")
    report_schedules.guardar(
        org_id, activo=True, dia_semana=0, hora_utc=7, destinatarios=["a@b.test"]
    )

    with patch(
        "observability.mailer.enviar", return_value=ResultadoEnvio(ok=True, backend="console")
    ) as enviar:
        primera = ejecutar(AHORA)
        # Cuatro horas después: otra pasada de la pipeline, misma ventana.
        segunda = ejecutar(AHORA + timedelta(hours=4))

    assert primera.enviados == 1
    assert segunda.programadas == 0 and segunda.enviados == 0
    assert enviar.call_count == 1


def test_la_semana_siguiente_vuelve_a_enviar(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    from db.repositories import report_schedules
    from observability.mailer import ResultadoEnvio
    from scheduler.jobs.informes_programados import ejecutar

    user_id, org_id = _organizacion(db_mod, "semanal@example.test")
    _pursuit(db_mod, org_id, user_id, id_externo="SEM-1")
    report_schedules.guardar(
        org_id, activo=True, dia_semana=0, hora_utc=7, destinatarios=["a@b.test"]
    )

    with patch(
        "observability.mailer.enviar", return_value=ResultadoEnvio(ok=True, backend="console")
    ) as enviar:
        ejecutar(AHORA)
        ejecutar(AHORA + timedelta(days=7))

    assert enviar.call_count == 2


def test_una_programacion_apagada_no_entra(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    from db.repositories import report_schedules

    _owner, org_id = _organizacion(db_mod, "apagada@example.test")
    report_schedules.guardar(org_id, activo=False, dia_semana=0, hora_utc=7, destinatarios=None)
    assert report_schedules.pendientes(AHORA) == []


def test_otro_dia_de_la_semana_no_entra(tmp_db: Any) -> None:
    """`AHORA` es lunes; una programación para el miércoles no toca."""
    db_mod, _ = tmp_db
    from db.repositories import report_schedules

    _owner, org_id = _organizacion(db_mod, "miercoles@example.test")
    report_schedules.guardar(org_id, activo=True, dia_semana=2, hora_utc=7, destinatarios=None)
    assert report_schedules.pendientes(AHORA) == []


def test_antes_de_la_hora_no_entra(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    from db.repositories import report_schedules

    _owner, org_id = _organizacion(db_mod, "temprano@example.test")
    report_schedules.guardar(org_id, activo=True, dia_semana=0, hora_utc=20, destinatarios=None)
    assert report_schedules.pendientes(AHORA) == []


def test_una_ventana_de_tarde_sigue_abierta_de_madrugada(tmp_db: Any) -> None:
    """Regresión: el filtro por hora en SQL cerraba las ventanas tardías antes.

    Con `hora_utc <= EXTRACT(HOUR)`, una programación de los lunes a las 20:00
    desaparecía de `pendientes()` en la pasada de las 03:00 del martes — que es
    justo cuando su ventana lleva siete horas abierta y el informe todavía no
    ha salido. El filtro parecía barato y le costaba el informe de la semana a
    cualquiera que lo programase por la tarde.
    """
    db_mod, _ = tmp_db
    from db.repositories import report_schedules

    _owner, org_id = _organizacion(db_mod, "tarde@example.test")
    report_schedules.guardar(org_id, activo=True, dia_semana=0, hora_utc=20, destinatarios=None)

    martes_de_madrugada = datetime(2026, 9, 15, 3, 0, tzinfo=UTC)
    pendiente = report_schedules.pendientes(martes_de_madrugada)
    assert [f["organization_id"] for f in pendiente] == [org_id]

    # Y 24 h después de abrirse, ya no: la ventana dura un día.
    assert report_schedules.pendientes(datetime(2026, 9, 15, 21, 0, tzinfo=UTC)) == []


def test_cambiar_la_programacion_no_reenvia_lo_ya_enviado(tmp_db: Any) -> None:
    """Mover el informe de día es cambiar de día, no pedir dos esta semana."""
    db_mod, _ = tmp_db
    from db.repositories import report_schedules

    _owner, org_id = _organizacion(db_mod, "mover@example.test")
    fila = report_schedules.guardar(
        org_id, activo=True, dia_semana=0, hora_utc=7, destinatarios=None
    )
    report_schedules.marcar_envio(int(fila["id"]), estado="enviado:1/1")

    report_schedules.guardar(org_id, activo=True, dia_semana=0, hora_utc=8, destinatarios=None)

    despues = report_schedules.get(org_id)
    assert despues is not None and despues["ultimo_envio_at"] is not None
    assert report_schedules.pendientes(AHORA.replace(hour=9)) == []


# ── 5. El adjunto llega de verdad ───────────────────────────────────────────


def test_el_correo_sale_con_el_pdf_adjunto(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    from db.repositories import report_schedules
    from observability.mailer import ResultadoEnvio
    from scheduler.jobs.informes_programados import ejecutar

    user_id, org_id = _organizacion(db_mod, "adjunto@example.test")
    _pursuit(db_mod, org_id, user_id, id_externo="ADJ-1")
    report_schedules.guardar(
        org_id, activo=True, dia_semana=0, hora_utc=7, destinatarios=["a@b.test"]
    )

    with patch(
        "observability.mailer.enviar", return_value=ResultadoEnvio(ok=True, backend="console")
    ) as enviar:
        ejecutar(AHORA)

    mensaje = enviar.call_args.args[0]
    assert len(mensaje.adjuntos) == 1
    adjunto = mensaje.adjuntos[0]
    assert adjunto.filename.endswith(".pdf")
    assert adjunto.contenido.startswith(b"%PDF")
    assert adjunto.content_type == "application/pdf"


def test_el_correo_lleva_enlace_de_baja_con_el_origen_real(tmp_db: Any) -> None:
    """Regresión: el enlace de baja salía vacío y el correo sin `List-Unsubscribe`.

    La primera versión leía ``getattr(settings, "FRONTEND_URL", "")``, y esa
    variable **no** está declarada en ``config/settings.py`` (existe en
    ``render.yaml`` y nada más), así que el `getattr` siempre devolvía "" y
    ``url_de_baja_alertas`` devolvía ``None`` en producción. El correo salía
    sin la cabecera RFC 8058 que `docs/informes-programados.md` promete, y
    nada fallaba: el fallo era silencioso por construcción.

    El origen se deduce ahora con ``services.app_urls.frontend_base_url()``,
    que es de donde ya lo sacan los digests de watchlist.
    """
    db_mod, _ = tmp_db
    from db.repositories import report_schedules
    from observability.mailer import ResultadoEnvio
    from scheduler.jobs.informes_programados import ejecutar

    user_id, org_id = _organizacion(db_mod, "baja@example.test")
    _pursuit(db_mod, org_id, user_id, id_externo="BAJA-1")
    report_schedules.guardar(org_id, activo=True, dia_semana=0, hora_utc=7, destinatarios=None)

    with (
        patch("services.app_urls.frontend_base_url", return_value="https://app.example.test"),
        patch("services.email_digest.token_de_baja", return_value="firma"),
        patch(
            "observability.mailer.enviar", return_value=ResultadoEnvio(ok=True, backend="console")
        ) as enviar,
    ):
        ejecutar(AHORA)

    mensaje = enviar.call_args.args[0]
    assert mensaje.unsubscribe_url is not None
    assert mensaje.unsubscribe_url.startswith("https://app.example.test/")
    # El mismo enlace en el pie del HTML, no sólo en la cabecera: quien lo
    # busca con el ratón tiene que encontrarlo. Se compara escapado porque en
    # el HTML el `&` del query string va como `&amp;`, que es lo correcto.
    assert escape(mensaje.unsubscribe_url, quote=False) in mensaje.html


def test_el_mime_pone_el_adjunto_fuera_de_las_alternativas() -> None:
    """La trampa clásica del `multipart`.

    Con texto, HTML y PDF como tres hermanos de un `mixed`, el cliente enseña
    el texto plano **y** el HTML uno detrás de otro en vez de elegir. Las
    alternativas van juntas en su propio contenedor, y el adjunto al lado.
    """
    from config import settings
    from observability.mailer import Adjunto, Mensaje, _construir_mime, _normalizar

    prep = _normalizar(
        Mensaje(
            to="a@b.test",
            subject="s",
            html="<p>hola</p>",
            adjuntos=[Adjunto("informe.pdf", b"%PDF-1.4")],
        ),
        settings,
    )
    msg = _construir_mime(prep)

    assert msg.get_content_type() == "multipart/mixed"
    tipos = [p.get_content_type() for p in msg.get_payload()]
    assert tipos == ["multipart/alternative", "application/pdf"]
    alternativas = [p.get_content_type() for p in msg.get_payload()[0].get_payload()]
    assert alternativas == ["text/plain", "text/html"]


def test_sin_adjuntos_el_correo_conserva_la_forma_de_siempre() -> None:
    """Cambiar la forma de todos los correos por una función que casi ninguno
    usa sería riesgo gratis."""
    from config import settings
    from observability.mailer import Mensaje, _construir_mime, _normalizar

    prep = _normalizar(Mensaje(to="a@b.test", subject="s", html="<p>hola</p>"), settings)
    assert _construir_mime(prep).get_content_type() == "multipart/alternative"


def test_un_adjunto_vacio_no_viaja() -> None:
    """Por SMTP saldría como una parte vacía; por HTTP lo rechaza el ESP con un
    422 que tumbaría el correo entero por algo que no aporta nada."""
    from config import settings
    from observability.mailer import Adjunto, Mensaje, _normalizar

    prep = _normalizar(
        Mensaje(
            to="a@b.test",
            subject="s",
            text="hola",
            adjuntos=[Adjunto("vacio.pdf", b""), Adjunto("  ", b"%PDF")],
        ),
        settings,
    )
    assert prep.adjuntos == []


# ── 6. El paso está en la secuencia canónica ────────────────────────────────


def test_el_paso_esta_declarado_y_es_advisory() -> None:
    from scheduler.pipeline_runs import CANONICAL_STEPS, STEP_TIER

    assert "informes_programados" in CANONICAL_STEPS
    assert STEP_TIER["informes_programados"] == "advisory"
    # Después de `digests`: los dos son correo, y el informe quiere los datos
    # de la pasada ya cerrados.
    assert CANONICAL_STEPS.index("informes_programados") > CANONICAL_STEPS.index("digests")


def test_el_paso_no_lanza_aunque_el_envio_falle(tmp_db: Any) -> None:
    """Advisory de verdad: un ESP caído no puede tumbar la pasada de ingesta."""
    db_mod, _ = tmp_db
    from db.repositories import report_schedules
    from scheduler.pipeline_runs import _run_informes_programados

    user_id, org_id = _organizacion(db_mod, "esp-caido@example.test")
    _pursuit(db_mod, org_id, user_id, id_externo="ESP-1")
    report_schedules.guardar(
        org_id, activo=True, dia_semana=0, hora_utc=7, destinatarios=["a@b.test"]
    )

    with patch("observability.mailer.enviar", side_effect=RuntimeError("ESP caído")):
        assert _run_informes_programados() in {"ok", "skipped"}


def test_el_opt_out_es_un_tipo_del_catalogo_de_preferencias() -> None:
    """Si no estuviera en `TIPOS`, la pantalla de Ajustes no pintaría el
    interruptor y el opt-out existiría sólo en la base."""
    from db.repositories.notification_preferences import TIPOS
    from scheduler.jobs.informes_programados import TIPO_AVISO

    assert TIPO_AVISO in {clave for clave, _ in TIPOS}


# ── Cálculo de la ventana ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("ahora", "dia", "hora", "esperado"),
    [
        # Lunes 07:30, programado lunes 07:00 → la ventana de hoy.
        (AHORA, 0, 7, datetime(2026, 9, 14, 7, tzinfo=UTC)),
        # Lunes 07:30, programado lunes 20:00 → todavía no; la de la semana
        # pasada, que ya está sellada.
        (AHORA, 0, 20, datetime(2026, 9, 7, 20, tzinfo=UTC)),
        # Lunes, programado martes → la del martes pasado.
        (AHORA, 1, 7, datetime(2026, 9, 8, 7, tzinfo=UTC)),
    ],
)
def test_inicio_de_ventana(ahora: datetime, dia: int, hora: int, esperado: datetime) -> None:
    from db.repositories.report_schedules import inicio_de_ventana

    assert inicio_de_ventana(ahora, dia_semana=dia, hora_utc=hora) == esperado


# ── Las dos rutas HTTP, que no tenían ningún test ───────────────────────────
#
# Y por eso T6 se entregó con las dos devolviendo **500** en cuanto existía una
# fila: `ReportScheduleOut(**fila)` chocaba con el `extra="forbid"` del DTO
# porque el repositorio devuelve además `id`, `created_at` y `updated_at`. El
# `GET` sólo funcionaba por el camino de los valores por defecto sintéticos
# —que no tiene columnas de más— y el `PUT` fallaba siempre. Los 24 tests de
# arriba ejercitan el servicio y el job, nunca la ruta; el contrato HTTP era el
# único trozo sin cubrir y era el único roto.


def _ctx_http(user_id: int, email: str) -> dict[str, Any]:
    from shared.identity import user_key_from_email

    return {
        "user_id": user_id,
        "email": email,
        "display_name": "Dirección",
        "is_admin": False,
        "auth_method": "session",
        "authenticated_at": datetime.now(UTC).isoformat(),
        "user_key": user_key_from_email(email, user_id),
    }


@pytest.fixture
def cliente_direccion(client, api_db, tmp_db):
    """`client` autenticado como owner de una organización recién creada."""
    from api.app import app
    from api.routes.dual_auth import require_any_auth

    db_mod, _ = tmp_db
    user_id, org_id = _organizacion(db_mod, "ruta-informe@example.test")
    app.dependency_overrides[require_any_auth] = lambda: _ctx_http(
        user_id, "ruta-informe@example.test"
    )
    try:
        yield client, org_id
    finally:
        app.dependency_overrides.pop(require_any_auth, None)


def test_get_sin_programacion_devuelve_los_valores_por_defecto(cliente_direccion) -> None:
    cliente, org_id = cliente_direccion
    with cliente as c:
        resp = c.get(f"/api/v1/organizations/{org_id}/report-schedule")

    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    assert cuerpo["activo"] is False
    assert cuerpo["dia_semana"] == 0
    assert cuerpo["hora_utc"] == 7
    assert cuerpo["organization_id"] == org_id


def test_put_guarda_y_el_get_siguiente_lo_devuelve(cliente_direccion) -> None:
    """El ciclo completo de la tarjeta: guardar y volver a entrar.

    Es el que fallaba: el `PUT` respondía 500 y, aunque hubiera guardado, el
    `GET` posterior también, porque ya existía la fila.
    """
    cliente, org_id = cliente_direccion
    with cliente as c:
        guardado = c.put(
            f"/api/v1/organizations/{org_id}/report-schedule",
            json={
                "activo": True,
                "dia_semana": 2,
                "hora_utc": 9,
                # `example.com` y no `.test`: `EmailStr` rechaza los TLD
                # reservados, que es justo lo que queremos de un campo que
                # acaba en la cabecera `To:` de un correo real.
                "destinatarios": ["comite@example.com"],
            },
        )
        assert guardado.status_code == 200, guardado.text
        assert guardado.json()["activo"] is True

        releido = c.get(f"/api/v1/organizations/{org_id}/report-schedule")

    assert releido.status_code == 200, releido.text
    cuerpo = releido.json()
    assert cuerpo["dia_semana"] == 2
    assert cuerpo["hora_utc"] == 9
    assert cuerpo["destinatarios"] == ["comite@example.com"]


def test_la_respuesta_no_filtra_las_columnas_internas(cliente_direccion) -> None:
    """`id`, `created_at` y `updated_at` son del repositorio, no del contrato."""
    cliente, org_id = cliente_direccion
    with cliente as c:
        c.put(
            f"/api/v1/organizations/{org_id}/report-schedule",
            json={"activo": True, "dia_semana": 0, "hora_utc": 7, "destinatarios": None},
        )
        cuerpo = c.get(f"/api/v1/organizations/{org_id}/report-schedule").json()

    assert set(cuerpo) == set(ReportScheduleOut.model_fields)


def test_un_campo_inventado_en_el_put_sigue_siendo_un_422(cliente_direccion) -> None:
    """El `extra="forbid"` del DTO de entrada no se toca al arreglar la salida.

    Es la razón de proyectar en la ruta en vez de relajar el modelo: quien
    manda `dia_semana_v2` tiene que enterarse, no que se lo ignoren.
    """
    cliente, org_id = cliente_direccion
    with cliente as c:
        resp = c.put(
            f"/api/v1/organizations/{org_id}/report-schedule",
            json={"activo": True, "dia_semana": 0, "hora_utc": 7, "inventado": 1},
        )

    assert resp.status_code == 422, resp.text


# ── El enlace de baja: apuntaba a la funcionalidad equivocada ────────────────


def test_el_enlace_de_baja_apaga_el_informe_y_no_la_watchlist(tmp_db: Any) -> None:
    """Regresión de un fallo que destruía datos de otra funcionalidad.

    El informe salía con el enlace de baja de los **digests**, que llama a
    `deactivate_all_for_user` y pausa **todas** las reglas de watchlist de esa
    persona, sin tocar `notification_preferences`. O sea que quien pulsaba
    «dejar de recibir este informe» —o cuyo Gmail lo pulsaba por él, que el
    `List-Unsubscribe` de RFC 8058 es un POST automático— perdía todas sus
    alertas de licitaciones **y seguía recibiendo el informe**, porque el
    opt-out del informe vive en otro sitio.

    La documentación prometía «el mismo mecanismo que los digests», que era
    exactamente el bug: *era* el mecanismo del digest, apuntando a la
    suscripción equivocada.
    """
    db_mod, _ = tmp_db
    from db.repositories import report_schedules
    from observability.mailer import ResultadoEnvio
    from scheduler.jobs.informes_programados import ejecutar

    user_id, org_id = _organizacion(db_mod, "baja-informe@example.test")
    _pursuit(db_mod, org_id, user_id, id_externo="BAJA-INF-1")
    report_schedules.guardar(org_id, activo=True, dia_semana=0, hora_utc=7, destinatarios=None)

    with (
        patch("services.app_urls.frontend_base_url", return_value="https://app.example.test"),
        patch(
            "observability.mailer.enviar", return_value=ResultadoEnvio(ok=True, backend="console")
        ) as enviar,
    ):
        ejecutar(AHORA)

    url = enviar.call_args.args[0].unsubscribe_url
    assert url is not None
    assert "/api/v1/notifications/baja" in url, url
    assert "tipo=informe_semanal" in url, url
    # Y sobre todo: **no** la baja de la watchlist.
    assert "watchlist" not in url, url


def test_la_baja_pone_el_informe_en_off_y_deja_la_watchlist_en_paz(tmp_db: Any) -> None:
    """El camino completo, desde el enlace del correo hasta la preferencia."""
    db_mod, _ = tmp_db
    from db.repositories import notification_preferences as prefs
    from services.email_digest import token_de_baja_de_tipo

    user_id, _org_id = _organizacion(db_mod, "baja-camino@example.test")
    token = token_de_baja_de_tipo(user_id, "informe_semanal")
    assert token is not None

    from api.routes.notifications import _apagar_por_enlace

    valida, _destino = _apagar_por_enlace(user_id, "informe_semanal", token)

    assert valida
    assert prefs.resolver(user_id, tipo="informe_semanal", canal="email") == "off"
    # Otra notificación del mismo usuario no se ha tocado.
    assert prefs.resolver(user_id, tipo="watchlist_match", canal="email") != "off"


def test_un_token_de_otro_tipo_no_sirve(tmp_db: Any) -> None:
    """La firma incluye el tipo: si no, una baja valdría para todas."""
    db_mod, _ = tmp_db
    from api.routes.notifications import _apagar_por_enlace
    from services.email_digest import token_de_baja_de_tipo

    user_id, _org_id = _organizacion(db_mod, "baja-cruzada@example.test")
    token = token_de_baja_de_tipo(user_id, "watchlist_match")
    assert token is not None

    valida, _ = _apagar_por_enlace(user_id, "informe_semanal", token)

    assert not valida


def test_un_tipo_que_no_existe_no_escribe_nada(tmp_db: Any) -> None:
    """El catálogo se comprueba antes de firmar nada contra la base."""
    db_mod, _ = tmp_db
    from api.routes.notifications import _apagar_por_enlace
    from services.email_digest import token_de_baja_de_tipo

    user_id, _org_id = _organizacion(db_mod, "baja-inventada@example.test")
    token = token_de_baja_de_tipo(user_id, "tipo_inventado") or "x.y"

    valida, _ = _apagar_por_enlace(user_id, "tipo_inventado", token)

    assert not valida


def test_un_fallo_del_proveedor_no_sella_la_ventana(tmp_db: Any) -> None:
    """Regresión: una caída del ESP dejaba a la organización sin informe la semana entera.

    El mailer **no lanza** ante un fallo del proveedor: devuelve
    `ResultadoEnvio(ok=False)`. El job llegaba igual a `marcar_envio` y
    estampaba `ultimo_envio_at`, así que `pendientes()` dejaba de devolver la
    fila y la pasada siguiente no reintentaba — lo contrario de lo que promete
    la ventana de un día. El test que había patcheaba `enviar` con un
    `side_effect=RuntimeError`, que cae por el `except` exterior y nunca llega
    a `marcar_envio`: cubría el único modo de fallo que sí se recuperaba.
    """
    db_mod, _ = tmp_db
    from db.repositories import report_schedules
    from observability.mailer import ResultadoEnvio
    from scheduler.jobs.informes_programados import ejecutar

    user_id, org_id = _organizacion(db_mod, "esp-caido@example.test")
    _pursuit(db_mod, org_id, user_id, id_externo="ESP-1")
    report_schedules.guardar(org_id, activo=True, dia_semana=0, hora_utc=7, destinatarios=None)

    with patch(
        "observability.mailer.enviar",
        return_value=ResultadoEnvio(ok=False, backend="resend", motivo="502"),
    ):
        resumen = ejecutar(AHORA)

    assert resumen.enviados == 0
    assert resumen.fallidos == 1
    fila = report_schedules.get(org_id)
    assert fila is not None
    assert fila["ultimo_envio_at"] is None, "la ventana quedó sellada: no habrá reintento"

    # Y la pasada siguiente sí lo recupera.
    with patch(
        "observability.mailer.enviar", return_value=ResultadoEnvio(ok=True, backend="console")
    ) as enviar:
        segunda = ejecutar(AHORA + timedelta(hours=4))

    assert segunda.enviados == 1
    assert enviar.called


def test_el_nombre_de_la_organizacion_no_se_interpreta_como_marcado(tmp_db: Any) -> None:
    """Regresión de seguridad: `Paragraph` de reportlab **no** recibe texto plano.

    Interpreta mini-XML, incluido `<img src=...>`, que abre el recurso: un
    fichero local o una URL. Y el título del PDF lleva dentro el nombre de la
    organización, que es texto libre del cliente (`SafeStr` sólo rechaza el
    byte NUL).

    Sin escapar, `Acme <b>x` hacía reventar la generación —y el adjunto
    desaparecía en silencio, porque el job captura ese fallo— y
    `Acme <img src="http://169.254.169.254/..."/>` convertía al scheduler en un
    lector de recursos internos cuyo resultado acababa incrustado en un PDF y
    enviado por correo. `render_html` ya escapaba; era el PDF el que no.
    """
    db_mod, _ = tmp_db
    from services.informes import construir, render_pdf

    user_id, org_id = _organizacion(db_mod, "marcado@example.test")
    _pursuit(db_mod, org_id, user_id, id_externo="MARCA-1")

    for nombre in ("Acme <b>negrita", 'Acme <img src="/etc/passwd"/>'):
        informe = construir(org_id, organizacion=nombre, ahora=AHORA)
        pdf = render_pdf(informe)
        assert pdf.startswith(b"%PDF"), nombre
        assert len(pdf) > 500, nombre

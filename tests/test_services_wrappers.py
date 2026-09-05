"""Tests para la capa de servicios wrapper: users, saved_filters, dlq, audit.

Todos los tests usan ``tmp_db`` (BD real con migraciones) — sin mocks,
porque los servicios son wrappers directos sobre ``db.*``.
"""

from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# services/users.py
# ---------------------------------------------------------------------------


def test_usuarios_get_or_create_idempotente(tmp_db):
    """Dos llamadas con el mismo (provider, sub) devuelven el mismo id."""
    from services.users import get_or_create_oauth_user

    uid1 = get_or_create_oauth_user(
        email="alice@example.com",
        oauth_provider="google",
        oauth_sub="google-sub-001",
        display_name="Alice",
    )
    uid2 = get_or_create_oauth_user(
        email="alice@example.com",
        oauth_provider="google",
        oauth_sub="google-sub-001",
        display_name="Alice",
    )
    assert isinstance(uid1, int)
    assert uid1 == uid2


def test_usuarios_get_or_create_distintos_subs(tmp_db):
    """Dos subs distintos crean dos usuarios distintos."""
    from services.users import get_or_create_oauth_user

    uid_a = get_or_create_oauth_user(
        email="user_a@example.com",
        oauth_provider="google",
        oauth_sub="sub-aaa",
    )
    uid_b = get_or_create_oauth_user(
        email="user_b@example.com",
        oauth_provider="google",
        oauth_sub="sub-bbb",
    )
    assert uid_a != uid_b


def test_usuarios_set_admin_is_admin_roundtrip(tmp_db):
    """set_admin(True) luego is_admin devuelve True; set_admin(False) → False."""
    from services.users import get_or_create_oauth_user, is_admin, set_admin

    uid = get_or_create_oauth_user(
        email="bob@example.com",
        oauth_provider="github",
        oauth_sub="gh-bob-42",
    )
    # Por defecto no es admin
    assert is_admin(uid) is False

    set_admin(uid, True)
    assert is_admin(uid) is True

    set_admin(uid, False)
    assert is_admin(uid) is False


def test_usuarios_list_users_devuelve_lista(tmp_db):
    """list_users devuelve lista; incluye el usuario recién creado."""
    from services.users import get_or_create_oauth_user, list_users

    uid = get_or_create_oauth_user(
        email="carol@example.com",
        oauth_provider="microsoft",
        oauth_sub="ms-carol-99",
        display_name="Carol",
    )
    usuarios = list_users()
    assert isinstance(usuarios, list)
    ids = [u["id"] for u in usuarios]
    assert uid in ids


def test_usuarios_list_users_respeta_limit(tmp_db):
    """list_users con limit=1 devuelve como máximo 1 elemento."""
    from services.users import get_or_create_oauth_user, list_users

    for i in range(3):
        get_or_create_oauth_user(
            email=f"limit_user_{i}@example.com",
            oauth_provider="github",
            oauth_sub=f"gh-limit-{i}",
        )
    resultado = list_users(limit=1)
    assert len(resultado) <= 1


def test_usuarios_deactivate_reactivate(tmp_db):
    """deactivate → usuario no aparece en list_users; reactivate → reaparece."""
    from services.users import (
        deactivate_user,
        get_or_create_oauth_user,
        list_users,
        reactivate_user,
    )

    uid = get_or_create_oauth_user(
        email="dave@example.com",
        oauth_provider="google",
        oauth_sub="google-dave-7",
    )

    # Activo por defecto
    ids_activos = [u["id"] for u in list_users()]
    assert uid in ids_activos

    deactivate_user(uid)
    ids_tras_baja = [u["id"] for u in list_users()]
    assert uid not in ids_tras_baja

    reactivate_user(uid)
    ids_reactivados = [u["id"] for u in list_users()]
    assert uid in ids_reactivados


def test_usuarios_deactivate_idempotente(tmp_db):
    """Llamar deactivate dos veces no lanza error."""
    from services.users import deactivate_user, get_or_create_oauth_user

    uid = get_or_create_oauth_user(
        email="eve@example.com",
        oauth_provider="github",
        oauth_sub="gh-eve-2",
    )
    deactivate_user(uid)
    deactivate_user(uid)  # segunda llamada — no debe explotar


def test_usuarios_log_access_no_explota(tmp_db):
    """log_access registra sin lanzar excepciones (con y sin user_id)."""
    from services.users import get_or_create_oauth_user, log_access

    uid = get_or_create_oauth_user(
        email="frank@example.com",
        oauth_provider="google",
        oauth_sub="google-frank-5",
    )
    log_access(auth_method="oauth", user_id=uid, email="frank@example.com")
    log_access(auth_method="api_key")  # sin user_id — también válido


def test_usuarios_lockout_ciclo_completo(tmp_db):
    """record_failed_login ×5 → is_login_locked_out True → clear → desbloqueado."""
    from services.users import clear_login_attempts, is_login_locked_out, record_failed_login

    client = "test-client-lockout-001"

    # Antes de cualquier intento no hay bloqueo
    bloqueado, _ = is_login_locked_out(client, max_attempts=5)
    assert bloqueado is False

    # Registrar 5 intentos fallidos
    conteo = 0
    for _ in range(5):
        conteo = record_failed_login(client)
    assert conteo == 5

    # Ahora debe estar bloqueado
    bloqueado, segundos = is_login_locked_out(client, max_attempts=5)
    assert bloqueado is True
    assert segundos > 0.0

    # Limpiar intentos → desbloqueado
    clear_login_attempts(client)
    bloqueado_tras_clear, _ = is_login_locked_out(client, max_attempts=5)
    assert bloqueado_tras_clear is False


def test_usuarios_lockout_umbral_exacto(tmp_db):
    """Con 4 intentos (< 5) no hay bloqueo; al 5º sí."""
    from services.users import is_login_locked_out, record_failed_login

    client = "test-client-umbral-002"

    for _ in range(4):
        record_failed_login(client)

    bloqueado_4, _ = is_login_locked_out(client, max_attempts=5)
    assert bloqueado_4 is False

    record_failed_login(client)
    bloqueado_5, _ = is_login_locked_out(client, max_attempts=5)
    assert bloqueado_5 is True


# ---------------------------------------------------------------------------
# services/saved_filters.py
#
# La fachada dejó de aceptar ``organization_id`` opcional (S4.3, 2026-09): con
# default ``None`` el CRUD de abajo caía a una query sin filtro de
# organización, y una fachada que lo omitiera reintroduciría ese fail-open.
# Los tests pasan por tanto una organización real (la FK de v64 rechaza un id
# inventado) y el de aislamiento cubre las dos dimensiones que existen ahora:
# dos usuarios de la misma organización, y dos organizaciones distintas.
# ---------------------------------------------------------------------------


def _organizacion_de_pruebas(nombre: str) -> int:
    """Crea una organización real (con su owner) y devuelve su id.

    ``saved_filters.organization_id`` es FK contra ``organizations``, así que
    un id inventado revienta el INSERT con ``ForeignKeyViolation`` antes de
    llegar a comprobar nada de lo que estos tests miran.
    """
    from db.repositories.organizations import OrganizationRepository
    from db.users import create_user

    owner = create_user(
        email=f"{nombre}@example.test",
        password_hash="test-hash",  # pragma: allowlist secret -- literal de test
        display_name=nombre,
    )
    return int(OrganizationRepository().create_organization(nombre, owner)["id"])


def test_filtros_save_list_roundtrip(tmp_db):
    """Guardar un filtro y listarlo devuelve la entrada esperada."""
    from services.saved_filters import list_saved_filters, save_filter

    organizacion = _organizacion_de_pruebas("filtros-roundtrip")
    user_key = "user-filtros-001"
    payload = json.dumps({"q": "SAP", "estados": ["PUB"]})

    save_filter(user_key, "Mi búsqueda SAP", payload, organizacion)

    filtros = list_saved_filters(user_key, organizacion)
    assert isinstance(filtros, list)
    assert len(filtros) == 1
    assert filtros[0]["name"] == "Mi búsqueda SAP"
    assert filtros[0]["filters_json"] == payload
    assert filtros[0]["organization_id"] == organizacion


def test_filtros_save_multiples(tmp_db):
    """Varios filtros del mismo usuario se listan todos."""
    from services.saved_filters import list_saved_filters, save_filter

    organizacion = _organizacion_de_pruebas("filtros-multiples")
    user_key = "user-filtros-002"
    nombres = ["Filtro A", "Filtro B", "Filtro C"]
    for nombre in nombres:
        save_filter(user_key, nombre, json.dumps({"q": nombre}), organizacion)

    filtros = list_saved_filters(user_key, organizacion)
    assert len(filtros) == 3
    nombres_guardados = {f["name"] for f in filtros}
    assert nombres_guardados == set(nombres)


def test_filtros_save_upsert_sobreescribe(tmp_db):
    """Guardar con el mismo (user_key, name) sobreescribe el payload."""
    from services.saved_filters import list_saved_filters, save_filter

    organizacion = _organizacion_de_pruebas("filtros-upsert")
    user_key = "user-filtros-003"
    save_filter(user_key, "Búsqueda única", json.dumps({"q": "inicial"}), organizacion)
    save_filter(user_key, "Búsqueda única", json.dumps({"q": "actualizado"}), organizacion)

    filtros = list_saved_filters(user_key, organizacion)
    assert len(filtros) == 1
    assert json.loads(filtros[0]["filters_json"])["q"] == "actualizado"


def test_filtros_delete_roundtrip(tmp_db):
    """Guardar y luego borrar → lista vacía."""
    from services.saved_filters import delete_saved_filter, list_saved_filters, save_filter

    organizacion = _organizacion_de_pruebas("filtros-delete")
    user_key = "user-filtros-004"
    save_filter(user_key, "Para borrar", json.dumps({"q": "x"}), organizacion)

    filtros = list_saved_filters(user_key, organizacion)
    assert len(filtros) == 1
    fid = filtros[0]["id"]

    delete_saved_filter(fid, user_key, organizacion)

    filtros_tras_borrado = list_saved_filters(user_key, organizacion)
    assert filtros_tras_borrado == []


def test_filtros_aislamiento_por_usuario(tmp_db):
    """Aislamiento en sus dos dimensiones: entre usuarios y entre organizaciones.

    La primera mitad es el guardrail de siempre (dos usuarios no se ven los
    filtros). La segunda es la que aparece con la tenencia obligatoria: el
    MISMO ``user_key`` mirando desde dos organizaciones ve dos listas
    distintas, no la unión. Fusionarlas era exactamente el bug fail-open —
    omitir ``organization_id`` devolvía todo lo del ``user_key``, cruzando
    organizaciones.
    """
    from services.saved_filters import list_saved_filters, save_filter

    equipo = _organizacion_de_pruebas("filtros-equipo")
    otro_equipo = _organizacion_de_pruebas("filtros-otro-equipo")

    save_filter("user-A", "Solo A", json.dumps({"q": "A"}), equipo)
    save_filter("user-B", "Solo B", json.dumps({"q": "B"}), equipo)
    save_filter("user-A", "A en el otro equipo", json.dumps({"q": "A2"}), otro_equipo)

    filtros_a = list_saved_filters("user-A", equipo)
    filtros_b = list_saved_filters("user-B", equipo)
    filtros_a_otro = list_saved_filters("user-A", otro_equipo)

    assert [f["name"] for f in filtros_a] == ["Solo A"]
    assert [f["name"] for f in filtros_b] == ["Solo B"]
    assert [f["name"] for f in filtros_a_otro] == ["A en el otro equipo"]


def test_filtros_usuario_sin_filtros_devuelve_lista_vacia(tmp_db):
    """Un usuario que nunca guardó filtros recibe lista vacía."""
    from services.saved_filters import list_saved_filters

    organizacion = _organizacion_de_pruebas("filtros-vacios")
    resultado = list_saved_filters("usuario-inexistente-xyz", organizacion)
    assert resultado == []


# ---------------------------------------------------------------------------
# services/dlq.py
# ---------------------------------------------------------------------------


def test_dlq_record_and_list_unresolved(tmp_db):
    """record_failure (via db.dlq) + list_unresolved devuelve la entrada."""
    from db.dlq import record_failure
    from services.dlq import list_unresolved

    record_failure("run-001", "fuente_test", ValueError("fallo simulado"), scope="scope-A")

    entradas = list_unresolved()
    assert isinstance(entradas, list)
    assert len(entradas) >= 1
    fuentes = [e["fuente"] for e in entradas]
    assert "fuente_test" in fuentes


def test_dlq_mark_resolved(tmp_db):
    """record_failure → mark_resolved → ya no aparece en list_unresolved."""
    from db.dlq import record_failure
    from services.dlq import list_unresolved, mark_resolved

    record_failure("run-002", "fuente_resolve", RuntimeError("err"), scope="scope-B")

    antes = list_unresolved()
    fid = next(e["id"] for e in antes if e["fuente"] == "fuente_resolve")

    mark_resolved(fid)

    despues = list_unresolved()
    ids_despues = [e["id"] for e in despues]
    assert fid not in ids_despues


def test_dlq_mark_matching_resolved(tmp_db):
    """mark_matching_resolved con scope específico resuelve esos fallos.

    La SQL usa COALESCE(scope, '') = COALESCE(%s, ''), por lo que pasar scope=None
    solo resuelve filas con scope NULL. Para resolver con scope concreto hay que
    pasarlo explícitamente.
    """
    from db.dlq import record_failure
    from services.dlq import list_unresolved, mark_matching_resolved

    # Dos fallos con scope NULL → ambos resueltos por mark_matching_resolved(fuente)
    record_failure("run-003", "fuente_batch_null", Exception("err1"), scope=None)
    record_failure("run-003b", "fuente_batch_null", Exception("err2"), scope=None)

    antes = [e for e in list_unresolved() if e["fuente"] == "fuente_batch_null"]
    assert len(antes) >= 1  # al menos el primero (el segundo puede hacer upsert)

    # Con scope=None resuelve las filas cuyo scope es NULL
    n = mark_matching_resolved("fuente_batch_null", None)
    assert n >= 1

    despues = [e for e in list_unresolved() if e["fuente"] == "fuente_batch_null"]
    assert despues == []


def test_dlq_unresolved_summary(tmp_db):
    """unresolved_summary devuelve agrupación por fuente."""
    from db.dlq import record_failure
    from services.dlq import unresolved_summary

    record_failure("run-004", "fuente_summary", OSError("io err"))

    resumen = unresolved_summary()
    assert isinstance(resumen, list)
    fuentes = [r["fuente"] for r in resumen]
    assert "fuente_summary" in fuentes


def test_dlq_lista_vacia_sin_datos(tmp_db):
    """list_unresolved en BD vacía devuelve lista vacía."""
    from services.dlq import list_unresolved

    resultado = list_unresolved()
    assert isinstance(resultado, list)
    assert resultado == []


def test_dlq_incrementa_retry_count(tmp_db):
    """Dos record_failure con mismo (fuente, scope) incrementan retry_count."""
    from db.dlq import record_failure
    from services.dlq import list_unresolved

    record_failure("run-005", "fuente_retry", ValueError("primer intento"), scope="scope-retry")
    record_failure("run-005", "fuente_retry", ValueError("segundo intento"), scope="scope-retry")

    entradas = [e for e in list_unresolved() if e["fuente"] == "fuente_retry"]
    assert len(entradas) == 1
    assert entradas[0]["retry_count"] >= 1


# ---------------------------------------------------------------------------
# services/audit.py
# ---------------------------------------------------------------------------


def test_auditoria_log_action_y_list_recent(tmp_db):
    """log_action + list_recent devuelve la acción registrada."""
    from services.audit import list_recent, log_action

    log_action("user-hash-001", "sess-abc", "export_excel", "detalle de prueba")

    entradas = list_recent()
    assert isinstance(entradas, list)
    acciones = [e["action"] for e in entradas]
    assert "export_excel" in acciones


def test_auditoria_list_recent_filtro_user_key(tmp_db):
    """list_recent con user_key filtra correctamente."""
    from services.audit import list_recent, log_action

    log_action("user-AAA", "sess-1", "login", "")
    log_action("user-BBB", "sess-2", "logout", "")

    entradas_aaa = list_recent(user_key="user-AAA")
    assert all(e["user_key"] == "user-AAA" for e in entradas_aaa)
    assert any(e["action"] == "login" for e in entradas_aaa)


def test_auditoria_list_recent_filtro_action(tmp_db):
    """list_recent con action filtra solo ese tipo de acción."""
    from services.audit import list_recent, log_action

    log_action("user-CCC", "sess-3", "watchlist_add", "")
    log_action("user-CCC", "sess-3", "export_pdf", "")

    watchlist_entries = list_recent(action="watchlist_add")
    assert all(e["action"] == "watchlist_add" for e in watchlist_entries)


def test_auditoria_list_recent_respeta_limit(tmp_db):
    """list_recent con limit=1 no devuelve más de 1 entrada."""
    from services.audit import list_recent, log_action

    for i in range(5):
        log_action(f"user-limit-{i}", "sess-x", "login", "")

    resultado = list_recent(limit=1)
    assert len(resultado) <= 1


def test_auditoria_multiples_acciones_misma_sesion(tmp_db):
    """Múltiples acciones de un mismo usuario se registran todas."""
    from services.audit import list_recent, log_action

    acciones = ["login", "watchlist_add", "export_excel", "logout"]
    for accion in acciones:
        log_action("user-DDD", "sess-DDD", accion, f"detalle {accion}")

    entradas = list_recent(user_key="user-DDD")
    acciones_registradas = {e["action"] for e in entradas}
    assert acciones_registradas == set(acciones)


def test_auditoria_bd_vacia_devuelve_lista(tmp_db):
    """list_recent en BD vacía devuelve lista (vacía o no falla)."""
    from services.audit import list_recent

    resultado = list_recent()
    assert isinstance(resultado, list)


def test_auditoria_detail_persiste(tmp_db):
    """El campo detail se persiste y recupera correctamente."""
    from services.audit import list_recent, log_action

    detalle_esperado = "exportado 42 filas en formato xlsx"
    log_action("user-EEE", "sess-EEE", "export_excel", detalle_esperado)

    entradas = list_recent(user_key="user-EEE", action="export_excel")
    assert len(entradas) >= 1
    assert entradas[0]["detail"] == detalle_esperado

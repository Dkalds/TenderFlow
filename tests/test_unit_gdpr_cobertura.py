"""El borrado y el export RGPD cubren ``follows`` y las tablas con ``user_id`` propio.

Cada una tenía su ``borrar_de_usuario`` documentado como «lo llama el borrado
GDPR» y nadie lo llamaba: el derecho de supresión dejaba esos datos vivos.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

_COLABORADORES = (
    "services.gdpr._watchlist_repo",
    "services.gdpr.delete_user_profile",
    "services.gdpr.radar_dismissals",
    "services.gdpr._feedback_repo",
    "services.gdpr._pursuit_repo",
    "services.gdpr._pursuit_comment_repo",
    "services.gdpr._pursuit_task_repo",
    "services.gdpr.delete_totp",
    "services.gdpr._organization_repo",
    "services.gdpr._api_key_repo",
    "services.watchlist_rules.delete_all_for_user",
    "db.saved_filters.delete_all_for_user",
    "services.notifications.delete_all_alerts",
    "services.notifications.delete_email_prefs",
)


def _anonimizar(**kwargs: object) -> dict[str, MagicMock]:
    from contextlib import ExitStack

    from services.gdpr import anonymize_user_data

    with ExitStack() as pila:
        for ruta in _COLABORADORES:
            pila.enter_context(patch(ruta))
        follows = pila.enter_context(patch("db.repositories.follows.borrar_de_usuario"))
        votos = pila.enter_context(patch("db.repositories.asistente_feedback.borrar_de_usuario"))
        prefs = pila.enter_context(
            patch("db.repositories.notification_preferences.borrar_de_usuario")
        )
        anonymize_user_data("clave", **kwargs)  # type: ignore[arg-type]  # kwargs de test
    return {"follows": follows, "votos": votos, "prefs": prefs}


def test_el_borrado_alcanza_follows_votos_y_preferencias() -> None:
    llamadas = _anonimizar(user_id=5)
    llamadas["follows"].assert_called_once_with("clave", user_id=5)
    llamadas["votos"].assert_called_once_with(5)
    llamadas["prefs"].assert_called_once_with(5)


def test_sin_user_id_solo_se_borra_lo_que_se_guarda_por_clave() -> None:
    llamadas = _anonimizar()
    llamadas["follows"].assert_called_once_with("clave", user_id=None)
    llamadas["votos"].assert_not_called()
    llamadas["prefs"].assert_not_called()


def test_export_follows_delega_en_el_repositorio() -> None:
    from services.gdpr import export_follows

    filas = [{"id": 1}]
    with patch("db.repositories.follows.exportar_de_usuario", return_value=filas) as exportar:
        assert export_follows("clave", user_id=5) == filas
    exportar.assert_called_once_with("clave", user_id=5)

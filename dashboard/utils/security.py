from __future__ import annotations


def safe_url(url: str | None) -> str | None:
    """Devuelve la URL solo si usa esquema http/https; en caso contrario ``None``.

    Previene la inyección de esquemas peligrosos como ``javascript:`` o ``data:``.
    Devolver ``None`` (en lugar del antiguo ``"#"``) obliga al call site a
    decidir explícitamente si renderizar enlace o texto plano, evitando que un
    href manipulado a ``"#"`` pase como autorreferencia válida.

    No realiza validación de dominio: la responsabilidad de que el destino sea
    legítimo recae en el código que genera la URL (p. ej. solo deben pasarse
    URLs procedentes de la API de PLACE, nunca de entrada libre del usuario).
    """
    if not url or not isinstance(url, str):
        return None
    stripped = url.strip()
    if stripped.lower().startswith(("http://", "https://")):
        return stripped
    return None

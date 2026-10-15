"""Servidor MCP interno de TenderFlow: consulta de solo lectura para administradores.

Proceso aparte de la API. Expone tools de lectura sobre la base de datos con un
rol propio (``tenderflow_mcp``: solo ``SELECT``, transacciones de solo lectura,
``statement_timeout`` y conexiones limitadas) y autentica con OAuth 2.1
(login con Google; solo ``users.is_admin`` activos con acceso OAuth permitido).

Capa: la más alta (``scripts/check_layers.py``). Importa de ``config``, ``db``,
``services`` y por debajo; **no** importa de ``api/`` ni de ``scraper/``.
"""

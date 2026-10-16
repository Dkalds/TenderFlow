"""Autorización OAuth 2.1 del MCP interno: proveedor propio y login con Google.

``proveedor`` implementa ``OAuthAuthorizationServerProvider`` del SDK sobre
``db/mcp_oauth.py``; ``google`` hace el salto a Google y verifica la identidad.
"""

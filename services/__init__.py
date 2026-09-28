"""Capa de servicios — reglas y transformaciones de dominio.

Los módulos de este paquete encapsulan lógica de negocio sobre ``db/`` (que
posee todo el SQL, ADR-022). No son una frontera obligatoria: el CRUD simple
llama a ``db.*`` directamente, también desde ``api/routes/`` (ADR-024).
"""

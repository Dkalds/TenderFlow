"""Capa de servicios — orquesta lógica de negocio entre pages y repositorios.

Los módulos de este paquete exponen funciones puras ``(filters, pagination) → DataFrame|DTO``
que delegan en ``db/repositories/`` para acceso a datos. Las pages del dashboard sólo
deben importar desde ``services/`` (nunca SQL directo).
"""

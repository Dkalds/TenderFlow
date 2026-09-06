"""F1.5 (cuentas objetivo) y F1.6 (etiquetas de organización).

**Cuentas.** Mercado → Órganos es un corte analítico sin acción: enseña
cuánto licita un órgano y no deja hacer nada al respecto. Un comercial que
trabaja cuentas —no expedientes— no tiene dónde decir «este cliente me
interesa aunque hoy no publique nada», así que esa lista vive en su cabeza o
en una hoja aparte, y con ella se va cuando se va él.

**Etiquetas (D38).** Libres por organización, hasta treinta, con color,
aplicables a favoritos, oportunidades y cuentas. El límite no es decorativo:
por encima de treinta, una taxonomía libre deja de organizar y empieza a
esconder, y el selector se vuelve una lista que hay que leer entera.

Permisos
--------
Crear una cuenta o una etiqueta es escritura de organización: un ``viewer`` no
puede. Se resuelve con ``resolve_organization(..., write=True)``, el mismo
control que el resto de escrituras de equipo, en vez de una comprobación de
rol propia — que sería un segundo sitio donde equivocarse.
"""

from __future__ import annotations

import json
from typing import Any

from db.repositories.cuentas import CuentasRepository, EtiquetasRepository
from observability.logging import get_logger
from services.organizations import resolve_organization
from shared.dto import (
    CuentaObjetivo,
    Etiqueta,
    EtiquetaAplicada,
    ObjetoEtiquetable,
)

log = get_logger(__name__)

_cuentas = CuentasRepository()
_etiquetas = EtiquetasRepository()

#: Tope de etiquetas por organización (D38).
MAX_ETIQUETAS = 30

__all__ = [
    "MAX_ETIQUETAS",
    "EtiquetaLimiteError",
    "aplicar_etiqueta",
    "crear_etiqueta",
    "etiquetas_de",
    "listar_cuentas",
    "listar_etiquetas",
    "quitar_etiqueta",
    "seguir_organo",
]


class EtiquetaLimiteError(Exception):
    """La organización llegó al tope de etiquetas de D38."""


def listar_cuentas(user_id: int, *, organization_id: int | None = None) -> list[CuentaObjetivo]:
    resuelta, _ = resolve_organization(user_id, organization_id)
    return [CuentaObjetivo.model_validate(f) for f in _cuentas.list_for_organization(resuelta)]


def seguir_organo(
    user_id: int,
    *,
    organo: str,
    nota: str | None = None,
    organization_id: int | None = None,
) -> CuentaObjetivo:
    """Sigue un órgano como cuenta objetivo. Idempotente."""
    resuelta, _ = resolve_organization(user_id, organization_id, write=True)
    fila = _cuentas.follow(
        organization_id=resuelta, organo_nombre=organo, user_id=user_id, nota=nota
    )
    log.info("organo_seguido", organization_id=resuelta)
    return CuentaObjetivo.model_validate(fila)


def dejar_de_seguir(user_id: int, cuenta_id: int, *, organization_id: int | None = None) -> bool:
    resuelta, _ = resolve_organization(user_id, organization_id, write=True)
    return _cuentas.unfollow(resuelta, cuenta_id)


def listar_etiquetas(user_id: int, *, organization_id: int | None = None) -> list[Etiqueta]:
    resuelta, _ = resolve_organization(user_id, organization_id)
    return [Etiqueta.model_validate(f) for f in _etiquetas.list_for_organization(resuelta)]


def crear_etiqueta(
    user_id: int, *, nombre: str, color: str, organization_id: int | None = None
) -> tuple[Etiqueta, bool]:
    """``(etiqueta, creada)``. ``creada=False`` si ya existía con ese nombre.

    Devolver la existente en vez de un error es lo correcto para el caso real:
    dos personas etiquetando a la vez «Q4» quieren la misma etiqueta, no un
    conflicto que una de las dos tenga que resolver.
    """
    resuelta, _ = resolve_organization(user_id, organization_id, write=True)
    if _etiquetas.count(resuelta) >= MAX_ETIQUETAS:
        raise EtiquetaLimiteError(
            f"La organización ya tiene {MAX_ETIQUETAS} etiquetas, que es el máximo. "
            "Borra alguna antes de crear otra."
        )
    fila = _etiquetas.create(organization_id=resuelta, nombre=nombre, color=color, user_id=user_id)
    if fila is not None:
        return Etiqueta.model_validate(fila), True

    existentes = _etiquetas.list_for_organization(resuelta)
    from db.repositories.cuentas import normalizar_nombre

    buscada = normalizar_nombre(nombre)
    for f in existentes:
        if str(f["nombre_norm"]) == buscada:
            return Etiqueta.model_validate(f), False
    # No debería ocurrir: el INSERT sólo devuelve vacío por conflicto.
    raise EtiquetaLimiteError("No se pudo crear ni recuperar la etiqueta.")


def borrar_etiqueta(user_id: int, etiqueta_id: int, *, organization_id: int | None = None) -> bool:
    resuelta, _ = resolve_organization(user_id, organization_id, write=True)
    return _etiquetas.delete(resuelta, etiqueta_id)


def aplicar_etiqueta(
    user_id: int,
    *,
    etiqueta_id: int,
    objeto_tipo: ObjetoEtiquetable,
    objeto_id: str,
    organization_id: int | None = None,
) -> bool:
    """Aplica una etiqueta. ``False`` si la etiqueta no es de la organización."""
    resuelta, _ = resolve_organization(user_id, organization_id, write=True)
    aplicada = _etiquetas.aplicar(
        organization_id=resuelta,
        etiqueta_id=etiqueta_id,
        objeto_tipo=objeto_tipo,
        objeto_id=objeto_id,
        user_id=user_id,
    )
    if aplicada:
        log.info("etiqueta_aplicada", objeto=objeto_tipo)
    return aplicada


def quitar_etiqueta(
    user_id: int,
    *,
    etiqueta_id: int,
    objeto_tipo: ObjetoEtiquetable,
    objeto_id: str,
    organization_id: int | None = None,
) -> bool:
    resuelta, _ = resolve_organization(user_id, organization_id, write=True)
    return _etiquetas.quitar(
        organization_id=resuelta,
        etiqueta_id=etiqueta_id,
        objeto_tipo=objeto_tipo,
        objeto_id=objeto_id,
    )


def etiquetas_de(
    user_id: int,
    *,
    objeto_tipo: ObjetoEtiquetable,
    objeto_ids: list[str],
    organization_id: int | None = None,
) -> dict[str, list[EtiquetaAplicada]]:
    """Las etiquetas de varios objetos, para pintar una lista de una vez."""
    resuelta, _ = resolve_organization(user_id, organization_id)
    crudo: dict[str, list[dict[str, Any]]] = _etiquetas.por_objeto(
        resuelta, objeto_tipo, objeto_ids
    )
    return {
        objeto: [EtiquetaAplicada.model_validate(e) for e in etiquetas]
        for objeto, etiquetas in crudo.items()
    }


# ── F6.4: plantillas de organización ────────────────────────────────────────


def aplicar_plantillas(organization_id: int, user_id: int) -> int:
    """Copia las plantillas de la organización a un miembro recién activado.

    Devuelve cuántas copias creó; **0 si ya se le habían aplicado**.

    La idempotencia la da la clave única de ``plantillas_aplicadas`` y no una
    comprobación previa: entre un ``SELECT`` y un ``INSERT`` caben dos
    activaciones simultáneas de la misma membresía, y el resultado serían las
    reglas duplicadas que F6.4 dice explícitamente que no puede haber.

    Se copian **contenidos, no referencias**: el miembro puede borrar lo suyo
    sin tocar la plantilla y editarlo sin que cambie para los demás. Con
    referencias pasaría lo contrario, que es justo lo que F6.4 descarta.

    Un fallo copiando una plantilla no aborta las demás: es mejor que el
    miembro entre con tres de sus cuatro reglas que con ninguna, y el log deja
    cuál falló.
    """
    from db.repositories.cartera import PlantillasRepository

    repo = PlantillasRepository()
    if not repo.reservar_aplicacion(organization_id, user_id):
        log.info("plantillas_ya_aplicadas", organization_id=organization_id)
        return 0

    copias = 0
    for plantilla in repo.list_for_organization(organization_id):
        tipo = str(plantilla.get("tipo") or "")
        contenido = plantilla.get("contenido") or {}
        try:
            if tipo == "etiqueta":
                # Las etiquetas son de la organización, no del miembro: no se
                # copian, ya las tiene. Se cuenta para que el número refleje lo
                # que la plantilla cubre.
                copias += 1
            elif tipo in ("regla", "vista"):
                _copiar_para_miembro(tipo, contenido, organization_id, user_id)
                copias += 1
        except Exception as exc:
            log.warning(
                "plantilla_no_copiada",
                tipo=tipo,
                organization_id=organization_id,
                error=str(exc)[:200],
            )

    repo.registrar_copias(organization_id, user_id, copias)
    log.info("plantillas_aplicadas", organization_id=organization_id, copias=copias)
    return copias


def _copiar_para_miembro(
    tipo: str, contenido: dict[str, Any], organization_id: int, user_id: int
) -> None:
    """Materializa una plantilla como objeto propio del miembro.

    Está separado del bucle para que el `try` de arriba envuelva una unidad
    entera: media plantilla copiada sería peor que ninguna.
    """
    from db.users import get_user_by_id
    from shared.identity import user_key_from_email

    usuario = get_user_by_id(user_id)
    email = str((usuario or {}).get("email") or "")
    if not email:
        raise ValueError("El miembro no tiene email: no hay clave de usuario a la que copiar.")
    user_key = user_key_from_email(email, user_id)

    if tipo == "regla":
        from services.watchlist_rules import WatchlistRule, create_rule

        create_rule(
            user_key,
            WatchlistRule(**contenido),
            user_id=user_id,
            organization_id=organization_id,
            # `private`: la copia es **del miembro**, no de la organización.
            # Con `organization` la vería todo el equipo y editarla se la
            # cambiaría a los demás, que es lo contrario de lo que F6.4 pide.
            visibility="private",
        )
    elif tipo == "vista":
        from services.saved_filters import save_filter

        save_filter(
            user_key,
            str(contenido.get("nombre") or "Vista del equipo"),
            json.dumps(contenido.get("criterio") or {}, ensure_ascii=False),
            organization_id,
        )

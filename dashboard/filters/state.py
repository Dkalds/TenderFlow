"""Estado de filtros del sidebar — dataclass serializable a session_state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class FiltersState:
    q: str = ""
    rango: tuple[date, date] | None = None
    estados: list[str] = field(default_factory=list)
    ccaas: list[str] = field(default_factory=list)
    organos: list[str] = field(default_factory=list)
    tipos_proy: list[str] = field(default_factory=list)
    tecnologias: list[str] = field(default_factory=list)
    importe_min: int = 0
    comparar: bool = False
    rango_b: tuple[date, date] | None = None
    lic_id: str | None = None  # deep-link a una licitación individual

    def is_active(self) -> bool:
        """Devuelve True si algún filtro distinto al rango está activo."""
        return bool(
            self.q
            or self.estados
            or self.ccaas
            or self.organos
            or self.tipos_proy
            or self.tecnologias
            or self.importe_min > 0
        )

    def active_labels(self) -> list[str]:
        """Lista de etiquetas de filtros activos (para chips de la UI)."""
        return [label for label, _key, _val in self.active_items()]

    def active_items(self) -> list[tuple[str, str, str | None]]:
        """Lista de (display_label, session_key, valor_a_eliminar | None) para chips interactivos.

        - Si ``valor_a_eliminar`` es ``None`` el filtro es escalar (se borra la clave).
        - Si es una cadena se elimina sólo ese valor de la lista en session_state.
        """
        items: list[tuple[str, str, str | None]] = []
        if self.q:
            items.append((f'Búsqueda: "{self.q}"', "fs_q", None))
        for e in self.estados:
            items.append((f"Estado: {e}", "fs_estados", e))
        for c in self.ccaas:
            items.append((f"CCAA: {c}", "fs_ccaas", c))
        for o in self.organos:
            items.append((f"Órgano: {o[:25]}", "fs_organos", o))
        for t in self.tipos_proy:
            items.append((f"Tipo: {t}", "fs_tipos", t))
        for tech in self.tecnologias:
            items.append((f"Tecnología: {tech}", "fs_tecnologias", tech))
        if self.importe_min > 0:
            items.append((f"Imp. ≥ {self.importe_min:,} €", "fs_imp_min", None))
        return items

    def to_query_params(self) -> dict[str, str]:
        """Serializa el estado activo a parámetros de URL (solo campos con valor)."""
        params: dict[str, str] = {}
        if self.q:
            params["q"] = self.q
        if self.rango:
            params["fecha_desde"] = self.rango[0].isoformat()
            params["fecha_hasta"] = self.rango[1].isoformat()
        if self.estados:
            params["estados"] = ",".join(self.estados)
        if self.ccaas:
            params["ccaas"] = ",".join(self.ccaas)
        if self.organos:
            params["organos"] = ",".join(self.organos)
        if self.tipos_proy:
            params["tipos"] = ",".join(self.tipos_proy)
        if self.tecnologias:
            params["tecnologias"] = ",".join(self.tecnologias)
        if self.importe_min > 0:
            params["imp_min"] = str(self.importe_min)
        return params

    @classmethod
    def from_query_params(cls, params: dict[str, str]) -> FiltersState:
        """Reconstruye un FiltersState desde parámetros de URL."""
        rango = None
        if "fecha_desde" in params and "fecha_hasta" in params:
            try:
                d0 = date.fromisoformat(params["fecha_desde"])
                d1 = date.fromisoformat(params["fecha_hasta"])
                rango = (min(d0, d1), max(d0, d1))
            except ValueError:
                pass
        try:
            importe_min = int(params.get("imp_min") or 0)
        except (ValueError, TypeError):
            importe_min = 0
        return cls(
            q=params.get("q", ""),
            rango=rango,
            estados=[e for e in params.get("estados", "").split(",") if e],
            ccaas=[c for c in params.get("ccaas", "").split(",") if c],
            organos=[o for o in params.get("organos", "").split(",") if o],
            tipos_proy=[t for t in params.get("tipos", "").split(",") if t],
            tecnologias=[t for t in params.get("tecnologias", "").split(",") if t],
            importe_min=importe_min,
            lic_id=params.get("lic") or None,
        )

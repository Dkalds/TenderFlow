"""Superficie pública indexable: la proyección por allowlist de una licitación."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from shared.dto.primitivas import PgDateTime

# ── Superficie pública indexable ──────────────────────────────────────────
#
# Estos modelos son deliberadamente **nuevos** y no heredan de
# `LicitacionSummary`/`LicitacionDetail`. Dos motivos, los dos aprendidos por
# las malas:
#
# 1. **Fuga por herencia.** El `LicitacionSummary` de
#    `api/routes/licitaciones.py` lleva `tecnologia`, `ml_tecnologias`,
#    `ml_proba_max` y `ml_tech_principal`. Heredar de él publicaría la
#    analítica propia el primer día, con la petición devolviendo 200 y sin que
#    nada fallara. La proyección pública se construye por allowlist explícita:
#    un campo nuevo aguas arriba no aparece aquí solo por añadirse.
# 2. **Colisión de nombres en el OpenAPI.** Dos modelos distintos con el mismo
#    nombre hacen que FastAPI los renombre con prefijo de módulo, y eso
#    reescribe `components["schemas"]` en `web/src/generated/api.d.ts`,
#    rompiendo en cascada el frontend que lo referencia. De ahí el sufijo
#    `Publica`. (Este módulo tuvo tres homónimos de `api/routes/licitaciones.py`
#    hasta 2026-09-03; se borraron porque además estaban muertos.)
#
# Lo que NO está aquí y no debe añadirse: `ml_proba`, `ml_proba_max`,
# `ml_tecnologias`, `ml_tech_principal`, `tecnologia`, `raw_keywords`,
# `filter_version`, `classifier_model_version`, `inclusion_reason`,
# `analysis_universe` y `peso_precio_pct`. Todo eso es pipeline propio.
# Tampoco nada de `adjudicaciones`: el adjudicatario puede ser una persona
# física y no hay lógica en el repositorio que lo distinga.
# `scripts/check_public_surface.py` (que CI corre con `--strict`) NO escanea
# este fichero: vigila `api/routes/publico*.py` y la proyección por allowlist de
# `db/repositories/publico.py`, que son las dos puertas por las que un campo
# llegaría hasta aquí. Esta lista, por tanto, se sostiene por revisión; el guard
# cubre el camino, no el DTO.


class LotePublico(BaseModel):
    """Lote de una licitación. La tabla `lotes` no tiene campos de persona."""

    model_config = ConfigDict(from_attributes=True)

    numero: str
    titulo: str | None = None
    cpv: str | None = None
    importe: float | None = Field(default=None, ge=0)
    fecha_limite: PgDateTime | None = None


class LicitacionPublica(BaseModel):
    """Anuncio de licitación tal y como lo publica la fuente oficial.

    Todos los campos provienen del anuncio de PLACSP o TED, que ya es open data
    reutilizable. `url` y `actualizado` no son decorativos: la Ley 37/2007
    condiciona la reutilización a citar la fuente e indicar la fecha de la
    última actualización, así que ambos tienen que llegar a la página.
    """

    model_config = ConfigDict(from_attributes=True)

    #: Referencia opaca apta para URL. Ver `shared/public_ref.py`: los
    #: `id_externo` reales llevan espacios y barras y no caben en un segmento
    #: de ruta.
    ref: str
    #: Número de expediente tal cual lo publica el órgano: el expediente
    #: natural del `id_externo` (`shared/identidad_placsp.py`), sin prefijo de
    #: fuente ni el órgano que acota la clave de PLACSP.
    expediente: str
    titulo: str
    descripcion: str | None = None
    organo_contratacion: str | None = None
    importe: float | None = Field(default=None, ge=0)
    moneda: str | None = None
    cpv: str | None = None
    tipo_contrato: str | None = None
    estado: str | None = None
    procedimiento: str | None = None
    tramitacion: str | None = None
    fecha_publicacion: PgDateTime | None = None
    fecha_limite: PgDateTime | None = None
    fecha_inicio: PgDateTime | None = None
    fecha_fin: PgDateTime | None = None
    duracion_valor: float | None = None
    duracion_unidad: str | None = None
    provincia: str | None = None
    ccaa: str | None = None
    nuts_code: str | None = None
    #: Enlace al anuncio original: el vehículo de atribución a la fuente.
    url: str | None = None
    #: `placsp` | `ted` | ...
    fuente: str
    #: Fecha de la última actualización del dato, exigida por la Ley 37/2007.
    actualizado: PgDateTime | None = None
    lotes: list[LotePublico] = Field(default_factory=list)

"""v180: ``contrato_modificaciones`` — los anuncios de modificación de contrato (art. 207.3 LCSP).

Revision ID: v180_contrato_modificaciones
Revises: v178_sistema_contratacion
Create Date: 2026-11-10

Qué falta hoy
-------------
Lo que un contrato acaba costando no se puede medir con ``contrato_eventos``,
que son diferencias entre dos capturas de la misma fila: de los 746 expedientes
de TI que PLACSP marca con un anuncio de modificación (``DOC_MOD`` en
``tipos_anuncio``, medido el 2026-11-10), solo 18 tienen ahí un evento de
modificación o prórroga. El dato sí viene en las fuentes y no se leía: el
bloque ``cac:ContractModification`` de CODICE (importe de la modificación,
importe final, plazo, lote, motivo) y los avisos ``can-modif`` de eForms en TED
(motivo BT-200/201, descripción BT-202, aviso original BT-1501), que hasta
ahora entraban como una licitación adjudicada más.

Forma, y por qué
----------------
Una fila por modificación publicada. ``clave`` la identifica en su fuente y es
lo que hace idempotente la escritura (``ON CONFLICT (clave)``): en PLACSP el
expediente, el contrato y el número de la modificación; en TED el número del
aviso.

``licitacion_id`` es nullable: un aviso de TED cuyo expediente no está en
``licitaciones`` se guarda sin enlazar, no se descarta ni se enlaza por título;
``enlace`` dice cómo se llegó al expediente cuando se llegó. Clave ajena con
``ON DELETE SET NULL``: borrar un expediente deja la modificación sin enlazar,
no la borra (por eso no hay un ``CHECK`` que ate ``enlace`` a
``licitacion_id``: el ``SET NULL`` lo violaría y el borrado fallaría). Y
``ON UPDATE CASCADE``: una re-key de ``id_externo`` (``v164``) arrastra la
modificación.

Cada importe lleva su base (ADR-032) en su propia columna, con el mismo
vocabulario que ``licitaciones.importe_tipo``. ``importe_modificacion`` e
``importe_final`` son los de CODICE, sin IVA. ``importe_aviso`` es el BT-720
de un aviso de TED: la documentación de eForms lo llama «el valor de la
modificación» sin decir si es el incremento ni la base, en los avisos de
España es el valor del contrato tras la modificación unas veces y una copia
del valor del original otras (260 de 262 pares medidos el 2026-11-10 lo
repiten), así que se guarda como «valor publicado en el aviso», base
``desconocido``, y no se compara con nada.

``identificador_aviso`` es el ``notice-identifier`` (UUID) de un aviso de TED:
el BT-1501 de la modificación siguiente apunta a él, y así una cadena de
modificaciones encuentra su expediente aunque solo la primera case.

Las fechas son ``text`` ISO (``YYYY-MM-DD``), como en ``licitaciones``.

Por qué no bloquea, y por qué se puede repetir
----------------------------------------------
La tabla es nueva y vacía: los índices se crean con ella. La clave ajena pide un
``SHARE ROW EXCLUSIVE`` breve sobre ``licitaciones``; el ``lock_timeout`` evita
que espere detrás de una consulta larga y encole la tabla (la lección de
``v159``). ``IF NOT EXISTS`` en todo: un reintento tras un fallo encuentra hecho
lo que ya se hizo.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v180_contrato_modificaciones"
down_revision: str | Sequence[str] | None = "v178_sistema_contratacion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Congelados aquí: una migración describe el esquema del día en que se escribió.
_FUENTES = ("placsp", "ted")
_ENLACES = ("fuente", "aviso_original", "referencia")
_BASES = ("sin_iva", "con_iva", "desconocido")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _en(valores: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in valores)


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS contrato_modificaciones (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            clave text NOT NULL UNIQUE,
            fuente text NOT NULL CHECK (fuente IN ({_en(_FUENTES)})),
            licitacion_id text
                REFERENCES licitaciones (id_externo) ON DELETE SET NULL ON UPDATE CASCADE,
            enlace text CHECK (enlace IN ({_en(_ENLACES)})),
            numero text,
            contrato_ref text,
            lote_numero text,
            fecha_publicacion text,
            motivo_codigo text,
            motivo text,
            descripcion text,
            importe_modificacion double precision,
            importe_modificacion_base text
                CHECK (importe_modificacion_base IN ({_en(_BASES)})),
            importe_final double precision,
            importe_final_base text CHECK (importe_final_base IN ({_en(_BASES)})),
            importe_aviso double precision,
            importe_aviso_base text CHECK (importe_aviso_base IN ({_en(_BASES)})),
            moneda text,
            plazo_modificacion double precision,
            plazo_final double precision,
            plazo_unidad text,
            identificador_aviso text,
            aviso_original text,
            expediente_ref text,
            organo text,
            url text,
            fecha_extraccion text NOT NULL
        )
        """
    )
    # La ficha lee por expediente; el enlazado de TED, las que siguen sin él.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_contrato_modif_licitacion "
        "ON contrato_modificaciones (licitacion_id) WHERE licitacion_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_contrato_modif_aviso "
        "ON contrato_modificaciones (identificador_aviso) WHERE identificador_aviso IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_contrato_modif_sin_enlazar "
        "ON contrato_modificaciones (fuente, fecha_publicacion) WHERE licitacion_id IS NULL"
    )
    # Alembic puede aplicar varias revisiones en la misma transacción: el
    # ``SET LOCAL`` no debe acotar los locks de las que vengan detrás.
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("DROP TABLE IF EXISTS contrato_modificaciones")
    op.execute("RESET lock_timeout")

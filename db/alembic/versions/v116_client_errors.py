"""v116: ``client_errors`` — lo que falla en el navegador llega a alguien (C2.6, D26).

Qué corrige
-----------
``POST /security/client-error`` recibe los errores de JavaScript del navegador y
**termina en un ``log.warning``**. Un log de Render no es un destino: nadie lo
mira salvo cuando ya hay un incidente, no se puede agregar, y a los pocos días
se rota. Un fallo del layout raíz —que ocurre por encima de la sesión y por
tanto afecta a todo el mundo— desaparecía sin que nadie contara cuántas veces
pasó.

Sentry es opt-in y solo de backend; el frontend no tiene SDK.

Por qué tabla propia y no un SDK (D26)
--------------------------------------
Un SDK de terceros recibiría trazas del navegador de cada visitante, con lo que
eso arrastra: PII en stacks, URLs completas, y un tercero más en el registro de
tratamientos. La tabla propia cuesta una migración y no añade destinatario.

Qué se guarda, y qué no
-----------------------
La fila lleva **huella, no identidad**: ruta sin query string, mensaje truncado,
versión de build y un contador de ocurrencias. **No** lleva IP, email, id de
usuario, query string ni el ``extra`` que los call-sites pasan a ``reportError``.
Es el mismo criterio que ya aplica ``csp_violation`` y que el docstring del
endpoint documenta línea a línea.

La agregación por huella es lo que convierte «mil líneas de log» en «un error,
mil veces»: sin ella la tabla sería un log con otro nombre.

Retención
---------
30 días (``RETENTION_CLIENT_ERRORS_DAYS``), publicados en ``docs/SECURITY.md`` y
aplicados por ``retention_cleanup``. Una huella sin PII sigue siendo dato que no
hace falta guardar más de lo que dura investigar una regresión.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v116_client_errors"
down_revision: str | Sequence[str] | None = "v115_api_keys_organizacion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    if "client_errors" in set(sa.inspect(op.get_bind()).get_table_names()):
        return

    op.create_table(
        "client_errors",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        # Huella estable del error: hash de (mensaje normalizado, ruta, origen).
        # Es la clave de agregación y **no** contiene el texto original.
        sa.Column("fingerprint", sa.Text, nullable=False),
        # `onerror`, `unhandledrejection`, `global-error`, `manual`.
        sa.Column("origen", sa.Text, nullable=True),
        # Ruta SIN query string: la query puede llevar términos de búsqueda del
        # usuario, que son dato personal en un endpoint sin autenticación.
        sa.Column("ruta", sa.Text, nullable=True),
        sa.Column("mensaje", sa.Text, nullable=True),
        sa.Column("build", sa.Text, nullable=True),
        sa.Column("ocurrencias", sa.Integer, nullable=False, server_default="1"),
        sa.Column("primera_vez", sa.Text, nullable=False, server_default=_NOW),
        sa.Column("ultima_vez", sa.Text, nullable=False, server_default=_NOW),
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_client_errors_fingerprint "
        "ON client_errors(fingerprint)"
    )
    # La vista de `/ops` ordena por recencia: sin este índice, con la tabla
    # creciendo a diario, sería un seq scan por carga de pantalla.
    op.create_index("idx_client_errors_ultima_vez", "client_errors", ["ultima_vez"])


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP TABLE IF EXISTS client_errors CASCADE")

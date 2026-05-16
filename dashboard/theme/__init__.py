"""Sistema de diseño centralizado.

Única fuente de verdad para colores, spacing, tipografía y breakpoints del
dashboard. Se consume desde tres sitios:

- `css.build_css(tokens)` inyectado en Streamlit.
- `plotly_template.build_plotly_template(tokens)` para todos los charts.
- `streamlit_config.main()` regenera `.streamlit/config.toml` (offline).
"""

from dashboard.theme.css import COMPACT_DENSITY_CSS, build_css
from dashboard.theme.plotly_template import (
    PLOTLY_CONFIG,
    PLOTLY_TEMPLATE_NAME,
    PLOTLY_TEMPLATE_NAME_LIGHT,
    build_plotly_template,
    build_plotly_template_light,
    current_plotly_template,
    get_color_sequence,
    register_plotly_template,
)
from dashboard.theme.tokens import TOKENS, Tokens

__all__ = [
    "COMPACT_DENSITY_CSS",
    "PLOTLY_CONFIG",
    "PLOTLY_TEMPLATE_NAME",
    "PLOTLY_TEMPLATE_NAME_LIGHT",
    "TOKENS",
    "Tokens",
    "build_css",
    "build_plotly_template",
    "build_plotly_template_light",
    "current_plotly_template",
    "get_color_sequence",
    "register_plotly_template",
]

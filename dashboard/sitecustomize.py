"""Bootstrap de path para ejecución de scripts dentro de dashboard/.

Python importa automáticamente ``sitecustomize`` durante el arranque (si está
presente en ``sys.path``). Como Streamlit Cloud suele ejecutar
``dashboard/app.py`` como script, el primer entry de ``sys.path`` puede quedar
en ``.../dashboard`` y romper imports absolutos ``from dashboard...``.

Este módulo garantiza que el root del repo esté al frente de ``sys.path``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

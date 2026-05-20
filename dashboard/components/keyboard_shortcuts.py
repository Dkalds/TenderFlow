"""Atajos de teclado globales para el dashboard."""

from __future__ import annotations

import json

import streamlit as st


def render_keyboard_shortcuts(visible_sections: list[str]) -> None:
    """Inyecta el bloque JS de atajos de teclado.

    Atajos disponibles:
    - ``/``   → enfocar el input de búsqueda en el sidebar
    - ``1``–``5`` → seleccionar la sección del top-nav correspondiente
    - ``?``   → mostrar/ocultar el panel de ayuda
    - ``Esc`` → cerrar el panel de ayuda
    """
    section_list_js = json.dumps(visible_sections)
    st.markdown(
        f"""
        <script>
        (function() {{
          var SECTIONS = {section_list_js};
          var _helpVisible = false;

          function getSearchInput() {{
            var inputs = document.querySelectorAll(
              '[data-testid="stSidebarContent"] input[type="text"]'
            );
            for (var i = 0; i < inputs.length; i++) {{
              if ((inputs[i].getAttribute('placeholder') || '').indexOf('CPV') !== -1)
                return inputs[i];
            }}
            return null;
          }}

          function clickTopNavOption(idx) {{
            var radios = document.querySelectorAll(
              '[data-testid="stMainBlockContainer"] [role="radiogroup"] label'
            );
            if (radios[idx]) radios[idx].click();
          }}

          function showHelp() {{
            var existing = document.getElementById('kb-help-overlay');
            if (existing) {{ existing.remove(); _helpVisible = false; return; }}
            _helpVisible = true;
            var overlay = document.createElement('div');
            overlay.id = 'kb-help-overlay';
            overlay.style.cssText = [
              'position:fixed','top:50%','left:50%',
              'transform:translate(-50%,-50%)',
              'background:rgba(20,20,30,0.97)',
              'border:1px solid rgba(255,255,255,0.12)',
              'border-radius:12px','padding:24px 32px',
              'z-index:99999','min-width:280px',
              'font-size:0.88rem','color:#e8e8e8',
              'box-shadow:0 8px 32px rgba(0,0,0,0.6)',
              'line-height:2',
            ].join(';');
            overlay.innerHTML = [
              '<b style="font-size:1rem">Atajos de teclado</b><hr style="margin:8px 0;opacity:0.2">',
              '<kbd>/</kbd> &nbsp; Enfocar búsqueda',
              '<br><kbd>1</kbd>–<kbd>' + Math.min(SECTIONS.length, 5) + '</kbd> &nbsp; Cambiar sección',
              '<br><kbd>?</kbd> &nbsp; Mostrar/ocultar esta ayuda',
              '<br><kbd>Esc</kbd> &nbsp; Cerrar',
              '<br><br><span style="opacity:0.5;font-size:0.78rem">Haz clic fuera para cerrar</span>',
            ].join('');
            document.body.appendChild(overlay);
            overlay.addEventListener('click', function(e) {{ e.stopPropagation(); }});
            document.addEventListener('click', function closeHelp() {{
              overlay.remove(); _helpVisible = false;
              document.removeEventListener('click', closeHelp);
            }});
          }}

          document.addEventListener('keydown', function(e) {{
            var tag = (document.activeElement || {{}}).tagName || '';
            var isInput = ['INPUT','TEXTAREA','SELECT'].indexOf(tag) !== -1;

            if (e.key === 'Escape') {{
              var h = document.getElementById('kb-help-overlay');
              if (h) {{ h.remove(); _helpVisible = false; }}
              return;
            }}
            if (isInput) return;  // No interferir cuando el usuario está escribiendo

            if (e.key === '/') {{
              e.preventDefault();
              var inp = getSearchInput();
              if (inp) inp.focus();
              return;
            }}

            if (e.key === '?') {{
              showHelp();
              return;
            }}

            var n = parseInt(e.key, 10);
            if (!isNaN(n) && n >= 1 && n <= SECTIONS.length) {{
              clickTopNavOption(n - 1);
              return;
            }}
          }});
        }})();
        </script>
        """,
        unsafe_allow_html=True,
    )

"""Componente de búsqueda con autocompletado JS y debounce 300ms.

Inyecta un overlay de sugerencias bajo el ``st.text_input`` del sidebar
usando un script JS vanilla. Las sugerencias se construyen del lado Python
y se pasan como JSON embebido, sin llamadas a endpoint externo.

Uso:
    render_search_autocomplete(suggestions)

Donde ``suggestions`` es una lista de strings (hasta ~200 para mantener el
JSON liviano).
"""

from __future__ import annotations

import json

import streamlit as st


def render_search_autocomplete(suggestions: list[str], input_key: str = "fs_q") -> None:
    """Inyecta el JS de autocompletado sobre el input de búsqueda del sidebar.

    Args:
        suggestions: Lista de sugerencias (títulos, CPV descriptions, keywords).
        input_key: Clave del st.text_input al que se adjunta el autocompletado.
    """
    if not suggestions:
        return

    # Truncar a 300 para mantener JSON liviano; escapar para evitar XSS
    safe_suggestions = [str(s)[:80] for s in suggestions[:300]]
    suggestions_json = json.dumps(safe_suggestions, ensure_ascii=False)

    # ID del input de Streamlit: Streamlit asigna el id basado en la clave
    # El selector más fiable es data-testid + label o el input dentro del
    # contenedor que contiene el label collapsed con key
    autocomplete_js = f"""
    <script>
    (function() {{
      var SUGGESTIONS = {suggestions_json};
      var DEBOUNCE_MS = 300;
      var _timer = null;
      var _dropdown = null;
      var _activeIdx = -1;

      function getInput() {{
        // Buscar el text input que tiene placeholder "Título, descripción, CPV…"
        var inputs = document.querySelectorAll(
          '[data-testid="stSidebarContent"] input[type="text"]'
        );
        for (var i = 0; i < inputs.length; i++) {{
          if (inputs[i].getAttribute('placeholder') &&
              inputs[i].getAttribute('placeholder').indexOf('CPV') !== -1) {{
            return inputs[i];
          }}
        }}
        return null;
      }}

      function buildDropdown(input) {{
        if (_dropdown) return _dropdown;
        var dd = document.createElement('div');
        dd.id = 'ac-dropdown';
        dd.style.cssText = [
          'position:absolute',
          'z-index:9999',
          'background:var(--background-color, #1e1e1e)',
          'border:1px solid var(--secondary-background-color, #333)',
          'border-radius:6px',
          'max-height:220px',
          'overflow-y:auto',
          'width:100%',
          'box-shadow:0 4px 16px rgba(0,0,0,0.4)',
          'font-size:0.82rem',
          'margin-top:2px',
        ].join(';');
        input.parentNode.style.position = 'relative';
        input.parentNode.appendChild(dd);
        _dropdown = dd;

        document.addEventListener('click', function(e) {{
          if (_dropdown && !_dropdown.contains(e.target) && e.target !== input) {{
            hideDropdown();
          }}
        }});
        return dd;
      }}

      function hideDropdown() {{
        if (_dropdown) {{ _dropdown.style.display = 'none'; }}
        _activeIdx = -1;
      }}

      function showSuggestions(input, query) {{
        var q = query.trim().toLowerCase();
        if (q.length < 2) {{ hideDropdown(); return; }}

        var matches = SUGGESTIONS.filter(function(s) {{
          return s.toLowerCase().indexOf(q) !== -1;
        }}).slice(0, 8);

        if (!matches.length) {{ hideDropdown(); return; }}

        var dd = buildDropdown(input);
        dd.innerHTML = '';
        _activeIdx = -1;

        matches.forEach(function(m, idx) {{
          var item = document.createElement('div');
          item.textContent = m;
          item.style.cssText = [
            'padding:7px 10px',
            'cursor:pointer',
            'border-bottom:1px solid rgba(255,255,255,0.05)',
            'color:var(--text-color, #fafafa)',
            'transition:background .12s',
          ].join(';');
          item.addEventListener('mouseenter', function() {{
            item.style.background = 'rgba(0,163,224,0.15)';
          }});
          item.addEventListener('mouseleave', function() {{
            item.style.background = '';
          }});
          item.addEventListener('mousedown', function(e) {{
            e.preventDefault();
            // Insertar el valor en el input de Streamlit y disparar React change
            var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
              window.HTMLInputElement.prototype, 'value'
            ).set;
            nativeInputValueSetter.call(input, m);
            input.dispatchEvent(new Event('input', {{ bubbles: true }}));
            input.dispatchEvent(new Event('change', {{ bubbles: true }}));
            hideDropdown();
          }});
          dd.appendChild(item);
        }});

        dd.style.display = 'block';
      }}

      function attachToInput(input) {{
        input.addEventListener('input', function() {{
          clearTimeout(_timer);
          var val = input.value;
          _timer = setTimeout(function() {{ showSuggestions(input, val); }}, {300});
        }});
        input.addEventListener('keydown', function(e) {{
          if (!_dropdown || _dropdown.style.display === 'none') return;
          var items = _dropdown.querySelectorAll('div');
          if (e.key === 'ArrowDown') {{
            e.preventDefault();
            _activeIdx = Math.min(_activeIdx + 1, items.length - 1);
          }} else if (e.key === 'ArrowUp') {{
            e.preventDefault();
            _activeIdx = Math.max(_activeIdx - 1, 0);
          }} else if (e.key === 'Enter' && _activeIdx >= 0) {{
            items[_activeIdx].dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true }}));
            return;
          }} else if (e.key === 'Escape') {{
            hideDropdown(); return;
          }}
          items.forEach(function(it, i) {{
            it.style.background = i === _activeIdx ? 'rgba(0,163,224,0.25)' : '';
          }});
        }});
        input.addEventListener('blur', function() {{
          setTimeout(hideDropdown, 150);
        }});
      }}

      // Esperar a que el sidebar esté en el DOM
      function tryAttach() {{
        var input = getInput();
        if (input && !input.__acAttached) {{
          input.__acAttached = true;
          attachToInput(input);
        }} else if (!input) {{
          setTimeout(tryAttach, 500);
        }}
      }}

      if (document.readyState === 'loading') {{
        document.addEventListener('DOMContentLoaded', tryAttach);
      }} else {{
        tryAttach();
      }}
    }})();
    </script>
    """
    st.markdown(autocomplete_js, unsafe_allow_html=True)

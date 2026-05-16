"""Tour guiado de onboarding con overlay spotlight (JS/CSS inyectado).

El tour se activa la primera vez que el usuario visita el dashboard
(basado en ``session_state["_onboarding_done"]``). Consta de 5 pasos
con un spotlight CSS que resalta el elemento objetivo.

Pasos:
  1. Top-nav: secciones principales
  2. KPI bar: indicadores de mercado
  3. Sidebar: filtros
  4. Breadcrumb: navegación
  5. Exportación global

Uso:
    render_onboarding_tour()  # en app.py tras el renderizado inicial

La lógica JS gestiona el avance/cierre del tour y actualiza el estado
vía un input oculto de Streamlit. Cuando el tour finaliza se escribe
``session_state["_onboarding_done"] = True``.
"""

from __future__ import annotations

import streamlit as st

_TOUR_STEPS = [
    {
        "title": "Secciones principales",
        "body": "Navega entre Vista General, Mercado, Competencia y Personal usando estas pestañas.",
        "selector": '[data-testid="stMainBlockContainer"] [role="radiogroup"]',
        "position": "bottom",
    },
    {
        "title": "Indicadores clave (KPIs)",
        "body": "Aquí ves el total de licitaciones, importes y órganos. Haz clic en cada KPI para ir a la vista correspondiente.",
        "selector": ".kpi-card",
        "position": "bottom",
    },
    {
        "title": "Filtros del sidebar",
        "body": "Filtra por fecha, estado, CCAA, importe y más. Los cambios se reflejan en tiempo real en toda la app.",
        "selector": '[data-testid="stSidebarContent"]',
        "position": "right",
    },
    {
        "title": "Breadcrumb de navegación",
        "body": "Muestra tu posición en la app. Haz clic en la sección para volver a ella desde cualquier sub-página.",
        "selector": 'nav[aria-label="breadcrumb"]',
        "position": "bottom",
    },
    {
        "title": "Exportación global",
        "body": "Descarga los datos filtrados en Excel o CSV con el botón '⬇ Exportar' de la barra superior.",
        "selector": 'button[title="Exportar datos filtrados"]',
        "position": "bottom",
    },
]


def render_onboarding_tour() -> None:
    """Renderiza el tour de onboarding si no ha sido completado aún.

    Se activa solo una vez por sesión (``session_state["_onboarding_done"]``).
    """
    from dashboard.session_keys import ONBOARDING_DONE

    if st.session_state.get(ONBOARDING_DONE, False):
        return

    import json

    steps_json = json.dumps(_TOUR_STEPS, ensure_ascii=False)

    tour_js = f"""
    <style>
    #ot-overlay {{
      position: fixed; inset: 0; z-index: 99990;
      background: rgba(0,0,0,0.55); pointer-events: none;
    }}
    #ot-spotlight {{
      position: fixed; z-index: 99991; border-radius: 8px;
      box-shadow: 0 0 0 9999px rgba(0,0,0,0.55);
      transition: all 0.3s ease;
      pointer-events: none;
    }}
    #ot-tooltip {{
      position: fixed; z-index: 99992;
      background: #1a1a2e; border: 1px solid rgba(0,163,224,0.4);
      border-radius: 10px; padding: 16px 20px; max-width: 320px;
      color: #e8e8e8; font-size: 0.88rem; line-height: 1.5;
      box-shadow: 0 8px 32px rgba(0,0,0,0.5);
      pointer-events: all;
    }}
    #ot-tooltip b {{ color: #00A3E0; font-size: 0.95rem; }}
    #ot-tooltip p {{ margin: 6px 0 12px 0; opacity: 0.9; }}
    .ot-btn {{
      background: #00A3E0; color: #fff; border: none;
      border-radius: 6px; padding: 7px 16px; font-size: 0.82rem;
      cursor: pointer; margin-right: 8px; font-weight: 600;
      transition: background 0.15s;
    }}
    .ot-btn:hover {{ background: #0082b3; }}
    .ot-btn-skip {{
      background: transparent; color: rgba(255,255,255,0.45);
      border: 1px solid rgba(255,255,255,0.15);
    }}
    .ot-btn-skip:hover {{ color: rgba(255,255,255,0.7); }}
    #ot-progress {{ font-size: 0.75rem; opacity: 0.5; margin-top: 8px; }}
    </style>

    <div id="ot-overlay" style="display:none"></div>
    <div id="ot-spotlight" style="display:none"></div>
    <div id="ot-tooltip" style="display:none">
      <b id="ot-title"></b>
      <p id="ot-body"></p>
      <button class="ot-btn" id="ot-next">Siguiente →</button>
      <button class="ot-btn ot-btn-skip" id="ot-skip">Saltar tour</button>
      <div id="ot-progress"></div>
    </div>

    <script>
    (function() {{
      var STEPS = {steps_json};
      var current = 0;

      function getEl(selector) {{
        return document.querySelector(selector);
      }}

      function positionSpotlight(el) {{
        if (!el) return;
        var r = el.getBoundingClientRect();
        var pad = 8;
        var sp = document.getElementById('ot-spotlight');
        sp.style.left   = (r.left - pad) + 'px';
        sp.style.top    = (r.top - pad) + 'px';
        sp.style.width  = (r.width + pad * 2) + 'px';
        sp.style.height = (r.height + pad * 2) + 'px';
        sp.style.display = 'block';
      }}

      function positionTooltip(el, position) {{
        var tt = document.getElementById('ot-tooltip');
        tt.style.display = 'block';
        var r = el ? el.getBoundingClientRect() : {{left:100,top:100,width:0,height:0}};
        var ttW = 340; var ttH = 160;
        var vw = window.innerWidth; var vh = window.innerHeight;
        var left = r.left;
        var top = r.bottom + 12;
        if (position === 'right') {{ left = r.right + 12; top = r.top; }}
        if (left + ttW > vw) left = vw - ttW - 12;
        if (top + ttH > vh) top = r.top - ttH - 12;
        if (top < 0) top = 12;
        tt.style.left = Math.max(8, left) + 'px';
        tt.style.top  = Math.max(8, top) + 'px';
      }}

      function showStep(idx) {{
        if (idx >= STEPS.length) {{ endTour(); return; }}
        var step = STEPS[idx];
        var el = document.querySelector(step.selector);

        document.getElementById('ot-title').textContent = step.title;
        document.getElementById('ot-body').textContent  = step.body;
        document.getElementById('ot-progress').textContent =
          'Paso ' + (idx + 1) + ' de ' + STEPS.length;

        var overlay = document.getElementById('ot-overlay');
        overlay.style.display = 'block';

        if (el) {{
          el.scrollIntoView({{behavior:'smooth', block:'nearest'}});
          setTimeout(function() {{
            positionSpotlight(el);
            positionTooltip(el, step.position);
          }}, 200);
        }} else {{
          document.getElementById('ot-spotlight').style.display = 'none';
          positionTooltip(null, 'bottom');
        }}

        var nextLbl = idx === STEPS.length - 1 ? 'Finalizar ✓' : 'Siguiente →';
        document.getElementById('ot-next').textContent = nextLbl;
        current = idx;
      }}

      function endTour() {{
        ['ot-overlay','ot-spotlight','ot-tooltip'].forEach(function(id) {{
          var el = document.getElementById(id);
          if (el) el.style.display = 'none';
        }});
        // Señal a Streamlit para no volver a mostrar el tour
        try {{
          window.parent.postMessage({{type:'streamlit:setComponentValue', value:true}}, '*');
        }} catch(e) {{}}
      }}

      document.getElementById('ot-next').addEventListener('click', function() {{
        showStep(current + 1);
      }});
      document.getElementById('ot-skip').addEventListener('click', endTour);

      // Arrancar el tour al cargar la página
      function startTour() {{
        var firstEl = document.querySelector(STEPS[0].selector);
        if (firstEl) {{
          showStep(0);
        }} else {{
          setTimeout(startTour, 800);
        }}
      }}

      setTimeout(startTour, 1200);
    }})();
    </script>
    """

    st.markdown(tour_js, unsafe_allow_html=True)

    # Botón oculto para que el usuario pueda cerrar el tour desde Python
    # (aparece cuando JS no está disponible)
    if st.button(
        "Cerrar tour",
        key="_onboarding_close",
        help="Cerrar el tour de introducción",
    ):
        from dashboard.session_keys import ONBOARDING_DONE

        st.session_state[ONBOARDING_DONE] = True
        st.rerun()

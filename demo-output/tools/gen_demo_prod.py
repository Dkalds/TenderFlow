"""Genera la composición Hyperframes de la demo general de TenderFlow.

Lee el manifiesto del rodaje (capturas reales + caja del elemento pulsado) y el
guion de abajo, y escribe demo-output/composition/: index.html, una escena por
capítulo en compositions/, y las capturas en assets/shots/ (jpg).
"""

import json
import math
import shutil
import subprocess
import sys
from html import escape
from pathlib import Path

SHOTS = Path(sys.argv[1])
OUT = Path(sys.argv[2])
BRAG = Path(sys.argv[3])  # skills/brag/assets
MAN = json.loads((SHOTS / "manifest.json").read_text())
FILES = {e["file"]: e for v in MAN.values() for e in v}

FRAME = (192, 120, 1536, 864)  # x, y, w, h del marco de pantalla
FIT = FRAME[2] / 1920  # 0.8
BEAT0, BEAT = 0.02, 0.4992  # rejilla de la pista vol-1 (~120.19 BPM)


def snap_up(t):
    k = math.ceil((t - BEAT0) / BEAT - 1e-6)
    return round(BEAT0 + k * BEAT, 3)


def frames(prefijo_shot, prefijo):
    """Fotogramas de tecleo en orden: <shot>-NN-<prefijo>-tNNN.png"""
    out = [f for f in sorted(FILES) if f.startswith(prefijo_shot + "-") and f"-{prefijo}-t" in f]
    return out


def S(img, dur, click=False, cam=None, cam_at=0.0):
    return {"img": img, "dur": dur, "click": click, "cam": cam, "cam_at": cam_at}


def T(shot, prefijo, every=0.09):
    return [S(f, every) for f in frames(shot, prefijo)]


# --------------------------------------------------------------------------
# Guion. cam = (zoom relativo al encaje, foco x, foco y) en coordenadas 1920x1080.
CAPS = [
    {
        "id": "publico", "num": "01", "title": "La parte pública", "demo": False,
        "caps": [(0, "Cada anuncio TI tiene su ficha pública, con la fuente citada.")],
        "steps": [
            S("publico-00-landing.png", 2.6, cam=(1.2, 760, 420), cam_at=0.5),
            S("publico-01-indice.png", 1.9, click=True, cam=(1.3, 900, 420)),
            S("publico-02-hub.png", 1.9, click=True, cam=(1.2, 900, 480)),
            S("publico-03-ficha.png", 2.6, cam=(1.25, 820, 520)),
        ],
    },
    {
        "id": "radar", "num": "02", "title": "Radar", "demo": False,
        "caps": [
            (0, "Los concursos abiertos, ordenados por lo que encajan contigo."),
            (3.3, "Cada puntuación dice de dónde sale: seis dimensiones, a la vista."),
        ],
        "steps": [
            S("radar-00-bandeja.png", 3.2, click=True, cam=(1.25, 720, 640), cam_at=0.5),
            S("radar-01-inspector.png", 3.6, click=True, cam=(1.45, 1600, 700), cam_at=0.15),
        ],
    },
    {
        "id": "oportunidad", "num": "03", "title": "Oportunidad", "demo": False,
        "caps": [
            (0, "Del Radar a la oferta, fase a fase."),
            (4.2, "GO o NO-GO, con el motivo por escrito."),
            (9.6, "Quién lo tiene hoy, contra quién se compite y a qué precio."),
        ],
        "steps": [
            S("radar-02-pursuit-identificada.png", 2.4, click=True, cam=(1.25, 640, 430), cam_at=0.3),
            S("pursuit-00-cualificacion.png", 1.6, click=True),
            S("pursuit-01-decision.png", 1.7, click=True, cam=(1.35, 800, 660)),
            S("pursuit-02-go-elegido.png", 0.9, click=True),
            *T("pursuit", "motivo"),
            S("pursuit-11-motivo-escrito.png", 1.0, click=True),
            S("pursuit-12-decidida.png", 1.7, click=True, cam=(1.25, 640, 450)),
            S("pursuit-13-preparando.png", 1.6, click=True, cam=(1.15, 820, 360)),
            S("pursuit-14-precio.png", 3.2, cam=(1.35, 620, 640), cam_at=0.3),
            S("pursuit-15-precio-2.png", 3.4, cam=(1.4, 620, 680)),
        ],
    },
    {
        "id": "agenda", "num": "04", "title": "Tablero y agenda", "demo": False,
        "caps": [(0, "El tablero del equipo y la agenda de cada uno: tareas, plazos y próxima acción.")],
        "steps": [
            S("tablero-00-kanban.png", 2.8, cam=(1.3, 900, 420), cam_at=0.4),
            S("agenda-00-agenda.png", 1.7, click=True, cam=(1.0, 960, 540)),
            S("agenda-01-detalle.png", 1.3, click=True, cam=(1.45, 1520, 620)),
            *T("agenda", "tarea"),
            S("agenda-08-tarea-escrita.png", 0.8, click=True),
            S("agenda-09-tarea-creada.png", 1.0, click=True),
            S("agenda-10-tarea-hecha.png", 1.8),
        ],
    },
    {
        "id": "detalle", "num": "05", "title": "Detalle", "demo": False,
        "caps": [
            (0, "Todo el expediente: importe, plazo, puntuación y baja esperada."),
            (3.2, "Y su competencia: quién lo tiene hoy y quién suele ganar."),
        ],
        "steps": [
            S("detalle-00-ficha.png", 3.2, click=True, cam=(1.45, 1620, 420), cam_at=0.6),
            S("detalle-01-ficha-competencia.png", 3.6, cam=(1.45, 1620, 740), cam_at=0.1),
        ],
    },
    {
        "id": "investigador", "num": "06", "title": "Investigador", "demo": False,
        "caps": [
            (0, "Pregunta o busca dentro de las licitaciones y sus pliegos."),
            (3.2, "Entiende la comunidad y el estado que pides, y filtra por ellos."),
        ],
        "steps": [
            S("investigador-00-vacio.png", 1.2, click=True, cam=(1.3, 900, 380)),
            *T("investigador", "frase"),
            S("investigador-08-frase-escrita.png", 0.8, click=True),
            S("investigador-09-resultados.png", 3.8, cam=(1.3, 760, 600), cam_at=0.2),
        ],
    },
    {
        "id": "alertas", "num": "07", "title": "Alertas", "demo": False,
        "caps": [(0, "Reglas por palabra, CPV, importe y comunidad, con vista previa antes de guardar.")],
        "steps": [
            S("watchlist-00-vacia.png", 1.3, click=True, cam=(1.35, 820, 450)),
            *T("watchlist", "palabra", every=0.16),
            S("watchlist-04-palabra-escrita.png", 0.9, click=True),
            S("watchlist-05-vista-previa.png", 2.4, click=True, cam=(1.25, 900, 560)),
            S("watchlist-06-regla-creada.png", 1.3),
            S("watchlist-07-resultados-regla.png", 2.6, cam=(1.3, 800, 400), cam_at=0.1),
        ],
    },
    {
        "id": "competencia", "num": "08", "title": "Competencia", "demo": False,
        "caps": [(0, "Quién se lleva estos contratos y con qué cuota.")],
        "steps": [
            S("competencia-00-panorama.png", 3.4, cam=(1.4, 760, 340), cam_at=0.6),
            S("competencia-01-ranking.png", 1.8, click=True, cam=(1.25, 820, 560)),
            S("competencia-02-perfil.png", 3.0, cam=(1.15, 900, 420)),
        ],
    },
    {
        "id": "mercado", "num": "09", "title": "Mercado", "demo": False,
        "caps": [(0, "El mercado por mes, comunidad, CPV y órgano.")],
        "steps": [
            S("mercado-00-tiempo.png", 2.6, cam=(1.2, 960, 560), cam_at=0.4),
            S("mercado-01-geografia.png", 2.2),
            S("mercado-02-cpv.png", 2.4, cam=(1.0, 960, 540)),
            S("mercado-03-organos.png", 2.8, cam=(1.2, 900, 520), cam_at=0.2),
        ],
    },
    {
        "id": "cuentas", "num": "10", "title": "Cuentas", "demo": False,
        "caps": [(0, "Los órganos que trabaja tu equipo: lo que publican y lo que vence.")],
        "steps": [
            S("cuentas-00-vacio.png", 1.5, click=True),
            S("cuentas-01-dialogo.png", 1.0, click=True, cam=(1.5, 960, 600)),
            *T("cuentas", "organo", every=0.12),
            S("cuentas-05-opciones.png", 0.9, click=True),
            S("cuentas-06-elegido.png", 0.9, click=True),
            S("cuentas-07-lista.png", 1.4, click=True, cam=(1.3, 640, 330)),
            S("cuentas-08-ficha.png", 3.2, cam=(1.2, 820, 460), cam_at=0.2),
        ],
    },
    {
        "id": "atajos", "num": "11", "title": "Atajos", "demo": False,
        "caps": [(0, "⌘K para ir a cualquier sitio: páginas, expedientes y órganos.")],
        "steps": [
            S("paleta-00-abierta.png", 1.3, cam=(1.4, 960, 520)),
            S("paleta-01-buscando.png", 2.6),
        ],
    },
    {
        "id": "equipo", "num": "12", "title": "Equipo y seguridad", "demo": False,
        "caps": [(0, "Equipos con roles, verificación en dos pasos y claves de API.")],
        "steps": [
            S("equipo-00-equipo.png", 2.8, cam=(1.3, 760, 720), cam_at=0.3),
            S("equipo-01-seguridad.png", 1.9, cam=(1.4, 760, 380)),
            S("equipo-02-claves.png", 1.9, cam=(1.3, 900, 360)),
        ],
    },
    {
        "id": "resumen", "num": "13", "title": "Resumen", "demo": False,
        "caps": [(0, "Cada mañana, lo que vence esta semana y lo que ha cambiado.")],
        "steps": [S("resumen1-00-resumen.png", 4.4, cam=(1.35, 900, 800), cam_at=0.6)],
    },
]

INTRO_DUR = snap_up(4.0)
OUTRO_LEN = 6.0
PAD_IN, PAD_OUT = 0.35, 0.35

# --------------------------------------------------------------------------
FONT_FACES = """    @font-face { font-family: "Geist"; src: url("assets/fonts/Geist-Variable.woff2") format("woff2"); font-weight: 100 900; }
    @font-face { font-family: "Geist Mono"; src: url("assets/fonts/GeistMono-Variable.woff2") format("woff2"); font-weight: 100 900; }
    @font-face { font-family: "Fraunces"; src: url("assets/fonts/Fraunces-opsz.woff2") format("woff2"); font-weight: 100 900; }"""

CURSOR = '<path d="M3 2 L3 34 L11 26.5 L16.5 39 L22 36.5 L16.6 24.4 L27.5 24 Z" fill="#f4f1ec" stroke="#0e0d0c" stroke-width="2.2" stroke-linejoin="round" />'


def cam_xy(z, fx, fy):
    s = FIT * z
    x = FRAME[2] / 2 - fx * s
    y = FRAME[3] / 2 - fy * s
    x = min(0, max(FRAME[2] - 1920 * s, x))
    y = min(0, max(FRAME[3] - 1080 * s, y))
    return round(x, 1), round(y, 1), round(s, 4)


def words(text, cls="w"):
    return " ".join(f'<span class="{cls}">{escape(w)}</span>' for w in text.split())


SHOT_DIR = OUT / "assets" / "shots"
SHOT_DIR.mkdir(parents=True, exist_ok=True)
(OUT / "compositions").mkdir(parents=True, exist_ok=True)
usados = set()

audio_clicks = []  # tiempos globales de clic
audio_keys = []  # tiempos globales de tecla
hosts = []

t_global = INTRO_DUR
for cap in CAPS:
    cid = cap["id"]
    # tiempos locales de cada estado
    t = PAD_IN
    for st in cap["steps"]:
        st["start"] = round(t, 3)
        t += st["dur"]
    contenido = t
    dur = round(snap_up(t_global + contenido + PAD_OUT) - t_global, 3)
    extra = dur - (contenido + PAD_OUT)
    cap["steps"][-1]["dur"] += extra
    cap["dur"] = dur
    cap["start"] = round(t_global, 3)

    imgs, js = [], []
    # cámara inicial
    x0, y0, s0 = cam_xy(1.0, 960, 540)
    js.append(f'tl.set("#{cid}-cam", {{ x: {x0}, y: {y0}, scale: {s0} }}, 0);')
    cur = None  # posición del cursor (coords imagen)
    cursor_visible = False
    first_click_t = None
    for i, st in enumerate(cap["steps"]):
        f = st["img"]
        usados.add(f)
        jpg = f.replace(".png", ".jpg")
        start = st["start"] if i else 0.0
        end = round(st["start"] + st["dur"], 3)
        imgs.append(
            f'<img id="{cid}-i{i}" class="clip shot" data-start="{start}" data-duration="{round(end - start, 3)}" '
            f'src="assets/shots/{jpg}" alt="" />'
        )
        if st["cam"]:
            z, fx, fy = st["cam"]
            x, y, s = cam_xy(z, fx, fy)
            pantalla_nueva = i > 0 and not cap["steps"][i - 1]["click"] and st["cam_at"] == 0
            if pantalla_nueva:
                # Pantalla nueva sin clic que la cause: la cámara se coloca con el corte.
                js.append(f'tl.set("#{cid}-cam", {{ x: {x}, y: {y}, scale: {s} }}, {st["start"]});')
            else:
                js.append(
                    f'tl.to("#{cid}-cam", {{ x: {x}, y: {y}, scale: {s}, duration: 0.7, ease: "power2.inOut" }}, {round(st["start"] + st["cam_at"], 3)});'
                )
        if st["click"]:
            tgt = FILES[f]["target"]
            cx = tgt["x"] + min(tgt["w"] / 2, 60) if tgt["w"] > 300 else tgt["x"] + tgt["w"] / 2
            cy = tgt["y"] + tgt["h"] / 2
            t_click = round(end - 0.08, 3)
            mov = min(0.65, max(0.25, st["dur"] - 0.3))
            if cur is None:
                cur = (cx + 260, cy + 220)
                js.append(f'tl.set("#{cid}-cur", {{ x: {cur[0] - 3}, y: {cur[1] - 2} }}, 0);')
            if not cursor_visible:
                js.append(f'tl.fromTo("#{cid}-cur", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.15, ease: "none" }}, {round(t_click - mov - 0.15, 3)});')
                cursor_visible = True
            js.append(
                f'tl.to("#{cid}-cur", {{ x: {round(cx - 3, 1)}, y: {round(cy - 2, 1)}, duration: {mov}, ease: "power3.inOut" }}, {round(t_click - mov - 0.04, 3)});'
            )
            js.append(f'tl.to("#{cid}-cur", {{ scale: 0.86, duration: 0.05, ease: "power2.in", transformOrigin: "3px 2px" }}, {round(t_click - 0.05, 3)});')
            js.append(f'tl.to("#{cid}-cur", {{ scale: 1, duration: 0.12, ease: "power2.out", transformOrigin: "3px 2px" }}, {t_click});')
            cur = (cx, cy)
            audio_clicks.append(round(cap["start"] + t_click, 3))
        if "-t" in f and "-t0" in f or "-t1" in f:
            pass
        if any(p.startswith("t") and p[1:4].isdigit() for p in f[:-4].split("-")):
            audio_keys.append(round(cap["start"] + start, 3))
    if cursor_visible:
        js.append(f'tl.to("#{cid}-cur", {{ opacity: 0, duration: 0.2, ease: "power2.in" }}, {round(cap["steps"][-1]["start"] + 0.4, 3)});')

    # rótulos
    caps_html = []
    for j, (tc, texto) in enumerate(cap["caps"]):
        t0 = 0.0 if j == 0 else tc
        t1 = cap["caps"][j + 1][0] if j + 1 < len(cap["caps"]) else dur
        caps_html.append(
            f'<p id="{cid}-cap{j}" class="clip cap" data-start="{t0}" data-duration="{round(t1 - t0, 3)}">{words(texto)}</p>'
        )
        tin = 0.25 if j == 0 else tc + 0.12
        js.append(
            f'tl.fromTo("#{cid}-cap{j} .w", {{ opacity: 0, filter: "blur(6px)" }}, {{ opacity: 1, filter: "blur(0px)", duration: 0.14, ease: "power4.out", stagger: 0.04 }}, {round(tin, 3)});'
        )
        tout = (t1 - 0.2) if j + 1 < len(cap["caps"]) else dur - 0.22
        js.append(f'tl.to("#{cid}-cap{j}", {{ opacity: 0, filter: "blur(6px)", duration: 0.16, ease: "power3.in" }}, {round(tout, 3)});')

    demo_html = (
        f'<p id="{cid}-demo" class="clip demo" data-start="0" data-duration="{dur}">Datos de demostración</p>' if cap["demo"] else ""
    )
    html = f"""<template>
  <style>
{FONT_FACES}
    #root {{ position: absolute; inset: 0; overflow: hidden; background: #0e0d0c; color: hsl(36 12% 93%); font-family: "Geist", sans-serif; }}
    .lbl {{ position: absolute; left: 192px; top: 34px; display: flex; align-items: baseline; gap: 18px; }}
    .lbl .n {{ font-family: "Geist Mono", monospace; font-size: 30px; color: #f39349; letter-spacing: 0.06em; }}
    .lbl .t {{ font-family: "Fraunces", Georgia, serif; font-size: 58px; font-weight: 540; letter-spacing: -0.02em; line-height: 1; }}
    .lbl .w {{ display: inline-block; }}
    .frame {{ position: absolute; left: {FRAME[0]}px; top: {FRAME[1]}px; width: {FRAME[2]}px; height: {FRAME[3]}px; border-radius: 16px; overflow: hidden; background: #0f0e0d; box-shadow: 0 0 0 1.5px hsla(34, 12%, 60%, 0.22), 0 30px 80px -30px rgba(0, 0, 0, 0.9); }}
    .cam {{ position: absolute; left: 0; top: 0; width: 1920px; height: 1080px; transform-origin: 0 0; }}
    .shot {{ position: absolute; left: 0; top: 0; width: 1920px; height: 1080px; }}
    .cur {{ position: absolute; left: 0; top: 0; width: 42px; height: 54px; }}
    .cap {{ position: absolute; left: 192px; right: 192px; top: 1006px; font-size: 32px; font-weight: 500; letter-spacing: -0.005em; }}
    .cap .w {{ display: inline-block; }}
    .demo {{ position: absolute; right: 192px; top: 52px; font-size: 24px; color: hsl(34 8% 65%); }}
  </style>
  <div id="root" data-composition-id="{cid}" data-width="1920" data-height="1080">
    <div id="{cid}-lbl" class="clip lbl" data-start="0" data-duration="{dur}"><span class="n">{cap["num"]}</span><span class="t">{words(cap["title"])}</span></div>
    <div id="{cid}-frame" class="clip frame" data-start="0" data-duration="{dur}" data-layout-allow-overflow>
      <div id="{cid}-cam" class="cam">
        {chr(10).join("        " + h for h in imgs).strip()}
        <svg id="{cid}-cur" class="clip cur" data-start="0" data-duration="{dur}" viewBox="0 0 34 44" aria-hidden="true">{CURSOR}</svg>
      </div>
    </div>
    {chr(10).join("    " + h for h in caps_html).strip()}
    {demo_html}
  </div>
  <script>
    (function () {{
      const tl = gsap.timeline({{ paused: true }});
      // Entrada: el marco llega con desenfoque sobre el mismo fondo; el rótulo, palabra a palabra.
      tl.fromTo("#{cid}-frame", {{ opacity: 0, y: 18, filter: "blur(10px)" }}, {{ opacity: 1, y: 0, filter: "blur(0px)", duration: 0.45, ease: "expo.out" }}, 0);
      tl.fromTo("#{cid}-lbl .n, #{cid}-lbl .w", {{ opacity: 0, filter: "blur(6px)" }}, {{ opacity: 1, filter: "blur(0px)", duration: 0.14, ease: "power4.out", stagger: 0.067 }}, 0.05);
      {"tl.fromTo('#" + cid + "-demo', { opacity: 0 }, { opacity: 1, duration: 0.3, ease: 'power2.out' }, 0.3);" if cap["demo"] else ""}
      // Cámara, cursor (sobre la caja real del elemento pulsado) y rótulos.
      {(chr(10) + "      ").join(js)}
      // Salida.
      tl.to("#{cid}-frame, #{cid}-lbl{", #" + cid + "-demo" if cap["demo"] else ""}", {{ opacity: 0, filter: "blur(10px)", duration: 0.2, ease: "power3.in" }}, {round(dur - 0.22, 3)});
      window.__timelines["{cid}"] = tl;
    }})();
  </script>
</template>
"""
    (OUT / "compositions" / f"{cid}.html").write_text(html, encoding="utf-8")
    hosts.append((cid, cap["start"], dur))
    t_global = round(t_global + dur, 3)

OUTRO_START = t_global
TOTAL = round(snap_up(OUTRO_START + OUTRO_LEN), 3)
OUTRO_DUR = round(TOTAL - OUTRO_START, 3)

# --------------------------------------------------------------------------
# Apertura y cierre
INTRO = f"""<template>
  <style>
{FONT_FACES}
    #root {{ position: absolute; inset: 0; overflow: hidden; background: #0e0d0c; color: hsl(36 12% 93%); font-family: "Geist", sans-serif; }}
    #in-halo {{ position: absolute; left: 560px; top: 90px; width: 800px; height: 640px; border-radius: 50%; background: radial-gradient(ellipse, rgba(243, 147, 73, 0.28) 0%, rgba(243, 147, 73, 0.1) 40%, rgba(243, 147, 73, 0) 70%); }}
    #in-brand {{ position: absolute; left: 0; right: 0; top: 330px; display: flex; justify-content: center; align-items: center; gap: 34px; }}
    #in-box {{ width: 156px; height: 156px; border-radius: 40px; background: #f39349; display: flex; align-items: center; justify-content: center; }}
    #in-box svg {{ width: 90px; height: 90px; overflow: visible; }}
    #in-box path {{ fill: none; stroke: #1a130d; stroke-width: 2.7; stroke-linecap: round; }}
    #in-word {{ font-size: 108px; font-weight: 650; letter-spacing: -0.035em; }}
    #in-sub {{ position: absolute; left: 0; right: 0; top: 560px; text-align: center; font-family: "Fraunces", Georgia, serif; font-size: 64px; font-weight: 500; letter-spacing: -0.015em; }}
    #in-sub .w {{ display: inline-block; }}
    #in-kick {{ position: absolute; left: 0; right: 0; top: 670px; text-align: center; font-family: "Geist Mono", monospace; font-size: 28px; letter-spacing: 0.12em; color: hsl(34 8% 65%); }}
  </style>
  <div id="root" data-composition-id="intro" data-width="1920" data-height="1080">
    <div id="in-halo" class="clip" data-start="0" data-duration="{INTRO_DUR}" data-layout-ignore></div>
    <div id="in-brand" class="clip" data-start="0" data-duration="{INTRO_DUR}">
      <div id="in-box"><svg viewBox="0 0 24 24" aria-hidden="true"><path id="in-p1" d="M3.5 6 H20.5" pathLength="1" /><path id="in-p2" d="M12 6 V19" pathLength="1" /><path id="in-p3" d="M12 12 H18.5" pathLength="1" /></svg></div>
      <div id="in-word">TenderFlow</div>
    </div>
    <h1 id="in-sub" class="clip" data-start="0" data-duration="{INTRO_DUR}">{words("Recorrido por el producto")}</h1>
    <p id="in-kick" class="clip" data-start="0" data-duration="{INTRO_DUR}">LICITACIONES TI · SECTOR PÚBLICO ESPAÑOL</p>
  </div>
  <script>
    (function () {{
      const tl = gsap.timeline({{ paused: true }});
      tl.fromTo("#in-halo", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.8, ease: "power2.out" }}, 0);
      tl.fromTo("#in-box", {{ scale: 0.7, opacity: 0, filter: "blur(10px)" }}, {{ scale: 1, opacity: 1, filter: "blur(0px)", duration: 0.55, ease: "expo.out" }}, 0.1);
      ["#in-p1", "#in-p2", "#in-p3"].forEach(function (p, i) {{
        tl.fromTo(p, {{ strokeDasharray: 1, strokeDashoffset: 1 }}, {{ strokeDashoffset: 0, duration: 0.22, ease: "power3.out" }}, 0.22 + i * 0.12);
      }});
      tl.fromTo("#in-word", {{ opacity: 0, filter: "blur(8px)" }}, {{ opacity: 1, filter: "blur(0px)", duration: 0.2, ease: "power4.out" }}, 0.3);
      tl.fromTo("#in-sub .w", {{ opacity: 0, filter: "blur(6px)" }}, {{ opacity: 1, filter: "blur(0px)", duration: 0.14, ease: "power4.out", stagger: 0.067 }}, 0.75);
      tl.fromTo("#in-kick", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.4, ease: "power2.out" }}, 1.1);
      tl.to("#in-brand, #in-sub, #in-kick, #in-halo", {{ opacity: 0, filter: "blur(10px)", duration: 0.22, ease: "power3.in" }}, {round(INTRO_DUR - 0.24, 3)});
      window.__timelines["intro"] = tl;
    }})();
  </script>
</template>
"""
(OUT / "compositions" / "intro.html").write_text(INTRO, encoding="utf-8")

OUTRO = INTRO.replace('"intro"', '"outro"').replace("in-", "out-")
OUTRO = OUTRO.replace(f'data-duration="{INTRO_DUR}"', f'data-duration="{OUTRO_DUR}"')
OUTRO = OUTRO.replace(words("Recorrido por el producto"), words("Dónde pujar, a qué precio, contra quién."))
OUTRO = OUTRO.replace("LICITACIONES TI · SECTOR PÚBLICO ESPAÑOL", '<span id="out-btn">Solicita acceso</span><span id="out-url">tenderflow.es</span>')
OUTRO = OUTRO.replace(
    "#out-kick {",
    '#out-btn { font-family: "Geist", sans-serif; letter-spacing: 0; background: #f39349; color: hsl(30 30% 8%); font-size: 34px; font-weight: 650; border-radius: 14px; padding: 18px 36px; margin-right: 30px; }\n    #out-url { font-size: 30px; letter-spacing: 0; }\n    #out-kick {',
)
OUTRO = OUTRO.replace("top: 670px; text-align: center;", "top: 690px; text-align: center;")
OUTRO = OUTRO.replace(
    f'tl.to("#out-brand, #out-sub, #out-kick, #out-halo", {{ opacity: 0, filter: "blur(10px)", duration: 0.22, ease: "power3.in" }}, {round(INTRO_DUR - 0.24, 3)});',
    "",
)
OUTRO = OUTRO.replace("<p id=\"out-kick\"", "<div id=\"out-kick\"").replace("tenderflow.es</span></p>", "tenderflow.es</span></div>")
(OUT / "compositions" / "outro.html").write_text(OUTRO, encoding="utf-8")

# --------------------------------------------------------------------------
# Capturas: png -> jpg de calidad alta
for f in sorted(usados):
    dst = SHOT_DIR / f.replace(".png", ".jpg")
    if not dst.exists():
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(SHOTS / f), "-q:v", "2", str(dst)], check=True)

# Sonido
for sub, files in {"ui": ["click2.ogg", "mouseclick1.ogg"], "interface": ["bong_001.ogg"], "keyboard": ["keypress-003.wav", "keypress-011.wav", "keypress-019.wav", "keypress-027.wav"]}.items():
    (OUT / "assets" / "sfx" / sub).mkdir(parents=True, exist_ok=True)
    for fn in files:
        shutil.copy(BRAG / "sfx" / sub / fn, OUT / "assets" / "sfx" / sub / fn)
(OUT / "assets" / "music").mkdir(parents=True, exist_ok=True)
shutil.copy(BRAG / "music" / "happy-beats-business-moves-vol-1-by-ende-dot-app.mp3", OUT / "assets" / "music")

audio = []
for i, t in enumerate(audio_clicks):
    src = ["ui/click2.ogg", "ui/mouseclick1.ogg"][i % 2]
    audio.append(f'<audio id="clic-{i}" class="clip" data-start="{t}" data-duration="0.06" data-track-index="{11 + i % 2}" data-volume="0.55" src="assets/sfx/{src}"></audio>')
for i, t in enumerate(audio_keys):
    src = ["keypress-003.wav", "keypress-011.wav", "keypress-019.wav", "keypress-027.wav"][i % 4]
    audio.append(f'<audio id="tecla-{i}" class="clip" data-start="{t}" data-duration="0.25" data-track-index="{13 + i % 4}" data-volume="0.28" src="assets/sfx/keyboard/{src}"></audio>')
audio.append(f'<audio id="acento-in" class="clip" data-start="0.12" data-duration="0.13" data-track-index="17" data-volume="0.55" src="assets/sfx/interface/bong_001.ogg"></audio>')
audio.append(f'<audio id="acento-out" class="clip" data-start="{round(OUTRO_START + 0.12, 3)}" data-duration="0.13" data-track-index="18" data-volume="0.55" src="assets/sfx/interface/bong_001.ogg"></audio>')

host_html = [
    f'<div id="intro" data-composition-id="intro" data-composition-src="compositions/intro.html" data-start="0" data-duration="{INTRO_DUR}" data-track-index="1" data-track-kind="graphics" data-width="1920" data-height="1080"></div>'
]
for cid, st, d in hosts:
    host_html.append(
        f'<div id="{cid}" data-composition-id="{cid}" data-composition-src="compositions/{cid}.html" data-start="{st}" data-duration="{d}" data-track-index="1" data-track-kind="graphics" data-width="1920" data-height="1080"></div>'
    )
host_html.append(
    f'<div id="outro" data-composition-id="outro" data-composition-src="compositions/outro.html" data-start="{OUTRO_START}" data-duration="{OUTRO_DUR}" data-track-index="1" data-track-kind="graphics" data-width="1920" data-height="1080"></div>'
)

INDEX = f"""<!doctype html>
<html lang="es" data-resolution="landscape" data-composition-variables='[
    {{"id":"color-ground","type":"color","label":"Fondo","default":"#0E0D0C"}},
    {{"id":"color-ink","type":"color","label":"Texto","default":"#EFEDEA"}},
    {{"id":"color-accent","type":"color","label":"Acento","default":"#F39349"}},
    {{"id":"font-display","type":"string","label":"Titulares","default":"Fraunces"}}
  ]'>
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1920, height=1080" />
    <title>TenderFlow · demo del producto</title>
    <script src="assets/vendor/gsap.min.js"></script>
    <style>
{FONT_FACES}
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ width: 1920px; height: 1080px; overflow: hidden; background: #0e0d0c; }}
      #ground {{ position: absolute; inset: 0; background: #0e0d0c; }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{TOTAL}" data-width="1920" data-height="1080">
      <div id="ground"></div>
      {(chr(10) + "      ").join(host_html)}
      <audio id="bg-music" class="clip" data-start="0" data-duration="{TOTAL}" data-track-index="10" data-volume="0.34" data-fade-out="2.5" src="assets/music/happy-beats-business-moves-vol-1-by-ende-dot-app.mp3"></audio>
      {(chr(10) + "      ").join(audio)}
    </div>
    <script>
      const tl = gsap.timeline({{ paused: true }});
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
"""
(OUT / "index.html").write_text(INDEX, encoding="utf-8")
print("total", TOTAL, "capitulos", [(c, s, d) for c, s, d in hosts], "clics", len(audio_clicks), "teclas", len(audio_keys), "capturas", len(usados))

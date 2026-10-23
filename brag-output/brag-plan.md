# Brag Plan: TenderFlow

## What is this app?
Un radar de concursos públicos de tecnología en España: reúne PLACSP, TED y los canales
autonómicos, se queda solo con lo que tiene señal TI y le dice a un equipo comercial
dónde pujar, a qué precio y contra quién.

## The angle
El sector público español publica de todo —firmes de carretera, material de curas,
limpieza de edificios— y un responsable de ofertas de un partner SAP/Salesforce/Microsoft
tiene que encontrar los suyos. El vídeo empieza en ese muro de anuncios y deja que el
producto lo ordene: filtra, puntúa, propone precio y nombra al rival. La promesa entera
del producto cabe en su propio titular —«dónde pujar, a qué precio, contra quién»— y el
vídeo lo usa como esqueleto: cada una de las tres frases es un capítulo que se demuestra
con la consola funcionando.

## Hook (first 2-3 seconds)
Un muro de anuncios de licitación que sube sin parar (chips de fuente PLACSP, TED,
Galicia, Euskadi), casi todos de obra, sanidad o suministros. Encima, en Fraunces grande:
«¿A cuál te presentas?». La pregunta que el producto contesta, antes de nombrarlo.

## Key moments (the middle)
- El filtro: los anuncios que no son tecnología se apagan y caen; los que quedan se
  encienden en naranja con el motivo por el que entraron (ERP, cloud, software…).
- La bandeja del Radar: los expedientes llegan ordenados por score con su banda
  (Caliente / Atractiva), el cursor abre uno y el desglose de las seis dimensiones
  (Importe, Plazo, Competencia, Margen, Señal técnica, Riesgo) se pinta en el panel.
- Escenarios de precio: Defensivo / Central / Competitivo con su baja, «Muestra robusta»,
  y el clic en «Usar como oferta prevista» que se convierte en «Es la oferta prevista».
- Competencia esperada: «~5 ofertas esperadas», quién lo tiene hoy (Incumbente) y contra
  quién, con expedientes, cuota y baja mediana de cada rival.

## Outro / punchline
El monograma TF se dibuja con sus tres trazos, «TenderFlow», y el CTA real del producto:
«Solicita acceso» · tenderflow.es. Debajo, la acotación honesta de la landing en pequeño
no cabe; el cierre es el CTA y el dominio.

## User flow worth showing
Entrada → acción clave → resultado, tal como lo vive un usuario en la consola:
1. Abre la bandeja del Radar (triaje diario ordenado por score).
2. Abre un expediente y lee de dónde sale su puntuación.
3. Fija un precio desde los escenarios y ve contra quién compite.

## Tone
- Preset: polished
- Creative direction: «informe de mercado de prensa económica» — el carácter que
  DESIGN.md pide (papel cálido/consola densa, un solo acento, Fraunces del linaje de la
  prensa económica, «nada se mueve si no explica algo»).
- Interpretation: pocas escenas con holds largos, movimiento con causa (filas que llegan,
  barras que se rellenan, clics), transiciones suaves de blur/fundido; nada de rebotes ni
  pulsos; humor cero salvo la sequedad del muro de anuncios ajenos.

## Format: landscape — 1920x1080, 30 fps
## Duration: 23 s

## Visual identity (from the project)
- Background: `hsl(30 8% 5%)` = `#0E0D0C` (tema oscuro, `--background`; `MARCA_HEX.tinta`)
- Card: `hsl(30 8% 8%)`; muted `hsl(30 7% 15%)`; border `hsl(34 12% 60% / 0.22)`
- Accent: `hsl(26 88% 62%)` = `#F39349` (`--primary` oscuro; `MARCA_HEX.naranja`)
- Text: `hsl(36 12% 93%)`; secundario `hsl(34 8% 65%)`
- Score: hot `hsl(0 75% 58%)`, warm `hsl(45 90% 55%)`; success `hsl(152 60% 45%)`; info `hsl(207 90% 64%)`
- Display font: Fraunces (eje óptico), solo titulares
- Body font: Geist; Geist Mono para expediente, CPV e identificadores
- Strongest visual element: la bandeja del Radar con el panel de desglose de score
  (`web/src/app/(publico)/_assets/radar-hero.webp`, la captura que enseña la landing)

## Share copy (draft)
Dónde pujar, a qué precio y contra quién: TenderFlow lee PLACSP, TED, Galicia y Euskadi,
se queda solo con las licitaciones de tecnología y te las ordena cada mañana.

## Audio direction
- Role: warm bed + sparse professional accents
- Music: `happy-beats-business-moves-vol-12-by-ende-dot-app.mp3` (steady and clean; ~110 BPM)
- Music treatment: entra desde 0 s a volumen de cama (~0.32), fade-out bajo el cierre
  (21.8 → 23.0 s), terminando cerca del strong cue de 22.93 s.
- Music cue guidance: preset `assets/music/cues/happy-beats-business-moves-vol-12-by-ende-dot-app.music-cues.json`
  leído. Tempo 109.96 BPM (beat ≈ 0.546 s). Strong cues usables: 8.74 s, 17.47 s, 22.93 s.
  Beat grid para secuencias: filas del Radar desde 9.83 s; tarjetas de escenario en
  14.20 / 15.29 / 16.38 (un beat de cada dos, por legibilidad); rivales 18.02 / 18.56 / 19.10.
- Audio-reactive treatment: subtle; el RMS/graves de la música hace respirar el halo
  naranja detrás del monograma y la presencia del panel de detalle. Nada de barras ni ondas.
- SFX posture: sparse (polished): 4–6 en total, con causa visible.
- Audio-coupled moments: el apagado del muro (un golpe suave), el clic del cursor en la
  fila y en «Usar como oferta prevista», la llegada del monograma.
- Restraint rule: ningún SFX repetido en cada fila o tarjeta; nada brillante ni metálico.

## Storyboard

Cortes en el beat grid del preset (≈0.546 s).

### Scene 1 — El muro — 0.00–3.27 s (3.27 s)
Cuatro columnas de tarjetas de anuncio subiendo a velocidad constante: chip de fuente
(PLACSP / TED / Galicia / Euskadi), título y órgano. Mezcla de no-TI («Reparación del firme…»,
«Suministro de material de curas», «Limpieza de edificios municipales») con los expedientes
TI de demostración del seed. Encima, en Fraunces ~96 px: «¿A cuál te presentas?», con
«cuál» en naranja; entra palabra a palabra con blur, hold ≥ 2 s.
Sequential/interaction: las tarjetas fluyen; el titular entra por palabras.
Audio intent: la cama arranca, sin acentos; el muro es ruido de fondo.
Audio-coupled idea: none.
Transition mood: soft → Scene 2 (el titular sale con blur; el muro sigue).

### Scene 2 — El filtro — 3.27–6.00 s (2.73 s)
El mismo muro se congela. Las tarjetas sin señal TI bajan a ~12 % y se desenfocan; las de
tecnología se encienden con borde naranja y el chip del motivo («ERP», «cloud», «software»).
Texto (verbatim de la landing, recortado): «Solo entra el expediente con señal de tecnología.»
Hold ≈ 2.1 s.
Sequential/interaction: las tarjetas TI se encienden una a una (rápido, ~60 ms).
Audio intent: un golpe cálido cuando el muro se apaga.
Audio-coupled idea: impact suave al inicio del apagado.
Transition mood: soft → Scene 3 (lo apagado se funde a fondo; quedan las naranjas y vuelan).

### Scene 3 — Reveal — 6.00–9.29 s (3.29 s)
El monograma TF (los tres trazos de `TF_MARK_PATHS`) se dibuja en su caja naranja, al lado
«TenderFlow». Debajo, en Fraunces, el titular del producto por frases:
«Dónde pujar, · a qué precio, · contra quién.» Hold ≥ 2.3 s.
Sequential/interaction: tres frases, ~0.25 s entre ellas, luego quieto.
Audio intent: presencia; el halo del logo respira con la música.
Audio-coupled idea: acento suave en la llegada del logo.
Transition mood: clean → Scene 4 (blur swap; «Dónde pujar» queda como rótulo de capítulo).

### Scene 4 — Dónde pujar: el Radar — 9.29–13.64 s (4.35 s)
Consola recreada en el tema oscuro: rail lateral, pestañas «Bandeja 12 · Siguiendo ·
Descartadas · Todas», cabecera SCORE / LICITACIÓN / ÓRGANO / TECNOLOGÍA / IMPORTE / PLAZO.
Seis filas del seed llegan escalonadas (79 Caliente, 76 Caliente, 73 Atractiva…) con su
barra de plazo. El cursor baja a «Implantación de sistema ERP para gestión municipal»
(SEED-2026-008, 76), clic, se abre el panel de detalle: banda Caliente, órgano, importe
890.000 €, y el «Desglose de score» con seis barras que se rellenan.
Rótulo de capítulo arriba a la izquierda: «Dónde pujar». Esquina: «Datos de demostración».
Sequential/interaction: filas escalonadas (40–80 ms, son textura hasta que se fijan);
cursor + clic; barras del desglose una tras otra.
Audio intent: la cama manda; un clic con causa.
Audio-coupled idea: clic del cursor.
Transition mood: soft → Scene 5 (el panel de detalle se lleva al centro y se convierte en
la pestaña de precio).

### Scene 5 — A qué precio — 13.64–17.47 s (3.83 s)
Panel «Escenarios de precio» con badge «Muestra robusta» y la línea
«Cuantiles de bajas observadas en adjudicaciones comparables.» Tres tarjetas llegan en beats
alternos: Defensivo (Baja 8,0 %), Central (Baja 14,0 %), Competitivo (Baja 21,0 %) sobre
890.000 €. Pie: «Comparables por: mismo órgano · mismo CPV (4 dígitos) · importe parecido».
El cursor pulsa «Usar como oferta prevista» en Central → cambia a «✓ Es la oferta prevista».
Rótulo: «A qué precio».
Sequential/interaction: tarjetas una a una (beat sí, beat no) + clic.
Audio intent: clic + pequeño acento de confirmación.
Audio-coupled idea: clic del botón.
Transition mood: clean → Scene 6 (whip horizontal corto).

### Scene 6 — Contra quién — 17.47–20.19 s (2.72 s)  ← beat-locked 17.47
Bloque «Competencia esperada»: «Cuántos se presentarán: ~5 ofertas esperadas»; «Quién lo
tiene hoy» con badge «Incumbente»; «Contra quién»: tres rivales con «N exp. · cuota %» y
«Baja mediana X %». Nombres de empresa ficticios (ver nota de datos).
Rótulo: «Contra quién».
Sequential/interaction: rivales uno a uno en el beat grid y luego quietos.
Audio intent: la música empuja; sin SFX por fila.
Audio-coupled idea: none.
Transition mood: dramatic-soft → Scene 7 (dip a fondo).

### Scene 7 — Cierre — 20.19–23.00 s (2.81 s)
Monograma TF + «TenderFlow», debajo «Licitaciones TI del sector público español» y el CTA
de la landing como botón naranja: «Solicita acceso», y «tenderflow.es». Hold ≥ 2.3 s.
Audio intent: llegada del logo y fade-out de la música.
Audio-coupled idea: acento cálido de logo.

**Music mood for this video:** upbeat-restrained (corporate clean)
**Audio summary:** cama limpia y constante de principio a fin, un golpe cuando el muro se
apaga, dos clics con causa en la consola y un acento final bajo el logo mientras la música cae.

## Nota sobre datos
Todo lo que aparece dentro de la consola es dato de demostración: los expedientes
`SEED-2026-0xx` salen de `scripts/seed_dev.py` / la captura de la landing; los importes de los
escenarios y del desglose son ilustrativos. Los nombres de empresa rivales son ficticios
(«Integra Sistemas», «Nubalia Consulting», «Datatec Norte»): el producto muestra adjudicatarios
reales, que no se enseñan en un vídeo público. El vídeo lo dice con «Datos de demostración»
en la esquina, igual que la landing («Los expedientes de la imagen son datos de demostración»).

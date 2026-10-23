# Hyperframes Composition Brief: TenderFlow

## Objective
Create a short launch-style brag video for TenderFlow.

## Output
- Composition directory: `brag-output/composition/`
- Rendered video: `brag-output/brag.mp4`
- Format: landscape — 1920x1080, 30 fps
- Duration: 23 s

## Source Material
- Project root: `/home/user/TenderFlow`
- Primary files read: `README.md`, `DESIGN.md`, `web/src/app/globals.css` (tema `.dark`),
  `web/src/lib/tipografia.ts`, `web/src/lib/marca.ts`,
  `web/src/app/(publico)/_content/landing.ts`, `web/src/app/(publico)/_assets/radar-hero.webp`,
  `web/e2e/capturas-landing.spec.ts`, `scripts/seed_dev.py`,
  `web/src/components/pursuits/price-scenarios.tsx`, `web/src/components/competencia-esperada.tsx`
- Product name: TenderFlow
- Tagline / strongest claim: «Licitaciones TI: dónde pujar, a qué precio, contra quién»
- Key UI moment to recreate: la bandeja del Radar + panel «Desglose de score»; el panel
  «Escenarios de precio»; el bloque «Competencia esperada».
- Copy that must appear verbatim:
  - «Dónde pujar» · «A qué precio» · «Contra quién» (los tres pilares de la landing)
  - «Solo entra el expediente con señal de tecnología.»
  - «Escenarios de precio», «Muestra robusta», «Usar como oferta prevista», «Es la oferta prevista»
  - «Cuantiles de bajas observadas en adjudicaciones comparables.»
  - «Competencia esperada», «Cuántos se presentarán», «Quién lo tiene hoy», «Incumbente», «Baja mediana»
  - «Solicita acceso»
  - «Datos de demostración»

## Creative Direction
- Tone preset: polished
- Creative direction: informe de mercado de prensa económica
- Interpretation: holds largos, movimiento solo con causa, sin rebotes ni pulsos; titulares
  en Fraunces quietos una vez aterrizan; la consola en su tema oscuro real.
- Angle: el muro de anuncios del sector público, y el producto ordenándolo en las tres
  decisiones de su titular, cada una demostrada con la consola funcionando.
- Hook: muro de anuncios subiendo + «¿A cuál te presentas?»
- Outro / punchline: monograma TF, «TenderFlow», «Solicita acceso», tenderflow.es
- Avoid:
  - Generic SaaS language
  - Abstract filler visuals
  - Unrelated visual redesign
  - Cifras de clientes, ahorro o probabilidad de ganar (la landing lo prohíbe expresamente)

## Visual Identity
- Background: `#0E0D0C` (`hsl(30 8% 5%)`)
- Card: `hsl(30 8% 8%)`; muted `hsl(30 7% 15%)`; border `hsla(34,12%,60%,0.22)`
- Text: `hsl(36 12% 93%)`; muted text `hsl(34 8% 65%)`
- Accent: `#F39349` (`hsl(26 88% 62%)`), foreground on accent `hsl(30 30% 8%)`
- Score: hot `hsl(0 75% 58%)`, warm `hsl(45 90% 55%)`; success `hsl(152 60% 45%)`; info `hsl(207 90% 64%)`; warning `hsl(45 93% 56%)`
- Display font: Fraunces (variable, eje opsz) — `assets/fonts/Fraunces-opsz.woff2`
- Body font: Geist — `assets/fonts/Geist-Variable.woff2`; mono: Geist Mono — `assets/fonts/GeistMono-Variable.woff2`
- Visual references from the project: radar-hero.webp; monograma TF (`TF_MARK_PATHS`
  `M3.5 6 H20.5`, `M12 6 V19`, `M12 12 H18.5`, viewBox 24, stroke 2.7, round caps; caja
  naranja con radio 0.26 del lado, glifo al 58 %); paneles `rounded-xl` con borde; badges `rounded-md`.

## Storyboard
Use the storyboard in `brag-output/brag-plan.md` as the creative contract.

Scene summary:
1. El muro — 0.00–3.27 s — muro de anuncios + «¿A cuál te presentas?»
2. El filtro — 3.27–6.00 s — no-TI se apaga, TI se enciende; «Solo entra el expediente con señal de tecnología.»
3. Reveal — 6.00–9.29 s — monograma + «TenderFlow» + «Dónde pujar, a qué precio, contra quién.»
4. Dónde pujar — 9.29–13.64 s — bandeja del Radar, clic en SEED-2026-008, desglose de score
5. A qué precio — 13.64–17.47 s — Escenarios de precio, clic en «Usar como oferta prevista»
6. Contra quién — 17.47–20.19 s — Competencia esperada (beat-locked 17.47)
7. Cierre — 20.19–23.00 s — logo, «Solicita acceso», tenderflow.es

## Audio
- Audio role: warm bed + sparse professional accents
- Audio arc: cama constante; golpe suave al apagar el muro; clics con causa en la consola; acento bajo el logo final mientras la música cae.
- Music: `assets/music/happy-beats-business-moves-vol-12-by-ende-dot-app.mp3` (CC BY 4.0, Sascha Ende)
- Music treatment: volumen ~0.32, fade-out 21.8 → 23.0 s
- Music cue guidance: preset `<brag-skill>/assets/music/cues/happy-beats-business-moves-vol-12-by-ende-dot-app.music-cues.json`; 110 BPM; strong cues 8.74, 17.47, 22.93
- Audio-reactive treatment: subtle — RMS/graves modulan el halo naranja del monograma y la sombra del panel de detalle
- Audio-coupled moments:
  - Escena 2 — apagado del muro — impacto suave
  - Escena 4 — clic del cursor en la fila
  - Escena 5 — clic en «Usar como oferta prevista»
  - Escena 7 — llegada del logo
- SFX selection guidance: pocos y cálidos; nada metálico ni brillante; ningún sonido por fila
- SFX analysis guidance: `<brag-skill>/assets/sfx/sfx-analysis.md` (preferir HF risk bajo)
- Exact SFX choice: Hyperframes elige ficheros, tiempos y volúmenes sobre la animación hecha.
- Audio files: copiados a `brag-output/composition/assets/`

## Hyperframes Instructions
Loaded `hyperframes` (contract, `references/format.md`, `references/motion.md`,
`references/look.md`), `hyperframes-cli` and `media-use` (audio-reactive pattern). Skipped
the storyline step, `SPEC.md`, usage/history/feedback/REVIEW.md as /brag requires; `check`
is the gate. Local creation and rendering only.

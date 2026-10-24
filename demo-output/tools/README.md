# Cómo se regenera la demo

## Versión vigente: producción

1. Entorno: `tenderflowesp.vercel.app` permitido en la red y `TF_DEMO_EMAIL` / `TF_DEMO_PASSWORD` como variables (cuenta con contraseña). `TF_ORG` (por defecto 10) es la organización donde se escribe: usa una personal o de demo, nunca la de un equipo.
2. Rodaje: `node shoot_prod.mjs <dir-capturas> [escenas]`. Escribe de verdad (oportunidad, tarea, alerta, cuenta) y deja lo creado en `<dir-capturas>/creados.json`. Antes de cada captura sustituye correos y el usuario de la cuenta en el DOM.
3. Limpieza, siempre: `node limpiar_prod.mjs <dir-capturas>/creados.json`. Borra tarea, alerta y cuenta y retira la oportunidad (la API no tiene borrado de oportunidades).
4. Composición: `python3 gen_demo_prod.py <dir-capturas> ../composition <skills/brag/assets>`, y `npx hyperframes check` / `render --quality delivery` en `../composition`.

## Primera versión: stack local con el seed

`reset_db.sh` (BD `tenderflow_demo` migrada y sembrada; necesita `postgresql-16-pgvector`), API en `:8080` y web en `:3000`; rodaje con `shoot.mjs` (credenciales del seed en `web/e2e/fixtures.ts`) y composición con `gen_demo.py`.

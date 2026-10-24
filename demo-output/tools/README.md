# Cómo se regenera la demo

1. Stack local con la BD de demo: `reset_db.sh` (crea `tenderflow_demo`, migra y siembra con `scripts/seed_dev.py --with-predicciones`; necesita `postgresql-16-pgvector`), API en `:8080` (`ENV=dev APP_PROFILE=api python -m uvicorn api.app:app`) y web en `:3000` (`npm run build && npm run start` con `API_BASE_URL=http://localhost:8080`).
2. Rodaje: `DEMO_PW=… ADMIN_PW=… node shoot.mjs <dir-capturas>` con las credenciales del seed (`web/e2e/fixtures.ts`). Recorre la app real con Playwright y guarda cada estado (1920×1080) y la caja del elemento pulsado en `manifest.json`. Hace escrituras reales: ejecútalo sobre una BD recién sembrada.
3. Composición: `python3 gen_demo.py <dir-capturas> ../composition <skills/brag/assets>` escribe la composición Hyperframes (guion al principio del script).
4. `npx hyperframes check` y `npx hyperframes render --quality delivery` dentro de `../composition`.

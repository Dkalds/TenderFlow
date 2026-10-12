import { test, expect } from "@playwright/test";
import { SEED_ADJUDICATARIAS } from "./fixtures";

/**
 * Competencia: quién gana en el ámbito y el perfil de una adjudicataria.
 *
 * Con la sesión del proyecto (el usuario del seed) y no con una cuenta
 * desechable: el recorrido solo lee. Abrir un perfil no escribe nada —la
 * empresa abierta es estado de la pantalla, ni siquiera va a la URL—, así que
 * no hay nada que aislar.
 *
 * El seed trae tres adjudicaciones y ningún maestro de empresas. Por eso el
 * perfil que se abre es el de una adjudicataria «sin identidad»: sus cifras
 * del ámbito y la salida a Empresas, sin dónde gana, quién le compra ni cómo
 * le ha ido contra ti, que piden una empresa resuelta. Lo que se afirma es lo
 * que hay.
 */

const [PRIMERA, SEGUNDA] = SEED_ADJUDICATARIAS;

test("el ranking lista las adjudicatarias del seed y abre el perfil de la que se pulsa", async ({ page }) => {
  // CU-18
  await page.goto("/competencia");

  // ── Quién gana ───────────────────────────────────────────────────────────
  const ranking = page.getByRole("table", { name: /^Ranking de competidores/ });
  await expect(ranking).toBeVisible({ timeout: 20_000 });
  for (const empresa of SEED_ADJUDICATARIAS) {
    await expect(ranking.getByRole("button", { name: empresa, exact: true })).toBeVisible();
  }

  // La pantalla abre con el perfil de la primera por importe.
  const perfilInicial = page.getByRole("region", { name: `Perfil de ${PRIMERA}` });
  await expect(perfilInicial).toBeVisible();

  // ── Abrir el perfil de otra ──────────────────────────────────────────────
  const boton = ranking.getByRole("button", { name: SEGUNDA, exact: true });
  await expect(boton).toHaveAttribute("aria-pressed", "false");
  await boton.click();

  const perfil = page.getByRole("region", { name: `Perfil de ${SEGUNDA}` });
  await expect(perfil).toBeVisible();
  await expect(perfil.getByRole("heading", { level: 2, name: SEGUNDA })).toBeVisible();
  await expect(boton).toHaveAttribute("aria-pressed", "true");
  // Un perfil a la vez: el de la primera se ha ido.
  await expect(perfilInicial).toHaveCount(0);

  // Sus adjudicaciones en el ámbito, y por dónde seguir.
  await expect(perfil.getByText("Importe adjudicado")).toBeVisible();
  await expect(perfil.getByText("Expedientes ganados")).toBeVisible();
  // Empresas es una vista de este mismo espacio desde 2026-10.
  await expect(perfil.getByRole("link", { name: "Buscarla en Empresas" })).toHaveAttribute(
    "href",
    `/competencia?vista=empresas&q=${encodeURIComponent(SEGUNDA)}`,
  );

  // ── Cerrarlo ─────────────────────────────────────────────────────────────
  await perfil.getByRole("button", { name: "Cerrar perfil del competidor" }).click();
  await expect(perfil).toHaveCount(0);
  await expect(boton).toHaveAttribute("aria-pressed", "false");
});

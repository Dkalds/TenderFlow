/**
 * Tests de la migración one-shot del `localStorage` legacy
 * (`_hooks/use-legacy-rule-migration.ts`).
 *
 * Salieron de `use-watchlist-rules.test.tsx` cuando la migración se separó a su
 * propio módulo: es el único trozo de esta pantalla que puede **borrar reglas
 * del usuario**, y lo que se protege aquí es exactamente eso —que un 403 no
 * vacíe el legacy— además del guard contra el doble montaje de StrictMode.
 */
import { describe, it, expect, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import {
  legacyToBody,
  migrateLegacyRules,
  useLegacyRuleMigration,
  type LegacyMigrationDeps,
  type LegacyRule,
} from "../_hooks/use-legacy-rule-migration";

describe("legacyToBody", () => {
  it("traduce las frecuencias en castellano del formato viejo", () => {
    expect(legacyToBody({ frequency: "inmediata" }).frequency).toBe("immediate");
    expect(legacyToBody({ frequency: "diaria" }).frequency).toBe("daily");
    expect(legacyToBody({ frequency: "semanal" }).frequency).toBe("weekly");
  });

  it("sin frecuencia, diaria; con una desconocida, también", () => {
    expect(legacyToBody({}).frequency).toBe("daily");
    expect(
      legacyToBody({ frequency: "mensual" as LegacyRule["frequency"] }).frequency,
    ).toBe("daily");
  });

  it("renombra cpvFilter a cpv y activa por defecto", () => {
    const body = legacyToBody({ keyword: " SAP ", cpvFilter: "72000000" });
    expect(body.cpv).toBe("72000000");
    expect(body.keyword).toBe("SAP");
    expect(body.active).toBe(true);
  });

  it("respeta una regla legacy desactivada", () => {
    expect(legacyToBody({ active: false }).active).toBe(false);
  });
});

describe("migrateLegacyRules", () => {
  it("sube todas y confirma", async () => {
    const post = vi.fn().mockResolvedValue({});
    await expect(
      migrateLegacyRules([{ keyword: "A" }, { keyword: "B" }], post),
    ).resolves.toBe(true);
    expect(post).toHaveBeenCalledTimes(2);
  });

  it("una que falla no corta las demás, pero el resultado es falso", async () => {
    // Es la garantía que impide vaciar el legacy: si algo no subió, la próxima
    // sesión tiene que poder reintentarlo.
    const post = vi
      .fn()
      .mockRejectedValueOnce(new Error("403"))
      .mockResolvedValue({});
    await expect(
      migrateLegacyRules([{ keyword: "A" }, { keyword: "B" }], post),
    ).resolves.toBe(false);
    expect(post).toHaveBeenCalledTimes(2);
  });

  it("sin reglas no llama al servidor", async () => {
    const post = vi.fn();
    await expect(migrateLegacyRules([], post)).resolves.toBe(true);
    expect(post).not.toHaveBeenCalled();
  });
});

describe("useLegacyRuleMigration", () => {
  function deps(over: Partial<LegacyMigrationDeps> = {}) {
    return {
      readFlag: vi.fn(() => false),
      readLegacy: vi.fn((): LegacyRule[] => []),
      markMigrated: vi.fn(),
      clearLegacy: vi.fn(),
      post: vi.fn().mockResolvedValue({}),
      onDone: vi.fn(),
      ...over,
    };
  }

  it("no hace nada si ya se migró", () => {
    const d = deps({ readFlag: vi.fn(() => true) });
    renderHook(() => useLegacyRuleMigration(d));
    expect(d.readLegacy).not.toHaveBeenCalled();
    expect(d.post).not.toHaveBeenCalled();
  });

  it("sin legacy marca la migración hecha sin llamar al servidor", () => {
    const d = deps();
    renderHook(() => useLegacyRuleMigration(d));
    expect(d.markMigrated).toHaveBeenCalledOnce();
    expect(d.post).not.toHaveBeenCalled();
  });

  it("sube las reglas, marca el flag, vacía el legacy y refresca", async () => {
    const d = deps({ readLegacy: vi.fn(() => [{ keyword: "SAP" }]) });
    renderHook(() => useLegacyRuleMigration(d));
    await waitFor(() => expect(d.onDone).toHaveBeenCalled());
    expect(d.post).toHaveBeenCalledWith(
      expect.objectContaining({ keyword: "SAP", frequency: "daily" }),
    );
    expect(d.markMigrated).toHaveBeenCalledOnce();
    expect(d.clearLegacy).toHaveBeenCalledOnce();
  });

  it("si el POST falla NO marca migrado ni borra el legacy", async () => {
    // El bug que esto fija: con un 403 se vaciaba `watchlist_rules` igual y el
    // usuario perdía sus reglas sin aviso.
    const d = deps({
      readLegacy: vi.fn(() => [{ keyword: "SAP" }]),
      post: vi.fn().mockRejectedValue(new Error("403")),
    });
    renderHook(() => useLegacyRuleMigration(d));
    await waitFor(() => expect(d.onDone).toHaveBeenCalled());
    expect(d.markMigrated).not.toHaveBeenCalled();
    expect(d.clearLegacy).not.toHaveBeenCalled();
  });

  it("no se ejecuta dos veces aunque el componente se remonte en el efecto", async () => {
    // StrictMode monta dos veces en desarrollo; sin el guard cada regla del
    // usuario se duplicaba.
    const d = deps({ readLegacy: vi.fn(() => [{ keyword: "SAP" }]) });
    const { rerender } = renderHook(() => useLegacyRuleMigration(d));
    rerender();
    rerender();
    await waitFor(() => expect(d.onDone).toHaveBeenCalled());
    expect(d.post).toHaveBeenCalledTimes(1);
  });
});

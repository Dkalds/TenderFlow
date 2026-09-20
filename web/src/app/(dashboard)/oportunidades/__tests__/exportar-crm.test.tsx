/**
 * F6.3 — el botón «Exportar a CRM» del tablero.
 *
 * Lo que fija: la descarga va a `/api/v1/exports/crm` con la organización
 * activa y pasa por `triggerDownload` (que mira el estado y mide
 * `export_lanzado` con `formato=crm`); sin organización activa no inventa una.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const { triggerDownload } = vi.hoisted(() => ({ triggerDownload: vi.fn() }));
let organizacion: number | null = 21;

vi.mock("@/lib/export", () => ({ triggerDownload }));
vi.mock("@/hooks/use-organization", () => ({
  // Réplica de la real: `undefined` es «todavía no se sabe»; `null`, «no hay
  // ninguna», que sí es una respuesta y deja pasar la consulta.
  organizacionResuelta: (id: unknown) => id !== undefined,
  useActiveOrganizationId: () => organizacion,
}));

import { ExportarCrm, urlExportCrm } from "../_components/exportar-crm";

afterEach(() => {
  cleanup();
  triggerDownload.mockReset();
  organizacion = 21;
});

describe("ExportarCrm", () => {
  it("descarga el CSV del CRM con la organización activa", async () => {
    triggerDownload.mockResolvedValue(undefined);
    render(<ExportarCrm />);

    fireEvent.click(screen.getByRole("button", { name: "Exportar a CRM" }));

    await waitFor(() => expect(triggerDownload).toHaveBeenCalledWith("/api/v1/exports/crm?organization_id=21"));
    expect(await screen.findByRole("button", { name: "Exportar a CRM" })).toBeEnabled();
  });

  it("sin organización activa no manda ninguna", () => {
    expect(urlExportCrm(null)).toBe("/api/v1/exports/crm");
  });
});

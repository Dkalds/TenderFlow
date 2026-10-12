/**
 * CU-28 — en Detalle la etiqueta filtra en servidor: es un parámetro más del
 * listado, con la organización a la que pertenece.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";
import { TODAS_LAS_ETIQUETAS } from "@/components/etiquetas/filtro-etiqueta";
import { useEtiquetaDelListado } from "../_hooks/use-etiqueta-listado";

const organizacion = vi.hoisted(() => ({ id: 7 as number | null }));
vi.mock("@/hooks/use-organization", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/use-organization")>();
  return { ...actual, useActiveOrganizationId: () => organizacion.id };
});

afterEach(() => {
  cleanup();
  organizacion.id = 7;
});

describe("useEtiquetaDelListado", () => {
  it("sin etiqueta no añade nada al listado", () => {
    const { result } = renderHook(() => useEtiquetaDelListado());
    expect(result.current.filtro).toBe(TODAS_LAS_ETIQUETAS);
    expect(result.current.params).toEqual({});
  });

  it("con etiqueta manda su id y la organización dueña", () => {
    const { result } = renderHook(() => useEtiquetaDelListado());
    act(() => result.current.setFiltro("4"));
    expect(result.current.params).toEqual({ etiqueta: "4", organization_id: "7" });
  });

  it("en la organización personal deja que el servidor la resuelva", () => {
    organizacion.id = null;
    const { result } = renderHook(() => useEtiquetaDelListado());
    act(() => result.current.setFiltro("4"));
    expect(result.current.params).toEqual({ etiqueta: "4" });
  });
});

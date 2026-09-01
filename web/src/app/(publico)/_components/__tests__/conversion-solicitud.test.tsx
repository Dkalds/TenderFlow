import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { track } from "@vercel/analytics";
import { ConversionSolicitud } from "../conversion-solicitud";

vi.mock("@vercel/analytics", () => ({ track: vi.fn() }));

describe("ConversionSolicitud", () => {
  it("registra la conversión sin adjuntar datos del formulario", () => {
    render(<ConversionSolicitud />);

    expect(track).toHaveBeenCalledWith("solicitud_acceso_registrada");
  });
});

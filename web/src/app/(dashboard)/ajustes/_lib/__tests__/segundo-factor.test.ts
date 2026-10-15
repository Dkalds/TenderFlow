import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api-client";
import {
  agruparSecreto,
  codigoDeRecuperacionValido,
  codigoTotpValido,
  limpiarCodigo,
  mensajeDelSegundoFactor,
  secretoDeUri,
} from "../segundo-factor";

const URI = "otpauth://totp/TenderFlow:ana%40example.com?secret=JBSWY3DPEHPK3PXP&issuer=TenderFlow";

describe("secretoDeUri", () => {
  it("saca la clave del URI otpauth, que es lo único que trae", () => {
    expect(secretoDeUri(URI)).toBe("JBSWY3DPEHPK3PXP");
  });

  it("sin clave devuelve null en vez de inventarla", () => {
    expect(secretoDeUri("otpauth://totp/TenderFlow:ana?issuer=TenderFlow")).toBeNull();
    expect(secretoDeUri("no es un uri")).toBeNull();
  });
});

describe("agruparSecreto", () => {
  it("parte la clave en bloques de cuatro para teclearla sin perderse", () => {
    expect(agruparSecreto("JBSWY3DPEHPK3PXP")).toBe("JBSW Y3DP EHPK 3PXP");
    expect(agruparSecreto("ABCDEF")).toBe("ABCD EF");
  });
});

describe("códigos", () => {
  it("limpia espacios y guiones que la gente copia con el código", () => {
    expect(limpiarCodigo(" 123 456 ")).toBe("123456");
    expect(limpiarCodigo("abcd-ef01-2345-6789")).toBe("abcdef0123456789");
  });

  it("un TOTP son seis cifras", () => {
    expect(codigoTotpValido("123456")).toBe(true);
    expect(codigoTotpValido("12345")).toBe(false);
    expect(codigoTotpValido("12345a")).toBe(false);
  });

  it("uno de recuperación son dieciséis caracteres hexadecimales", () => {
    expect(codigoDeRecuperacionValido("0123456789abcdef")).toBe(true);
    expect(codigoDeRecuperacionValido("0123456789ABCDEF")).toBe(true);
    expect(codigoDeRecuperacionValido("0123456789abcdeg")).toBe(false);
  });
});

describe("mensajeDelSegundoFactor", () => {
  it("un código rechazado se explica sin hablar de HTTP", () => {
    const mensaje = mensajeDelSegundoFactor(new ApiError(400, "Invalid TOTP code"));
    expect(mensaje).toMatch(/código no es válido/);
    expect(mensaje).not.toMatch(/400|Invalid/);
  });

  it("el bloqueo por intentos dice que hay que esperar", () => {
    expect(mensajeDelSegundoFactor(new ApiError(429, "Too many failed MFA attempts."))).toMatch(
      /Espera unos minutos/,
    );
  });

  it("cualquier otro fallo usa el mensaje de acción de siempre", () => {
    expect(mensajeDelSegundoFactor(new ApiError(500, "boom"))).toMatch(/Error del servidor/);
  });
});

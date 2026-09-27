/**
 * Un mismo icono = un mismo concepto: el mapa de `lib/iconos.ts` no repite
 * glifo entre espacios y cubre todos los espacios de la consola.
 */
import { describe, it, expect } from "vitest";
import { MessageSquareText } from "lucide-react";
import { ICONO_CONCEPTO, ICONO_ENTIDAD, ICONO_ESPACIO } from "@/lib/iconos";
import { CONSOLE_SPACES } from "@/lib/console-spaces";

describe("ICONO_ESPACIO", () => {
  it("un icono distinto por espacio", () => {
    const iconos = Object.values(ICONO_ESPACIO);
    expect(new Set(iconos).size).toBe(iconos.length);
  });

  it("cubre todos los espacios de la consola", () => {
    const sinIcono = CONSOLE_SPACES.map((espacio) => espacio.key).filter((clave) => !(clave in ICONO_ESPACIO));
    expect(sinIcono).toEqual([]);
  });

  it("los espacios que son una entidad usan el icono de esa entidad", () => {
    expect(ICONO_ESPACIO.oportunidades).toBe(ICONO_ENTIDAD.oportunidad);
    expect(ICONO_ESPACIO.cuentas).toBe(ICONO_ENTIDAD.cuenta);
    expect(ICONO_ESPACIO.empresas).toBe(ICONO_ENTIDAD.empresa);
  });
});

describe("ICONO_ENTIDAD", () => {
  it("cuenta, empresa y órgano no comparten glifo", () => {
    const { cuenta, empresa, organo } = ICONO_ENTIDAD;
    expect(new Set([cuenta, empresa, organo]).size).toBe(3);
  });
});

describe("ICONO_CONCEPTO", () => {
  it("la IA se nombra con un glifo de texto, no con destellos", () => {
    expect(ICONO_CONCEPTO.ia).toBe(MessageSquareText);
  });
});

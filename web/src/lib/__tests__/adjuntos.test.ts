import { describe, expect, it } from "vitest";
import {
  estadoDeCita,
  extensionDe,
  extensionesAdmitidas,
  extensionesCitables,
  motivoNoCitable,
  nombreParaCabecera,
  tipoDeFichero,
  validarFichero,
  type PoliticaAdjuntos,
} from "@/lib/adjuntos";

/** Una política como la que sirve `GET /pursuits/adjuntos/politica`. */
const politica: PoliticaAdjuntos = {
  almacen_disponible: true,
  max_bytes: 25 * 1024 * 1024,
  tipos: [
    { content_type: "application/pdf", extensiones: [".pdf"] },
    { content_type: "text/csv", extensiones: [".csv"] },
    { content_type: "text/plain", extensiones: [".txt", ".md"] },
  ],
  indexado_max_documentos: 5,
  indexado_max_bytes: 5 * 1024 * 1024,
  indexado_tipos: ["application/pdf", "text/plain"],
};

describe("reglas de adjuntos leídas de la política", () => {
  it("saca la extensión en minúsculas y sin confundir un punto inicial", () => {
    expect(extensionDe("Propuesta.PDF")).toBe(".pdf");
    expect(extensionDe("presupuesto.v2.xlsx")).toBe(".xlsx");
    expect(extensionDe(".bashrc")).toBe("");
    expect(extensionDe("sin-extension")).toBe("");
    expect(extensionDe("acaba.")).toBe("");
  });

  it("deduce el tipo de la extensión, no del que diga el sistema operativo", () => {
    // Windows llama `application/vnd.ms-excel` a un `.csv`; el servidor exige
    // que tipo y extensión concuerden, así que manda el de la política.
    expect(tipoDeFichero("ofertas.csv", politica)).toBe("text/csv");
    expect(tipoDeFichero("notas.md", politica)).toBe("text/plain");
    expect(tipoDeFichero("instalador.exe", politica)).toBeNull();
  });

  it("lista las extensiones admitidas sin repetir, para el selector y el texto", () => {
    expect(extensionesAdmitidas(politica)).toEqual([".csv", ".md", ".pdf", ".txt"]);
  });

  it("rechaza antes de subir lo que el servidor va a rechazar", () => {
    expect(validarFichero({ name: "vacio.pdf", size: 0 }, politica)).toEqual({
      ok: false,
      motivo: "El fichero está vacío.",
    });
    const grande = validarFichero({ name: "anexos.pdf", size: 30 * 1024 * 1024 }, politica);
    expect(grande).toEqual({ ok: false, motivo: "Ocupa 30 MB y el máximo es 25 MB." });
    const tipo = validarFichero({ name: "instalador.exe", size: 10 }, politica);
    expect(tipo.ok).toBe(false);
    expect(!tipo.ok && tipo.motivo).toContain(".csv, .md, .pdf, .txt");
  });

  it("acepta un fichero admitido con el tipo de la política", () => {
    expect(validarFichero({ name: "Propuesta técnica.pdf", size: 2048 }, politica)).toEqual({
      ok: true,
      contentType: "application/pdf",
    });
  });

  it("codifica el nombre para la cabecera: una cabecera solo lleva Latin-1", () => {
    expect(nombreParaCabecera("Oferta — v2 Łódź.pdf")).toBe("Oferta%20%E2%80%94%20v2%20%C5%81%C3%B3d%C5%BA.pdf");
  });

  it("dice de qué extensiones se puede leer el texto para citarlo", () => {
    expect(extensionesCitables(politica)).toEqual([".md", ".pdf", ".txt"]);
  });

  it("explica por qué un fichero no puede citarse, en el orden del servidor", () => {
    expect(motivoNoCitable({ content_type: "application/pdf", size_bytes: 1024 }, politica)).toBeNull();
    expect(motivoNoCitable({ content_type: "text/csv", size_bytes: 1024 }, politica)).toContain(
      "no se puede leer el texto",
    );
    expect(motivoNoCitable({ content_type: "application/pdf", size_bytes: 6 * 1024 * 1024 }, politica)).toContain(
      "el máximo es 5 MB",
    );
  });

  it("traduce el estado del servidor a lo que se enseña en la fila", () => {
    const base = { indexable: true, index_error: null };
    expect(estadoDeCita({ indexable: false, index_status: null, index_error: null })).toBeNull();
    expect(estadoDeCita({ ...base, index_status: "pending" })).toEqual({
      tono: "info",
      etiqueta: "Leyendo el documento…",
    });
    expect(estadoDeCita({ ...base, index_status: "indexed" })?.etiqueta).toBe("Se puede citar");
    expect(estadoDeCita({ ...base, index_status: "sin_texto", index_error: "El PDF no tiene texto." })).toEqual({
      tono: "warning",
      etiqueta: "Sin texto que citar",
      detalle: "El PDF no tiene texto.",
    });
    expect(estadoDeCita({ ...base, index_status: "error" })?.etiqueta).toBe("No se pudo leer");
  });
});

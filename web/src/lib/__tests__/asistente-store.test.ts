/**
 * El estado del asistente único: si está abierto, sobre qué responde y qué
 * se le ha pedido al abrirlo.
 *
 * Hasta 2026-10 había tres asistentes con tres estados —el copiloto global, el
 * chat del Investigador y la pestaña IA de la ficha—. Hoy hay uno, y cada
 * entrada lo abre con su contexto: el expediente abierto, la oportunidad, los
 * resultados marcados en el Investigador o la bandeja de comparación.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { MAX_EXPEDIENTES_ASISTENTE, useAsistente } from "@/lib/asistente-store";
import { useUiStore } from "@/lib/ui-store";

const A = { id: "A", titulo: "Expediente A" };
const B = { id: "B", titulo: "Expediente B" };
const C = { id: "C", titulo: "Expediente C" };
const D = { id: "D", titulo: "Expediente D" };

beforeEach(() => {
  useAsistente.getState().reiniciar();
  useUiStore.setState({ commandOpen: false });
});

describe("asistente — abrir con contexto", () => {
  it("empieza cerrado, sobre todas las licitaciones y sin nada pedido", () => {
    const estado = useAsistente.getState();
    expect(estado.abierto).toBe(false);
    expect(estado.contexto).toEqual({ expedientes: [], origen: null });
    expect(estado.pedido).toBeNull();
  });

  it("la ficha lo abre con su expediente", () => {
    useAsistente.getState().abrir({ contexto: { expedientes: [A], origen: "ficha" } });
    const estado = useAsistente.getState();
    expect(estado.abierto).toBe(true);
    expect(estado.contexto).toEqual({ expedientes: [A], origen: "ficha" });
  });

  it("abrir sin contexto conserva el que había: es volver a la conversación", () => {
    useAsistente.getState().abrir({ contexto: { expedientes: [A], origen: "oportunidad" } });
    useAsistente.getState().cerrar();
    useAsistente.getState().abrir();
    expect(useAsistente.getState().contexto.expedientes).toEqual([A]);
  });

  it("un contexto nuevo sustituye las opciones del anterior", () => {
    useAsistente.getState().abrir({ contexto: { expedientes: [], origen: "investigador" }, opciones: { topK: 20 } });
    useAsistente.getState().abrir({ contexto: { expedientes: [A], origen: "ficha" } });
    expect(useAsistente.getState().opciones).toEqual({});
  });

  it("nunca pasa de tres expedientes: es el tope de `POST /ask`", () => {
    useAsistente.getState().abrir({ contexto: { expedientes: [A, B, C, D], origen: "comparacion" } });
    expect(useAsistente.getState().contexto.expedientes).toHaveLength(MAX_EXPEDIENTES_ASISTENTE);
  });

  it("una pregunta al abrir queda pedida, con una clave nueva cada vez", () => {
    useAsistente.getState().abrir({ pregunta: "¿Qué vence?" });
    const primero = useAsistente.getState().pedido;
    useAsistente.getState().abrir({ pregunta: "¿Qué vence?" });
    const segundo = useAsistente.getState().pedido;
    expect(primero).toMatchObject({ tipo: "pregunta", texto: "¿Qué vence?", nueva: false });
    expect(segundo?.clave).toBeGreaterThan(primero!.clave);
  });

  it("pedir el resumen exige un solo expediente", () => {
    useAsistente.getState().abrir({ contexto: { expedientes: [A], origen: "ficha" }, resumir: true });
    expect(useAsistente.getState().pedido).toMatchObject({ tipo: "resumen" });
    useAsistente.getState().reiniciar();
    useAsistente.getState().abrir({ contexto: { expedientes: [A, B], origen: "comparacion" }, resumir: true });
    expect(useAsistente.getState().pedido).toBeNull();
  });

  it("atender un pedido lo retira, salvo que ya haya otro más nuevo", () => {
    useAsistente.getState().abrir({ pregunta: "uno" });
    const clave = useAsistente.getState().pedido!.clave;
    useAsistente.getState().abrir({ pregunta: "dos" });
    useAsistente.getState().atender(clave);
    expect(useAsistente.getState().pedido).toMatchObject({ texto: "dos" });
    useAsistente.getState().atender(useAsistente.getState().pedido!.clave);
    expect(useAsistente.getState().pedido).toBeNull();
  });

  it("abrirlo cierra la paleta de comandos", () => {
    useUiStore.setState({ commandOpen: true });
    useAsistente.getState().abrir();
    expect(useUiStore.getState().commandOpen).toBe(false);
  });
});

describe("asistente — la selección del Investigador", () => {
  it("marcar un resultado empieza una selección propia, aunque hubiera otro contexto", () => {
    useAsistente.getState().abrir({ contexto: { expedientes: [A], origen: "ficha" } });
    useAsistente.getState().alternarExpediente(B, "investigador");
    expect(useAsistente.getState().contexto).toEqual({ expedientes: [B], origen: "investigador" });
  });

  it("marca y desmarca dentro de la selección, hasta tres", () => {
    const { alternarExpediente } = useAsistente.getState();
    alternarExpediente(A, "investigador");
    alternarExpediente(B, "investigador");
    alternarExpediente(C, "investigador");
    expect(useAsistente.getState().alternarExpediente(D, "investigador")).toBe(false);
    expect(useAsistente.getState().contexto.expedientes.map((e) => e.id)).toEqual(["A", "B", "C"]);
    useAsistente.getState().alternarExpediente(B, "investigador");
    expect(useAsistente.getState().contexto.expedientes.map((e) => e.id)).toEqual(["A", "C"]);
  });

  it("los ajustes de una pantalla solo se fijan si el contexto es suyo", () => {
    useAsistente.getState().abrir({ contexto: { expedientes: [A], origen: "ficha" } });
    useAsistente.getState().fijarOpciones("investigador", { topK: 20 });
    expect(useAsistente.getState().opciones).toEqual({});
    useAsistente.getState().alternarExpediente(B, "investigador");
    useAsistente.getState().fijarOpciones("investigador", { topK: 20 });
    expect(useAsistente.getState().opciones).toEqual({ topK: 20 });
  });

  it("quitar un expediente lo saca del contexto, y soltar los de un origen deja todas las licitaciones", () => {
    useAsistente.getState().abrir({ contexto: { expedientes: [A, B], origen: "investigador" } });
    useAsistente.getState().quitarExpediente("A");
    expect(useAsistente.getState().contexto.expedientes).toEqual([B]);
    useAsistente.getState().soltarExpedientes("ficha");
    expect(useAsistente.getState().contexto.expedientes).toEqual([B]);
    useAsistente.getState().soltarExpedientes("investigador");
    expect(useAsistente.getState().contexto).toEqual({ expedientes: [], origen: null });
  });
});

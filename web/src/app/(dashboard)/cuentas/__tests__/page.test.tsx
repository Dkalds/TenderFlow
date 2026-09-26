/**
 * La lista de /cuentas: la cartera del equipo con lo que pasa en cada cuenta.
 *
 * Lo que se fija:
 *
 * 1. Cada fila enlaza a su ficha y trae las cuatro cifras del resumen del
 *    backend; una cifra que no llegó es «—», nunca un cero inventado.
 * 2. Un `viewer` no ve crear, editar ni dejar de seguir: la API se lo negaría
 *    (403), y la pantalla le dice por qué no están.
 * 3. Dejar de seguir avisa con «Deshacer», que rehace la cuenta con sus órganos,
 *    su nota y sus etiquetas.
 *
 * Los hooks de datos van mockeados: su contrato con la API está en
 * `hooks/__tests__/use-cuentas.test.tsx`.
 */
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

const estado = vi.hoisted(() => ({
  cuentas: [] as unknown[],
  resumen: undefined as unknown,
  resumenError: false,
  puedeEscribir: true,
  rol: "member" as string | undefined,
  dejar: vi.fn(),
  recuperar: vi.fn(),
  toast: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("sonner", () => ({
  toast: Object.assign(estado.toast, { error: vi.fn(), success: vi.fn() }),
}));
vi.mock("@/components/layout/space-shell", () => ({
  useSpaceView: () => ({ view: "seguidas", setView: vi.fn() }),
  SpaceShell: ({ children, actions }: { children: React.ReactNode; actions?: React.ReactNode }) => (
    <div>
      {actions}
      {children}
    </div>
  ),
}));
vi.mock("@/hooks/use-organization", () => ({
  usePuedeEscribir: () => estado.puedeEscribir,
  useRolActivo: () => estado.rol,
}));
vi.mock("@/hooks/use-etiquetas", () => ({ useEtiquetasDe: () => ({ data: {} }) }));
vi.mock("@/components/etiquetas/etiquetas-objeto", () => ({
  EtiquetaChips: () => null,
  EtiquetasEditor: ({ descripcion }: { descripcion: string }) => (
    <button type="button">Etiquetas de {descripcion}</button>
  ),
}));
vi.mock("@/hooks/use-cuentas", () => ({
  useCuentas: () => ({ data: estado.cuentas, isLoading: false, isError: false, refetch: vi.fn() }),
  useCuentasResumen: () => ({
    data: estado.resumenError ? undefined : estado.resumen,
    isLoading: false,
    isError: estado.resumenError,
  }),
  useDejarDeSeguirCuenta: () => ({ mutate: estado.dejar, isPending: false }),
  useRecuperarCuenta: () => ({ mutate: estado.recuperar }),
  useCrearCuenta: () => ({ mutate: vi.fn(), isPending: false }),
  useEditarCuenta: () => ({ mutate: vi.fn(), isPending: false }),
  useBuscarOrganos: () => ({
    q: "",
    activa: false,
    pendiente: false,
    candidatos: [],
    isFetching: false,
    isError: false,
  }),
}));

import CuentasPage from "@/app/(dashboard)/cuentas/page";

const AMBITO = { universo: "Licitaciones tecnológicas.", ventana: "Hoy." };

const MADRID = {
  id: 1,
  organization_id: 21,
  nombre: "Ayuntamiento de Madrid",
  organo_nombre: "Área de Gobierno de Economía del Ayuntamiento de Madrid",
  organo_norm: "area de gobierno de economia del ayuntamiento de madrid",
  organos: [
    { id: 10, organo_nombre: "Área de Gobierno de Economía del Ayuntamiento de Madrid", organo_norm: "a" },
    { id: 11, organo_nombre: "Organismo Autónomo Informática del Ayuntamiento de Madrid", organo_norm: "b" },
  ],
  nota: "Renueva en marzo",
  created_at: "2026-09-20T00:00:00Z",
};

const GETAFE = {
  id: 2,
  organization_id: 21,
  nombre: "Ayuntamiento de Getafe",
  organo_nombre: "Ayuntamiento de Getafe",
  organo_norm: "ayuntamiento de getafe",
  organos: [{ id: 20, organo_nombre: "Ayuntamiento de Getafe", organo_norm: "c" }],
  created_at: "2026-09-20T00:00:00Z",
};

const RESUMEN = {
  filas: [
    {
      cuenta_id: 1,
      abiertas: 4,
      ultima_publicacion: "2026-09-24T10:00:00+00:00",
      vencen: 3,
      oportunidades_activas: 2,
    },
    { cuenta_id: 2, abiertas: 0, ultima_publicacion: null, vencen: 0, oportunidades_activas: 0 },
  ],
  ambito_abiertas: AMBITO,
  ambito_ultima_publicacion: AMBITO,
  ambito_vencen: AMBITO,
  ambito_oportunidades: AMBITO,
};

beforeEach(() => {
  estado.cuentas = [MADRID, GETAFE];
  estado.resumen = RESUMEN;
  estado.resumenError = false;
  estado.puedeEscribir = true;
  estado.rol = "member";
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function fila(nombre: string): HTMLElement {
  const enlace = screen.getByRole("link", { name: nombre });
  const tr = enlace.closest("tr");
  if (!tr) throw new Error(`sin fila para ${nombre}`);
  return tr;
}

describe("CuentasPage", () => {
  it("cada fila enlaza a su ficha y trae las cifras del resumen", () => {
    render(<CuentasPage />);

    expect(screen.getByRole("link", { name: "Ayuntamiento de Madrid" })).toHaveAttribute(
      "href",
      "/cuentas/1",
    );
    const madrid = within(fila("Ayuntamiento de Madrid"));
    // Una cuenta de varios órganos dice cuántos; su nota va debajo.
    expect(madrid.getByText("2 órganos")).toBeInTheDocument();
    expect(madrid.getByText("Renueva en marzo")).toBeInTheDocument();
    expect(madrid.getByText("4")).toBeInTheDocument();
    expect(madrid.getByText("3")).toBeInTheDocument();
    expect(madrid.getByText("2")).toBeInTheDocument();

    const getafe = within(fila("Ayuntamiento de Getafe"));
    // Un órgano que se llama como la cuenta no se repite.
    expect(getafe.queryByText("Ayuntamiento de Getafe", { selector: "span" })).toBeNull();
    expect(getafe.getByText("Sin publicaciones")).toBeInTheDocument();

    // El universo y la ventana de cada cifra, a un clic (ADR-014).
    expect(screen.getByText("Qué cuentan estas cifras")).toBeInTheDocument();
  });

  it("si el resumen falla, las cifras dicen «—» y no cero", () => {
    estado.resumenError = true;

    render(<CuentasPage />);

    const getafe = within(fila("Ayuntamiento de Getafe"));
    expect(getafe.getAllByText("—")).toHaveLength(4);
    expect(getafe.queryByText("Sin publicaciones")).toBeNull();
    expect(screen.queryByText("Qué cuentan estas cifras")).toBeNull();
  });

  it("un viewer no ve crear, editar ni dejar de seguir, y sabe por qué", () => {
    estado.puedeEscribir = false;
    estado.rol = "viewer";

    render(<CuentasPage />);

    expect(screen.queryByRole("button", { name: /Nueva cuenta/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Editar/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Dejar de seguir/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Etiquetas de/ })).toBeNull();
    expect(screen.getByText(/Tu rol en esta organización es de solo lectura/)).toBeInTheDocument();
  });

  it("sin cuentas explica qué hace una y ofrece crear la primera", () => {
    estado.cuentas = [];

    render(<CuentasPage />);

    expect(screen.getByText("Tu equipo todavía no sigue ninguna cuenta")).toBeInTheDocument();
    // La del estado vacío y la de la cabecera.
    expect(screen.getAllByRole("button", { name: /Nueva cuenta/ }).length).toBeGreaterThan(0);
  });

  it("dejar de seguir avisa con deshacer, que rehace la cuenta con sus órganos", () => {
    render(<CuentasPage />);

    fireEvent.click(screen.getByRole("button", { name: "Dejar de seguir Ayuntamiento de Madrid" }));

    expect(estado.dejar).toHaveBeenCalledTimes(1);
    const [variables, opciones] = estado.dejar.mock.calls[0] as [
      { id: number },
      { onSuccess: () => void },
    ];
    expect(variables).toEqual({ id: 1 });
    opciones.onSuccess();

    expect(estado.toast).toHaveBeenCalledTimes(1);
    const [titulo, aviso] = estado.toast.mock.calls[0] as [
      string,
      { action: { label: string; onClick: () => void } },
    ];
    expect(titulo).toBe("Dejaste de seguir «Ayuntamiento de Madrid»");
    expect(aviso.action.label).toBe("Deshacer");

    aviso.action.onClick();
    expect(estado.recuperar).toHaveBeenCalledWith({
      nombre: "Ayuntamiento de Madrid",
      organos: [
        "Área de Gobierno de Economía del Ayuntamiento de Madrid",
        "Organismo Autónomo Informática del Ayuntamiento de Madrid",
      ],
      nota: "Renueva en marzo",
      etiquetaIds: [],
    });
  });
});

/**
 * La ficha de una cuenta (`/cuentas/[id]`): la mitad de F1.5 que faltaba.
 *
 * Lo que se fija:
 *
 * 1. Cada bloque dice su universo y su ventana (ADR-014), y lo que no es un dato
 *    firme se rotula: una fecha de fin estimada dice «(estimado)».
 * 2. Enlaza a donde vive cada cosa: el expediente a Detalle, el adjudicatario a
 *    su dossier, la oportunidad a su ficha.
 * 3. Los órganos se pueden quitar mientras quede más de uno; el último no, que
 *    una cuenta sin órganos no avisaría de nada.
 * 4. Un `viewer` la lee entera pero no ve ninguna acción de escritura.
 */
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

const estado = vi.hoisted(() => ({
  id: "1",
  ficha: undefined as unknown,
  error: null as Error | null,
  puedeEscribir: true,
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: estado.id }),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }));
vi.mock("@/hooks/use-organization", () => ({ usePuedeEscribir: () => estado.puedeEscribir }));
vi.mock("@/hooks/use-etiquetas", () => ({ useEtiquetasDe: () => ({ data: {} }) }));
vi.mock("@/components/etiquetas/etiquetas-objeto", () => ({
  EtiquetaChips: () => null,
  EtiquetasEditor: () => <button type="button">Etiquetas</button>,
}));
// El análisis por órgano pide Mercado por su cuenta; aquí no es el sujeto.
vi.mock("@/app/(dashboard)/cuentas/[id]/_components/analisis-organo", () => ({
  AnalisisOrgano: () => <section aria-label="Análisis por órgano" />,
}));
vi.mock("@/hooks/use-cuentas", () => ({
  useFichaCuenta: () => ({
    data: estado.ficha,
    isPending: false,
    error: estado.error,
    refetch: vi.fn(),
  }),
  useDejarDeSeguirCuenta: () => ({ mutate: vi.fn(), isPending: false }),
  useRecuperarCuenta: () => ({ mutate: vi.fn() }),
  useEditarCuenta: () => ({ mutate: vi.fn(), isPending: false }),
  useAnadirOrganos: () => ({ mutate: vi.fn(), isPending: false }),
  useQuitarOrgano: () => ({ mutate: vi.fn(), isPending: false }),
  useBuscarOrganos: () => ({
    q: "",
    activa: false,
    pendiente: false,
    candidatos: [],
    isFetching: false,
    isError: false,
  }),
}));

import FichaCuentaPage from "@/app/(dashboard)/cuentas/[id]/page";

const AMBITO_PUBLICACIONES = {
  universo: "Licitaciones tecnológicas de los órganos de la cuenta.",
  ventana: "Vistas por primera vez en los últimos 90 días.",
};
const AMBITO_VENCEN = {
  universo: "Contratos adjudicados de los órganos de la cuenta.",
  ventana: "Fecha de fin entre hoy y dentro de 12 meses.",
};
const AMBITO_OPORTUNIDADES = {
  universo: "Oportunidades de tu organización.",
  ventana: "Todas: primero las activas.",
};

function ficha(organos = 2) {
  return {
    cuenta: {
      id: 1,
      organization_id: 21,
      nombre: "Ayuntamiento de Madrid",
      organo_nombre: "Área de Gobierno de Economía del Ayuntamiento de Madrid",
      organo_norm: "a",
      organos: [
        { id: 10, organo_nombre: "Área de Gobierno de Economía del Ayuntamiento de Madrid", organo_norm: "a" },
        { id: 11, organo_nombre: "Organismo Autónomo Informática del Ayuntamiento de Madrid", organo_norm: "b" },
      ].slice(0, organos),
      nota: "Renueva en marzo",
      created_at: "2026-09-20T00:00:00Z",
    },
    publicaciones: {
      ambito: AMBITO_PUBLICACIONES,
      total: 25,
      items: [
        {
          id_externo: "MAD-1",
          titulo: "Soporte SAP",
          organo: "Área de Gobierno de Economía del Ayuntamiento de Madrid",
          importe: 120000,
          importe_tipo: "sin_iva",
          fecha_publicacion: "2026-09-20",
          fecha_limite: "2026-10-10",
          abierta: true,
        },
      ],
    },
    vencimientos: {
      ambito: AMBITO_VENCEN,
      total: 1,
      items: [
        {
          licitacion_id: "MAD-VENCE",
          titulo: "Mantenimiento ERP",
          empresa_id: 44,
          empresa: "Incumbente SA",
          importe_adjudicado: 50000,
          fecha_fin: "2026-12-24",
          fecha_fin_origen: "estimada_inicio",
        },
      ],
    },
    oportunidades: {
      ambito: AMBITO_OPORTUNIDADES,
      activas: 1,
      items: [
        {
          id: 7,
          licitacion_id: "MAD-1",
          titulo: "Soporte SAP",
          status: "qualifying",
          activa: true,
          next_action: "Llamar al jefe de servicio",
          next_action_due: "2026-09-27",
          responsable: "Ana",
        },
        {
          id: 8,
          licitacion_id: "MAD-0",
          titulo: "Licencias",
          status: "lost",
          activa: false,
          responsable: null,
        },
      ],
    },
  };
}

beforeEach(() => {
  estado.id = "1";
  estado.ficha = ficha();
  estado.error = null;
  estado.puedeEscribir = true;
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("FichaCuentaPage", () => {
  it("cada bloque dice su universo y su ventana, y cuántas filas se ven", () => {
    render(<FichaCuentaPage />);

    expect(screen.getByRole("heading", { name: "Ayuntamiento de Madrid" })).toBeInTheDocument();
    expect(screen.getByText("Renueva en marzo")).toBeInTheDocument();
    for (const ambito of [AMBITO_PUBLICACIONES, AMBITO_VENCEN, AMBITO_OPORTUNIDADES]) {
      expect(screen.getByText(`${ambito.ventana} ${ambito.universo}`)).toBeInTheDocument();
    }
    // 25 en la ventana, una en pantalla: se dice, no se deja creer que son todas.
    expect(screen.getByText("Se muestran 1 de 25 publicaciones.")).toBeInTheDocument();
  });

  it("rotula lo abierto, la base del importe y la fecha estimada", () => {
    render(<FichaCuentaPage />);

    expect(screen.getByText("Abierta")).toBeInTheDocument();
    expect(screen.getByText(/sin IVA/)).toBeInTheDocument();
    expect(screen.getByText(/\(estimado\)/)).toBeInTheDocument();
  });

  it("enlaza el expediente, el adjudicatario y la oportunidad a sus fichas", () => {
    render(<FichaCuentaPage />);

    expect(screen.getByRole("link", { name: "Mantenimiento ERP" })).toHaveAttribute(
      "href",
      "/detalle?lic=MAD-VENCE",
    );
    expect(screen.getByRole("link", { name: "Lo tiene Incumbente SA" })).toHaveAttribute(
      "href",
      "/competencia/empresa/44",
    );
    const oportunidades = screen.getAllByRole("link", { name: /Soporte SAP|Licencias/ });
    expect(oportunidades.map((enlace) => enlace.getAttribute("href"))).toEqual(
      expect.arrayContaining(["/oportunidades/7", "/oportunidades/8"]),
    );
    expect(screen.getByText(/Próxima acción: Llamar al jefe de servicio/)).toBeInTheDocument();
  });

  it("los órganos se pueden quitar mientras quede más de uno", () => {
    const { unmount } = render(<FichaCuentaPage />);
    expect(
      screen.getAllByRole("button", { name: /Quitar .* de la cuenta/ }),
    ).toHaveLength(2);
    unmount();

    estado.ficha = ficha(1);
    render(<FichaCuentaPage />);
    expect(screen.queryByRole("button", { name: /Quitar .* de la cuenta/ })).toBeNull();
    expect(screen.getByText("Órgano de contratación")).toBeInTheDocument();
  });

  it("un viewer la lee entera pero no ve ninguna acción de escritura", () => {
    estado.puedeEscribir = false;

    render(<FichaCuentaPage />);

    const cabecera = within(screen.getByRole("banner"));
    expect(cabecera.queryByRole("button", { name: /Editar/ })).toBeNull();
    expect(cabecera.queryByRole("button", { name: /Dejar de seguir/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Añadir/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Quitar/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Etiquetas" })).toBeNull();
    expect(screen.getByText("Mantenimiento ERP")).toBeInTheDocument();
  });

  it("un enlace que no es de ninguna cuenta lo dice sin pedir nada", () => {
    estado.id = "no-es-un-id";

    render(<FichaCuentaPage />);

    expect(screen.getByText("Esa cuenta no existe")).toBeInTheDocument();
  });

  it("si la ficha no llega, lo dice con el motivo", () => {
    estado.ficha = undefined;
    estado.error = new Error("Esa cuenta no existe en tu organización.");

    render(<FichaCuentaPage />);

    expect(screen.getByText("No se pudo abrir esta cuenta")).toBeInTheDocument();
    expect(screen.getByText("Esa cuenta no existe en tu organización.")).toBeInTheDocument();
  });
});

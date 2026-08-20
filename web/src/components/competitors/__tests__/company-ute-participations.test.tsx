import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CompanyUteParticipation } from "../company-profile-types";
import { CompanyUteParticipations } from "../company-ute-participations";

const participations: CompanyUteParticipation[] = [
  {
    ute_empresa_id: 42,
    ute_nombre: "UTE Ejemplo Digital - Sistemas Beta",
    otros_miembros: ["Sistemas Beta"],
    contratos: 2,
    importe_total: 180000,
  },
  {
    ute_empresa_id: 43,
    ute_nombre: "UTE Ejemplo Digital - Redes Gamma",
    otros_miembros: [],
    contratos: 1,
    importe_total: 90000,
  },
];

describe("CompanyUteParticipations", () => {
  it("renders nothing when the company is not a member of any UTE", () => {
    const { container } = render(<CompanyUteParticipations participations={[]} companyName="Ejemplo Digital" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("lists every UTE with its own activity and its other members", () => {
    render(<CompanyUteParticipations participations={participations} companyName="Ejemplo Digital" />);

    expect(screen.getByText("Participación en UTEs")).toBeInTheDocument();
    expect(screen.getByText("UTE Ejemplo Digital - Sistemas Beta")).toBeInTheDocument();
    expect(screen.getByText("UTE Ejemplo Digital - Redes Gamma")).toBeInTheDocument();
    expect(screen.getByText("Sistemas Beta")).toBeInTheDocument();
    expect(screen.getByText("Sin otros miembros identificados")).toBeInTheDocument();
    expect(screen.getByText("2 adjudicaciones de la UTE")).toBeInTheDocument();
    expect(screen.getByText("1 adjudicación de la UTE")).toBeInTheDocument();
  });

  it("links each UTE to its own dossier, since the UTE is a company of its own", () => {
    render(<CompanyUteParticipations participations={participations} companyName="Ejemplo Digital" />);

    expect(screen.getByRole("link", { name: "UTE Ejemplo Digital - Sistemas Beta" })).toHaveAttribute(
      "href",
      "/competidores/empresa/42",
    );
  });

  it("states that the amounts are additional and must not be added to the company totals", () => {
    render(<CompanyUteParticipations participations={participations} companyName="Ejemplo Digital" />);

    const note = screen.getByRole("note");
    expect(note).toHaveTextContent("Importes adicionales, no un desglose de los totales");
    expect(note).toHaveTextContent(/Nada de lo que aparece aquí está incluido en el importe adjudicado/i);
    expect(note).toHaveTextContent(/contaría el mismo dinero dos veces/i);
    expect(
      screen.getByText(/Los totales del dossier miden solo lo adjudicado directamente a Ejemplo Digital/),
    ).toBeInTheDocument();
  });

  it("keeps the UTE amounts out of any rendered total, so the section cannot be read as a breakdown", () => {
    render(<CompanyUteParticipations participations={participations} companyName="Ejemplo Digital" />);

    // Cada importe es el de su UTE; la sección no agrega ni mezcla con los
    // totales propios de la empresa (270.000 € sería la suma prohibida).
    expect(screen.queryByText(/270/)).not.toBeInTheDocument();
  });
});

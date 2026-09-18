/**
 * Los dos formularios de `/equipo` con esquema (S7.2): alta de espacio
 * (`OrganizationCreate`) e invitación de miembro (`OrganizationMemberInvite`).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const crear = vi.fn();
const anadir = vi.fn();
vi.mock("@/hooks/use-organization", () => ({
  useCreateOrganization: () => ({ mutateAsync: crear, isPending: false }),
  useAddOrganizationMember: () => ({ mutateAsync: anadir, isPending: false }),
}));

import { toast } from "sonner";
import { AnadirMiembroForm } from "../anadir-miembro-form";
import { CrearOrganizacionForm } from "../crear-organizacion-form";

afterEach(() => {
  crear.mockReset();
  anadir.mockReset();
  vi.mocked(toast.success).mockClear();
});

describe("CrearOrganizacionForm", () => {
  it("sin nombre el botón sigue apagado, como antes del esquema", () => {
    render(<CrearOrganizacionForm />);
    expect(screen.getByRole("button", { name: /Crear espacio/ })).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Nombre del espacio"), { target: { value: "   " } });
    expect(screen.getByRole("button", { name: /Crear espacio/ })).toBeDisabled();
  });

  it("manda el nombre recortado y vacía el campo al crear", async () => {
    crear.mockResolvedValue({});
    render(<CrearOrganizacionForm />);
    const campo = screen.getByLabelText("Nombre del espacio");

    fireEvent.change(campo, { target: { value: "  Equipo Comercial " } });
    fireEvent.click(screen.getByRole("button", { name: /Crear espacio/ }));

    await waitFor(() => expect(crear).toHaveBeenCalledWith("Equipo Comercial"));
    await waitFor(() => expect(campo).toHaveValue(""));
    expect(toast.success).toHaveBeenCalledWith("Organización creada");
  });

  it("un nombre de más de 200 caracteres se explica debajo del campo", async () => {
    render(<CrearOrganizacionForm />);
    const campo = screen.getByLabelText("Nombre del espacio");

    fireEvent.change(campo, { target: { value: "x".repeat(201) } });
    fireEvent.click(screen.getByRole("button", { name: /Crear espacio/ }));

    const error = await screen.findByText("Máximo 200 caracteres.");
    expect(error).toHaveAttribute("id", "new-org-name-error");
    expect(campo).toHaveAttribute("aria-invalid", "true");
    expect(campo).toHaveAttribute("aria-describedby", "new-org-name-error");
    // El error no se cuela en el nombre accesible del campo.
    expect(screen.getByLabelText("Nombre del espacio")).toBe(campo);
    expect(crear).not.toHaveBeenCalled();
  });
});

describe("AnadirMiembroForm", () => {
  it("un correo mal escrito no llega al backend y queda enlazado al campo", async () => {
    render(<AnadirMiembroForm organizationId={7} />);
    const campo = screen.getByLabelText("Correo de la persona");

    fireEvent.change(campo, { target: { value: "persona-sin-arroba" } });
    fireEvent.click(screen.getByRole("button", { name: /Añadir/ }));

    expect(await screen.findByText("Ese correo no parece válido.")).toHaveAttribute("id", "member-email-error");
    expect(campo).toHaveAttribute("aria-describedby", "member-email-error");
    expect(anadir).not.toHaveBeenCalled();
  });

  it("manda correo y rol con las claves del DTO y distingue invitación de alta", async () => {
    anadir.mockResolvedValue({ id: 3 });
    render(<AnadirMiembroForm organizationId={7} />);

    fireEvent.change(screen.getByLabelText("Correo de la persona"), {
      target: { value: " ana@example.test " },
    });
    fireEvent.click(screen.getByRole("button", { name: /Añadir/ }));

    await waitFor(() => expect(anadir).toHaveBeenCalledWith({ email: "ana@example.test", role: "member" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Invitación enviada por correo"));
  });

  it("si la persona ya tenía cuenta, dice que se ha añadido", async () => {
    anadir.mockResolvedValue({ user_id: 5, role: "member" });
    render(<AnadirMiembroForm organizationId={7} />);

    fireEvent.change(screen.getByLabelText("Correo de la persona"), { target: { value: "ana@example.test" } });
    fireEvent.click(screen.getByRole("button", { name: /Añadir/ }));

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Miembro añadido"));
  });
});

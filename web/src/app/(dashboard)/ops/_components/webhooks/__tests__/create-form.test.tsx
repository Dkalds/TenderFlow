/**
 * Alta de webhook con el esquema de `WebhookCreate` (S7.2).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const mutate = vi.fn();
vi.mock("@/hooks/use-webhooks", () => ({
  useWebhookEventTypes: () => ({ data: ["pursuit.created", "pursuit.updated"] }),
  useCreateWebhook: () => ({ mutate, isPending: false }),
}));

import { CreateForm } from "../create-form";

afterEach(() => {
  mutate.mockReset();
});

const nombre = () => screen.getByLabelText("Nombre del webhook");
const url = () => screen.getByLabelText("URL de destino");

describe("CreateForm (webhooks)", () => {
  it("vacío no crea nada y cada error queda enlazado a su campo", async () => {
    render(<CreateForm organizationId={7} onCreated={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: /Crear/ }));

    expect(await screen.findByText("Escribe un nombre.")).toHaveAttribute("id", "webhook-name-error");
    expect(screen.getByText("Escribe la URL de destino.")).toHaveAttribute("id", "webhook-url-error");
    expect(nombre()).toHaveAttribute("aria-describedby", "webhook-name-error");
    expect(url()).toHaveAttribute("aria-invalid", "true");
    expect(mutate).not.toHaveBeenCalled();
  });

  it("una URL que no es https se para en cliente, como la pararía el backend", async () => {
    render(<CreateForm organizationId={7} onCreated={vi.fn()} />);

    fireEvent.change(nombre(), { target: { value: "Slack" } });
    fireEvent.change(url(), { target: { value: "http://hooks.example.test/x" } });
    fireEvent.click(screen.getByRole("button", { name: /Crear/ }));

    expect(await screen.findByText("La URL debe empezar por https://")).toBeInTheDocument();
    expect(nombre()).not.toHaveAttribute("aria-invalid");
    expect(mutate).not.toHaveBeenCalled();
  });

  it("sin eventos elegidos pide todos (\"*\") y entrega el secreto al crear", async () => {
    const onCreated = vi.fn();
    mutate.mockImplementation((_body, opciones: { onSuccess: (r: { secret: string }) => void }) =>
      opciones.onSuccess({ secret: "s3cr3t" }), // pragma: allowlist secret
    );
    render(<CreateForm organizationId={7} onCreated={onCreated} />);

    fireEvent.change(nombre(), { target: { value: " Slack " } });
    fireEvent.change(url(), { target: { value: " https://hooks.example.test/x " } });
    fireEvent.click(screen.getByRole("button", { name: /Crear/ }));

    await waitFor(() =>
      expect(mutate).toHaveBeenCalledWith(
        {
          name: "Slack",
          url: "https://hooks.example.test/x",
          event_types: ["*"],
          formato: "json",
          organization_id: 7,
        },
        expect.anything(),
      ),
    );
    expect(onCreated).toHaveBeenCalledWith("s3cr3t");
    await waitFor(() => expect(nombre()).toHaveValue(""));
  });
});

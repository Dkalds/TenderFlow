/**
 * La pantalla de acceso es el camino por el que entra todo el mundo, y acaba de
 * repartirse entre `_hooks/use-login-form.ts` y seis piezas de `_components/`.
 * Hasta ahora solo la cubría el E2E, que exige API, build y navegador; estos
 * casos fijan sin nada de eso lo que el troceado no podía cambiar: qué se
 * ofrece primero, qué se enseña cuando falla y qué gates dependen de una
 * bandera de entorno.
 *
 * No se ejercitan aquí los caminos que acaban en `window.location.href`: en
 * jsdom no hay navegación que comprobar. Esos los cubre `e2e/login.spec.ts`.
 *
 * La sesión se simula: la página pregunta a `useSession` si ya hay alguien
 * dentro (F55) y, sin `SessionProvider`, el hook real lanza.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

type UsuarioSimulado = {
  user_id: string;
  email: string;
  display_name: null;
  is_admin: boolean;
  mfa_required?: boolean;
};

const { query, sesion } = vi.hoisted(() => ({
  query: { actual: "" },
  sesion: { actual: { user: null as UsuarioSimulado | null, isLoading: false } },
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(query.actual),
}));

vi.mock("@/lib/analytics", () => ({
  registrarEvento: vi.fn(),
  primeraVez: vi.fn(),
}));

vi.mock("@/lib/auth", () => ({
  useSession: () => ({
    ...sesion.actual,
    isAuthenticated: sesion.actual.user !== null,
    isAdmin: false,
    refresh: async () => {},
  }),
}));

const USUARIO: UsuarioSimulado = {
  user_id: "u-1",
  email: "persona@example.test",
  display_name: null,
  is_admin: false,
};

import LoginPage from "@/app/login/page";

/** Respuesta de error tal y como la devuelve la API (RFC-7807 abreviado). */
function respuestaError(status: number, detail: string): Response {
  return new Response(JSON.stringify({ detail }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  query.actual = "";
  sesion.actual = { user: null, isLoading: false };
  window.history.replaceState({}, "", "/login");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("orden de los caminos de entrada", () => {
  it("Google se ofrece antes que el formulario de cuenta local", () => {
    // Es el acceso recomendado: el que menos falla y el único que no exige
    // recordar una contraseña. El E2E comprueba lo mismo sobre el build.
    render(<LoginPage />);

    const google = screen.getByRole("button", { name: "Continuar con Google" });
    const email = screen.getByLabelText(/correo electrónico/i);

    expect(google.compareDocumentPosition(email) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("sin bandera de entorno no se ofrece Microsoft", () => {
    // El backend responde 501 a `/auth/oauth/microsoft/authorize` mientras
    // `OAUTH_MICROSOFT_CLIENT_ID` no esté configurado: enseñar el botón sería
    // prometer una entrada que no existe. El caso contrario —con la bandera
    // puesta— vive en `oauth-microsoft.test.tsx`, porque la constante se lee al
    // evaluar el módulo y hay que fijar el entorno antes de importarlo.
    render(<LoginPage />);

    expect(screen.queryByRole("button", { name: "Continuar con Microsoft" })).toBeNull();
  });

  it("con el alta cerrada no hay pestaña de registro ni confirmación", () => {
    // En producción `ALLOW_SELF_REGISTRATION` está apagado y `POST
    // /auth/register` responde 403: la pestaña llevaba a un formulario cuyo
    // único final posible era un error.
    render(<LoginPage />);

    expect(screen.queryByRole("tab", { name: /crear cuenta/i })).toBeNull();
    expect(document.querySelector("#confirm-password")).toBeNull();
    expect(screen.getByText(/el acceso es por invitación/i)).toBeInTheDocument();
  });
});

describe("acceso con contraseña", () => {
  it("un 401 se traduce a «Credenciales incorrectas» y marca los campos", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respuestaError(401, "Unauthorized")));
    render(<LoginPage />);

    fireEvent.change(screen.getByLabelText(/correo electrónico/i), {
      target: { value: "persona@example.test" },
    });
    fireEvent.change(screen.getByLabelText(/^contraseña/i), {
      target: { value: "la-que-no-es" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Iniciar sesión" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Credenciales incorrectas");
    expect(document.querySelector("#email")).toHaveAttribute("aria-invalid", "true");
    // El `aria-describedby` es lo que hace que el lector de pantalla anuncie el
    // motivo del fallo al volver al campo.
    expect(document.querySelector("#password")?.getAttribute("aria-describedby")).toContain(
      "login-error",
    );
  });

  it("cualquier otro fallo de la API enseña su detalle, no un genérico", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(respuestaError(429, "Demasiados intentos desde esta IP")),
    );
    render(<LoginPage />);

    fireEvent.change(screen.getByLabelText(/correo electrónico/i), {
      target: { value: "persona@example.test" },
    });
    fireEvent.change(screen.getByLabelText(/^contraseña/i), { target: { value: "sea-cual-sea" } });
    fireEvent.click(screen.getByRole("button", { name: "Iniciar sesión" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Demasiados intentos desde esta IP");
  });

  it("el ojo alterna entre ocultar y mostrar la contraseña", () => {
    render(<LoginPage />);

    expect(document.querySelector("#password")).toHaveAttribute("type", "password");
    fireEvent.click(screen.getByRole("button", { name: "Mostrar contraseña" }));
    expect(document.querySelector("#password")).toHaveAttribute("type", "text");
    fireEvent.click(screen.getByRole("button", { name: "Ocultar contraseña" }));
    expect(document.querySelector("#password")).toHaveAttribute("type", "password");
  });
});

describe("lo que trae la URL", () => {
  it("«?mfa=required» abre el gate del segundo factor en vez del formulario", async () => {
    // El callback de OAuth vuelve así cuando la cuenta tiene TOTP: la sesión ya
    // existe pero está pendiente, y ofrecer el formulario de acceso aquí
    // mandaría al usuario a repetir un login que ya hizo.
    query.actual = "mfa=required";
    render(<LoginPage />);

    // El gate llega en su propio trozo (React.lazy): se espera a que aparezca.
    expect(await screen.findByLabelText("Código de verificación")).toBeInTheDocument();
    expect(screen.queryByLabelText(/correo electrónico/i)).toBeNull();
    expect(screen.getByRole("button", { name: /Verificar/ })).toBeInTheDocument();
  });

  it("un error del callback se traduce a un mensaje propio", () => {
    query.actual = "error=email_not_allowed";
    render(<LoginPage />);

    expect(screen.getByRole("alert")).toHaveTextContent("Tu cuenta no tiene acceso a TenderFlow");
  });

  it("un código de error desconocido cae al mensaje genérico", () => {
    query.actual = "error=algo_que_nadie_previo";
    render(<LoginPage />);

    expect(screen.getByRole("alert")).toHaveTextContent("No se pudo completar el inicio de sesión");
  });

  it("«?invitacion=» avisa de que hay que entrar con el mismo correo", () => {
    query.actual = "invitacion=tok3n";
    render(<LoginPage />);

    expect(screen.getByRole("status")).toHaveTextContent(/mismo correo/);
  });

  it("sin invitación no se enseña el aviso", () => {
    render(<LoginPage />);

    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("gate del segundo factor", () => {
  beforeEach(() => {
    query.actual = "mfa=required";
  });

  it("no se puede verificar sin código", async () => {
    render(<LoginPage />);

    expect(await screen.findByRole("button", { name: /Verificar/ })).toBeDisabled();
  });

  it("un código incorrecto se distingue de un bloqueo por intentos", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respuestaError(401, "invalid code")));
    render(<LoginPage />);

    fireEvent.change(await screen.findByLabelText("Código de verificación"), {
      target: { value: "000000" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Verificar/ }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Código incorrecto"),
    );
  });

  it("el 429 pide esperar en vez de repetir el código", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respuestaError(429, "rate limited")));
    render(<LoginPage />);

    fireEvent.change(await screen.findByLabelText("Código de verificación"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Verificar/ }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Demasiados intentos fallidos"),
    );
  });
});

describe("con la sesión ya abierta (F55)", () => {
  it("ofrece seguir en vez de volver a pedir la contraseña", async () => {
    sesion.actual = { user: USUARIO, isLoading: false };
    render(<LoginPage />);

    // La rama llega en su propio trozo (React.lazy): se espera a que aparezca.
    expect(await screen.findByText(/Ya has entrado como/)).toHaveTextContent("persona@example.test");
    expect(screen.getByRole("link", { name: "Ir a Resumen" })).toHaveAttribute("href", "/resumen");
    expect(screen.getByRole("button", { name: "Entrar con otra cuenta" })).toBeInTheDocument();
    expect(screen.queryByLabelText(/correo electrónico/i)).toBeNull();
  });

  it("el botón lleva al destino del «?redirect=» saneado", async () => {
    sesion.actual = { user: USUARIO, isLoading: false };
    query.actual = "redirect=%2Fradar";
    render(<LoginPage />);

    expect(await screen.findByRole("link", { name: "Continuar" })).toHaveAttribute("href", "/radar");
  });

  it("mientras la sesión no ha respondido se enseña el formulario", () => {
    sesion.actual = { user: null, isLoading: true };
    render(<LoginPage />);

    expect(screen.getByLabelText(/correo electrónico/i)).toBeInTheDocument();
    expect(screen.queryByText(/Ya has entrado como/)).toBeNull();
  });

  it("una cuenta con segundo factor sigue viendo el formulario", () => {
    // `/auth/me` no dice si el segundo factor de esta sesión ya se verificó:
    // ante la duda, el formulario, como antes.
    sesion.actual = { user: { ...USUARIO, mfa_required: true }, isLoading: false };
    render(<LoginPage />);

    expect(screen.getByLabelText(/correo electrónico/i)).toBeInTheDocument();
    expect(screen.queryByText(/Ya has entrado como/)).toBeNull();
  });

  it("con una invitación en la URL manda el formulario: se canjea al entrar", () => {
    sesion.actual = { user: USUARIO, isLoading: false };
    query.actual = "invitacion=tok3n";
    render(<LoginPage />);

    expect(screen.getByRole("status")).toHaveTextContent(/mismo correo/);
    expect(screen.getByLabelText(/correo electrónico/i)).toBeInTheDocument();
  });

  it("con un error del callback manda el formulario, con su aviso", () => {
    sesion.actual = { user: USUARIO, isLoading: false };
    query.actual = "error=email_not_allowed";
    render(<LoginPage />);

    expect(screen.getByRole("alert")).toHaveTextContent("Tu cuenta no tiene acceso a TenderFlow");
    expect(screen.queryByText(/Ya has entrado como/)).toBeNull();
  });
});

describe("la puerta", () => {
  it("tiene un titular y el logo lleva a la portada", () => {
    render(<LoginPage />);

    expect(screen.getByRole("heading", { level: 1, name: "Entra en TenderFlow" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "TenderFlow — inicio" })).toHaveAttribute("href", "/");
    // Destino del enlace de salto del layout raíz.
    expect(document.querySelector("main#main-content")).toHaveAttribute("tabindex", "-1");
  });

  it("la nota de invitación enlaza siempre al formulario de la portada", () => {
    render(<LoginPage />);

    expect(screen.getByRole("link", { name: "Solicita acceso para tu equipo" })).toHaveAttribute(
      "href",
      "/#solicitar-acceso",
    );
  });

  it("con el alta cerrada el formulario no se anuncia como panel de pestañas", () => {
    // Un `tabpanel` etiquetado por una pestaña que no existe era un error de ARIA.
    render(<LoginPage />);

    expect(screen.queryByRole("tabpanel")).toBeNull();
    expect(document.querySelector("#auth-panel")).not.toBeNull();
  });
});

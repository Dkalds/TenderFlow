/**
 * La pantalla de acceso es el camino por el que entra todo el mundo, y acaba de
 * repartirse entre `_hooks/use-login-form.ts` y seis piezas de `_components/`.
 * Hasta ahora solo la cubría el E2E, que exige API, build y navegador; estos
 * casos fijan sin nada de eso lo que el troceado no podía cambiar: qué se
 * ofrece primero, qué se enseña cuando falla y qué gates dependen de una
 * bandera de entorno. También los dos finales del alta (RFC
 * 2026-10-21-alta-con-contrasena-tras-concesion): 201 con sesión en el modo
 * abierto y 202 con «Revisa tu correo» en el cerrado.
 *
 * No se ejercitan aquí los caminos que acaban en `window.location.href`: en
 * jsdom no hay navegación que comprobar. Esos los cubre `e2e/login.spec.ts`.
 *
 * La sesión se simula: la página pregunta a `useSession` si ya hay alguien
 * dentro (F55) y, sin `SessionProvider`, el hook real lanza.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

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
import { registrarEvento } from "@/lib/analytics";

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
  vi.mocked(registrarEvento).mockClear();
});

/** Respuesta correcta de la API con su estado. */
function respuesta(status: number, cuerpo: unknown): Response {
  return new Response(JSON.stringify(cuerpo), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const CORREO = "persona@example.test";
const CLAVE = "NuevaClave2026"; // pragma: allowlist secret

/** Abre la pestaña de alta y rellena el formulario con datos válidos. */
function rellenarAlta() {
  fireEvent.click(screen.getByRole("tab", { name: "Crear cuenta" }));
  fireEvent.change(screen.getByLabelText(/correo electrónico/i), { target: { value: CORREO } });
  fireEvent.change(document.querySelector("#password")!, { target: { value: CLAVE } });
  fireEvent.change(document.querySelector("#confirm-password")!, { target: { value: CLAVE } });
}

/** Rellena el acceso con contraseña y lo envía. */
function entrarConContrasena() {
  fireEvent.change(screen.getByLabelText(/correo electrónico/i), { target: { value: CORREO } });
  fireEvent.change(screen.getByLabelText(/^contraseña/i), { target: { value: CLAVE } });
  fireEvent.click(screen.getByRole("button", { name: "Iniciar sesión" }));
}

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

  it("la pestaña de crear cuenta se ofrece siempre, sin bandera de entorno", () => {
    // Estuvo oculta tras `NEXT_PUBLIC_ALLOW_SELF_REGISTRATION` mientras el alta
    // solo podía acabar en 403. Con la concesión de acceso, quien la tiene se
    // da de alta aquí.
    render(<LoginPage />);

    expect(screen.getByRole("tab", { name: "Iniciar sesión" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Crear cuenta" })).toHaveAttribute("aria-selected", "false");
    expect(document.querySelector("#confirm-password")).toBeNull();
    expect(screen.getByText(/el acceso es por invitación/i)).toBeInTheDocument();
  });

  it("el alta avisa de que hace falta el acceso concedido, con enlace a pedirlo", () => {
    render(<LoginPage />);
    fireEvent.click(screen.getByRole("tab", { name: "Crear cuenta" }));

    expect(screen.getByText(/tu correo tiene que tener el acceso concedido/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "¿Aún no lo tienes? Solicítalo" })).toHaveAttribute(
      "href",
      "/#solicitar-acceso",
    );
    // La nota del acceso no se repite debajo con el mismo enlace.
    expect(screen.queryByText(/el acceso es por invitación/i)).toBeNull();
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
    expect(document.querySelector("#password")?.getAttribute("aria-describedby")).toContain("login-error");
  });

  it("cualquier otro fallo de la API enseña su detalle, no un genérico", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respuestaError(429, "Demasiados intentos desde esta IP")));
    render(<LoginPage />);

    fireEvent.change(screen.getByLabelText(/correo electrónico/i), {
      target: { value: "persona@example.test" },
    });
    fireEvent.change(screen.getByLabelText(/^contraseña/i), { target: { value: "sea-cual-sea" } });
    fireEvent.click(screen.getByRole("button", { name: "Iniciar sesión" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Demasiados intentos desde esta IP");
  });

  it("una cuenta sin activar lo explica y ofrece otro enlace desde el alta", async () => {
    // La contraseña es buena pero nadie pulsó el enlace del correo. El enlace
    // nuevo sale repitiendo el alta con el mismo correo.
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respuestaError(403, "email_not_verified")));
    render(<LoginPage />);

    entrarConContrasena();

    const aviso = await screen.findByRole("alert");
    expect(aviso).toHaveTextContent("Todavía no has activado la cuenta");
    expect(document.querySelector("#email")?.getAttribute("aria-describedby")).toContain("login-error");

    fireEvent.click(within(aviso).getByRole("button", { name: "Recibir otro enlace" }));

    expect(screen.getByRole("tab", { name: "Crear cuenta" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByLabelText(/correo electrónico/i)).toHaveValue(CORREO);
    expect(document.querySelector("#confirm-password")).not.toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("una cuenta que perdió el acceso lo dice y enlaza a pedirlo", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respuestaError(403, "access_not_granted")));
    render(<LoginPage />);

    entrarConContrasena();

    const aviso = await screen.findByRole("alert");
    expect(aviso).toHaveTextContent("Tu cuenta ya no tiene acceso a TenderFlow.");
    expect(within(aviso).getByRole("link", { name: "Solicita acceso" })).toHaveAttribute("href", "/#solicitar-acceso");
    // El código crudo de la API no llega a la pantalla.
    expect(aviso).not.toHaveTextContent("access_not_granted");
  });

  it("el ojo alterna entre ocultar y mostrar la contraseña", () => {
    render(<LoginPage />);

    expect(document.querySelector("#password")).toHaveAttribute("type", "password");
    fireEvent.click(screen.getByRole("button", { name: "Mostrar contraseña" }));
    expect(document.querySelector("#password")).toHaveAttribute("type", "text");
    fireEvent.click(screen.getByRole("button", { name: "Ocultar contraseña" }));
    expect(document.querySelector("#password")).toHaveAttribute("type", "password");
  });

  it("quien la ha olvidado tiene un enlace a la pantalla de recuperación", () => {
    // Sin esta salida, la recuperación existe pero no se encuentra: nadie
    // llega a `/restablecer-contrasena` si no es desde aquí o desde el correo.
    render(<LoginPage />);

    expect(screen.getByRole("link", { name: "¿Has olvidado tu contraseña?" })).toHaveAttribute(
      "href",
      "/restablecer-contrasena",
    );
  });
});

describe("alta con correo y contraseña", () => {
  it("con el alta cerrada (202) pide revisar el correo y no entra", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        respuesta(202, { detail: "Revisa tu correo: te hemos enviado un enlace para activar la cuenta." }),
      );
    vi.stubGlobal("fetch", fetchMock);
    render(<LoginPage />);

    rellenarAlta();
    fireEvent.click(screen.getByRole("button", { name: "Crear cuenta" }));

    // El panel llega en su propio trozo (React.lazy).
    const aviso = await screen.findByRole("status");
    expect(aviso).toHaveTextContent("Revisa tu correo");
    expect(aviso).toHaveTextContent(CORREO);
    // Sin sesión no hay entrada que contar ni adónde navegar.
    expect(registrarEvento).not.toHaveBeenCalled();
    expect(window.location.pathname).toBe("/login");
    expect(screen.queryByLabelText(/correo electrónico/i)).toBeNull();

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/auth/register");
    expect(JSON.parse(String(init.body))).toEqual({ email: CORREO, password: CLAVE });
  });

  it("«Volver a enviar el enlace» repite el alta con los mismos datos", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => respuesta(202, { detail: "Revisa tu correo." }));
    vi.stubGlobal("fetch", fetchMock);
    render(<LoginPage />);

    rellenarAlta();
    fireEvent.click(screen.getByRole("button", { name: "Crear cuenta" }));
    fireEvent.click(await screen.findByRole("button", { name: "Volver a enviar el enlace" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const [, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({ email: CORREO, password: CLAVE });
    expect(await screen.findByText(/te hemos enviado otro enlace/i)).toBeInTheDocument();
  });

  it("«Usar otro correo» vuelve al formulario con lo escrito", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respuesta(202, { detail: "Revisa tu correo." })));
    render(<LoginPage />);

    rellenarAlta();
    fireEvent.click(screen.getByRole("button", { name: "Crear cuenta" }));
    fireEvent.click(await screen.findByRole("button", { name: "Usar otro correo" }));

    expect(screen.getByLabelText(/correo electrónico/i)).toHaveValue(CORREO);
    expect(screen.getByRole("tab", { name: "Crear cuenta" })).toHaveAttribute("aria-selected", "true");
  });

  it("con el alta abierta (201) entra y cuenta la sesión", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          respuesta(201, { user_id: 7, email: CORREO, display_name: null, is_admin: false, mfa_required: false }),
        ),
    );
    render(<LoginPage />);

    rellenarAlta();
    fireEvent.click(screen.getByRole("button", { name: "Crear cuenta" }));

    await waitFor(() => expect(registrarEvento).toHaveBeenCalledWith("sesion_iniciada", { metodo: "registro" }));
    expect(screen.queryByText("Revisa tu correo")).toBeNull();
  });

  it("un correo sin el acceso concedido lo dice y enlaza a pedirlo", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respuestaError(403, "access_not_granted")));
    render(<LoginPage />);

    rellenarAlta();
    fireEvent.click(screen.getByRole("button", { name: "Crear cuenta" }));

    const aviso = await screen.findByRole("alert");
    expect(aviso).toHaveTextContent("Este correo no tiene acceso a TenderFlow todavía.");
    expect(within(aviso).getByRole("link", { name: "Solicita acceso" })).toHaveAttribute("href", "/#solicitar-acceso");
    expect(document.querySelector("#confirm-password")?.getAttribute("aria-describedby")).toContain("login-error");
    expect(registrarEvento).not.toHaveBeenCalled();
  });

  it("una contraseña que la API rechaza enseña su motivo", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respuestaError(400, "La contraseña es demasiado común.")));
    render(<LoginPage />);

    rellenarAlta();
    fireEvent.click(screen.getByRole("button", { name: "Crear cuenta" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("La contraseña es demasiado común.");
  });
});

describe("lo que trae la URL", () => {
  it("«?modo=registro&email=» abre el alta con el correo puesto", () => {
    // Es el enlace del correo de «acceso concedido».
    query.actual = `modo=registro&email=${encodeURIComponent("nueva+equipo@example.test")}`;
    render(<LoginPage />);

    expect(screen.getByRole("tab", { name: "Crear cuenta" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByLabelText(/correo electrónico/i)).toHaveValue("nueva+equipo@example.test");
    expect(document.querySelector("#confirm-password")).not.toBeNull();
  });

  it("«?email=» solo prerrellena el acceso", () => {
    query.actual = "email=persona%40example.test";
    render(<LoginPage />);

    expect(screen.getByRole("tab", { name: "Iniciar sesión" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByLabelText(/correo electrónico/i)).toHaveValue("persona@example.test");
  });

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

  it("el correo de una cuenta de otro proveedor dice con cuál entrar (ADR-037)", () => {
    query.actual = "error=account_other_provider";
    render(<LoginPage />);

    expect(screen.getByRole("alert")).toHaveTextContent("ya tiene cuenta con otro proveedor");
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

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Código incorrecto"));
  });

  it("el 429 pide esperar en vez de repetir el código", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respuestaError(429, "rate limited")));
    render(<LoginPage />);

    fireEvent.change(await screen.findByLabelText("Código de verificación"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Verificar/ }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Demasiados intentos fallidos"));
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

  it("lleva el fondo en movimiento, decorativo y después del formulario", async () => {
    // Volvió el 2026-10-04. Llega en su propio trozo (React.lazy), va al final
    // del DOM —detrás solo por apilamiento— y el lector de pantalla no lo ve.
    // Lo que hace el lienzo se comprueba en `fondo-particulas.test.tsx`; aquí
    // jsdom no le da contexto 2D y no pinta nada.
    render(<LoginPage />);

    const lienzo = await waitFor(() => {
      const encontrado = document.querySelector("canvas");
      expect(encontrado).not.toBeNull();
      return encontrado as HTMLCanvasElement;
    });

    expect(lienzo).toHaveAttribute("aria-hidden", "true");
    const principal = document.querySelector("main#main-content") as HTMLElement;
    expect(principal.compareDocumentPosition(lienzo) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(principal.contains(lienzo)).toBe(false);
  });

  it("la nota de invitación enlaza siempre al formulario de la portada", () => {
    render(<LoginPage />);

    expect(screen.getByRole("link", { name: "Solicita acceso para tu equipo" })).toHaveAttribute(
      "href",
      "/#solicitar-acceso",
    );
  });

  it("el formulario es el panel de la pestaña activa", () => {
    render(<LoginPage />);

    expect(screen.getByRole("tabpanel")).toHaveAttribute("id", "auth-panel");
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", "tab-login");
    fireEvent.click(screen.getByRole("tab", { name: "Crear cuenta" }));
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", "tab-register");
  });
});

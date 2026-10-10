import { describe, expect, it } from "vitest";
import type { Breadcrumb, ErrorEvent } from "@sentry/nextjs";
import { limpiarEvento, limpiarMiga, sinQuery } from "@/lib/sentry-opciones";

function evento(parcial: Partial<ErrorEvent>): ErrorEvent {
  return { type: undefined, ...parcial };
}

describe("sinQuery", () => {
  it("recorta la query y el fragmento", () => {
    expect(sinQuery("https://tenderflow.es/mercado?tecnologia=SAP&organo=Acme#fila")).toBe(
      "https://tenderflow.es/mercado",
    );
    expect(sinQuery("/radar#detalle")).toBe("/radar");
  });

  it("deja igual una URL sin ninguno de los dos", () => {
    expect(sinQuery("/oportunidades/42")).toBe("/oportunidades/42");
  });
});

describe("limpiarEvento", () => {
  it("la URL y el Referer viajan sin query", () => {
    const limpio = limpiarEvento(
      evento({
        request: {
          url: "https://tenderflow.es/mercado?empresa=Acme+SL",
          headers: { Referer: "https://tenderflow.es/cuentas?q=Acme", "User-Agent": "Firefox" },
        },
      }),
    );
    expect(limpio.request?.url).toBe("https://tenderflow.es/mercado");
    expect(limpio.request?.headers).toEqual({ Referer: "https://tenderflow.es/cuentas", "User-Agent": "Firefox" });
  });

  it("no viajan la query aparte, las cookies ni el cuerpo", () => {
    const limpio = limpiarEvento(
      evento({
        request: {
          url: "/login",
          query_string: "redirect=/mercado",
          cookies: { session: "token" },
          data: { mensaje: "texto del formulario" },
        },
      }),
    );
    expect(limpio.request).toEqual({ url: "/login" });
  });

  it("de las cabeceras solo pasan host, user-agent y referer, se escriban como se escriban", () => {
    const limpio = limpiarEvento(
      evento({
        request: {
          headers: {
            Host: "tenderflow.es",
            "user-agent": "Firefox",
            cookie: "session=valor",
            Authorization: "Bearer valor",
            "x-forwarded-for": "203.0.113.7",
            "x-vercel-ip-city": "Madrid",
            "x-nonce": "abc",
            "content-security-policy": "script-src 'nonce-abc'",
          },
        },
      }),
    );
    expect(limpio.request?.headers).toEqual({ Host: "tenderflow.es", "user-agent": "Firefox" });
  });

  it("la ruta que apunta el SDK de Next viaja sin query", () => {
    const limpio = limpiarEvento(
      evento({ contexts: { nextjs: { request_path: "/mercado?empresa=Acme", router_kind: "App Router" } } }),
    );
    expect(limpio.contexts?.nextjs).toEqual({ request_path: "/mercado", router_kind: "App Router" });
  });

  it("del usuario solo queda el id", () => {
    const limpio = limpiarEvento(
      evento({ user: { id: "u_1", email: "ana@acme.es", username: "ana", ip_address: "203.0.113.7" } }),
    );
    expect(limpio.user).toEqual({ id: "u_1" });
  });

  it("un usuario sin id se queda vacío", () => {
    expect(limpiarEvento(evento({ user: { email: "ana@acme.es" } })).user).toEqual({});
  });

  it("un evento sin petición ni usuario pasa tal cual", () => {
    const original = evento({ message: "boom" });
    expect(limpiarEvento(original)).toEqual({ type: undefined, message: "boom" });
  });
});

describe("limpiarMiga", () => {
  it("descarta las de consola", () => {
    expect(limpiarMiga({ category: "console", message: "objeto de dominio" })).toBeNull();
  });

  it("las de navegación y de red viajan sin query", () => {
    const navegacion: Breadcrumb = { category: "navigation", data: { from: "/mercado?organo=Acme", to: "/radar?p=2" } };
    expect(limpiarMiga(navegacion)?.data).toEqual({ from: "/mercado", to: "/radar" });

    const red: Breadcrumb = { category: "fetch", data: { url: "/api/v1/licitaciones?q=Acme", status_code: 200 } };
    expect(limpiarMiga(red)?.data).toEqual({ url: "/api/v1/licitaciones", status_code: 200 });
  });

  it("deja pasar una miga sin datos", () => {
    const clic: Breadcrumb = { category: "ui.click", message: "button.tf-boton" };
    expect(limpiarMiga(clic)).toEqual(clic);
  });
});

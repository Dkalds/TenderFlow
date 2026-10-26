# Runbook: IP del cliente tras Vercel y Render (secreto de origen)

**Propósito**: que la API vea la IP de cada visitante y no la del proxy de
Render, para que el rate limiting, el bloqueo de login y la recuperación de
contraseña cuenten por persona.

**Responsable**: propietario (paneles de Vercel y Render).
**Decisión**: [RFC 2026-10-24, opción B](../rfc/2026-10-24-rfc-ip-del-cliente-tras-vercel-y-render.md) (D58 del [plan 2026-10](../plans/2026-10-plan-foco-piloto.md)).

---

## Cómo funciona

1. Vercel reenvía `/api/*` a Render. Una ruta de `web/vercel.json` borra la
   cabecera `x-tf-origin-secret` que traiga el visitante y pone en su lugar el
   valor de la variable `API_ORIGIN_SECRET`.
2. El prefetch SSR (`web/src/lib/server-prefetch.ts`) manda el mismo secreto y
   el `x-real-ip` que recibió.
3. La API (`api/middleware.py::_trusted_client_ip`) compara la cabecera en
   tiempo constante con `API_ORIGIN_SECRET` y `API_ORIGIN_SECRET_PREVIOUS`. Si
   casa, la IP es `x-real-ip`; si no, la de antes (el nodo `10.19x` del proxy).

Un fallo de configuración —secreto ausente o distinto en un lado— **no bloquea
a nadie**: la API vuelve a contar por nodo del proxy. Por eso hay que
verificarlo (paso 4), porque no se nota solo.

## 1. Generar el secreto

```bash
openssl rand -hex 32
```

(o `python -c "import secrets; print(secrets.token_hex(32))"`). Mínimo 32
caracteres: la API no arranca con uno más corto. No lo pegues en ningún chat,
issue ni commit.

## 2. Ponerlo en los dos paneles

- **Render**, servicio de la API (`TenderFlow`): *Environment* →
  `API_ORIGIN_SECRET` = el valor. `render.yaml` ya la declara `sync: false`.
  Guardar redespliega.
- **Vercel**, proyecto `tenderflow`: *Settings → Environment Variables* →
  `API_ORIGIN_SECRET`, marcada **Sensitive**, solo en **Production**. Nunca con
  prefijo `NEXT_PUBLIC_` (iría al navegador). Redesplegar producción para que
  la tome.

El orden da igual: hasta que los dos lados coinciden, todo sigue como antes.

## 3. Comprobar la regla en un preview (una vez, antes de producción)

`web/vercel.json` añade una ruta `routes` con `continue: true` delante del
rewrite que genera `next.config.ts`. Hay que confirmar que conviven:

1. Poner temporalmente `API_ORIGIN_SECRET` también en *Preview* (puede ser otro
   valor) y abrir el preview del PR.
2. La app carga y las llamadas a `/api/*` responden (si el preview no tiene
   `API_BASE_URL`, el rewrite apunta a localhost y esto no se puede ver; usar
   un preview con la variable).
3. Si `/api/*` deja de responder, la ruta se queda con la petición en vez de
   seguir al rewrite: mover el rewrite a esa misma ruta
   (`"dest": "${API_BASE_URL}/api/$1"` con `"env": ["API_BASE_URL"]`) y
   quitarlo de `next.config.ts`. Anotarlo en el RFC.
4. Quitar la variable de *Preview* al terminar.

Confirmar también que el plan del proyecto de Vercel admite `transforms` en
`routes` (pregunta 3 del RFC).

## 4. Verificar en producción (dos redes distintas)

Lo hace el propietario: son peticiones contra producción.

1. Dos personas, en redes distintas (wifi de casa y datos del móvil), abren la
   app con sesión.
2. En los logs del servicio de la API en Render, filtrar `http_request` con
   `path` `/api/v1/auth/me`:
   - cada persona tiene su `client_ip`, **pública**, distinta de la otra y
     estable durante la sesión;
   - ninguna empieza por `10.`.
3. En `proxy_cabeceras_diag` (diagnóstico temporal) `origen_acreditado` es
   `true` y `ip_elegida.h` coincide con `x_real_ip.h`.
4. Petición directa al host de Render, sin pasar por Vercel, con una IP
   inventada y un secreto falso:

   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" \
     -H "x-tf-origin-secret: falso" -H "X-Real-IP: 203.0.113.7" \
     https://tenderflow-jrtr.onrender.com/api/v1/auth/me
   ```

   En el log, su `client_ip` **no** es `203.0.113.7`.
5. Cuota por persona: cinco logins fallidos contra una cuenta de prueba desde
   una red → 429 ahí; la misma cuenta entra desde la otra red.
6. `/me/sesiones` enseña la IP del visitante, no la del proxy.

Anotar fecha y resultado en el RFC (§7 y criterios de aceptación). Con eso se
puede retirar `api/diagnostico_proxy.py` y su test.

## Rotar el secreto

1. Generar uno nuevo (paso 1).
2. **Render**: `API_ORIGIN_SECRET_PREVIOUS` = el valor actual;
   `API_ORIGIN_SECRET` = el nuevo. Redesplegar. Ahora acepta los dos.
3. **Vercel**: `API_ORIGIN_SECRET` = el nuevo. Redesplegar producción.
4. Comprobar el paso 4.2 (IPs públicas y distintas).
5. **Render**: vaciar `API_ORIGIN_SECRET_PREVIOUS`. Redesplegar.

Si se sospecha que el secreto se filtró, lo mismo, sin esperar: quien lo
conoce puede elegir con qué IP cuenta en las cuotas, pero no autenticarse.

## Si algo va mal

- **Arranque con `api_origin_secret_not_configured`**: falta la variable en
  Render. La API funciona y cuenta por nodo del proxy.
- **La API no arranca: «API_ORIGIN_SECRET tiene que tener al menos 32
  caracteres»**: valor corto o mal pegado en Render.
- **Siguen saliendo `10.x` con el secreto en los dos lados**: mirar
  `origen_acreditado` en `proxy_cabeceras_diag`. Si es `false`, los valores no
  coinciden o Vercel no aplica la regla (paso 3). Si es `true` y aun así sale
  `10.x`, no llega `x-real-ip` ni un `X-Forwarded-For` utilizable: revisar el
  RFC (§4 y §6).
- **Marcha atrás**: vaciar `API_ORIGIN_SECRET` en Render. Vuelve el
  comportamiento de antes; no hace falta tocar Vercel.

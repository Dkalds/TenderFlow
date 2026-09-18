---
rfc: 2026-09-18-retirar-user-key-payload-watchlist-rule-matched
title: Retirar `user_key` del payload del webhook `watchlist_rule.matched`
issue: (sin issue: ADR-030 fase 3, T4 del plan de arquitectura 2026-09 v2)
author: agent:claude-code
date: 2026-09-18
status: draft
retirada_propuesta: 2026-12-17
---

## Contexto

ADR-030 retira `user_key` —la clave `sha256(email)[:16]`— como identidad
interna. La fase 3 (v135, 2026-09-18) deja de escribirla en `user_profiles`,
mueve las PK de `user_profiles` y `radar_dismissals` a `user_id` y baja el
ratchet de `scripts/check_user_key_ratchet.py` de 69 a 63 ficheros.

Uno de los 63 no se puede sacar tocando sólo código interno:
`shared/events.py` declara el evento de webhook `watchlist_rule.matched` con
los campos `("rule_id", "user_key", "total_matches")`, y
`scheduler/watchlist_rules_alerts.py` lo escribe en el outbox con este payload:

```json
{
  "rule_id": 42,
  "user_key": "<16 caracteres hex>",
  "nombre": "…", "keyword": "…", "cpv": "…",
  "total_matches": 3,
  "licitaciones": ["…"]
}
```

El evento existía como suscripción de webhook **antes** del catálogo de S4, así
que hay receptores externos —integraciones de las organizaciones— que pueden
estar leyendo `user_key`. Quitarlo es un cambio incompatible del contrato
publicado, y `docs/api-design.md` no deja hacerlo sin RFC y sin ventana.

## Por qué esto necesita un RFC

* Es contrato hacia fuera: el receptor no está en este repositorio y no hay
  forma de saber desde aquí si alguien usa el campo.
* `user_key` **cambia cuando el usuario cambia de correo**. Un receptor que la
  use para agrupar o deduplicar por persona ya tiene hoy un fallo latente: tras
  un cambio de email, la misma persona aparece como otra. Mantener el campo
  indefinidamente es mantener ese fallo.
* La derivación es un hash de 16 hex sin sal sobre el correo normalizado. Para
  quien conozca el correo de un usuario es trivial comprobar la
  correspondencia: es un dato personal seudonimizado, no anónimo, que viaja a
  terceros sin que ninguna decisión lo haya pedido.

## Propuesta

Dos fases, con la ventana de 90 días del contrato
(`api/errors.py::DEPRECATION_WINDOW_DAYS`) contada desde el anuncio.

**Fase A — anuncio (desde la aprobación de este RFC).** El campo **sigue en el
payload con el mismo valor**; no cambia nada para ningún receptor. Se anuncia
la retirada, con su fecha, a quien tenga una suscripción activa a
`watchlist_rule.matched` (el canal concreto lo decide quien apruebe el RFC). Este RFC fija esa fecha en `retirada_propuesta`
(2026-09-18 + 90 días = 2026-12-17) y se corre si el anuncio sale más tarde.

**Fase B — retirada (no antes de la fecha).** `user_key` sale de
`CATALOGO["watchlist_rule.matched"].campos` y del payload de
`scheduler/watchlist_rules_alerts.py`. Con ello `shared/events.py` sale del
ratchet.

### Qué recibe el receptor en su lugar — decisión pendiente

Es lo único que este RFC **no** decide, porque no es una decisión técnica:

1. **Nada.** El receptor ya tiene `rule_id`, y la regla pertenece a una persona
   dentro de su organización. Es la opción mínima y la que no expone nada
   nuevo. Recomendada si no hay un receptor que necesite la persona.
2. **`user_id`.** Estable ante cambios de correo, pero es el entero secuencial
   interno de `users`: publicarlo a terceros abre la enumeración de cuentas y
   ata el contrato a la clave primaria.
3. **Un identificador opaco por organización** (p. ej. HMAC del `user_id` con
   un secreto de la organización). Estable y no enumerable, pero es un concepto
   nuevo que habría que mantener para un único campo.

Mientras no se decida, **no se añade ningún campo nuevo**: añadir `user_id`
«por si acaso» convertiría la opción 2 en un hecho consumado.

## Alternativas descartadas

* **Quitarlo ya, sin ventana.** Rompe a quien lo lea sin aviso; es justo lo que
  `docs/api-design.md` prohíbe.
* **Dejarlo para siempre.** Mantiene en el contrato una clave que cambia con el
  correo (el fallo latente de arriba) y bloquea que el ratchet llegue a cero.
* **Congelar el valor** (enviar siempre la clave del primer correo). Estable,
  pero exige guardar esa clave por usuario para siempre: es no retirar
  `user_key`, sólo esconderla.

## Consecuencias

* Hasta la fase B el payload no cambia: ningún receptor nota nada.
* Tras la fase B, un receptor que aún lea `user_key` recibe el evento sin él.
  El resto del payload no cambia.
* `shared/events.py` sale del ratchet en la fase B; hasta entonces sigue en la
  lista con la anotación de 2026-09-07 que ya lo justifica.

## Verificación

* Fase A: `shared/events.py` y `scheduler/watchlist_rules_alerts.py` sin cambios
  de payload; este RFC en `approved` con la opción de «qué recibe en su lugar»
  elegida.
* Fase B: `grep -n user_key shared/events.py` vacío;
  `python scripts/check_user_key_ratchet.py` falla hasta que la entrada se
  borre de `CONGELADOS`, que es la señal de que se ha hecho.

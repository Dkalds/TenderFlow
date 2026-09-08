# ADR-031 — Seguimiento unificado: una tabla `follows`, un control «Seguir»

- **Estado:** aceptado
- **Fecha:** 2026-09-06
- **Relacionado:** [ADR-022](ADR-022-frontera-de-persistencia.md),
  [ADR-027](ADR-027-backbone-de-eventos-outbox.md),
  [ADR-030](ADR-030-identidad-user-id-y-oidc.md)
- **Implementa:** T1 de
  [docs/plans/2026-09-plan-arquitectura-v2.md](../plans/2026-09-plan-arquitectura-v2.md)

---

## Contexto

«Seguir algo» está implementado cuatro veces, con cuatro tablas, cuatro juegos
de endpoints y cuatro controles distintos en la interfaz:

| Qué se sigue | Tabla | Superficie |
|---|---|---|
| Expediente | `watchlist_items` | Radar, Detalle |
| Empresa | `watchlist_empresas` | Empresas |
| Expediente descartado | `radar_dismissals` | Radar |
| Criterio (regla) | `watchlist_rules` | Mi watchlist |

Las consecuencias son las esperables: seguir un órgano o un CPV no existe
porque haría falta una quinta tabla; el usuario aprende cuatro controles que
hacen lo mismo; y cada canal de notificación nuevo (ADR-027) tiene que
enumerar las cuatro tablas para saber a quién avisar.

---

## Decisión

### A. Una tabla poligámica, con `target_type` cerrado

```
follows(id, organization_id, user_id, target_type, target_id, kind,
        visibility, channels_json, created_at)
```

- `target_type ∈ {licitacion, lote, empresa, organo, cpv}` — enumeración
  cerrada, validada en el DTO y en un `CHECK`.
- `kind ∈ {seguir, descartar}` — descartar es seguir con signo negativo, no
  otro concepto. Esa es la razón de que `radar_dismissals` entre aquí.
- `visibility` — personal o de organización (ADR-030 §D: una nota privada sigue
  siendo personal aunque el favorito sea compartido).

**Las reglas no entran.** `watchlist_rules` se queda donde está: una regla es
un criterio que genera coincidencias, no un puntero a una entidad. La interfaz
puede presentarlas juntas (`target_type = regla` solo como etiqueta de UI); el
modelo no las mezcla.

### B. Backfill, lectura dual, y solo entonces retirada

1. Migración aditiva y backfill desde las tres tablas.
2. **Lectura dual** mientras un script de paridad no reproduzca, para cada
   usuario, favoritos + empresas + descartes desde `follows` con **cero
   diferencias**, ejecutado contra producción.
3. Retirada de los nueve endpoints antiguos por RFC, con fecha.

El orden importa: retirar antes de la paridad convierte un bug de backfill en
pérdida de datos del usuario.

### C. Un solo componente «Seguir»

Radar, Detalle, Empresas y Órganos usan el mismo componente. Un control que se
comporta distinto en dos pantallas es dos controles.

### D. `follows` es un productor de eventos, no un notificador

Seguir algo escribe un evento (ADR-027); quién recibe qué lo decide el
despachador cruzando `follows` con las preferencias de notificación. `follows`
no inserta en `user_notifications`.

---

## Consecuencias

**A favor.** Seguir un órgano o un CPV pasa a ser una fila, no una tabla.
El despachador consulta un sitio. La interfaz enseña un control.

**En contra.** Una migración grande sobre datos que el usuario ve todos los
días, y una ventana de lectura dual. La paridad medida en producción (§B) es la
red.

**Riesgo.** `target_id` es polimórfico y por tanto no puede llevar clave
foránea. Mitigación: el `CHECK` sobre `target_type`, y un control periódico que
cuenta `follows` cuyo objetivo ya no existe — igual que los huérfanos que
`audit_domain_truth` ya vigila en otras tablas.

**Lo que este ADR no decide.** Los canales por seguimiento (`channels_json` es
la columna, su vocabulario lo fija C2.7 del plan complementario) ni la fecha de
retirada de los endpoints antiguos, que va por RFC.

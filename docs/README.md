---
title: "Documentación de TenderFlow"
tags: [indice]
---

# Documentación de TenderFlow

Nota de inicio de `docs/`: dónde está cada cosa. Las reglas para trabajar en el
repo no viven aquí sino en [AGENTS.md](../AGENTS.md), en la raíz. Si abriste
`docs/` como vault de Obsidian, ese fichero queda fuera del vault; los ajustes
para que lo que edites en Obsidian se vea igual en GitHub están en
[runbooks/obsidian.md](runbooks/obsidian.md).

`tests/test_docs_paths.py` comprueba que esta nota enlaza todos los documentos
de primer nivel de `docs/` y el índice de cada carpeta: un documento nuevo se
añade aquí en el mismo cambio.

## Estado y trabajo pendiente

- [STATUS.md](STATUS.md) — estado calculado desde el código (generado).
- [IMPROVEMENT_BACKLOG.md](IMPROVEMENT_BACKLOG.md) — el trabajo priorizado; lo
  cerrado pasa a [archive/IMPROVEMENT_BACKLOG_CERRADOS.md](archive/IMPROVEMENT_BACKLOG_CERRADOS.md).
- [UX_AUDIT.md](UX_AUDIT.md) — diagnóstico UX/UI del frontend y su roadmap por olas.
- [casos-de-uso.md](casos-de-uso.md) — lo que una persona hace con el producto
  de punta a punta, y el test que lo recorre.

## Decisiones

- [adr/README.md](adr/README.md) — índice de ADR: decisiones estructurales vigentes (generado).
- [rfc/README.md](rfc/README.md) — índice de RFC: propuestas y su estado (generado).
- `plans/` — planes de trabajo en curso; `superpowers/` — diseños y planes de
  implementación escritos con los skills de superpowers.

## Arquitectura y contratos

- [c4-architecture.md](c4-architecture.md) — diagramas C4.
- [database-schema.md](database-schema.md) — esquema de la BD (generado).
- [api-design.md](api-design.md) — diseño de la API REST y matriz de scopes.
- [frontend-data-invariants.md](frontend-data-invariants.md) — integridad analítica del frontend (ADR-014).
- [frontend-motion.md](frontend-motion.md) — motion en `web/`.
- [testing.md](testing.md) — cómo se organiza y se corre la suite.
- [taxonomia-tecnologica.md](taxonomia-tecnologica.md) — taxonomía tecnológica.

## Datos y cobertura

- [regional-source-coverage.md](regional-source-coverage.md) — cobertura regional de contratación.
- [watched-company-awards-coverage.md](watched-company-awards-coverage.md) — cobertura de adjudicaciones por empresa vigilada.
- [informes-programados.md](informes-programados.md) — informe semanal programado.

## Operación y seguridad

- [runbooks/README.md](runbooks/README.md) — punto de entrada de operación, on-call e incidentes.
- [sli-slo.md](sli-slo.md) — SLI y SLO.
- [SECURITY.md](SECURITY.md) — seguridad y rotación de credenciales.
- [seguridad-resumen.md](seguridad-resumen.md) — resumen para cuestionarios de clientes.
- [COSTES.md](COSTES.md) — coste mensual por proveedor.

## Integraciones

- [integraciones/webhooks.md](integraciones/webhooks.md) — formatos, firma y rotación del secret.
- [integraciones/crm.md](integraciones/crm.md) — exportar el pipeline al CRM.

## Legal

- [legal/registro-tratamientos.md](legal/registro-tratamientos.md) — registro del art. 30 RGPD.
- [legal/anexo-encargo-tratamiento.md](legal/anexo-encargo-tratamiento.md) — anexo de encargo para clientes B2B.
- [legal/subencargados.md](legal/subencargados.md) — subencargados y ubicación del tratamiento.

## Agentes y entorno de trabajo

- [AGENT_PLAYBOOK.md](AGENT_PLAYBOOK.md) — paquetes, workflows, comandos y prerrequisitos.
- [skills-inventory.md](skills-inventory.md) — skills instalados (generado).
- [windows-happy-path.md](windows-happy-path.md) y
  [runbooks/entorno-wsl.md](runbooks/entorno-wsl.md) — entorno en Windows.
- [runbooks/obsidian.md](runbooks/obsidian.md) — leer y editar `docs/` con Obsidian.

## Archivo

`archive/` guarda lo que ya no rige pero explica cómo se llegó a lo que rige: el
backlog cerrado, planes y runbooks ya ejecutados,
[archive/adr-discussions/README.md](archive/adr-discussions/README.md) (las
discusiones de issues y RFC hasta 2026-07) y
[archive/redesign/README.md](archive/redesign/README.md) (el rediseño de
consola).

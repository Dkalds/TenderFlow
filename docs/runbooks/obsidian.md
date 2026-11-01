---
title: "Leer y editar docs/ con Obsidian"
tags: [runbook, entorno, obsidian]
---

# Leer y editar `docs/` con Obsidian

`docs/` se lee en tres sitios a la vez: en GitHub, en Obsidian y desde los
agentes, que leen el texto crudo. Todo lo de esta nota sirve para que un cambio
hecho en Obsidian se siga viendo bien en los otros dos.

## Qué carpeta abrir como vault

**`docs/`.** Es donde está toda la documentación, y la nota de inicio es
[docs/README.md](../README.md). El repo también admite abrir la raíz: el
`.gitignore` cubre `.obsidian/`, `.trash/` y las notas sin nombre en los dos
casos. Con la raíz, el vault suma `AGENTS.md` y el `README.md` del repo, pero
también todos los `.md` de `tests/` y demás, y sobre todo los de
`web/node_modules/`: unos 1.800 de las ~2.060 notas que verá (medido el
2026-10-31). Hay que excluirlos (ver «Excluded files» abajo).

Los links de `docs/` al código (`../services/*.py`, `../web/src/…`) salen en
Obsidian como no resueltos, porque Obsidian no abre `.py` ni `.tsx`. Están bien
así: en GitHub funcionan, que es donde se siguen.

## Ajustes

Viven en `.obsidian/`, que no se versiona (es estado de cada persona), así que
hay que ponerlos a mano una vez:

| Dónde | Ajuste | Valor | Por qué |
|---|---|---|---|
| Files and links | `Use [[Wikilinks]]` | **desactivado** | GitHub no renderiza wikilinks: en el cuerpo de una nota salen como texto literal, y en una tabla el `\|` del alias parte la celda. `make check-agent-docs` los rechaza. |
| Files and links | New link format | **Relative path to file** | Es como están escritos todos los links de `docs/`, y lo único que resuelve igual en GitHub. |
| Files and links | Automatically update internal links | **activado** | Al renombrar o mover una nota desde Obsidian se reescriben los links que apuntan a ella. Mover ficheros fuera de Obsidian (explorador, `git mv`) los rompe. |
| Files and links | Excluded files | con el vault en la raíz: `web/node_modules/` y `graphify-out/` (con `docs/` como vault no hace falta ninguna; si generas el vault de graphify, también `codegraph/`) | `web/node_modules/` trae la documentación de Next.js y de cada dependencia: sin excluirla, el 88 % de lo que Obsidian indexa no es del proyecto y entierra la documentación en la búsqueda, el grafo y el selector rápido. Además, al seguir sus enlaces `/docs/app/…` Obsidian crea notas vacías dentro de `docs/`. `graphify-out/` y el vault de graphify son cachés locales que no se versionan. |
| Files and links | Default location for new attachments | una carpeta fija, p. ej. `assets` | Si no, cada imagen pegada cae en la raíz del vault como `Pasted image 2026….png`. Renombrala antes de commitearla. |
| Files and links | Deleted files | System trash (o Obsidian trash) | Las dos valen: `.trash/` está ignorada. |
| Editor | Strict line breaks | **activado** | Los docs están cortados a ~80 columnas. Con el ajuste desactivado (el valor por defecto) Obsidian pinta cada salto de línea y los párrafos se ven rotos; activado se leen como en GitHub. |

## Convenciones al escribir

- **Links en el cuerpo: markdown relativo**, `[ADR-022](../adr/ADR-022-frontera-de-persistencia.md)`.
  Con los ajustes de arriba, Obsidian los escribe así al arrastrar una nota o
  al autocompletar.
- **Wikilinks solo en el frontmatter.** Dentro de una propiedad
  (`related`, `supersedes`, `superseded_by`…) el wikilink es el único formato
  que Obsidian convierte en link, y GitHub muestra el frontmatter como tabla sin
  interpretarlo. Las comillas son obligatorias: `related: ["[[ADR-016-destino-persistencia-supabase]]"]`.
- **El frontmatter tiene que ser YAML válido**, o Obsidian deja la nota sin
  ninguna propiedad. Lo habitual es un valor sin comillas que lleva `: ` o
  empieza por `[` o `(`: entrecomillalo. `tests/test_docs_paths.py` lo comprueba
  en todo `docs/`.
- **Anclas a una sección: al estilo GitHub** (`#3-comandos`, minúsculas y
  guiones). En GitHub saltan a la sección; en Obsidian abren la nota arriba. El
  formato que genera Obsidian (`#Título%20de%20sección`) no resuelve en GitHub.
- **Diagramas en Mermaid** y avisos con `> [!NOTE]`: los dos se ven bien en
  GitHub y en Obsidian.
- **Un ADR o un RFC nuevo empieza por su frontmatter**: las plantillas están en
  [adr/README.md](../adr/README.md) y [rfc/README.md](../rfc/README.md). El
  `status` sale del vocabulario cerrado que valida cada índice.

## Lo que no se edita a mano

Estos documentos (o bloques) los escribe un script: lo que se edite a mano se
pierde en la siguiente regeneración, y casi todos tienen un `--check` que hace
fallar CI si el fichero no coincide con lo que generaría el script:

| Documento | Lo regenera |
|---|---|
| [STATUS.md](../STATUS.md) | `make status` |
| Índice de [adr/README.md](../adr/README.md) | `python scripts/gen_adr_index.py` |
| Índice de [rfc/README.md](../rfc/README.md) | `python scripts/gen_rfc_index.py` |
| [database-schema.md](../database-schema.md) | `make schema-doc` (necesita una BD migrada) |
| [skills-inventory.md](../skills-inventory.md) | `make skills-inventory` |
| Tabla de trazabilidad de [casos-de-uso.md](../casos-de-uso.md) | `make casos-uso` |
| Matriz de scopes de [api-design.md](../api-design.md) | `python scripts/gen_scopes_doc.py` |
| Política de retención de [SECURITY.md](../SECURITY.md) | `python scripts/gen_retention_doc.py` |

## Plugins

Los plugins core (Bases, Templates, Graph) no tocan los ficheros salvo cuando
los usás. Cuidado con los de comunidad que reescriben notas en lote (Linter,
los que rellenan frontmatter solos, los que reordenan propiedades): una pasada
cambia cientos de docs, ensucia el diff y puede romper el vocabulario de
`status` que validan los índices de ADR y RFC.

Con el frontmatter de los ADR y los RFC, una base de **Bases** filtrada por
carpeta (`adr` o `rfc`) con las columnas `status`, `date` y `superseded_by` da
un tablero de decisiones editable. Es una vista local: los índices
generados de `docs/adr/README.md` y `docs/rfc/README.md` siguen siendo la
fuente que se ve en GitHub.

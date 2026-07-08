---
tags: [dashboard]
---

# Dashboard — RFCs & ADRs

> Requiere el plugin comunitario **Dataview** (Settings → Community plugins → Browse → "Dataview" → Install + Enable). Sin eso, los bloques de abajo se ven como código plano.

## RFCs por status

```dataview
TABLE status, date, author
FROM "rfc"
WHERE tags != null
SORT status ASC, date DESC
```

## RFCs abiertos (draft / review / approved)

```dataview
TABLE status, date, author
FROM "rfc"
WHERE status = "draft" OR status = "review" OR status = "approved"
SORT date DESC
```

## ADRs por status

```dataview
TABLE status, date, deciders, supersedes
FROM "adr"
SORT date DESC
```

## ADRs reemplazados (tienen `supersedes` apuntándolos)

```dataview
LIST
FROM "adr"
WHERE supersedes
```

## RFCs sin actividad reciente (> 30 días, no implementados)

```dataview
TABLE status, date
FROM "rfc"
WHERE date AND status != "implemented" AND status != "obsolete" AND status != "rejected"
  AND date(date) < date(today) - dur(30 days)
SORT date ASC
```

// Base común de los PDFs del producto (services/pdf_accesible.py).
//
// Los datos llegan como JSON en `sys.inputs.datos` y se pintan como valores,
// nunca como marcado: un título de licitación con `#`, `*` o `<b>` sale tal
// cual. Por eso ninguna plantilla interpola texto de terceros en código Typst.

#let azul = rgb("#1a5276")
#let gris = rgb("#5b6b7c")
#let gris_etiqueta = rgb("#42526b")
#let linea = rgb("#e2e8f0")
#let ambar = rgb("#b45309")

#let datos() = json(bytes(sys.inputs.datos))

// Documento: metadatos (título, autor, asunto, idioma) y estilo base. El
// título es el `/Title` que el visor enseña (PDF/UA exige DisplayDocTitle).
#let documento(titulo: "", asunto: "", horizontal: false, margen: 18mm, cuerpo) = {
  set document(title: titulo, author: "TenderFlow", description: asunto)
  set text(lang: "es", region: "ES", font: "Libertinus Serif", size: 9.5pt)
  set page(paper: "a4", flipped: horizontal, margin: margen)
  set par(justify: false, leading: 0.55em)
  show heading.where(level: 1): set text(size: 16pt, weight: "bold")
  show heading.where(level: 1): set block(above: 0pt, below: 8pt)
  show heading.where(level: 2): set text(size: 11pt, weight: "bold", fill: azul)
  show heading.where(level: 2): set block(above: 12pt, below: 4pt)
  cuerpo
}

#let pequeno(cuerpo) = text(size: 7.5pt, fill: gris, cuerpo)

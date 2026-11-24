// PDF tabular: una o varias tablas tituladas (services/pdf_tabular.py).
//
// La cabecera se repite en cada página y la lee el lector de pantalla como
// cabecera (`table.header`). Los anchos llegan estimados por el contenido y se
// reparten como fracciones de la página.

#import "comun.typ": *

#let d = datos()
#show: documento.with(titulo: d.titulo, asunto: d.subtitulo, horizontal: true, margen: (x: 20pt, y: 40pt))

#heading(level: 1, d.titulo)
#d.generado

#if d.subtitulo != "" [#d.subtitulo]
#v(8pt)

#for s in d.secciones {
  if s.encabezado != "" { heading(level: 2, s.encabezado) }
  if s.columnas.len() == 0 {
    [Sin resultados.]
  } else {
    table(
      columns: s.anchos.map(a => a * 1fr),
      stroke: 0.25pt + rgb("#aab7c4"),
      inset: (x: 4pt, y: 3pt),
      align: horizon + left,
      fill: (x, y) => if y == 0 { azul } else if calc.odd(y) { white } else { rgb("#eaf0fb") },
      table.header(..s.columnas.map(c => text(size: 8pt, weight: "bold", fill: white, c))),
      ..s.filas.flatten().map(c => text(size: 8pt, c)),
    )
  }
  v(12pt)
}

#if d.pie != "" [#d.pie]

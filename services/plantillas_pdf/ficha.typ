// F2.7 — la ficha de una oportunidad (services/ficha_pdf.py).
//
// Un bloque sin datos imprime su nota en lugar de la tabla, y cada bloque va
// entero en una página: su procedencia no puede quedar huérfana en la
// siguiente, lejos de la cifra que califica.

#import "comun.typ": *

#let d = datos()
#show: documento.with(titulo: d.titulo, asunto: d.subtitulo)

#heading(level: 1, d.titulo)
#d.subtitulo

#pequeno(d.generado)
#v(6pt)

#for b in d.bloques {
  block(breakable: false, below: 9pt)[
    #heading(level: 2, b.titulo)
    #if b.filas.len() == 0 {
      pequeno(b.nota)
    } else {
      let n = b.filas.len()
      table(
        columns: (52mm, 1fr),
        stroke: (x, y) => (bottom: if y < n - 1 { 0.25pt + linea } else { none }),
        inset: (x: 0pt, top: 2pt, bottom: 3pt),
        align: top + left,
        ..b.filas.map(f => (text(size: 8.5pt, fill: gris_etiqueta, f.at(0)), text(size: 8.5pt, f.at(1)))).flatten(),
      )
      if b.procedencia != "" { pequeno(b.procedencia) }
    }
  ]
}

// Guion de la oferta técnica (services/rag/guion_oferta.py, `a_pdf`).
//
// Misma forma que el Markdown: un apartado por criterio, sus puntos con la
// cita al pliego (o la marca de «sin base») y, si las hay, las citas de los
// documentos de la organización.

#import "comun.typ": *

#let d = datos()
#show: documento.with(titulo: d.titulo, asunto: d.asunto)

#heading(level: 1, d.titulo)
#d.intro

#pequeno(d.exportado)
#v(6pt)

#if d.aviso != "" { emph(d.aviso) }

#for c in d.criterios {
  heading(level: 2, c.titulo)
  if c.puntos.len() > 0 {
    list(..c.puntos.map(p => text(size: 9pt)[
      #p.texto#if p.sin_base != "" [ #text(fill: ambar, emph("[" + p.sin_base + "]"))]#if p.refs != "" [ #text(fill: gris, emph("(" + p.refs + ")"))]
    ]))
  }
  if c.propias.len() > 0 {
    text(size: 9pt, strong(d.de_tus_documentos))
    list(..c.propias.map(p => text(size: 9pt)[«#p.cita» #text(fill: gris, emph("(" + p.origen + ")"))]))
  }
  v(4pt)
}

/**
 * Las familias que enumera la landing (`CONTENIDO.familias`), en su propio
 * módulo para que `landing.ts` quepa en las 300 líneas de `src/app/**`: las
 * tres familias de D2 (2026-09-27) lo pasaron de largo.
 *
 * Es la única enumeración de las familias en toda la página. El canon es
 * `config/keywords.py` (`TECH_CATEGORIAS`): trece fabricantes y doce
 * categorías, con su etiqueta legible. Si cambia allí, cambia aquí y el conteo
 * de `familiasTitulo` en `landing.ts`.
 */

export const FAMILIAS_LANDING: string[] = [
  "SAP",
  "Salesforce",
  "Oracle",
  "Microsoft",
  "ServiceNow",
  "Workday",
  "IBM",
  "OpenText",
  "Unit4",
  "Meta4",
  "Sopra",
  "Sage",
  "Infor",
  "ERP",
  "CRM",
  "Infraestructura, cloud y redes",
  "Ciberseguridad",
  "Datos e IA",
  "Desarrollo de software",
  "GIS y geoinformación",
  "Sanidad digital",
  "Administración electrónica",
  "RRHH y nómina",
  "Gestión documental",
  "Puesto de trabajo y soporte",
];

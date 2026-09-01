import type { Metadata } from "next";
import { PaginaEvidencia, type SeccionEvidencia } from "../_components/pagina-evidencia";

export const metadata: Metadata = {
  title: "Seguridad",
  description: "Controles de identidad, sesión, segundo factor, aislamiento y credenciales API implementados en TenderFlow.",
  alternates: { canonical: "/seguridad" },
};

const SECCIONES: SeccionEvidencia[] = [
  {
    titulo: "Identidad y sesión",
    texto: [
      "El acceso por Google se limita a emails o dominios autorizados. El estado OAuth se firma con HMAC-SHA256, caduca y usa nonces contra repetición; el flujo conserva el verificador PKCE en una cookie HttpOnly de corta vida.",
    ],
    puntos: [
      "La sesión del navegador usa cookie HttpOnly, Secure en HTTPS y SameSite=Lax.",
      "Las mutaciones autenticadas por cookie exigen un token CSRF firmado.",
      "Las contraseñas locales, cuando existen, se almacenan con Argon2id y fallback bcrypt.",
    ],
  },
  {
    titulo: "Segundo factor y acciones sensibles",
    texto: [
      "La cuenta puede activar TOTP. El secreto se entrega durante el alta, los códigos de recuperación se muestran una sola vez y el login queda pendiente hasta verificar el segundo factor cuando corresponde.",
    ],
    puntos: [
      "Los intentos fallidos de MFA tienen ventana y límite configurables.",
      "Las operaciones irreversibles exigen autenticación reciente y, si la cuenta usa MFA, elevación reciente del segundo factor.",
      "Cerrar o eliminar una cuenta revoca sesiones y claves API asociadas.",
    ],
  },
  {
    titulo: "Datos de usuario y organización",
    texto: [
      "El perfil de scoring, reglas de vigilancia, favoritos, vistas y oportunidades se asocian al usuario y a su organización. El frontend no accede directamente a la base de datos: consume contratos HTTP tipados de la API.",
    ],
    puntos: [
      "La cuenta permite exportar sus datos y solicitar su eliminación con confirmación explícita.",
      "El borrado anonimiza el histórico que debe conservarse y revoca credenciales activas.",
      "Las acciones administrativas requieren identidad autenticada y comprobación de rol.",
    ],
  },
  {
    titulo: "Claves API",
    texto: [
      "Las claves se almacenan como hash HMAC-SHA256 cuando existe secreto de servidor. Cada petición vuelve a comprobar la clave en tiempo constante, su propietario, expiración y ámbito requerido por la ruta.",
    ],
    puntos: [
      "Las claves nuevas nacen con mínimo privilegio y caducidad configurada.",
      "La rotación entrega el token nuevo una sola vez y admite un periodo de gracia controlado.",
      "El valor bruto de una clave no se escribe en auditoría ni se recupera desde la base de datos.",
    ],
  },
  {
    titulo: "Alcance de esta declaración",
    texto: [
      "Esta página describe controles implementados en el producto. No afirma certificación ISO 27001, ENS ni una auditoría externa que el proyecto no haya documentado. Los detalles legales y el canal de derechos están en el aviso legal.",
    ],
  },
];

export default function SeguridadPage() {
  return (
    <PaginaEvidencia
      kicker="Seguridad"
      titulo="Controles concretos, sin certificaciones implícitas"
      introduccion="La confianza también exige delimitar lo que se protege y cómo. Estos son los controles verificables que sostienen el acceso y los datos guardados en TenderFlow."
      secciones={SECCIONES}
    />
  );
}

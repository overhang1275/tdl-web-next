# Diseño de producto — TDL Console

Fecha: 2026-10-26
Estado: guía de diseño para la migración Next.js; se valida en `/design-auditor`.
Producto: consola de operaciones para descargar media de Telegram con `tdl`.
Usuario: un administrador técnico que gestiona trabajos, archivos y sesión.

## 1. Principio

No es una landing page ni un panel genérico. Es una consola de operaciones: el estado real se
entiende en segundos, las acciones destructivas son explícitas y el contenido denso sigue siendo
legible. La estética debe sentirse como un SaaS de infraestructura, no como un proyecto personal.

## 2. Personalidad

- **Claridad operativa:** primero estado, progreso y siguiente acción.
- **Confianza sobria:** bordes finos, superficies limpias, color con propósito.
- **Densidad con aire:** tablas y tarjetas compactas, pero con espacio entre secciones.
- **Sin adornos:** nada de gradientes morados, glassmorphism, ilustraciones genéricas ni charts
  decorativos. Los datos reales son el protagonista.
- **Profesional, no corporativo:** lenguaje directo en español, sin signos de exclamación.

## 3. Marca

- Nombre visible: **TDL Console**.
- Marca: monograma cuadrado redondeado con una “T” y un punto de estado; sin logotipo complejo.
- Etiqueta secundaria: “Telegram media operations”.
- Tono: “Tu cola de descargas, sin sorpresas”.

## 4. Color

Tokens semánticos; no se usan colores sueltos en componentes.

### Claro

| Token | Valor | Uso |
|---|---|---|
| `--background` | `#F7F8F6` | Fondo general |
| `--surface` | `#FFFFFF` | Tarjetas, tablas |
| `--surface-muted` | `#F1F3F1` | Filas alternas, inputs |
| `--foreground` | `#0F172A` | Texto principal |
| `--muted-foreground` | `#5D6C80` | Texto secundario; contraste mínimo 4.80:1 en superficies claras |
| `--border` | `#E2E8F0` | Bordes |
| `--primary` | `#0F766E` | Acción primaria, foco |
| `--primary-hover` | `#115E59` | Hover |
| `--primary-foreground` | `#FFFFFF` | Texto sobre primario |
| `--success` | `#15803D` | Completado |
| `--warning` | `#B45309` | Pendiente/atención |
| `--danger` | `#B91C1C` | Error, borrar |
| `--info` | `#1D4ED8` | Enlaces, información |

### Oscuro

| Token | Valor | Uso |
|---|---|---|
| `--background` | `#0B1220` | Fondo general |
| `--surface` | `#111A2B` | Tarjetas |
| `--surface-muted` | `#162033` | Inputs, filas |
| `--foreground` | `#E2E8F0` | Texto |
| `--muted-foreground` | `#94A3B8` | Secundario |
| `--border` | `#24324A` | Bordes |
| `--primary` | `#2DD4BF` | Acción primaria |
| `--primary-foreground` | `#042F2E` | Texto sobre primario |
| `--success` | `#4ADE80` | Completado |
| `--warning` | `#FBBF24` | Atención |
| `--danger` | `#F87171` | Error |

Contraste mínimo AA (4.5:1) en texto normal y 3:1 en texto grande/controles.

## 5. Tipografía

- Familia: `ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif`.
- No se descargan fuentes externas en build; se usa la pila del sistema.
- Títulos: 600, tracking `-0.02em`; H1 28-32 px; H2 20 px; H3 16 px.
- Cuerpo: 14 px / 1.5; texto secundario 13 px.
- Métricas: 28-32 px, 600, `font-variant-numeric: tabular-nums`.
- IDs, logs y rutas: `ui-monospace, SFMono-Regular, Menlo, monospace`, 12-13 px.
- No usar mayúsculas sostenidas en párrafos; solo en eyebrows de 11-12 px.

## 6. Espaciado y forma

- Base 4 px; secciones 24-32 px; tarjetas 20-24 px; campos 10-12 px.
- Radios: 10 px tarjetas, 8 px inputs/botones, 999 px badges.
- Bordes: 1 px; sombra solo en diálogos/popovers (`0 12px 32px rgba(15,23,42,.12)`).
- Ancho de contenido: 1280 px; sidebar 248 px; topbar 64 px.
- Tablas: fila 52 px; cabecera 40 px; acciones alineadas a la derecha.
- Botones: 40 px de alto; iconos 16-18 px; gap 8 px.
- Foco: anillo 2 px `--primary`, offset 2 px; nunca `outline: none` sin reemplazo.

## 7. Layout

- Escritorio: sidebar fija, topbar con búsqueda global, chip de estado, tema y menú de usuario.
- Móvil: barra superior compacta, bottom nav de 5 destinos, CTA “Nueva descarga” visible.
- El contenido respira; no se usan tablas con scroll horizontal como patrón principal.
- En móvil, tablas se convierten en tarjetas con la información clave y acciones.
- Login: panel partido; marca/estado a la izquierda y un único botón “Continuar con Authentik”
  a la derecha. En móvil solo el botón, con la marca arriba. No hay formulario de contraseña.

## 8. Componentes

- **Status badge:** punto + etiqueta; colores semánticos; no solo color (texto siempre).
- **Metric card:** etiqueta, valor tabular, delta/contexto real; sin sparkline inventado.
- **Job progress:** barra determinada solo con datos; si no, barra indeterminada y stage.
- **Tabla:** cabecera sticky, filas con hover sutil, acciones en menú si son muchas.
- **Empty state:** título, una frase y acción; sin ilustraciones grandes.
- **Error state:** qué pasó, qué hacer, detalle técnico plegable.
- **Toast:** texto, no HTML; 4-8 s; acción “Abrir”.
- **Dialog:** confirmación para borrar/reset; el botón destructivo no es el primario.
- **Log viewer:** mono, fondo oscuro suave, autoscroll opcional, copiar y descargar.
- **File card:** miniatura segura, nombre truncado, tamaño, tipo, acciones.
- **Chat picker:** búsqueda, tipo, ID; selección clara; no un `<select>` gigante.

## 9. Movimiento

- 150 ms `ease-out` para hover/foco; 200 ms para paneles.
- Sin animaciones infinitas salvo spinner de carga.
- Respetar `prefers-reduced-motion`.
- El progreso no “late” ni simula velocidad.

## 10. Contenido

- Español directo: “Nueva descarga”, “Reintentar fallidos”, “Eliminar job”.
- Errores accionables: qué pasó + qué hacer; detalle técnico separado.
- No prometer pausa, reanudación o ETA si el backend no los da.
- Fechas en formato local `es-MX`, con hora; IDs en mono.
- Números grandes con separador de miles.

## 11. Accesibilidad

- Contraste AA; foco visible; navegación completa por teclado.
- `label` explícito en todos los campos; `aria-describedby` para ayudas/errores.
- `aria-live="polite"` para progreso y toasts; `role="status"` para estado.
- Diálogos con foco atrapado y cierre con Escape.
- Iconos decorativos `aria-hidden`; iconos con acción, `aria-label`.
- No depender solo del color para estado.

## 12. Qué evitar

- Gradientes morados, glassmorphism, sombras difusas en todo.
- Dashboard con gráficos aleatorios o métricas sin fuente.
- Tablas apretadas en móvil con scroll horizontal.
- Botones de 32 px en móvil; acciones destructivas sin confirmación.
- Texto en inglés en la UI.
- Modo oscuro invertido a mano: usar tokens.

## 13. Criterios de aceptación visual

- 390x844, 1280x800 y 1440x900 sin scroll horizontal.
- Login, Resumen, Descargas, Nueva descarga, Detalle, Chats, Registros y Configuración legibles.
- Estados vacío, carga, error, reconexión y sesión expirada visibles.
- Teclado: se puede completar login, crear job, cancelar y cerrar diálogos.
- Capturas antes/después en `docs/design-audit/screenshots/`.

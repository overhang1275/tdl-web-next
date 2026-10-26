# Migración de tdl-web a Next.js + FastAPI

Fecha: 2026-10-26
Estado: diseño propuesto, pendiente de aprobación
Commit base: `34f74c6e84a55606214902ba04be1df2378d4123`
Repositorio de trabajo: `C:\Users\init\Desktop\tdl-web-next` (origin privado nuevo; upstream original)
Informe de la app actual: `docs/audit/2026-10-26-current-app.md`
Grafo inicial: `docs/architecture/graphify/initial/`

## 1. Intención

Crear una nueva versión de tdl-web con frontend Next.js y backend FastAPI, conservando la
integración real con `tdl` y todas las funciones que hoy usa el administrador. La app actual
funciona, pero mezcla UI y API en un monolito Jinja/HTMX, tiene fallos de seguridad concretos y
no ofrece una API tipada. La migración debe reducir riesgo, no reescribir la lógica de descargas.

## 2. Objetivos

- Conservar el comportamiento real: login de Telegram, chats, filtros, exportación, descargas
  por lotes, progreso, cancelación, reintento/reanudación, borrado, galería, búsqueda,
  plantillas y logs.
- Separar responsabilidades: FastAPI ejecuta `tdl`, gestiona procesos y persiste; Next.js solo
  presenta y consume la API.
- API `/api/v1` tipada, con OpenAPI, errores consistentes y health/readiness.
- Interfaz renovada, responsive, en español, con tema claro/oscuro y accesibilidad.
- Despliegue en LXC Debian/Ubuntu sin Docker obligatorio.
- Corregir los riesgos de seguridad del informe y añadir pruebas que los cubran.

## 3. No objetivos

- Multiusuario, roles, cuotas o aislamiento entre administradores.
- Pausar/reanudar de verdad: `tdl` no ofrece pausa; solo cancelar y reintentar.
- WebSocket/SSE: el polling cubre el caso y es más simple.
- Editar `.env` o configuración sensible desde la UI.
- Límites de velocidad o programación: no verificados en la versión de `tdl`.
- Sustituir Redis/RQ por una cola propia.
- Docker como camino principal de despliegue.

## 4. Anti-objetivos

- Duplicar la lógica de `tdl`, filtros o trabajos en Next.js (API Routes/Server Actions).
- Mostrar porcentajes, ETA o velocidad inventados.
- Exponer secretos, rutas absolutas o sesiones de Telegram al navegador.
- Eliminar funciones existentes sin documentarlo.
- Cambiar el formato de la base de datos o los archivos de datos sin migración y respaldo.

## 5. Restricciones

- LXC Debian/Ubuntu, sin Docker obligatorio.
- Python 3.12+; Node 22 LTS; Redis local; Nginx; `tdl` instalado por el script oficial.
- SQLite existente y directorios de datos actuales.
- Un solo administrador y un solo worker de RQ.
- La UI y la API deben compartir origen en producción.
- No se publican cambios ni se hace merge/pull request sin autorización.

## 6. Enfoques considerados

### A. FastAPI + Redis/RQ existente, Next.js como frontend (elegido)

Se conservan `app/services/*`, `app/worker.py`, `app/models.py`, SQLite y la cola RQ. Se sustituye
la capa Jinja/HTMX por una API FastAPI y un frontend Next.js. El worker sigue ejecutando
`app.worker.run_download_job` y mantiene la reanudación por archivo y por rangos de exportación.

- Ventaja: reutiliza la lógica más delicada y ya probada; menor riesgo de perder progreso.
- Coste: Redis sigue siendo dependencia; hay que portar rutas y pruebas.
- Riesgo: el desacoplamiento de la UI puede romper contratos si no se prueba.

### B. FastAPI con cola propia en SQLite, sin Redis

Se elimina Redis/RQ y se implementa una cola en SQLite con reclamación atómica, cancelación,
reintentos, continuación y recuperación de huérfanos.

- Ventaja: menos servicios.
- Coste: reescribir la parte más delicada; más riesgo de duplicar trabajos o perder progreso.
- Riesgo: alto. No se elige.

### C. Conservar Jinja/HTMX y envolver con Next.js

Se mantiene la UI actual y se añade Next.js como capa externa.

- Ventaja: menos cambios inmediatos.
- Coste: no cumple la migración de frontend; duplica responsabilidades.
- Riesgo: deuda y confusión. No se elige.

## 7. Arquitectura elegida

```text
/
├── frontend/                 Next.js App Router + TypeScript + Tailwind + shadcn/ui
├── backend/
│   ├── app/
│   │   ├── main.py           crea FastAPI, middlewares, routers
│   │   ├── config.py         settings existentes
│   │   ├── database.py       engine, sesión, migraciones
│   │   ├── models.py         DownloadJob, DownloadFile, DownloadTemplate
│   │   ├── schemas.py        entrada/salida Pydantic
│   │   ├── security.py       Basic auth, CSRF, cabeceras, límites
│   │   ├── api/v1/           health, status, auth, chats, jobs, files, templates,
│   │   │                     search, dashboard, settings, admin
│   │   ├── services/         tdl, filtering, transfers, jobs, files, logs,
│   │   │                     chat_cache, search, errors, paths, login, status
│   │   ├── worker.py         ejecución RQ (misma ruta de importación)
│   │   └── rq_worker.py      arranque del worker
│   ├── tests/
│   └── requirements.txt
├── deploy/
│   ├── nginx/tdl-web.conf
│   ├── systemd/tdl-web-{api,worker,frontend}.service
│   ├── install.sh
│   └── update.sh
├── docs/
│   ├── architecture/
│   ├── audit/
│   ├── design-audit/
│   └── superpowers/
├── scripts/playwright.ps1
├── .env.example
├── README.md
└── .gitignore
```

El paquete Python sigue llamándose `app` y el directorio de trabajo del backend es `backend/`.
Así, la ruta `app.worker.run_download_job` no cambia y los jobs RQ en vuelo siguen siendo
importables durante la transición.

## 8. Responsabilidades

### FastAPI

- Ejecutar `tdl` con argumentos separados, sin `shell=True`.
- Gestionar la sesión de Telegram y el login interactivo por pty (solo Linux).
- Crear, reclamar, cancelar, reintentar y eliminar trabajos.
- Leer/escribir SQLite, exports, filtered, metadata, logs y descargas.
- Validar filtros, rutas, tamaños, estados y confirmaciones.
- Servir archivos con cabeceras seguras.
- Aplicar autenticación, CSRF, límites y errores consistentes.

### Next.js

- Presentar las pantallas y consumir `/api/v1`.
- Validar formularios en cliente para UX; la validación autoritativa es FastAPI.
- Gestionar tema, navegación, estados de carga/vacío/error/reconexión y accesibilidad.
- No ejecutar comandos, no leer archivos del servidor, no guardar secretos.

## 9. Modelo de trabajos

Se conserva el modelo actual:

1. `POST /api/v1/jobs` valida el payload, calcula una huella e inserta el job.
2. El job se encola en RQ (`telegram-downloads`) con `app.worker.run_download_job`.
3. El worker exporta por rangos de IDs, publica `export.json` atómicamente, filtra y registra
   cada archivo en `download_files`.
4. Descarga por lotes de `DOWNLOAD_BATCH_SIZE`; tras un fallo, reintenta por mensaje hasta 3 veces.
5. Cada lote se encola como un job RQ nuevo; un token impide que un worker viejo finalice otro intento.
6. Al terminar, el job queda `completed`, `failed` o `cancelled`.

Se conservan:
- `cancel_job`: marca `cancel_requested`; el worker comprueba cada segundo y termina el proceso.
- `retry_job`: continúa el mismo job desde los archivos pendientes; conserva los completados.
- `sync_pending_jobs_with_queue`: convierte jobs huérfanos en fallidos reanudables.
- `wipe_delete_job`: elimina la carpeta con `wipe` y solo entonces borra el registro.

Cambios:
- La creación usa una huella única (`dedupe_key`) y un índice único parcial para jobs activos.
  Dos peticiones simultáneas no crean dos jobs; la segunda recibe `409` con el job existente.
- La eliminación deja de usar `BackgroundTasks`. Se persiste `deletion_requested` y se encola
  `app.worker.delete_job`; si la web se reinicia, el worker o el reconciliador la retoman.
- `retry_job` acepta `mode=pending|failed`: `pending` conserva el comportamiento actual;
  `failed` reencola solo los archivos fallidos y deja los completados intactos.
- El progreso expone `total_expected_bytes` y `eta_seconds=null` cuando no hay datos fiables.

### Workers soportados

- **API:** un solo proceso Uvicorn (`--workers 1`). El login pty y el lock del caché de chats
  son estado en memoria; varios procesos los romperían.
- **RQ:** un solo worker con concurrencia 1. Evita dos procesos `tdl` compitiendo por la misma
  cuenta y disco. La cola puede crecer, pero no se ejecutan jobs en paralelo.
- Si en el futuro se necesita concurrencia, habrá que mover login/caché a estado compartido y
  añadir bloqueo por chat. No forma parte de esta migración.

## 10. Persistencia

Se conserva SQLite y el esquema actual:

- `download_jobs`: configuración, estado, stage, contadores, rutas de export/filtered/download,
  cursor de exportación, token RQ, error, timestamps, `deletion_requested`, `dedupe_key`.
- `download_files`: un registro por mensaje/archivo, estado, intentos, tamaño, error y ruta local.
- `download_templates`: plantillas de filtros.
- `chats.json`: caché de chats (título, id, username, tipo, topics).
- Archivos: `exports/<chat>/export.json`, `filtered-job-<id>.json`, `export-job-<id>.json`,
  fragmentos `export-job-<id>/<desde>-<hasta>.json`, `batch-job-<id>.json`, metadata.
- Descargas: `downloads/<chat>/<subcarpeta>/job-<id>/<message_id>/<archivo>`.
- Logs: `logs/job-<id>.log`, `logs/deleted-jobs.log`.

No hay conversión de datos. Las migraciones son aditivas (`ALTER TABLE`, índices) y se ejecutan
al arrancar. Antes de actualizar se hace copia de SQLite con WAL checkpoint.

## 11. API `/api/v1`

Todas las respuestas de error usan:

```json
{"error": {"code": "job_not_found", "message": "El job no existe.", "detail": null}}
```

Paginación:

```json
{"items": [], "page": 1, "per_page": 20, "total": 0, "page_count": 1}
```

Rutas:

| Método | Ruta | Función |
|---|---|---|
| GET | `/api/v1/health` | Liveness mínima, sin auth |
| GET | `/api/v1/status` | tdl, sesión, Redis, worker, almacenamiento, versión |
| POST | `/api/v1/auth/login/start` | Inicia login pty |
| POST | `/api/v1/auth/login/input` | Envía teléfono/código/2FA |
| POST | `/api/v1/auth/login/cancel` | Cancela login |
| GET | `/api/v1/auth/login` | Estado y salida redactada |
| GET | `/api/v1/chats` | Lista/cache, búsqueda, tipo, orden, paginación |
| GET | `/api/v1/chats/{chat_id}` | Perfil, export, jobs, archivos |
| DELETE | `/api/v1/chats/{chat_id}/downloads` | Limpia descargas con confirmación |
| GET | `/api/v1/templates` | Lista plantillas |
| POST | `/api/v1/templates` | Crea plantilla |
| PUT | `/api/v1/templates/{id}` | Edita plantilla |
| DELETE | `/api/v1/templates/{id}` | Borra plantilla con confirmación |
| GET | `/api/v1/jobs` | Historial con filtros y paginación |
| POST | `/api/v1/jobs` | Crea job; acepta `Idempotency-Key` |
| GET | `/api/v1/jobs/{id}` | Detalle y progreso |
| POST | `/api/v1/jobs/{id}/cancel` | Cancela |
| POST | `/api/v1/jobs/{id}/retry` | Reintenta `pending` o `failed` |
| DELETE | `/api/v1/jobs/{id}` | Solicita borrado con `wipe` |
| GET | `/api/v1/jobs/{id}/events` | Eventos recientes |
| GET | `/api/v1/jobs/{id}/logs` | Tail de log |
| GET | `/api/v1/jobs/{id}/files` | Archivos con paginación |
| GET | `/api/v1/jobs/{id}/files/{file_id}/content` | Descarga/preview segura |
| GET | `/api/v1/search` | Chats, jobs y archivos |
| GET | `/api/v1/dashboard` | Métricas y errores recientes |
| GET | `/api/v1/settings` | Configuración de solo lectura |
| POST | `/api/v1/admin/reset` | Reinicio total con `REINICIAR` |
| POST | `/api/v1/services/start` | Solo desarrollo; 404 en producción |

Esquemas principales: `JobCreate`, `JobRead`, `JobFileRead`, `TemplateCreate`, `TemplateRead`,
`ChatRead`, `StatusRead`, `DashboardRead`, `SearchRead`, `Page[T]`, `ApiError`.

## 12. Autenticación y seguridad

- **Basic auth obligatoria en producción.** `WEB_PASSWORD` es requerida si `APP_ENV=production`;
  el proceso no arranca sin ella. Nginx protege páginas y `/api/` con `auth_basic`; FastAPI vuelve
  a comprobar Basic como defensa en profundidad. No hay cookies de sesión.
- **TLS obligatorio** en Nginx. `ALLOW_INSECURE_HTTP=true` solo para un laboratorio explícito.
- **CSRF:** las escrituras exigen `X-Requested-With: tdl-web` y `Origin`/`Referer` del mismo
  origen. Una petición cruzada con cabecera personalizada no pasa el preflight CORS.
- **CORS:** sin CORS en producción (mismo origen). En desarrollo, lista explícita
  `CORS_ORIGINS=http://localhost:3000`.
- **Rate limit:** `limit_req` de Nginx para `/api/` y `/api/v1/auth/login/input`; bloqueo temporal
  tras fallos repetidos.
- **XSS:** Next.js escapa por defecto; prohibido `dangerouslySetInnerHTML` con datos de Telegram.
  Los toasts usan texto, no HTML.
- **Archivos:** `Content-Disposition: attachment` para HTML/SVG/XML; `CSP: sandbox` en respuestas
  de archivos; `X-Content-Type-Options: nosniff`; solo imágenes/video/audio/PDF inline.
- **Secretos:** nunca en `NEXT_PUBLIC_*`; el frontend solo conoce la URL relativa de la API.
- **Permisos:** `UMask=0077` en systemd y `os.umask(0o077)` al arrancar; DB, caché, logs y sesión
  en 600; directorios en 700.
- **Login:** no se registra la entrada del usuario; la salida de `tdl` se muestra con los valores
  sensibles redactados.
- **Confirmaciones:** borrado de job, limpieza de chat, borrado de plantilla y reset exigen un
  campo/token de confirmación validado en FastAPI; no basta `confirm()` del navegador.
- **Servicios:** `services/start` solo existe en desarrollo. En producción, systemd gestiona
  Redis y worker.
- **Redis:** bind a 127.0.0.1, sin exposición; opcional `requirepass` documentado.
- **Cabeceras:** CSP con `script-src 'self'` y nonce de Next.js, `frame-ancestors 'none'`,
  `Referrer-Policy: same-origin`, `Permissions-Policy` mínima, HSTS cuando hay TLS.

## 13. Progreso y reconexión

- Polling con TanStack Query: 2 s mientras el job está `pending/running`; 30 s si está terminal;
  se detiene al cerrar la pestaña.
- Antes de `transfer_initialized`, la UI muestra stage y barra indeterminada; no inventa porcentaje.
- Después, porcentaje = `total_downloaded_files / total_filtered_messages`, acotado a 100.
- Velocidad: solo se muestra si `download_speed_bps > 0` y el job está descargando; etiqueta
  “aproximado”.
- ETA: solo si `total_expected_bytes` es conocido, la velocidad es estable y quedan bytes; si no,
  `null` y “—”.
- Al recargar, la UI vuelve a pedir `/api/v1/jobs/{id}` y `/api/v1/status`; no inicia jobs.
- Si la API se cae, TanStack Query reintenta con backoff y muestra “Reconectando…”. El job sigue
  en el worker. Si el worker se cae, el reconciliador marca el job como fallido reanudable.
- Cerrar el navegador no cancela nada.

## 14. Interfaz

Pantallas:

1. **Resumen** (`/`): estado de sesión/servicios, métricas, jobs activos, últimos errores,
   botón “Nueva descarga”.
2. **Descargas** (`/downloads`): historial con filtros (estado, chat, texto), tabla en escritorio
   y tarjetas en móvil, paginación, acciones.
3. **Nueva descarga** (`/downloads/new`): selector de chat con búsqueda, filtros, plantillas,
   aviso de export existente, validación y confirmación.
4. **Detalle** (`/downloads/[id]`): progreso honesto, acciones (cancelar, reintentar, eliminar),
   eventos, logs con autocarga, archivos.
5. **Chats** (`/chats`, `/chats/[id]`): lista, perfil, export, jobs, limpiar descargas.
6. **Registros** (`/logs`): actividad reciente y acceso a logs por job.
7. **Configuración** (`/settings`): estado, rutas y límites de solo lectura, login Telegram,
   servicios (solo lectura en producción), zona de peligro con confirmación.

Navegación: sidebar en escritorio, bottom nav en móvil; “Nueva descarga” como acción primaria.
Tema claro/oscuro con `next-themes`; tipografía Inter; tokens en `DESIGN.md`.
Estados: carga (skeleton), vacío, error, reconexión, sin permiso, job eliminando.
Accesibilidad: foco visible, navegación por teclado, labels, `aria-live` para progreso/toasts,
contraste AA, `prefers-reduced-motion`.

## 15. Despliegue

- **SO:** Debian 13 o Ubuntu 24.04 (Debian 12 requiere Python 3.12 de backports).
- **Paquetes:** python3.12, venv, redis-server, nginx, nodejs 22 (NodeSource), build-essential,
  curl, ca-certificates, wipe.
- **tdl:** instalador oficial; `TDL_BINARY` configurable; validar versión y `tdl --version`.
- **Servicios systemd:**
  - `tdl-web-api.service`: `uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1`.
  - `tdl-web-worker.service`: `python -m app.rq_worker`.
  - `tdl-web-frontend.service`: `node .next/standalone/server.js` en 127.0.0.1:3000.
  - `UMask=0077`, `NoNewPrivileges=true`, `ProtectSystem=strict`, `ReadWritePaths` solo datos.
- **Nginx:** TLS, Basic auth, `/api/` → 8000, `/` → 3000, timeouts de descarga, límites de
  petición, logs sin credenciales.
- **Datos:** `/opt/tdl-web/data/{sessions,exports,downloads,logs}`, DB y backups; 700/600.
- **Actualización:** backup SQLite, build frontend, migración, restart, health check; rollback
  conservando DB y datos.
- **Docker:** opcional y fuera del camino principal; si se conserva, usuario no root y
  `WEB_PASSWORD` obligatoria.

## 16. Migración de datos y corte

1. Etiquetar el estado actual y respaldar SQLite (incluido WAL) y `chats.json`.
2. Detener web y worker antiguos; vaciar o drenar la cola RQ.
3. Desplegar backend nuevo con el mismo esquema; ejecutar migraciones aditivas.
4. Arrancar worker nuevo; verificar que `app.worker.run_download_job` se importa.
5. Arrancar API y frontend; verificar health, login, chats y un job de prueba sin Telegram real
   (fake `tdl`).
6. Si hay jobs en vuelo, dejarlos terminar antes del corte o marcarlos fallidos y reintentar.
7. Rollback: restaurar DB, arrancar servicios antiguos; los archivos descargados no se tocan.

No se convierten ni borran datos reales sin autorización.

## 17. Pruebas

- **Backend:** pytest con SQLite temporal, RQ falso y `TdlService` falso. Cubrir filtros, rutas,
  construcción de comandos, errores de tdl, ciclo de vida, duplicados, reanudación, export por
  rangos, cancelación, borrado, auth, CSRF, content-disposition, idempotencia y progreso honesto.
- **Frontend:** Vitest + Testing Library para formularios, estados y accesibilidad; Playwright para
  los flujos esenciales con API mockeada y, cuando sea posible, con backend real + `tdl` falso.
- **Verificación:** `ruff`, `pytest`, `eslint`, `tsc --noEmit`, `next build`, Playwright.
- Las pruebas no usan Telegram real ni descargan archivos reales. Los mocks se identifican.

## 18. Riesgos

| Riesgo | Mitigación |
|---|---|
| Pérdida de progreso al cambiar de worker | Misma ruta `app.worker.run_download_job`; drenar cola; pruebas de reanudación |
| Duplicar jobs por doble clic | `dedupe_key` + índice único parcial + `Idempotency-Key` |
| Borrado `wipe` perdido | Estado persistido + job RQ + reconciliación al arrancar |
| Login pty solo Linux | Guardar import de pty; probar en LXC; fallback de comando CLI |
| Redis expuesto | Bind localhost; opcional password; Nginx no lo publica |
| XSS por títulos/archivos | Next.js escapa; sin innerHTML; archivos peligrosos como attachment |
| Lentitud por `tdl chat ls` | Caché de estado con TTL; health separado |
| Búsqueda lenta | Consultar `DownloadFile`; límite y paginación |
| SQLite con dos procesos | Worker y API usan WAL; escrituras cortas; no hay dos workers |
| Basic auth sin TLS | Nginx TLS obligatorio; `ALLOW_INSECURE_HTTP` explícito |
| Pruebas en Windows | Backend se prueba en Linux/Docker; pty con import diferido |

## 19. Decisiones del diseño

- Se conserva Redis/RQ (A).
- Basic auth con Nginx + FastAPI, sin cookies de sesión.
- Polling, no SSE/WebSocket.
- Un worker de API y uno de RQ.
- SQLite existente, migraciones aditivas.
- Se elimina Jinja/HTMX del runtime; la UI antigua queda en el historial de Git.
- Se conserva `app.worker.run_download_job` como ruta de importación.
- Se añaden `dedupe_key`, `deletion_requested`, `total_expected_bytes` y `eta_seconds` calculado.
- La UI nueva no muestra rutas absolutas ni secretos.

## 20. Criterios de aceptación

- `GET /api/v1/health` responde 200; `GET /api/v1/status` informa tdl, Redis y worker.
- Sin `WEB_PASSWORD` en producción, la API no arranca.
- Un POST sin `X-Requested-With` o con origen cruzado recibe 403.
- Un intento de crear dos jobs idénticos activos devuelve uno solo y 409 en el segundo.
- Un job de prueba con `tdl` falso recorre export → filtro → descarga → completed.
- Cancelar detiene el proceso; reintentar conserva archivos completados.
- Eliminar un job usa `wipe`; si falla, el registro y la carpeta se conservan y se puede reintentar.
- La UI funciona a 390x844, 1280x800 y 1440x900; sin scroll horizontal; foco visible; tema claro/oscuro.
- `pytest`, `ruff`, `eslint`, `tsc --noEmit`, `next build` y Playwright pasan o queda documentado el bloqueo.
- `/design-auditor` produce `docs/design-audit/latest.md` y capturas antes/después.
- El proyecto original no cambia de rama, remotos, commits ni archivos.

## 21. Decisiones de implementación

### 21.1 Autenticación en dos capas

- Nginx protege `/` y `/api/` con `auth_basic` y
  `auth_basic_user_file /etc/nginx/tdl-web.htpasswd`.
- `location = /api/v1/health` y `location = /health` tienen `auth_basic off`.
- El instalador crea el usuario `admin` en el htpasswd con
  `openssl passwd -apr1 "$WEB_PASSWORD"`; no guarda la contraseña en el htpasswd.
- FastAPI vuelve a comprobar Basic en todas las rutas salvo health. Si Nginx ya autenticó,
  la cabecera `Authorization` llega al backend; el navegador la reenvía en las llamadas same-origin.
- No hay cookies de sesión. Las escrituras exigen `X-Requested-With: tdl-web` y origen propio.
- En desarrollo se puede omitir `WEB_PASSWORD`; la API solo escucha en `127.0.0.1`.
- Un 401 en el frontend muestra “No autorizado” y pide recargar; no se guardan credenciales en JS.

### 21.2 Datos en el frontend

- Las páginas usan componentes cliente para datos; el layout puede ser servidor.
- `apiFetch` usa rutas relativas `/api/v1`, `credentials: "same-origin"` y la cabecera
  `X-Requested-With`. No existe `NEXT_PUBLIC_API_URL`.
- En desarrollo, `next.config.ts` reescribe `/api/:path*` a `http://127.0.0.1:8000/api/:path*`.
  En producción Nginx enruta `/api/` directamente. No hay CORS.
- TanStack Query reintenta una vez, refresca al volver a la pestaña y detiene el polling cuando
  el job es terminal.
- Un 401/403 se muestra como estado de error, no como pantalla en blanco.

### 21.3 Corte y compatibilidad RQ

- `git mv app backend/app`, `git mv tests backend/tests`, `git mv requirements.txt backend/`.
- El directorio de trabajo de API y worker es `backend/`; el paquete sigue siendo `app`.
- Se conserva la cola `telegram-downloads` y la función `app.worker.run_download_job`.
- Antes del corte se drena la cola o se deja terminar el job en curso. Si no, se marca fallido y
  se reintenta con la nueva versión.
- `chats.json`, SQLite y los directorios de datos no cambian de sitio.
- El servicio web antiguo se detiene; se arrancan API, worker y frontend nuevos.

### 21.4 Archivos y tipos peligrosos

- Ruta principal: `GET /api/v1/jobs/{id}/files/{file_id}/content?download=true`.
- Compatibilidad: `GET /api/v1/jobs/{id}/files/content?path=...` para archivos antiguos sin fila
  en `download_files`; el path se valida con `safe_child`.
- `Content-Disposition: attachment` para `text/html`, `application/xhtml+xml`,
  `image/svg+xml`, `application/xml`, `text/xml` y desconocidos.
- `inline` solo para `image/*`, `video/*`, `audio/*` y `application/pdf`.
- Todas las respuestas de archivos llevan `X-Content-Type-Options: nosniff` y
  `Content-Security-Policy: sandbox`.
- La UI no usa iframes para HTML; el texto se muestra como texto.

### 21.5 Borrado con `wipe`

- `DELETE /api/v1/jobs/{id}` exige `{"confirm": true}`.
- Si el job está `pending/running`: se marca `cancel_requested`, se pone `deletion_requested=1`
  y se encola `app.worker.delete_job` con delay de 5 s.
- `delete_job` comprueba el estado; si sigue activo, vuelve a encolarse con delay. Cuando es
  terminal, ejecuta `wipe_delete_job`.
- Si `wipe` falla o no está instalado, guarda `deletion_error` y conserva el registro y la carpeta.
- Al arrancar el worker, `reconcile_deletions()` reencola los `deletion_requested` que no tengan
  un job de borrado activo.
- La UI muestra “Eliminando” mientras `deletion_requested=1` y el error si existe.

### 21.6 Idempotencia y duplicados

- `dedupe_key` es SHA-256 de la tupla canónica de filtros, chat, carpeta, export y modo.
- Índice único parcial `WHERE status IN ('pending','running')`.
- Migración: añadir columna, calcular claves de jobs activos, crear el índice. Si hay duplicados
  históricos, se conserva la clave del más antiguo y se dejan los demás en `NULL`.
- `POST /jobs` devuelve `409 duplicate_job` con `detail.job_id`.
- `Idempotency-Key` se incorpora a la huella si está presente; dos peticiones con la misma clave
  y payload devuelven el mismo job.

### 21.7 Progreso y ETA

- `JobRead` expone `progress_percent` (nullable), `total_expected_bytes` (nullable),
  `downloaded_bytes`, `speed_bps` y `eta_seconds` (nullable).
- Antes de `transfer_initialized`, `progress_percent` es `null`; la UI usa barra indeterminada.
- `total_expected_bytes` es la suma de `expected_size`; si algún archivo no tiene tamaño, es `null`.
- `speed_bps` usa una media exponencial; si es 0 o el job no está descargando, la UI muestra “—”.
- `eta_seconds` solo se calcula si `total_expected_bytes` no es `null` y `speed_bps > 0`.
- No se muestran porcentajes ni ETA inventados.

### 21.8 Reintento de fallidos

- `retry_job(db, job, mode="pending")` conserva el comportamiento actual.
- `mode="failed"` pone solo los archivos `failed` en `pending`, con `attempts=0` y sin tocar los
  `completed`; recalcula contadores y reencola.
- Si no hay archivos fallidos, responde `409 no_failed_files`.
- La UI ofrece “Reintentar pendientes” y “Reintentar fallidos” solo cuando el estado lo permite.

### 21.9 Build y servicios del frontend

- `next.config.ts`: `output: "standalone"`, `reactStrictMode: true`, `poweredByHeader: false`.
- Build: `npm ci && npm run build`; luego copiar `public/` y `.next/static/` dentro de
  `.next/standalone/`.
- systemd ejecuta `node server.js` en `.next/standalone` con `HOSTNAME=127.0.0.1`, `PORT=3000`,
  `NEXT_TELEMETRY_DISABLED=1`.
- Nginx enruta `/` a `127.0.0.1:3000` y `/api/` a `127.0.0.1:8000`.

### 21.10 Pruebas en Windows y Linux

- Windows: `pytest --basetemp=.pytest-tmp`; `pty` con import diferido; `tdl` falso como `.cmd`;
  Redis de pruebas en Docker solo si está disponible; Playwright con API fixture.
- Linux/LXC: suite completa, `pty`, `bash`, `wipe` falso, `tdl` falso como script ejecutable.
- Las pruebas de API usan `TestClient`, SQLite temporal y una cola RQ falsa.
- Las pruebas de navegador usan datos fixture; la integración real se prueba con backend + `tdl`
  falso y se identifica en el informe.

### 21.11 Alcance de Registros y Configuración

- `/logs` lista la actividad reciente de jobs y enlaza al log de cada job; no agrega logs globales.
- `/settings` muestra versión, entorno, rutas, límites, binario/namespace de `tdl`, estado de
  Redis/worker y sesión. No muestra `SECRET_KEY`, `WEB_PASSWORD` ni URLs con credenciales.
- El botón de arranque de servicios solo aparece en desarrollo.

## 22. Respuestas a la revisión del constructor

1. **¿Cómo llega el código existente a `tdl-web-next`?**
   La copia independiente ya se creó con `git clone` desde el repositorio original y contiene
   todo el historial y el código en el commit `34f74c6e`. La primera fase es un `git mv` dentro
   de esa copia (`app/` → `backend/app/`, `tests/` → `backend/tests/`), no una copia desde el
   checkout original. El original solo se leyó y no se modifica. La lógica delicada se reutiliza
   moviéndola, no reescribiéndola.

2. **¿Se conserva la raíz de datos?**
   Sí. Se conserva `/opt/tld-web/data` y las rutas actuales (`sessions`, `exports`, `downloads`,
   `logs`, SQLite, `chats.json`). Las rutas guardadas en `download_jobs` son absolutas; por eso
   el instalador respeta el `DATA_DIR`/`DOWNLOADS_DIR` existente y no reubica datos. Si una
   instalación ya usa otra raíz, se conserva su `.env` y solo se añaden las variables nuevas.
   El rollback restaura la misma raíz y la misma base.

3. **¿Next.js renderiza datos en servidor?**
   No. El layout puede ser servidor, pero los datos se piden en componentes cliente con
   TanStack Query. Basic auth la resuelve Nginx en el navegador; no hay llamadas SSR que
   necesiten reenviar `Authorization`. Por eso no hay URL interna de API ni CORS. En desarrollo
   se usa un rewrite de Next.js; en producción Nginx enruta `/api/`.

4. **¿Se permiten tablas nuevas?**
   No hacen falta. Las migraciones son aditivas: `ALTER TABLE` para `dedupe_key`,
   `deletion_requested`, `deletion_error` y `deletion_rq_job_id`, más índices. Los eventos se
   siguen derivando de `logs/job-<id>.log` (`job_events()`); no se crea tabla de eventos.
   `Idempotency-Key` no crea tabla: se incorpora a la huella `dedupe_key`; el índice único
   parcial sigue siendo la garantía.

5. **¿Qué borra exactamente `POST /admin/reset`?**
   Conserva el comportamiento actual de `reset_application_state`: cancela jobs activos, vacía
   la cola Redis, borra filas de `download_jobs`/`download_templates`, vacía `exports/`,
   `downloads/` y `logs/`, y borra `chats.json`. Conserva la base SQLite, el esquema, la
   configuración y los backups. `keep_session=true` conserva `sessions/`; `false` también borra
   la sesión de Telegram. No borra el archivo `.sqlite3` ni los backups. Exige `REINICIAR`.

6. **¿Hay runtime Linux para verificar?**
   Sí, Docker está disponible y se usa solo para desarrollo/pruebas, no para el despliegue.
   Windows puede ejecutar la mayoría de pruebas de servicios y API con `pytest --basetemp`,
   `tdl` falso `.cmd` y Redis de pruebas en Docker. Las pruebas de `pty`, `bash` y scripts de
   instalación se ejecutan en un contenedor Debian/Ubuntu o en el LXC; si el contenedor no
   arranca, se documenta el bloqueo y no se afirma que pasaron. Playwright puede correr en
   Windows con fixtures de API; la integración real con backend y `tdl` falso se hace con Redis
   en Docker.

La compatibilidad de importación de RQ es una red de seguridad, no una promesa de que un job
antiguo siga corriendo durante el corte: el procedimiento por defecto es drenar la cola o dejar
terminar el job en curso antes de cambiar servicios.

## 23. Lo que queda al constructor

- Versiones exactas de Next.js/React/Tailwind/shadcn, fijadas en lockfile.
- Composición visual concreta (paleta, tipografía, densidad) dentro de `DESIGN.md`.
- Elección de TLS (Let's Encrypt o certificado interno) según la red del LXC.
- Detalles de pruebas y nombres de componentes.
- División exacta de routers si algún archivo crece demasiado.

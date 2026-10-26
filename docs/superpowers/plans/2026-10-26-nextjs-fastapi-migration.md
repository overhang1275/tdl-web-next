# Migración Next.js + FastAPI — Plan de implementación

> **Para el ejecutor:** usar `superpowers:executing-plans` en modo nativo. Cada tarea termina con
> pruebas y commit. No se avanza con pruebas rojas no documentadas.

**Goal:** Reemplazar la UI Jinja/HTMX por Next.js y exponer FastAPI `/api/v1`, conservando la
lógica real de `tdl`, SQLite y Redis/RQ.

**Architecture:** Se mueve el paquete `app` existente a `backend/app`; se conservan servicios,
modelos y worker; se añade una capa API tipada y seguridad; Next.js consume la API con TanStack
Query. Redis/RQ sigue ejecutando `app.worker.run_download_job`. Un worker de API y uno de RQ.

**Tech Stack:** Python 3.12+, FastAPI 0.136.3, Pydantic 2.13.4, SQLAlchemy 2.0.50, Redis 5.2.1,
RQ 2.0.0, SQLite; Next.js 16.4.3, React 19.3.1, TypeScript 5.9.3, Tailwind 4.3.3, shadcn/ui,
TanStack Query 5.105.0, Zod 4.6.7, React Hook Form 7.91.0; pytest, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-26-nextjs-fastapi-migration-design.md`

## Global Constraints

- Copia de trabajo: `C:\Users\init\Desktop\tdl-web-next`; el original no se toca.
- Rama: `migration/nextjs-fastapi`; origin privado nuevo; upstream original.
- Un solo worker Uvicorn y un solo worker RQ.
- JWT con cookies HttpOnly (access 15 min, refresh 7 días); refresh revocable en Redis.
- `SECRET_KEY` de 32+ y credenciales de administrador obligatorias en producción; TLS en Nginx.
- Sin lógica de `tdl` en Next.js; sin `NEXT_PUBLIC_*` con secretos; tokens nunca en `localStorage`.
- SQLite y raíz de datos existentes; migraciones aditivas.
- No se borran datos reales sin autorización.
- Dependencias fijadas y lockfiles.
- Español en la UI; código e identificadores en inglés.

## Review Focus

- Un job creado dos veces no debe duplicar descargas.
- Un borrado con `wipe` no debe perder el registro ni la carpeta si falla.
- Un archivo HTML/SVG no debe ejecutarse en el origen de la app.
- Un job debe seguir siendo reanudable tras reiniciar API/worker.
- La UI no debe mostrar progreso, velocidad o ETA inventados.
- La app no debe arrancar en producción sin `SECRET_KEY` y credenciales.
- Un access token no debe servir como refresh; el logout debe revocar el refresh.
- Un 401 debe refrescar una vez y volver a `/login` si falla, sin bucles.
- Las cookies críticas no deben ser legibles desde JavaScript.

---

## Estructura de archivos

```text
backend/
  app/
    main.py
    config.py
    database.py
    models.py
    schemas.py
    security.py
    api/
      __init__.py
      deps.py
      errors.py
      v1/
        __init__.py
        router.py
        health.py
        status.py
        auth.py
        chats.py
        jobs.py
        files.py
        templates.py
        dashboard.py
        search.py
        settings.py
        admin.py
    services/
      tdl.py filtering.py transfers.py paths.py files.py logs.py
      chat_cache.py search.py jobs.py interactive_login.py errors.py
      pagination.py status.py progress.py auth.py
    worker.py
    rq_worker.py
  tests/
    conftest.py
    test_api_health.py
    test_api_jobs.py
    test_api_files.py
    test_api_security.py
    test_api_chats.py
    test_api_templates.py
    test_services_*.py
  requirements.txt
  requirements-dev.txt
  pyproject.toml
frontend/
  app/
    layout.tsx
    page.tsx
    globals.css
    not-found.tsx
    error.tsx
    login/page.tsx
    (dashboard)/
      layout.tsx
      downloads/page.tsx
      downloads/new/page.tsx
      downloads/[id]/page.tsx
      chats/page.tsx
      chats/[id]/page.tsx
      logs/page.tsx
      settings/page.tsx
  middleware.ts
  components/
    login-form.tsx
    auth-provider.tsx
    user-menu.tsx
    app-shell.tsx
    sidebar.tsx
    mobile-nav.tsx
    topbar.tsx
    theme-toggle.tsx
    status-badge.tsx
    metric-card.tsx
    page-header.tsx
    empty-state.tsx
    error-state.tsx
    pagination.tsx
    confirm-dialog.tsx
    job-table.tsx
    job-card.tsx
    job-progress.tsx
    job-actions.tsx
    file-grid.tsx
    log-viewer.tsx
    event-timeline.tsx
    chat-picker.tsx
    filter-bar.tsx
    template-select.tsx
    ui/ (button, card, input, select, badge, progress, dialog, tabs, tooltip, skeleton)
  lib/
    api.ts
    types.ts
    query-keys.ts
    format.ts
    utils.ts
  package.json
  package-lock.json
  next.config.ts
  tsconfig.json
  postcss.config.mjs
  eslint.config.mjs
  vitest.config.ts
  playwright.config.ts
deploy/
  nginx/tdl-web.conf
  systemd/tdl-web-api.service
  systemd/tdl-web-worker.service
  systemd/tdl-web-frontend.service
  install.sh
  update.sh
scripts/playwright.ps1
docs/design-audit/
```

---

### Task 0: Mover el backend y conservar la lógica

**Files:**
- Move: `app/` → `backend/app/`; `tests/` → `backend/tests/`; `requirements.txt` → `backend/requirements.txt`
- Create: `backend/requirements-dev.txt`, `backend/pyproject.toml`
- Delete: `backend/app/templates/`, `backend/app/static/`, `backend/app/main.py` (se reemplaza)
- Modify: `.gitignore`

**Interfaces:**
- Produce: paquete `app` importable desde `backend/`; `app.worker.run_download_job` sin cambios.

- [ ] Mover con `git mv`, conservando historial.
- [ ] En `backend/requirements.txt`: conservar FastAPI/SQLAlchemy/Redis/RQ; retirar `jinja2` y
      `python-multipart`; añadir `PyJWT` y `ruff`.
- [ ] Añadir `requirements-dev.txt` (`pytest`, `httpx`, `ruff`) y `pyproject.toml` con
      `pythonpath = ["."]`, `testpaths = ["tests"]`, `addopts = "-q"`, Ruff `line-length = 100`.
- [ ] Añadir a `.gitignore`: `backend/data/`, `.pytest-tmp/`, `frontend/node_modules/`,
      `frontend/.next/`, `frontend/playwright-report/`, `frontend/test-results/`.
- [ ] Verificar que `python -c "import app.worker"` funciona desde `backend/` con el venv.
- [ ] Commit: `refactor: mover backend y conservar servicios`.

**Verify:** `cd backend; ..\.venv\Scripts\python -c "import app.worker"` (Windows) o
`../.venv/bin/python -c "import app.worker"` (Linux).

---

### Task 1: Base FastAPI, configuración y seguridad

**Files:**
- Create: `backend/app/security.py`, `backend/app/services/auth.py`,
  `backend/app/api/deps.py`, `backend/app/api/errors.py`, `backend/app/api/v1/router.py`,
  `backend/app/api/v1/health.py`, `backend/app/api/v1/status.py`,
  `backend/app/services/status.py`
- Modify: `backend/app/config.py`, `backend/app/main.py`, `backend/requirements.txt`

**Interfaces:**
- `Settings.validate()` lanza `RuntimeError` si `APP_ENV=production` y falta `SECRET_KEY` (32+) o
  `WEB_PASSWORD_HASH`/`WEB_PASSWORD` (12+).
- `auth.hash_password(password) -> str` (scrypt), `auth.verify_password(password, encoded) -> bool`.
- `auth.create_access_token(username) -> str`, `auth.create_refresh_token(username) -> tuple[str, str]`
  (token, jti), `auth.decode_token(token, expected_type) -> dict`.
- `auth.set_auth_cookies(response, access, refresh, jti)`, `auth.clear_auth_cookies(response)`.
- `deps.get_current_user(request) -> User` valida el access JWT.
- `security.install(app)` registra CSRF, cabeceras y `TrustedHostMiddleware`.
- `ApiError(code: str, message: str, status_code: int, detail: Any | None = None)`.
- `status_service.get(force: bool = False) -> dict`.

- [ ] Añadir `PyJWT` a `requirements.txt`.
- [ ] Escribir pruebas de health 200 sin auth, `/api/v1/status` 401 sin cookie, token válido,
      token de refresh rechazado como access y contraseña hash.
- [ ] Implementar `Settings.validate()` y `services/auth.py`:
      - scrypt con sal; comparación con `hmac.compare_digest`.
      - HS256, claims `sub/role/type/jti/iat/exp`; access 15 min, refresh 7 días.
      - Redis `auth:refresh:<jti>` con TTL; fallo cerrado.
      - Cookies HttpOnly/Secure/SameSite; access `Lax`, refresh `Strict`.
- [ ] Implementar `security.py`: sin Basic; exigir `X-Requested-With` y origen propio en
      escrituras; cabeceras de seguridad; `TrustedHostMiddleware`.
- [ ] Implementar `status_service` con TTL 10 s, Redis ping, `Worker.all`, `TdlService.is_logged_in`,
      storage y `tdl_binary`; invalidación explícita.
- [ ] Crear `main.py` con `lifespan`, routers, handlers de `ApiError`/`RequestValidationError`/
      `HTTPException`, `/health` y `/api/docs`.
- [ ] Ejecutar pytest y commit: `feat: base FastAPI y JWT`.

**Verify:** `pytest tests/test_api_health.py tests/test_api_security.py -q`.

---

### Task 2: Esquemas, paginación y API de lectura

**Files:**
- Modify: `backend/app/schemas.py`
- Create: `backend/app/services/pagination.py`, `backend/app/services/progress.py`,
  `backend/app/api/v1/chats.py`, `jobs.py`, `files.py`, `dashboard.py`, `search.py`,
  `templates.py`, `settings.py`
- Modify: `backend/app/services/files.py`, `search.py`, `jobs.py`, `chat_cache.py`

**Interfaces:**
- `Page[T]` y `ApiError` con `ConfigDict(from_attributes=True)`.
- `JobRead` incluye `progress_percent: float | None`, `total_expected_bytes: int | None`,
  `downloaded_bytes: int`, `speed_bps: int`, `eta_seconds: int | None`, `deletion_requested`,
  `deletion_error`.
- `JobFileRead` incluye `file_id: int | None`, `name`, `relative_path`, `size`, `kind`,
  `status`, `attempts`, `last_error`, `content_url`.
- `paginate_chats()` y `paginate_downloads()` se mueven desde `main.py`.

- [ ] Añadir esquemas de lectura y helpers de paginación.
- [ ] `GET /chats`, `/chats/{id}`; reutilizar `chat_cache` y perfil actual.
- [ ] `GET /jobs` con filtros `status`, `chat_id`, `q`, paginación; `GET /jobs/{id}` con
      `queue_position` y progreso; `GET /jobs/{id}/files`, `/logs`, `/events`.
- [ ] `GET /dashboard`, `/search`, `/templates`, `/settings`.
- [ ] Pruebas de contrato y paginación.
- [ ] Commit: `feat: API de lectura`.

**Verify:** `pytest tests/test_api_chats.py tests/test_api_jobs.py tests/test_api_files.py -q`.

---

### Task 3: API de escritura y autenticación

**Files:**
- Modify: `backend/app/api/v1/jobs.py`, `templates.py`, `admin.py`
- Create: `backend/app/api/v1/auth.py`, `backend/app/api/v1/telegram.py`
- Modify: `backend/app/services/jobs.py`, `backend/app/services/interactive_login.py`,
  `backend/app/schemas.py`

**Interfaces:**
- `POST /auth/login` con `{username, password}`; set-cookie access/refresh; 401 genérico.
- `POST /auth/refresh` rota el access; `POST /auth/logout` revoca; `GET /auth/me`.
- `POST /telegram/login/start|input|cancel`, `GET /telegram/login`.
- `POST /jobs` acepta `JobCreate` y `Idempotency-Key`; devuelve 201 o 409
  `duplicate_job` con `detail.job_id`.
- `POST /jobs/{id}/cancel` devuelve `JobRead`.
- `POST /jobs/{id}/retry?mode=pending|failed` devuelve `JobRead`; 409 `no_failed_files`.
- `DELETE /jobs/{id}` exige `{"confirm": true}`; devuelve 202.
- `POST /templates`, `PUT /templates/{id}`, `DELETE /templates/{id}`.
- `POST /admin/reset` exige `{"confirmation": "REINICIAR", "keep_session": bool}`.

- [ ] Pruebas de login/refresh/logout, cookies, CSRF, creación, duplicado, cola caída,
      cancelación, reintento, borrado, plantillas y reset.
- [ ] Implementar routers y validaciones; no confiar en `confirm()` del navegador.
- [ ] `interactive_login` sin eco de entrada; import de `pty` dentro de `start()`.
- [ ] Servicios de arranque solo si `APP_ENV != production`.
- [ ] Commit: `feat: API de escritura, JWT y login de Telegram`.

**Verify:** `pytest tests/test_api_jobs.py tests/test_api_templates.py tests/test_api_security.py -q`.

---

### Task 4: Modelo, migraciones e idempotencia

**Files:**
- Modify: `backend/app/models.py`, `backend/app/database.py`
- Create: `backend/app/services/deletion.py`
- Modify: `backend/app/services/jobs.py`, `backend/app/worker.py`

**Interfaces:**
- Columnas nuevas: `dedupe_key`, `deletion_requested`, `deletion_error`, `deletion_rq_job_id`.
- Índice único parcial `uq_download_jobs_active_dedupe`.
- `dedupe_key(payload) -> str` (SHA-256 de la tupla canónica).
- `reconcile_deletions()` y `delete_job(job_id)`.

- [ ] Prueba de migración idempotente y de índice único.
- [ ] Añadir columnas, backfill de jobs activos y creación del índice; si hay duplicados
      históricos, conservar el más antiguo y dejar `NULL` en los demás.
- [ ] `create_job` calcula `dedupe_key`; captura `IntegrityError` y devuelve el job existente.
- [ ] `retry_job(mode="failed")` resetea solo fallidos.
- [ ] `delete_job` espera a que el job sea terminal y usa `wipe_delete_job`; guarda error.
- [ ] `update_transfer_totals` calcula bytes esperados; progreso con EMA y ETA nullable.
- [ ] Commit: `feat: idempotencia, borrado persistido y progreso honesto`.

**Verify:** `pytest tests/test_resume.py tests/test_api_jobs.py -q`.

---

### Task 5: Pruebas de backend completas

**Files:**
- Create: `backend/tests/conftest.py`, `test_api_security.py`, `test_api_files.py`,
  `test_api_chats.py`, `test_api_templates.py`
- Adapt: tests existentes a `backend/tests/`

- [ ] `conftest.py`: SQLite temporal, `TestClient`, `settings` dirs, RQ falsa, `TdlService` falsa.
- [ ] Cubrir auth, CSRF, cabeceras, content-disposition, traversal, dedupe, delete, retry,
      progreso null/fiable, reset.
- [ ] Ejecutar `ruff check app tests` y `pytest`.
- [ ] Documentar bloqueos de Windows (pty/bash).
- [ ] Commit: `test: cobertura de API y seguridad`.

**Verify:** `cd backend; ..\.venv\Scripts\python -m pytest --basetemp=.pytest-tmp` (Windows) o
`../.venv/bin/python -m pytest` (Linux).

---

### Task 6: Scaffold de Next.js

**Files:**
- Create: `frontend/package.json`, `next.config.ts`, `tsconfig.json`, `postcss.config.mjs`,
  `eslint.config.mjs`, `app/layout.tsx`, `app/globals.css`, `app/not-found.tsx`,
  `app/error.tsx`, `lib/api.ts`, `lib/types.ts`, `lib/query-keys.ts`, `lib/format.ts`,
  `lib/utils.ts`, `components/providers.tsx`

**Interfaces:**
- `apiFetch<T>(path, init?)` añade `X-Requested-With`, `Content-Type`, `credentials: same-origin`;
  en 401 intenta `POST /api/v1/auth/refresh` una vez y reintenta; si falla, va a `/login`.
- `middleware.ts` verifica `tdl_access` con `jose` y protege las rutas privadas; `/login` es pública.
- `next.config.ts` con `output: "standalone"` y rewrite `/api/:path*`.
- `QueryClient` con `retry: 1`, `refetchOnWindowFocus: true`.

- [ ] Escribir configuración y dependencias fijadas (`jose` incluido).
- [ ] Implementar `apiFetch`, tipos, query keys y cliente de auth.
- [ ] Implementar `middleware.ts` con verificación HS256 y redirect a `/login`.
- [ ] Layout raíz, tema claro/oscuro, Toaster, fuente del sistema.
- [ ] `npm install`, `npm run typecheck`, `npm run lint`.
- [ ] Commit: `feat: scaffold Next.js con middleware JWT`.

**Verify:** `cd frontend; npm run typecheck; npm run lint`.

---

### Task 7: Shell, login y pantallas

**Files:**
- Create: `components/ui/*`, `components/login-form.tsx`, `components/auth-provider.tsx`,
  `components/user-menu.tsx`, `components/app-shell.tsx`, `sidebar.tsx`, `mobile-nav.tsx`,
  `topbar.tsx`, `theme-toggle.tsx`, `status-badge.tsx`, `metric-card.tsx`,
  `page-header.tsx`, `empty-state.tsx`, `error-state.tsx`, `pagination.tsx`,
  `confirm-dialog.tsx`, `job-table.tsx`, `job-card.tsx`, `job-progress.tsx`,
  `job-actions.tsx`, `file-grid.tsx`, `log-viewer.tsx`, `event-timeline.tsx`,
  `chat-picker.tsx`, `filter-bar.tsx`, `template-select.tsx`
- Create pages: `app/login/page.tsx`, `app/page.tsx`, `(dashboard)/downloads/page.tsx`,
  `downloads/new/page.tsx`, `downloads/[id]/page.tsx`, `chats/page.tsx`, `chats/[id]/page.tsx`,
  `logs/page.tsx`, `settings/page.tsx`

- [ ] Implementar login profesional (marca, formulario, errores, loading) y menú de usuario.
- [ ] Implementar shell responsive con sidebar/bottom nav y búsqueda.
- [ ] Resumen: estado, métricas, activos, errores, CTA.
- [ ] Descargas: filtros, tabla/cards, paginación.
- [ ] Nueva descarga: chat picker, filtros, plantilla, validación, aviso de export.
- [ ] Detalle: progreso honesto, acciones, eventos, logs, archivos.
- [ ] Chats y perfil.
- [ ] Registros y Configuración con usuario/sesión y logout.
- [ ] `npm run typecheck`, `npm run build`.
- [ ] Commit: `feat: login y pantallas Next.js`.

**Verify:** `cd frontend; npm run typecheck; npm run build`.

---

### Task 8: Pruebas de frontend y Playwright

**Files:**
- Create: `frontend/vitest.config.ts`, `frontend/test/setup.ts`, component tests,
  `frontend/playwright.config.ts`, `frontend/e2e/*.spec.ts`, `scripts/playwright.ps1`

- [ ] Vitest para formatters, API client y formularios.
- [ ] Playwright para Resumen, Descargas, Nueva descarga, Detalle, Chats, Configuración.
- [ ] `scripts/playwright.ps1` ejecuta `npx playwright`.
- [ ] Capturas para el design audit.
- [ ] Commit: `test: frontend y Playwright`.

**Verify:** `cd frontend; npm test; npx playwright test`.

---

### Task 9: Integración local con `tdl` falso

**Files:**
- Create: `scripts/fake-tdl.cmd` (Windows), `scripts/fake-tdl.sh` (Linux),
  `scripts/seed-dev.py`
- Modify: `.env.example`

- [ ] El fake responde a `chat ls`, `chat export`, `download` y crea archivos.
- [ ] Seed de chats/jobs/archivos para la UI.
- [ ] Redis de pruebas en Docker (`127.0.0.1:6380`) solo para integración.
- [ ] Probar un job completo export → filtro → descarga → completed.
- [ ] Commit: `test: integración con tdl falso`.

**Verify:** `pytest` + job de prueba; Playwright contra backend real.

---

### Task 10: Despliegue LXC

**Files:**
- Create: `deploy/systemd/tdl-web-api.service`, `tdl-web-worker.service`,
  `tdl-web-frontend.service`, `deploy/nginx/tdl-web.conf`, `deploy/install.sh`,
  `deploy/update.sh`, `.env.example`, `README.md`
- Delete/retirar: `Dockerfile`, `docker-compose.yml` del camino principal.

- [ ] Script de instalación: usuario, venv, Redis, Node 22, build, `SECRET_KEY`,
      `WEB_PASSWORD_HASH`, `ADMIN_USERNAME`, Nginx, systemd, permisos 700/600, health check.
- [ ] Nginx: TLS, rate limit de login/API, `/api/` y `/`, health sin auth, timeouts. Sin Basic.
- [ ] systemd: `UMask=0077`, `NoNewPrivileges`, `ProtectSystem=strict`, `ReadWritePaths`;
      API y frontend reciben `SECRET_KEY`; solo API recibe `WEB_PASSWORD_HASH`.
- [ ] Update: backup SQLite + WAL, build, migración, restart, rollback.
- [ ] README con instalación, operación, logs, backup, login y migración.
- [ ] Commit: `feat: despliegue LXC con JWT`.

**Verify:** `bash -n deploy/install.sh deploy/update.sh`; revisar unidades con `systemd-analyze
verify` si está disponible; no afirmar instalación real sin LXC.

---

### Task 11: Design audit

**Files:**
- Create: `DESIGN.md`, `docs/design-audit/latest.md`, `docs/design-audit/screenshots/`

- [ ] Arrancar frontend y backend con fixtures/fake tdl.
- [ ] Ejecutar `/design-auditor` según su skill.
- [ ] Revisar 1280x800, 1440x900, 390x844; teclado, foco, contraste, estados.
- [ ] Corregir máximo 3 rondas.
- [ ] Guardar antes/después y verificar flujos.
- [ ] Commit: `fix: auditoría de diseño`.

---

### Task 12: Verificación final y Graphify

**Files:**
- Modify: `docs/architecture/current-state.md` (estado implementado), `migration-map.md`
- Create: `docs/architecture/graphify/final/`

- [ ] `pytest`, `ruff`, `npm run lint`, `npm run typecheck`, `npm run build`, Playwright.
- [ ] Job de prueba con fake tdl; cancelar, reintentar, borrar.
- [ ] Verificar original intacto (rama, remotos, HEAD, status).
- [ ] Ejecutar Graphify final en `graphify-out-final/` o copia separada; conservar inicial.
- [ ] Comparar mapas; actualizar docs con lo implementado y pendientes.
- [ ] Commit: `docs: cierre de migración y grafo final`.

---

## Self-review

- Cobertura del spec: paridad (tareas 2-4, 7), seguridad JWT (1, 3, 5), API (2-3), UI (6-8),
  despliegue (10), auditoría (11), grafo (12).
- Dependencias: 0 → 1 → 2/3 → 4 → 5; 6 → 7 → 8; 9 después de 5; 10 después de 8; 11 después de 8;
  12 al final.
- Tipos: `JobRead` y `apiFetch` se definen en 2 y se consumen en 7; `Page[T]` en 2; `ApiError` en 1;
  `TokenPair`/`User` en 1 y 3.
- Riesgos: los del diseño (JWT, borrado, duplicados, XSS, reanudación, progreso) tienen prueba o
  verificación explícita.

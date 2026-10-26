# TDL Console

Consola en español para descargar archivos de Telegram con `tdl`. Next.js sirve la UI;
FastAPI expone `/api/v1`; Redis/RQ ejecuta los trabajos. Se conservan SQLite, la sesión
de Telegram, los archivos descargados y la ruta `app.worker.run_download_job`.

Hay dos instalaciones independientes: **nativa para LXC, sin Docker**, y **Docker
Compose para producción**. Las pruebas completas usan un stack Docker aislado.

## Instalación nativa en LXC

Ejecuta `install-tld.sh` como root dentro de un LXC existente con systemd, Debian 13
(o Ubuntu 24.04/26.04), x86_64 o arm64. Usa Node y tdl oficiales con SHA-256, Python
con venv y Next.js standalone. El maestro no crea el LXC ni configura cloudflared.

Desde una copia de este repositorio:

```bash
sudo bash install-tld.sh --source-dir "$PWD"
```

El asistente permite instalar, actualizar, reparar, reconfigurar o cancelar. Enter
acepta los valores mostrados. Por defecto usa `/opt/tld-web`, `127.0.0.1:8080`, un
usuario de servicio `tld-web` sin login y Redis local opcional. Si eliges Redis
externo solicita su URL sin mostrarla y no configura el servicio Redis del LXC.
La API usa un puerto loopback separado (8000); los puertos ocupados se rechazan.

El login requiere Authentik externo. El asistente solicita issuer HTTPS, client ID
y secreto si faltan. Configura un proveedor OIDC confidencial con PKCE, firma
RS256, scopes `openid profile email offline_access tdl-groups`, y grupo `tdl-admin`.
El scope `tdl-groups` debe emitir `groups` con los nombres de los grupos. El callback
es exactamente `AUTH_URL/api/auth/callback/authentik`; para el acceso local por
defecto: `http://localhost:8080/api/auth/callback/authentik`.

`PUBLIC_URL` es una referencia opcional, vacía por defecto. No modifica `AUTH_URL`.
Para acceder por `https://tld.opencore.dpdns.org`, configura por tu cuenta el túnel
hacia `http://127.0.0.1:8080`, establece esa URL HTTPS como `AUTH_URL` y registra
`https://tld.opencore.dpdns.org/api/auth/callback/authentik` en Authentik.

Los defaults sin secretos se guardan en `/etc/tld-web/install.conf`; el entorno
sensible en `/etc/tld-web/tld-web.env`. Puedes preparar este último desde
`.env.native.example` antes de ejecutar. No sobrescribas un entorno existente.
Las instalaciones anteriores conservan su archivo en `/etc/telegram-downloader`,
usuario, rutas y nombres de servicio; su Nginx existente se mantiene.

```text
/opt/tld-web/tools/                Binarios versionados
/opt/tld-web/releases/<versión>/   Backend, venv y frontend standalone
/opt/tld-web/current               Enlace a la versión activa
/opt/tld-web/data/                 SQLite, sesión y archivos
/opt/tld-web/logs/                 Logs (ruta anterior si ya existía)
/opt/tld-web/tmp/                  Temporales
/opt/tld-web/backups/              Respaldos de recuperación, solo root
```

Código, herramientas y respaldos pertenecen a root; el servicio escribe en sus
carpetas de datos y caché. Los servicios nuevos son `tld-web-api`, `tld-web-worker`
y `tld-web`. Para mantenimiento:

```bash
sudo bash install-tld.sh --action update --source-dir "$PWD"
sudo bash install-tld.sh --action repair
sudo bash install-tld.sh --dry-run
sudo journalctl -u tld-web-api -u tld-web-worker -u tld-web -f
```

Sin `--source-dir`, `auto` busca un bundle GitHub Release para la arquitectura y,
si no existe, construye desde Git. Puedes indicar `--ref latest`, tag o commit,
y `--method source|release|auto`. El contrato de bundle es
`tld-web-linux-x64.tar.gz` o `tld-web-linux-arm64.tar.gz` más `SHA256SUMS`; incluye
backend/requirements.txt, scripts de configuración/backup y frontend standalone.
No se omite un checksum inválido. Repositorios privados requieren credenciales de
Git y, para consultar Releases, `GH_TOKEN` en el entorno, sin persistirlo.

Se construye antes del corte. La activación exige que no haya jobs, borrados ni
traslados pendientes, respalda SQLite, entorno, defaults, unidades, sesión,
exports y logs, y conserva las descargas en su sitio. Un fallo recupera el enlace,
configuración, unidades, base de datos y servicios anteriores. Los respaldos no
incluyen los archivos descargados; mantén también tu respaldo externo de datos.
`repair` y `configure` reutilizan la versión instalada sin descargar ni compilar.
Con entrada no interactiva, una instalación existente cancela si no se indica
`--action`. `--yes` acepta defaults; requiere las credenciales OIDC ya configuradas.

## Producción con Docker Compose

Esta vía incluye PostgreSQL, Authentik, Redis, API, worker, Next.js y Nginx. Solo Nginx
publica 80/443. Es independiente del instalador nativo del LXC.

```bash
python3 scripts/configure-env.py --deployment docker --output .env --domain example.test
docker compose --env-file .env -f deploy/docker/compose.yml config --quiet
```

Revisa `.env`, prepara `DATA_DIR` y `DOWNLOADS_DIR` con el UID/GID configurado
(`APP_UID`/`APP_GID`, por defecto `10001`) y coloca los certificados para
`app.DOMAIN` y `auth.DOMAIN` en `TLS_DIR`. Conserva las rutas absolutas originales al
migrar datos existentes. `DATABASE_DIR` debe ser el directorio de `DATABASE_URL`;
sesión, exports, logs y base tienen sus propios montajes aunque estén fuera de `DATA_DIR`. Después:

```bash
docker compose --env-file .env -f deploy/docker/compose.yml up -d --build --wait
bash deploy/authentik/bootstrap.sh
```

El blueprint crea el cliente OIDC y el grupo; el bootstrap añade `akadmin` a
`tdl-admin`. La contraseña inicial está en `AUTHENTIK_BOOTSTRAP_PASSWORD` del `.env`.
No publiques ese archivo. Antes de actualizar, drena la cola, respalda SQLite,
`pg_dump` de Authentik y los volúmenes; conserva las imágenes anteriores para rollback.
El archivo raíz `docker-compose.yml` incluye este mismo Compose.

## Pruebas en Docker

```bash
bash scripts/test.sh
```

En Windows:

```powershell
./scripts/test.ps1
```

Los runners ejecutan Ruff, pytest, ESLint, TypeScript, Vitest y Playwright. El stack
usa SQLite y Redis separados, OIDC/JWKS de prueba con RS256/PKCE y un ejecutable
`tdl` falso. La integración recorre login → API → cola → export → filtro → descarga
→ borrado persistido. No contacta Telegram ni monta datos de producción. Al salir,
los scripts eliminan exclusivamente los contenedores y volúmenes de pruebas.

Para una comprobación visual local después del build:

```powershell
$env:PLAYWRIGHT_PRODUCTION='1'
./scripts/playwright.ps1 test
```

Las capturas e informes de auditoría quedan en `docs/design-audit/`. `docs/` y
`graphify-out/` permanecen locales y están excluidos de los nuevos commits.

## Uso

Entra con Authentik, conecta Telegram en Configuración y selecciona un chat.
Puedes filtrar texto, hashtag, fechas y tipo de archivo. El progreso y la ETA se
muestran solo cuando existen datos fiables. Reintentar conserva los archivos
completos; eliminar exige confirmación y usa `wipe`.

En Configuración puedes editar la carpeta de descargas y los límites de comando,
lotes de descarga/exportación y espera sin progreso. Se guardan en SQLite y
prevalecen sobre los valores iniciales del entorno. Guarda con la cola vacía.
Cambiar la carpeta exige confirmar el traslado: el worker copia y verifica SHA-256,
actualiza las rutas de los archivos y después vacía el origen. Si falla, muestra
el error y permite reintentar; las descargas quedan bloqueadas hasta resolverlo.
El destino debe estar vacío, tener espacio para una copia completa y ser escribible.

En Docker utiliza una subcarpeta de DATA_DIR. Para otro volumen, móntalo con la
misma ruta en API y worker y declara su raíz en DOWNLOADS_ALLOWED_ROOTS (separadas
por dos puntos). La web no crea montajes del host. En LXC usa una carpeta dedicada
escribible por telegramdl. No modifiques los archivos manualmente durante un traslado.

El navegador solo llama al BFF de Next.js. Los access/refresh tokens permanecen
en una cookie cifrada HttpOnly y el BFF añade el Bearer hacia FastAPI. Las
escrituras verifican origen y `X-Requested-With`; la creación conserva
`Idempotency-Key`. No hay contraseñas locales ni tokens en localStorage.

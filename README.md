# TDL Console

Consola en español para descargar archivos de Telegram con `tdl`. Next.js sirve la UI;
FastAPI expone `/api/v1`; Redis/RQ ejecuta los trabajos. Se conservan SQLite, la sesión
de Telegram, los archivos descargados y la ruta `app.worker.run_download_job`.

Hay dos instalaciones independientes: **nativa para LXC, sin Docker**, y **Docker
Compose para producción**. Las pruebas completas usan un stack Docker aislado.

## Instalación nativa en LXC

Debian 13 o Ubuntu 24.04, x86_64 o arm64. Ejecuta desde una copia del repositorio.
El instalador usa binarios de Node y `tdl` con verificación SHA-256, Python en un
venv, Redis y Nginx del sistema. No instala Docker.

El login usa un **Authentik externo**. Primero crea allí un cliente OIDC confidencial
con PKCE, firma RS256, scopes `openid profile email offline_access tdl-groups`, y el
grupo `tdl-admin`. El scope `tdl-groups` debe emitir `groups` con los nombres de grupos
del usuario. Configura el callback exacto:

```text
https://tld.opencore.dpdns.org/api/auth/callback/authentik
```

La plantilla ya usa `https://tld.opencore.dpdns.org` y el Authentik externo en
`https://oak.opencore.dpdns.org`. Completa el client ID y el secreto del proveedor
(y confirma el issuer exacto después de crear la aplicación OIDC):

```bash
sudo install -d -m 750 /etc/telegram-downloader
sudo install -m 600 .env.native.example /etc/telegram-downloader/telegram-downloader.env
sudo nano /etc/telegram-downloader/telegram-downloader.env
sudo bash scripts/install.sh
```

Si ya tienes una instalación, conserva su archivo de entorno y añade únicamente
las variables de OIDC y `DOMAIN`/`AUTH_URL`. No copies la plantilla encima de una
configuración existente. El instalador preserva las rutas y los secretos existentes;
si falta el proveedor, termina antes de reemplazar los servicios.

La plantilla nativa usa `NATIVE_INGRESS=tunnel`: Nginx escucha exclusivamente en
`127.0.0.1:8080`, sin certificados locales ni redirección HTTP. Instala el conector
`cloudflared` como servicio nativo en **el mismo LXC** siguiendo los comandos del
panel Cloudflare. En la ruta publicada del túnel configura `tld.opencore.dpdns.org` y
**Service URL `http://127.0.0.1:8080`**. `AUTH_URL` debe seguir siendo la URL pública
`https://...`, y el callback de Authentik debe usar exactamente ese dominio.
Referencia: [configurar el túnel](https://developers.cloudflare.com/tunnel/get-started/).
El instalador no crea el túnel ni almacena su token.

Si prefieres acceso directo, usa `NATIVE_INGRESS=direct`, dirige el dominio al LXC
y prepara los certificados. Si faltan, se genera uno interno en
`/etc/telegram-downloader/certs/`; confía en él en tus clientes o reemplaza
`fullchain.pem` y `privkey.pem` por certificados de tu CA/ACME y recarga Nginx.

La instalación crea:

```text
/opt/tld-web/node/                  Node binario
/opt/tld-web/bin/tdl                tdl binario
/opt/tld-web/releases/<versión>/    Backend, venv y frontend standalone
/opt/tld-web/current                Enlace a la versión activa
/opt/tld-web/data/                  Datos existentes, sin reubicación
```

Los servicios `telegram-downloader-api`, `telegram-downloader-worker` y
`telegram-downloader-web` ejecutan API, RQ y Next.js con el usuario `telegramdl`.
Solo Nginx publica la app; API y frontend escuchan en localhost.

Para actualizar, actualiza tu copia del código y ejecuta:

```bash
git pull --ff-only
sudo bash scripts/update.sh
```

Se construye la versión nueva antes del corte. La actualización exige una cola sin
jobs activos o pendientes, respalda SQLite mediante su API de backup y guarda
configuración, sesión, exports y logs en `DATA_DIR/backups/`. Conserva las descargas.
Si falla el arranque, recupera la versión y las unidades de servicio anteriores.
Las migraciones de SQLite son aditivas; los respaldos permiten una restauración
manual si fuera necesario.

```bash
sudo journalctl -u telegram-downloader-api -u telegram-downloader-worker -u telegram-downloader-web -f
```

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

El navegador solo llama al BFF de Next.js. Los access/refresh tokens permanecen
en una cookie cifrada HttpOnly y el BFF añade el Bearer hacia FastAPI. Las
escrituras verifican origen y `X-Requested-With`; la creación conserva
`Idempotency-Key`. No hay contraseñas locales ni tokens en localStorage.

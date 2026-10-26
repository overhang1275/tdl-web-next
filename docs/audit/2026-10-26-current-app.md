# Auditoría de la app actual (tdl-web)

Fecha: 2026-10-26
Commit auditado: `34f74c6e84a55606214902ba04be1df2378d4123`
Copia: `C:\Users\init\Desktop\tdl-web-next` (origin: repositorio privado nuevo; upstream: original)
Carga asumida: un administrador, un LXC, un worker; cientos o miles de archivos. No es multiusuario.

## Qué hace el repositorio

Interfaz web FastAPI + Jinja/HTMX para `tdl`. Gestiona el login de Telegram, el caché de chats,
filtros por texto/hashtag/fecha/tipo, exportación por rangos, descargas por lotes, progreso,
cancelación, reintento/reanudación, galería de archivos y logs. Persiste en SQLite y usa Redis + RQ
para ejecutar `tdl` fuera de la petición web.

## Qué se revisó

README, requisitos, configuración, modelos, rutas, servicios, worker, plantillas, JS, pruebas,
scripts de instalación/actualización, systemd, Nginx y Docker. Se ejecutó la línea base compatible
con Windows: 37 pruebas pasaron y 1 quedó bloqueada por `pty`/`termios`; no se ejecutaron
`test_app.py`, `test_scripts.py` ni `test_tdl.py` por dependencias de Linux/shell.

## Must fix

1. **XSS en los avisos de jobs** (`app/static/js/app.js:352`)
   - **Qué es:** el toast construye HTML con `innerHTML` usando el título del chat que devuelve la API.
   - **Problema:** un chat de Telegram llamado `<img src=x onerror=...>` ejecuta JavaScript en el origen de la app y puede llamar a la API con la sesión del administrador.
   - **Fix:** crear nodos de texto (`textContent`) o dejar que Next.js escape; prohibir `dangerouslySetInnerHTML` para datos de Telegram.
   - **Si se omite:** cualquier chat controlado por un tercero puede robar o borrar datos.

2. **Archivos HTML/SVG se sirven inline en el origen de la app** (`app/main.py:1103-1117`, `app/templates/download_preview.html:22-24`)
   - **Qué es:** `FileResponse` usa el MIME detectado y `inline`; la vista previa abre HTML/SVG en un iframe.
   - **Problema:** un archivo descargado con JavaScript se ejecuta en el mismo origen y hereda el acceso a la API.
   - **Fix:** forzar `attachment` para `text/html`, `image/svg+xml` y XML; añadir `Content-Security-Policy: sandbox` a las respuestas de archivos; previsualizar HTML solo como texto.
   - **Si se omite:** un archivo malicioso de Telegram compromete la sesión.

3. **La autenticación es opcional si falta `WEB_PASSWORD`** (`app/config.py:57`, `app/main.py:76-87`)
   - **Qué es:** sin contraseña configurada, `basic_auth_ok` devuelve `True` para todas las rutas.
   - **Problema:** `docker-compose.yml` no define `WEB_PASSWORD`; un despliegue con Docker queda abierto. Un `.env` incompleto en LXC hace lo mismo.
   - **Fix:** fallar al arrancar en producción si `WEB_PASSWORD` falta o es débil; añadirla al compose; mantener `APP_ENV=development` como única excepción.
   - **Si se omite:** cualquiera con acceso al puerto puede borrar descargas y lanzar jobs.

4. **El login interactivo muestra códigos y teléfonos** (`app/services/interactive_login.py:90-98`, `144-146`)
   - **Qué es:** cada valor enviado se añade a la salida; solo se enmascara si tiene 6+ caracteres y no es numérico.
   - **Problema:** un código de Telegram de 5 dígitos se muestra en `/setup/login/output`; el teléfono también queda visible. La salida se sirve por HTTP.
   - **Fix:** no registrar la entrada; si hace falta, mostrar solo `***` y nunca el valor.
   - **Si se omite:** el código de acceso a Telegram queda en pantalla, logs y capturas.

5. **Acciones destructivas sin confirmación del servidor** (`app/main.py:794-802`, `889-895`, `1041-1052`)
   - **Qué es:** limpiar descargas, borrar plantilla y eliminar job con `wipe` confían en `confirm()` del navegador.
   - **Problema:** un POST directo o un CSRF omite el diálogo; `wipe` borra la carpeta física y no se puede deshacer.
   - **Fix:** exigir un campo `confirm`/token de un solo uso validado en FastAPI; registrar la acción y el usuario.
   - **Si se omite:** pérdida irreversible de archivos por un clic o una petición cruzada.

6. **Archivos sensibles con permisos por defecto** (`scripts/install.sh:148-152`, `app/config.py:59-61`)
   - **Qué es:** se fijan permisos 750 en directorios, pero la app crea SQLite, `chats.json`, logs y sesión de tdl con el umask del servicio.
   - **Problema:** con umask 022, los archivos pueden quedar 644 y ser legibles por otros usuarios del LXC; la sesión de Telegram permite leer y descargar todo.
   - **Fix:** `os.umask(0o077)` al arrancar y `chmod 600` para DB, caché, logs y sesión; 700 para sus carpetas.
   - **Si se omite:** otro proceso o usuario del LXC puede robar la sesión de Telegram.

7. **CSRF solo con Origin/Referer** (`app/main.py:90-107`)
   - **Qué es:** las escrituras se bloquean si `Origin` o `Referer` no coinciden con `Host`.
   - **Problema:** si el navegador omite esas cabeceras, la petición pasa; Basic auth se envía automáticamente al mismo origen.
   - **Fix:** exigir una cabecera propia (`X-Requested-With` o token CSRF) en POST/PUT/PATCH/DELETE y rechazar peticiones sin ella.
   - **Si se omite:** un sitio externo puede lanzar un borrado si consigue que el navegador no envíe Referer.

## Should fix

8. **Dos clics pueden crear el mismo job** (`app/main.py:929-946`, `app/services/jobs.py:120-135`)
   - **Qué es:** se busca un job activo parecido y después se crea; no hay restricción única ni transacción.
   - **Problema:** dos peticiones simultáneas pasan la comprobación y descargan dos veces el mismo chat.
   - **Fix:** índice único parcial para jobs activos con la misma huella, o `Idempotency-Key` + claim atómico.
   - **Si se omite:** duplica descargas, tráfico de Telegram y uso de disco.

9. **La eliminación con `wipe` puede perderse** (`app/main.py:1041-1052`, `app/services/jobs.py:245-258`)
   - **Qué es:** el borrado se lanza en `BackgroundTasks`; el job queda marcado como cancelado con un mensaje de “en progreso”.
   - **Problema:** si el proceso web se reinicia antes de ejecutar la tarea, la carpeta queda para siempre y la UI dice que se está borrando.
   - **Fix:** persistir el estado `deleting` y reintentar al arrancar; o ejecutar la eliminación en el worker con un job propio.
   - **Si se omite:** archivos huérfanos que ocupan disco y estados mentirosos.

10. **Cada página ejecuta `tdl chat ls`** (`app/main.py:131-169`, `459`, `500-502`)
    - **Qué es:** `system_status` y `dashboard` llaman a `tdl` para saber si hay sesión en cada carga.
    - **Problema:** `tdl` tarda segundos; la UI se bloquea y el threadpool se llena con pocas pestañas.
    - **Fix:** caché de estado con TTL (10-30 s), invalidada tras login/acciones; endpoint `/health` separado.
    - **Si se omite:** la app se siente lenta y el worker compite por Telegram.

11. **Búsqueda y dashboard recorren todo el disco** (`app/services/search.py:74-92`, `app/main.py:365-395`)
    - **Qué es:** la búsqueda de archivos recorre todos los jobs y `list_downloaded_files`; el dashboard mide `downloads/` completo.
    - **Problema:** con miles de archivos, cada búsqueda o carga del dashboard hace E/S recursiva.
    - **Fix:** consultar `DownloadFile` en SQLite para nombres/estados y cachear el tamaño de disco con TTL.
    - **Si se omite:** tiempos de respuesta crecientes y CPU alta.

12. **ETA y velocidad pueden mentir** (`app/worker.py:149-175`, `app/models.py:65-66`, `app/templates/partials/job_status.html:30-32`)
    - **Qué es:** la velocidad se calcula con una ventana corta y el ETA nunca se calcula; la UI muestra `-`.
    - **Problema:** si se muestra una velocidad ruidosa o un ETA inventado, el usuario decide mal; el código actual no promete ETA.
    - **Fix:** exponer `null` cuando no haya datos fiables; calcular ETA solo con bytes esperados y velocidad estable; etiquetar “aproximado”.
    - **Si se omite:** se percibe como progreso falso.

13. **CSP débil y HTMX desde CDN sin SRI** (`app/main.py:112`, `app/templates/base.html:7`)
    - **Qué es:** solo se envía `frame-ancestors`; htmx se carga desde `unpkg.com` sin `integrity`.
    - **Problema:** un CDN comprometido ejecuta código en el origen; no hay defensa en profundidad contra XSS.
    - **Fix:** empaquetar dependencias en Next.js y enviar CSP con `script-src 'self'` y nonce.
    - **Si se omite:** la superficie XSS sigue abierta.

14. **Sin límite de intentos de contraseña** (`app/main.py:102-113`)
    - **Qué es:** Basic auth se valida en cada petición sin throttling.
    - **Problema:** un atacante con acceso a la red puede probar contraseñas sin freno.
    - **Fix:** `limit_req` en Nginx y bloqueo temporal tras N fallos; o fail2ban.
    - **Si se omite:** fuerza bruta viable en una red local.

15. **`job_download_root` puede devolver 500** (`app/services/files.py:76-79`)
    - **Qué es:** `relative_to(downloads_dir)` no captura `ValueError` si la ruta guardada está fuera.
    - **Problema:** una base manipulada o migrada mal rompe la página de archivos con 500 en vez de 404.
    - **Fix:** validar y devolver 404/409 con un mensaje claro.
    - **Si se omite:** un job antiguo puede tumbar la galería.

16. **Faltan pruebas de los riesgos anteriores** (`tests/`)
    - **Qué es:** no hay pruebas de XSS en toasts, `Content-Disposition`, auth obligatoria, CSRF, permisos, doble creación ni confirmación de borrado.
    - **Problema:** una regresión de seguridad no se detecta.
    - **Fix:** añadir pruebas de contrato y de navegador para esos casos.
    - **Si se omite:** la migración puede repetir los mismos fallos.

17. **`app/main.py` mezcla demasiadas responsabilidades** (`app/main.py:1-1140`)
    - **Qué es:** rutas HTML, auth, estado, paginación, plantillas, descargas, borrado y arranque de servicios.
    - **Problema:** el grafo lo confirma como nodo central (140 conexiones); es difícil de probar y de migrar.
    - **Fix:** separar en `api/`, `services/`, `security/`, `schemas/` y dejar la UI fuera del backend.
    - **Si se omite:** la migración arrastra el monolito.

18. **El endpoint de arranque de servicios sobra en producción** (`app/main.py:194-228`, `527-530`)
    - **Qué es:** la web puede lanzar `redis-server` y el worker.
    - **Problema:** en un LXC con systemd, duplica la gestión y deja que la web cree procesos; complica permisos y logs.
    - **Fix:** deshabilitarlo en producción; mostrar estado y dejar el arranque a systemd.
    - **Si se omite:** procesos duplicados y arranques no auditados.

19. **Código muerto o solo usado por pruebas** (`app/services/files.py:108-109`, `app/services/filtering.py:93-110`)
    - **Qué es:** `scan_download_progress` no se usa; `exclude_message_ids` y `message_ids_from_export` solo aparecen en pruebas.
    - **Problema:** mantiene superficie y ruido en el grafo.
    - **Fix:** borrar lo que no se use o moverlo a un helper de pruebas explícito.
    - **Si se omite:** la migración copia código innecesario.

20. **Docker corre como root y sin contraseña web** (`Dockerfile`, `docker-compose.yml`)
    - **Qué es:** la imagen no define `USER`; el compose no define `WEB_PASSWORD`.
    - **Problema:** ruta opcional con más privilegios y UI abierta.
    - **Fix:** usuario no root y `WEB_PASSWORD` obligatoria; o retirar Docker del camino principal.
    - **Si se omite:** el camino “opcional” es el más inseguro.

## Mejoras y capacidades que faltan

Estas no son fallos; son decisiones de producto para la migración:

- API `/api/v1` tipada, OpenAPI, errores consistentes y health/readiness.
- Filtros y paginación del historial de jobs (hoy solo lista).
- Detalle por archivo y “reintentar solo fallidos” (la tabla `DownloadFile` ya lo permite).
- Progreso honesto: encontrados, verificados, fallidos, bytes y velocidad solo si son fiables.
- Modo claro/oscuro, responsive real, foco visible, teclado y nombres accesibles.
- Página de ajustes de solo lectura (rutas, límites, worker, versión de tdl); no editar `.env` desde la web.
- Descarga de logs y eventos por job.
- Aviso de espacio libre antes de crear un job grande.
- Idempotencia de creación de jobs.
- TLS en Nginx y contraseña obligatoria; Redis solo en localhost.
- Un solo worker de API y uno de RQ, documentado; la UI debe funcionar al recargar y reconectar.

## No incluir ahora

- Pausar/reanudar de verdad: `tdl` no ofrece pausa; solo cancelar y reintentar.
- Multiusuario, roles o cuotas: no hay necesidad comprobada.
- WebSocket/SSE: el polling actual cubre el caso y es más simple.
- Editar configuración desde la UI: riesgo alto y poca ganancia.
- Límites de velocidad o programación: no verificado en la versión de `tdl` usada.
- Eliminar Redis/RQ: perdería la reanudación y la cancelación ya probadas.

## Veredicto

La lógica de descargas es valiosa y está bien probada en lo esencial, pero la capa web tiene fallos de seguridad reales (XSS, archivos inline, auth opcional, permisos) y un monolito difícil de migrar. Primero se corrigen esos puntos; después se separa Next.js/FastAPI conservando servicios, SQLite y Redis/RQ.

## No comprobado

- No se ejecutó `tdl` real ni se usó una sesión de Telegram.
- No se ejecutaron `test_app.py`, `test_scripts.py` ni `test_tdl.py` en Windows por `pty`/`termios` y shell.
- No se probó la app en un LXC Debian/Ubuntu ni con Nginx/TLS.
- No se midió rendimiento con miles de jobs; las conclusiones de escala se basan en el código.

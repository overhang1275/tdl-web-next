# Graph Report - tdl-web-next  (2026-10-26)

## Corpus Check
- Corpus is ~23,153 words - fits in a single context window. You may not need a graph.

## Summary
- 527 nodes · 1580 edges · 15 communities (14 shown, 1 thin omitted)
- Extraction: 88% EXTRACTED · 12% INFERRED · 0% AMBIGUOUS · INFERRED: 185 edges (avg confidence: 0.91)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- API web, jobs y plantillas
- Integración tdl y sesión
- Páginas y plantillas Jinja
- Eliminación segura y pruebas web
- Ciclo de trabajos y reanudación
- Worker, transferencias y filtros
- Despliegue Docker
- Archivos, descargas y rutas
- Chats, caché y búsqueda
- Logs y detalle de job
- Cliente JS, polling y toasts
- Script de actualización
- Diseño de descargas reanudables
- Validación de filtros
- Script de instalación

## God Nodes (most connected - your core abstractions)
1. `DownloadJob` - 56 edges
2. `JobStatus` - 42 edges
3. `TdlService` - 35 edges
4. `run_download_job()` - 33 edges
5. `safe_child()` - 26 edges
6. `make_job()` - 24 edges
7. `get()` - 22 edges
8. `retry_job()` - 21 edges
9. `TdlError` - 21 edges
10. `download_batch()` - 20 edges

## Surprising Connections (you probably didn't know these)
- `Registro verificable por archivo` --conceptually_related_to--> `verified_file()`  [INFERRED]
  docs/superpowers/specs/2026-10-05-resumable-downloads-design.md → app/services/transfers.py
- `Export fragmentado por rangos + publicacion atomica de export.json` --conceptually_related_to--> `write_json_atomic()`  [INFERRED]
  docs/superpowers/specs/2026-10-05-resumable-downloads-design.md → app/services/transfers.py
- `Invocacion RQ por lote de 100 mensajes` --conceptually_related_to--> `download_batch()`  [INFERRED]
  docs/superpowers/specs/2026-10-05-resumable-downloads-design.md → app/worker.py
- `Reconciliacion de jobs huerfanos como fallidos reanudables` --conceptually_related_to--> `sync_pending_jobs_with_queue()`  [INFERRED]
  docs/superpowers/specs/2026-10-05-resumable-downloads-design.md → app/services/jobs.py
- `test_job_delete_returns_before_wipe()` --uses--> `JobStage`  [INFERRED]
  tests/test_app.py → app/models.py

## Import Cycles
- 2-file cycle: `app/database.py -> app/models.py -> app/database.py`

## Hyperedges (group relationships)
- **Destinos de navegacion primaria (sidebar + bottom nav)** — app_templates_base_html_sidebar_nav, app_templates_base_html_bottom_nav, app_main_dashboard, app_main_chats_page, app_main_jobs_page, app_main_search_page, app_main_setup, app_main_notifications_page [EXTRACTED 1.00]
- **Detalle de job actualizado por polling htmx (status/events/logs)** — app_templates_job_detail_html, app_templates_job_detail_html_status_panel, app_templates_job_detail_html_events_panel, app_templates_job_detail_html_logs_panel, app_templates_partials_job_status_html, app_templates_partials_job_events_html, app_templates_partials_job_logs_html [EXTRACTED 1.00]
- **Flujo de login interactivo por codigo en Setup** — app_templates_setup_html, app_templates_setup_html_login_start_form, app_templates_partials_login_console_html, app_templates_partials_login_output_html, app_templates_partials_login_controls_html, app_templates_partials_login_controls_html_input_form, app_templates_partials_login_controls_html_cancel_form, app_main_setup_login_start, app_main_setup_login_input, app_main_setup_login_cancel, app_main_setup_login_output [EXTRACTED 1.00]

## Communities (15 total, 1 thin omitted)

### Community 0 - "API web, jobs y plantillas"
Cohesion: 0.07
Nodes (49): Base, init_db(), migrate_exports_to_chat_paths(), migrate_sqlite(), apply_template_prefill(), get_job_or_404(), job_cancel(), job_detail() (+41 more)

### Community 1 - "Integración tdl y sesión"
Cohesion: 0.06
Nodes (19): load_env_file(), Settings, setup_context(), system_status(), InteractiveLoginService, LoginSession, TdlCancelled, TdlError (+11 more)

### Community 2 - "Páginas y plantillas Jinja"
Cohesion: 0.06
Nodes (45): api_job_notifications(), basic_auth_ok(), chat_clean_downloads(), chats_page(), dashboard(), downloads_page(), http_exception_handler(), index() (+37 more)

### Community 3 - "Eliminación segura y pruebas web"
Cohesion: 0.05
Nodes (29): chat_display_name(), chat_search_text(), chat_type_group(), health(), job_delete(), paginate_chats(), paginate_downloads(), redis_ping() (+21 more)

### Community 4 - "Ciclo de trabajos y reanudación"
Cohesion: 0.14
Nodes (40): get_db(), DownloadJob, JobStatus, retry_job(), finish_job(), mark_terminal(), run_download_job(), make_job() (+32 more)

### Community 5 - "Worker, transferencias y filtros"
Cohesion: 0.14
Nodes (28): DownloadFile, job_download_root(), exclude_message_ids(), extract_text(), filter_export(), find_messages_container(), has_media_type(), message_id() (+20 more)

### Community 6 - "Despliegue Docker"
Cohesion: 0.08
Nodes (33): APP_ENV, COMMAND_TIMEOUT_SECONDS, DATA_DIR, DATABASE_URL, DOWNLOADS_DIR, EXPORTS_DIR, LOGS_DIR, REDIS_URL (+25 more)

### Community 7 - "Archivos, descargas y rutas"
Cohesion: 0.13
Nodes (24): chat_profile(), dashboard_metrics(), download_file(), preview_file(), count_downloaded_files(), directory_size(), downloaded_file_path(), file_kind() (+16 more)

### Community 8 - "Chats, caché y búsqueda"
Cohesion: 0.14
Nodes (15): chats_list(), chats_cache_path(), ChatsRefreshInProgress, delete_chats_cache(), read_chats_cache(), refresh_chats_cache(), write_chats_cache(), global_search() (+7 more)

### Community 9 - "Logs y detalle de job"
Cohesion: 0.17
Nodes (11): job_events_partial(), job_logs_partial(), append_deleted_job_log(), job_events(), job_log_path(), read_job_log(), form (POST /jobs/{id}/cancel), form.cleanup-form (POST /jobs/{id}/delete) (+3 more)

### Community 10 - "Cliente JS, polling y toasts"
Cohesion: 0.20
Nodes (10): chatsPanel(), initChatsPanel(), isRefreshUrl(), loadChats(), pollJobNotifications(), readKnownStatuses(), setRefreshButtons(), showChatsLoading() (+2 more)

### Community 11 - "Script de actualización"
Cohesion: 0.26
Nodes (15): apply_update(), ask_yes_no(), backup_before_update(), check_updates(), ensure_transfer_settings(), ensure_web_password(), ensure_wipe(), env_value() (+7 more)

### Community 12 - "Diseño de descargas reanudables"
Cohesion: 0.33
Nodes (10): Resumable Downloads Implementation Plan, Descargas reanudables (diseno aprobado), Export fragmentado por rangos + publicacion atomica de export.json, Reintentos acotados por mensaje (3 intentos, espera creciente), Timeout de inactividad durante descarga, Reconciliacion de jobs huerfanos como fallidos reanudables, Registro verificable por archivo, Descargas reanudables (mismo job) (+2 more)

### Community 14 - "Script de instalación"
Cohesion: 0.50
Nodes (7): ensure_transfer_settings(), get_env_value(), migrate_database(), prompt_default(), random_value(), set_env_value(), install.sh script

## Knowledge Gaps
- **15 isolated node(s):** `image`, `restart`, `volumes`, `build`, `restart` (+10 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 83 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `chats_list()` connect `Chats, caché y búsqueda` to `Integración tdl y sesión`, `Páginas y plantillas Jinja`, `Eliminación segura y pruebas web`?**
  _High betweenness centrality (0.004) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `run_download_job()` (e.g. with `DownloadJob` and `JobStage`) actually correct?**
  _`run_download_job()` has 5 INFERRED edges - model-reasoned connections that need verification._
- **What connects `image`, `restart`, `volumes` to the rest of the system?**
  _15 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `API web, jobs y plantillas` be split into smaller, more focused modules?**
  _Cohesion score 0.06611813106082869 - nodes in this community are weakly interconnected._
- **Should `Integración tdl y sesión` be split into smaller, more focused modules?**
  _Cohesion score 0.058384547848990345 - nodes in this community are weakly interconnected._
- **Should `Páginas y plantillas Jinja` be split into smaller, more focused modules?**
  _Cohesion score 0.057859703020993344 - nodes in this community are weakly interconnected._
- **Should `Eliminación segura y pruebas web` be split into smaller, more focused modules?**
  _Cohesion score 0.05333333333333334 - nodes in this community are weakly interconnected._
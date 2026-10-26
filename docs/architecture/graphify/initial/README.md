# Graphify — estado inicial

Este directorio conserva el mapa generado antes de la migración. No se sobrescribe con el
grafo final.

## Metadatos

- Herramienta: `graphifyy 0.9.95` (Python 3.15, entorno `.venv-graphify`).
- Copia analizada: `C:\Users\init\Desktop\tdl-web-next`.
- Commit: `34f74c6e84a55606214902ba04be1df2378d4123`.
- Comando: pipeline `/graphify .` con extracción AST y extracción semántica de 25 documentos.
- Alcance: 57 archivos (`32` código, `25` documentos), 23.153 palabras.
- Exclusiones: `.git`, `.venv*`, `graphify-out/`, `data/`, `.env*`, `node_modules`, builds,
  cachés, SQLite, sesiones de Telegram, descargas, exports y logs.
- Archivos sensibles detectados: ninguno (`skipped_sensitive: []`).

## Artefactos

| Archivo | Contenido |
|---|---|
| `graph.json` | 527 nodos, 1.580 relaciones, 15 comunidades |
| `GRAPH_REPORT.md` | Informe, god nodes, conexiones sorprendentes, preguntas |
| `graph.html` | Visualización interactiva generada (no revisada visualmente en esta sesión) |
| `labels.json` | Nombres de comunidades |
| `detect.json` | Corpus detectado y exclusiones |
| `analysis.json` | Comunidades, cohesión, god nodes, sorpresas |
| `semantic-chunk.json` | Extracción semántica de plantillas y documentación |

## Limitaciones

- El 12% de las relaciones son inferidas; las críticas se validaron leyendo el código.
- 133 aristas de imports apuntan a módulos externos que no son nodos del repositorio; el build
  las descarta.
- 89 aristas se colapsan al pasar de multigrafo a `DiGraph` (misma pareja con varias relaciones).
- 1 self-loop real: `mark_terminal()` se llama a sí mismo.
- El enlace RQ `enqueue_job` → `app.worker.run_download_job` es un string y no aparece como
  arista AST; se verificó en `app/services/jobs.py`.
- El corpus es pequeño; el grafo ayuda a navegar, no sustituye la lectura ni las pruebas.
- La visualización HTML se generó, pero no se abrió ni revisó visualmente en esta sesión.

## Reproducir

```powershell
$target = 'C:\Users\init\Desktop\tdl-web-next'
Set-Location $target
$env:GRAPHIFY_NO_AUTO_REFRESH = '1'
.\.venv-graphify\Scripts\python.exe -m pip install graphifyy==0.9.95
# El pipeline completo está documentado en la skill Graphify.
```

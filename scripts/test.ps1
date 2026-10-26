$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Push-Location $root
function Invoke-TestCompose {
  & docker compose -f deploy/docker/compose.test.yml @args
  if ($LASTEXITCODE -ne 0) { throw "Docker tests failed ($LASTEXITCODE)" }
}
try {
  Invoke-TestCompose build backend-tests frontend-tests playwright api worker web oidc
  Invoke-TestCompose run --rm backend-tests
  Invoke-TestCompose run --rm frontend-tests
  Invoke-TestCompose up -d --wait redis oidc api worker web
  Invoke-TestCompose run --rm playwright
} finally {
  & docker compose -f deploy/docker/compose.test.yml down --volumes --remove-orphans
  Pop-Location
}

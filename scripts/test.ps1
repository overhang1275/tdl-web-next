$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Push-Location $root
$runId = [guid]::NewGuid().ToString()
$projects = @()
$previous = @{}
foreach ($key in 'TDL_TEST_IMAGE_PREFIX', 'RQ_QUEUE_NAME', 'AUTHENTIK_ENABLED') {
  $previous[$key] = [Environment]::GetEnvironmentVariable($key)
}
$env:TDL_TEST_IMAGE_PREFIX = "tdl-check-$runId"
$env:RQ_QUEUE_NAME = "tdl-$runId-downloads"
$env:AUTHENTIK_ENABLED = 'false'
$project = "tdl-check-$runId-local"
function Invoke-TestCompose {
  & docker compose -p $project -f deploy/docker/compose.test.yml @args
  if ($LASTEXITCODE -ne 0) { throw "Docker tests failed ($LASTEXITCODE)" }
}
try {
  $projects += $project
  Invoke-TestCompose build backend-tests frontend-tests playwright web
  Invoke-TestCompose run --rm backend-tests
  Invoke-TestCompose run --rm frontend-tests
  Invoke-TestCompose up -d --no-build --wait postgres redis migrate bootstrap api worker web auth-control
  Invoke-TestCompose run --rm playwright
  $env:AUTHENTIK_ENABLED = 'true'
  $env:RQ_QUEUE_NAME = "tdl-$([guid]::NewGuid())-downloads"
  $project = "tdl-check-$runId-oidc"
  $projects += $project
  Invoke-TestCompose up -d --no-build --wait postgres redis oidc migrate bootstrap api worker web auth-control
  Invoke-TestCompose run --rm playwright
} finally {
  foreach ($project in $projects) {
    & docker compose -p $project -f deploy/docker/compose.test.yml down --volumes --remove-orphans
  }
  foreach ($key in $previous.Keys) {
    [Environment]::SetEnvironmentVariable($key, $previous[$key])
  }
  Pop-Location
}

param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$Rest
)

$root = Split-Path $PSScriptRoot -Parent
Push-Location (Join-Path $root "frontend")
try {
  & node node_modules/@playwright/test/cli.js @Rest
  exit $LASTEXITCODE
} finally {
  Pop-Location
}

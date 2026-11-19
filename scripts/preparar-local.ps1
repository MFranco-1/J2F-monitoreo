$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $root '.local-run'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null

$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    & python -m venv (Join-Path $root 'backend\.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Se requiere Python 3.11 o posterior para crear .venv.' }
}
& $python -m pip install -r (Join-Path $root 'backend\requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias Python.' }

$nodeDirectory = 'node-v22.22.3-win-x64'
$nodeRoot = Join-Path $runtime $nodeDirectory
$node = Join-Path $nodeRoot 'node.exe'
if (-not (Test-Path -LiteralPath $node)) {
    $archive = Join-Path $runtime "$nodeDirectory.zip"
    Invoke-WebRequest -UseBasicParsing -Uri "https://nodejs.org/dist/v22.22.3/$nodeDirectory.zip" -OutFile $archive
    Expand-Archive -LiteralPath $archive -DestinationPath $runtime -Force
}
$previousPath = $env:PATH
try {
    $env:PATH = "$nodeRoot;$previousPath"
    Push-Location (Join-Path $root 'frontend')
    try {
        & $node (Join-Path $nodeRoot 'node_modules\npm\bin\npm-cli.js') ci --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias Angular.' }
    } finally { Pop-Location }
} finally { $env:PATH = $previousPath }

$envPath = Join-Path $root '.env.local'
if (-not (Test-Path -LiteralPath $envPath)) {
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $environment = "DATABASE_URL=postgresql://USUARIO:CLAVE@HOST/BASE?sslmode=require&channel_binding=require`nFLASK_ENV=development`nHOST=127.0.0.1`nPORT=5000`nCORS_ORIGINS=http://localhost:4200,http://127.0.0.1:4200"
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        foreach ($key in @('SECRET_KEY', 'JWT_SECRET_KEY')) {
            $bytes = New-Object byte[] 48
            $rng.GetBytes($bytes)
            $value = [Convert]::ToBase64String($bytes)
            $environment += "`n$key=$value"
        }
    } finally { $rng.Dispose() }
    [IO.File]::WriteAllText($envPath, $environment + "`n", $utf8)
}
$settingsPath = Join-Path $runtime 'runtime.json'
if (-not (Test-Path -LiteralPath $settingsPath)) {
    $settings = @{databaseMode = 'remote'; nodeDirectory = $nodeDirectory}
    $settings | ConvertTo-Json | Set-Content -LiteralPath $settingsPath -Encoding UTF8
}
Write-Host 'Entorno preparado. Configura DATABASE_URL en .env.local antes de iniciar.'
Write-Host 'Para iniciar: powershell -ExecutionPolicy Bypass -File .\scripts\iniciar-local.ps1'

param([switch]$OpenBrowser)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $root '.local-run'
$settingsPath = Join-Path $runtime 'runtime.json'
if (-not (Test-Path -LiteralPath $settingsPath)) {
    throw 'Ejecuta primero: powershell -ExecutionPolicy Bypass -File .\scripts\preparar-local.ps1'
}
$settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
$envPath = Join-Path $root '.env.local'
if (-not (Test-Path -LiteralPath $envPath)) { throw 'Configura la conexión privada en .env.local.' }
foreach ($line in Get-Content -LiteralPath $envPath) {
    if ($line.Trim() -and -not $line.TrimStart().StartsWith('#')) {
        $pair = $line.Split('=', 2)
        if ($pair.Count -ne 2) { throw 'Linea invalida en .env.local' }
        [Environment]::SetEnvironmentVariable($pair[0].Trim(), $pair[1].Trim(), 'Process')
    }
}

function Test-LocalPort([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try { $client.Connect('127.0.0.1', $Port); return $true }
    catch { return $false }
    finally { $client.Dispose() }
}

function Start-LocalApp($Name, $Executable, $Arguments, $Directory, $Port, $Marker) {
    $pidPath = Join-Path $runtime "$Name.pid"
    if (Test-Path -LiteralPath $pidPath) {
        $savedId = [int](Get-Content -LiteralPath $pidPath -Raw).Trim()
        $existing = Get-CimInstance Win32_Process -Filter "ProcessId = $savedId"
        if ($existing -and $existing.ExecutablePath -eq $Executable -and $existing.CommandLine.Contains($Marker)) {
            Write-Host "$Name ya esta iniciado (PID $savedId)."
            return
        }
        Remove-Item -LiteralPath $pidPath
    }
    if (Test-LocalPort $Port) { throw "El puerto $Port esta ocupado por otro proceso." }
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -WorkingDirectory $Directory `
        -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime "$Name.log") `
        -RedirectStandardError (Join-Path $runtime "$Name.error.log") -PassThru
    Set-Content -LiteralPath $pidPath -Value $process.Id -Encoding ascii
    Write-Host "$Name iniciado (PID $($process.Id))."
}

function Wait-LocalHttp($Url, $Name, $TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
            if ($response.StatusCode -eq 200) { return }
        } catch { }
        $pidPath = Join-Path $runtime "$Name.pid"
        if (Test-Path -LiteralPath $pidPath) {
            $processId = [int](Get-Content -LiteralPath $pidPath -Raw).Trim()
            if (-not (Get-Process -Id $processId -ErrorAction SilentlyContinue)) {
                throw "$Name se detuvo. Revisa .local-run/$Name.error.log"
            }
        }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    throw "$Name no respondio a tiempo. Revisa los logs en .local-run."
}

if ($settings.databaseMode -ne 'remote') {
    $pgData = Join-Path $runtime 'pgdata'
    $pgCtl = Join-Path $settings.postgresBin 'pg_ctl.exe'
    & $pgCtl status -D $pgData *> $null
    if ($LASTEXITCODE -ne 0) {
        if (Test-LocalPort ([int]$env:PGPORT)) { throw "El puerto PostgreSQL $env:PGPORT esta ocupado." }
        $pgArguments = @('start', '-D', ('"{0}"' -f $pgData), '-l', ('"{0}"' -f (Join-Path $runtime 'postgres.log')), '-w')
        $pgProcess = Start-Process -FilePath $pgCtl -ArgumentList $pgArguments -WindowStyle Hidden -PassThru
        $pgProcess.WaitForExit()
        $pgProcess.Refresh()
        if ($pgProcess.ExitCode -ne 0) { throw 'No se pudo iniciar PostgreSQL. Revisa .local-run/postgres.log' }
    }
} else {
    Write-Host 'Base de datos remota configurada en .env.local.'
}

$python = [IO.Path]::GetFullPath((Join-Path $root 'backend/.venv/Scripts/python.exe'))
$backendEntry = [IO.Path]::GetFullPath((Join-Path $root 'backend/run.py'))
Start-LocalApp 'backend' $python ('"{0}"' -f $backendEntry) (Join-Path $root 'backend') 5000 $backendEntry
Wait-LocalHttp 'http://127.0.0.1:5000/api/catalogs' 'backend' 40

$node = [IO.Path]::GetFullPath((Join-Path $runtime "$($settings.nodeDirectory)/node.exe"))
$frontendEntry = [IO.Path]::GetFullPath((Join-Path $root 'frontend/node_modules/@angular/cli/bin/ng.js'))
$frontendArguments = ('"{0}" serve --host 127.0.0.1 --port 4200 --proxy-config proxy.conf.json' -f $frontendEntry)
$backendPort = $env:PORT
try {
    $env:PORT = '4200'
    Start-LocalApp 'frontend' $node $frontendArguments (Join-Path $root 'frontend') 4200 $frontendEntry
} finally { $env:PORT = $backendPort }
Wait-LocalHttp 'http://127.0.0.1:4200/' 'frontend' 180
Wait-LocalHttp 'http://127.0.0.1:4200/api/catalogs' 'frontend' 20
Write-Host 'Proyecto disponible en http://127.0.0.1:4200'
if ($settings.databaseMode -eq 'remote') {
    Write-Host 'Acceso: utiliza las credenciales existentes de la base remota.'
} else { Write-Host 'Credenciales: .local-run/acceso-local.txt' }
Write-Host 'Para detenerlo: .\scripts\detener-local.ps1'
if ($OpenBrowser) { Start-Process 'http://127.0.0.1:4200' }

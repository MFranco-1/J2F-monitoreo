$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $root '.local-run'
$settingsPath = Join-Path $runtime 'runtime.json'
if (-not (Test-Path -LiteralPath $settingsPath)) { throw 'No existe configuracion local.' }
$settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json

foreach ($name in @('frontend', 'backend')) {
    $pidPath = Join-Path $runtime "$name.pid"
    if (-not (Test-Path -LiteralPath $pidPath)) { continue }
    $savedId = [int](Get-Content -LiteralPath $pidPath -Raw).Trim()
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $savedId"
    $expected = if ($name -eq 'frontend') {
        Join-Path $runtime "$($settings.nodeDirectory)/node.exe"
    } else { Join-Path $root 'backend/.venv/Scripts/python.exe' }
    $marker = if ($name -eq 'frontend') {
        Join-Path $root 'frontend/node_modules/@angular/cli/bin/ng.js'
    } else { Join-Path $root 'backend/run.py' }
    $expected = [IO.Path]::GetFullPath($expected)
    $marker = [IO.Path]::GetFullPath($marker)
    if ($process) {
        if ($process.ExecutablePath -ne $expected -or -not $process.CommandLine.Contains($marker)) {
            throw "El PID de $name pertenece a otro proceso; no se detuvo."
        }
        & taskkill.exe /PID $savedId /T /F | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "No se pudo detener $name." }
    }
    Remove-Item -LiteralPath $pidPath
}

if ($settings.databaseMode -ne 'remote') {
    $pgData = Join-Path $runtime 'pgdata'
    $pgCtl = Join-Path $settings.postgresBin 'pg_ctl.exe'
    & $pgCtl status -D $pgData *> $null
    if ($LASTEXITCODE -eq 0) {
        $arguments = @('stop', '-D', ('"{0}"' -f $pgData), '-m', 'fast', '-w')
        $process = Start-Process -FilePath $pgCtl -ArgumentList $arguments -WindowStyle Hidden -PassThru
        $process.WaitForExit()
        $process.Refresh()
        if ($process.ExitCode -ne 0) { throw 'No se pudo detener PostgreSQL local.' }
    }
}
Write-Host 'Proyecto detenido. Los datos se conservan.'

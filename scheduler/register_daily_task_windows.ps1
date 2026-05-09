# Registra una tarea programada en Windows que ejecuta el carril diario
# del scraper cada 4 horas. Ejecutar este script como Administrador.
#
# Uso: .\register_daily_task_windows.ps1

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = "$ProjectRoot\.venv\Scripts\python.exe"
$Script = "$ProjectRoot\scheduler\run_update.py"
$LogFile = "$ProjectRoot\data\scheduler-daily.log"
$RotateScript = {
    if ((Get-Item $LogFile -ErrorAction SilentlyContinue).Length -gt 5MB) {
        $archive = $LogFile -replace '\.log$', "_$(Get-Date -Format 'yyyyMMdd').log"
        Rename-Item -Path $LogFile -NewName $archive -Force
    }
}

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -Command `"& { $RotateScript }; & '$Python' '$Script' --daily >> '$LogFile' 2>&1`"" `
    -WorkingDirectory $ProjectRoot

# Trigger: cada 4 horas empezando a las 06:00
$Trigger = New-ScheduledTaskTrigger -Once -At 6:00am `
    -RepetitionInterval (New-TimeSpan -Hours 4) `
    -RepetitionDuration (New-TimeSpan -Days 365)

$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask `
    -TaskName "LicitacionesSAP-Daily" `
    -Description "Actualizacion cada 4h del feed ATOM en vivo de PLACSP" `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Force

Write-Host "Tarea programada 'LicitacionesSAP-Daily' registrada (cada 4h)." -ForegroundColor Green
Write-Host "Verificar: Get-ScheduledTask -TaskName LicitacionesSAP-Daily"

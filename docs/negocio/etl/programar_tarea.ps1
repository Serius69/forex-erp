# Programa la generación periódica de reportes Kapitalya FX como tarea de Windows.
# Corre build.py (ingesta + datos + render + archivado versionado) automáticamente.
#
# Uso:
#   powershell -ExecutionPolicy Bypass -File programar_tarea.ps1 -Frecuencia Semanal -Hora 20:00
#   powershell -ExecutionPolicy Bypass -File programar_tarea.ps1 -Frecuencia Diario
#   powershell -ExecutionPolicy Bypass -File programar_tarea.ps1 -Eliminar     # quita la tarea
#
# No requiere admin (tarea del usuario actual).

param(
    [ValidateSet("Diario", "Semanal")]
    [string]$Frecuencia = "Semanal",
    [string]$Hora = "20:00",
    [switch]$Eliminar
)

$TaskName = "KapitalyaFX-Reportes"
$Py     = "E:\data\production\venv\Scripts\python.exe"
$Script = "E:\data\production\forex-erp\docs\negocio\etl\build.py"

if ($Eliminar) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Tarea '$TaskName' eliminada."
    return
}

if (-not (Test-Path $Py))     { Write-Error "No existe el intérprete: $Py"; return }
if (-not (Test-Path $Script)) { Write-Error "No existe el script: $Script"; return }

$action = New-ScheduledTaskAction -Execute $Py -Argument "`"$Script`""

if ($Frecuencia -eq "Diario") {
    $trigger = New-ScheduledTaskTrigger -Daily -At $Hora
} else {
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At $Hora
}

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "Genera y archiva los reportes de Kapitalya FX" `
    -Force | Out-Null

Write-Host "Tarea '$TaskName' programada: $Frecuencia a las $Hora."
Write-Host "Ver:    Get-ScheduledTask -TaskName $TaskName"
Write-Host "Correr: Start-ScheduledTask -TaskName $TaskName"
Write-Host "Quitar: powershell -File programar_tarea.ps1 -Eliminar"

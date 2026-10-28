# Instala (o reinstala) la tarea programada del recordatorio diario. Sin acentos (PowerShell 5.1).
# Horario:
#   - lunes a viernes: 7:30, 8:00 y 8:30;
#   - sabado y domingo, mas laxo: una vez a las 11:00;
#   - cualquier dia: 30 minutos despues de iniciar sesion o desbloquear el ordenador.
# Si hoy ya estan hechos 2 ejercicios, el aviso no sale (recordatorio.ps1).
# Para quitarla: quitar-recordatorio.ps1.
# Registra la ruta de este recordatorio.ps1 (programa\herramientas\),
# asi que tras mover la carpeta basta con volver a ejecutar este script.
$nombre = 'calculo-diario recordatorio'
$script = Join-Path $PSScriptRoot 'recordatorio.ps1'

$accion = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`""

$semana = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At '07:30'
$semana.Repetition = (New-ScheduledTaskTrigger -Once -At '07:30' `
    -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Minutes 61)).Repetition
$finde = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday, Sunday -At '11:00'

$usuario = "$env:USERDOMAIN\$env:USERNAME"
$inicio = New-ScheduledTaskTrigger -AtLogOn -User $usuario
$inicio.Delay = 'PT30M'
$clase = Get-CimClass -Namespace 'Root/Microsoft/Windows/TaskScheduler' -ClassName 'MSFT_TaskSessionStateChangeTrigger'
$desbloqueo = New-CimInstance -CimClass $clase -ClientOnly
$desbloqueo.StateChange = 8   # desbloqueo de la sesion (al volver de la suspension)
$desbloqueo.UserId = $usuario
$desbloqueo.Delay = 'PT30M'
$desbloqueo.Enabled = $true

$principal = New-ScheduledTaskPrincipal -UserId $usuario -LogonType Interactive -RunLevel Limited
$ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $nombre -Action $accion -Trigger $semana, $finde, $inicio, $desbloqueo `
    -Principal $principal -Settings $ajustes -Force `
    -Description 'Aviso diario para practicar calculo (calculo-diario). No sale si hoy ya esta hecho.' | Out-Null
Write-Output "Tarea '$nombre' instalada."

# Quita la tarea programada del recordatorio diario. Sin acentos (PowerShell 5.1).
$nombre = 'calculo-diario recordatorio'
if (Get-ScheduledTask -TaskName $nombre -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $nombre -Confirm:$false
    Write-Output "Tarea '$nombre' quitada."
} else {
    Write-Output "No habia ninguna tarea '$nombre'."
}

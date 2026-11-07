# Crea el acceso "Calculo diario" en el menu Inicio. Sin acentos (PowerShell 5.1).
# Abre la ventana directamente con pythonw: sin ninguna consola, ni el instante de Practicar.bat.
# Si la ventana no abre, ella misma relanza Practicar.bat reparar (--respaldo-reparar).
# Para quitarlo: borrar el acceso del menu Inicio. Tras mover la carpeta, volver a ejecutar este script.
$programa = Split-Path -Parent $PSScriptRoot
$raiz = Split-Path -Parent $programa
$pythonw = Join-Path $raiz '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw)) {
    Write-Output 'Falta el entorno: abre una vez Practicar.bat (lo prepara) y vuelve a ejecutar este script.'
    exit 1
}
$menu = [Environment]::GetFolderPath('Programs')
$ruta = Join-Path $menu 'Calculo diario.lnk'
$acceso = (New-Object -ComObject WScript.Shell).CreateShortcut($ruta)
$acceso.TargetPath = $pythonw
$acceso.Arguments = "`"$(Join-Path $programa 'practica.py')`" ventana --respaldo-reparar"
$acceso.WorkingDirectory = $raiz
$acceso.Description = 'Sesion de calculo de hoy, sin consola'
$acceso.Save()
Write-Output "Acceso creado: $ruta"

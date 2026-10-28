@echo off
rem Doble clic: quita el aviso diario (tarea programada "calculo-diario recordatorio").
rem Para volver a ponerlo: programa\herramientas\instalar-recordatorio.ps1 (ver README).
chcp 65001 >nul <nul
rem Este .bat vive en otras-opciones\; se trabaja desde la raiz.
cd /d "%~dp0.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\programa\herramientas\quitar-recordatorio.ps1"
pause
exit /b 0

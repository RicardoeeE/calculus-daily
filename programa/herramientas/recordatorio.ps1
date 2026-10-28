# Recordatorio diario de calculo-diario.
# Lo lanza la tarea programada 'calculo-diario recordatorio' (instalar-recordatorio.ps1).
# Si hoy ya hay 2 ejercicios o mas, no hace nada. Si no, pregunta y abre Practicar.bat.
# Como mucho 3 avisos al dia, nunca dos en menos de 25 minutos, y 'Hoy no' (Cancelar)
# lo silencia hasta manana. El estado va en %LOCALAPPDATA%\calculo-diario\estado.txt.
# Sin acentos: PowerShell 5.1 lee los .ps1 sin BOM como ANSI.
#
#   -Prueba        ensena el aviso aunque hoy este hecho; no abre nada ni cuenta avisos
#   -SoloDecidir   no ensena nada: escribe la decision (para las pruebas). Con -Respuesta
#                  6 (Si), 7 (No), 2 (Cancelar = hoy no) o -1 (se cerro solo) simula el clic;
#                  -Carpeta, -Ahora, -Racha, -Python y -Guion sustituyen lo de verdad.
param(
    [switch]$Prueba,
    [switch]$SoloDecidir,
    [int]$Respuesta = 7,
    [string]$Carpeta = (Join-Path $env:LOCALAPPDATA 'calculo-diario'),
    [string]$Ahora = '',
    [string]$Racha = '',
    [int]$TopeRacha = 20,
    [string]$Python = '',
    [string]$Guion = ''
)

$MaxAvisos = 3
$MinutosEntreAvisos = 25

# Este script vive en programa\herramientas; la raiz es dos carpetas arriba.
$programa = Split-Path -Parent $PSScriptRoot
$raiz = Split-Path -Parent $programa
$python = if ($Python) { $Python } else { Join-Path $raiz '.venv\Scripts\python.exe' }
$guion = if ($Guion) { $Guion } else { Join-Path $programa 'practica.py' }
$bat = Join-Path $raiz 'Practicar.bat'
$momento = if ($Ahora) { [datetime]::Parse($Ahora) } else { Get-Date }
$hoy = $momento.ToString('yyyy-MM-dd')
$rutaEstado = Join-Path $Carpeta 'estado.txt'

function Leer-Estado {
    $e = @{ fecha = ''; avisos = 0; ultimo = ''; hoyno = '' }
    if (Test-Path -LiteralPath $rutaEstado) {
        foreach ($linea in (Get-Content -LiteralPath $rutaEstado -ErrorAction SilentlyContinue)) {
            $partes = $linea -split '=', 2
            if ($partes.Count -eq 2) { $e[$partes[0].Trim()] = $partes[1].Trim() }
        }
    }
    if ($e.fecha -ne $hoy) { $e.fecha = $hoy; $e.avisos = 0 }
    $e.avisos = [int]$e.avisos
    return $e
}

function Guardar-Estado($e) {
    New-Item -ItemType Directory -Force -Path $Carpeta | Out-Null
    $texto = "fecha=$($e.fecha)`r`navisos=$($e.avisos)`r`nultimo=$($e.ultimo)`r`nhoyno=$($e.hoyno)"
    Set-Content -LiteralPath $rutaEstado -Value $texto -Encoding ascii
}

# La decision, separada para poder probarla: 'avisar' o el motivo para no hacerlo.
function Decidir($e, $hecho) {
    if ($hecho) { return 'hecho' }
    if ($e.hoyno -eq $hoy) { return 'hoy-no' }
    if ($e.avisos -ge $MaxAvisos) { return 'tope' }
    if ($e.ultimo) {
        try {
            if (($momento - [datetime]::Parse($e.ultimo)).TotalMinutes -lt $MinutosEntreAvisos) { return 'reciente' }
        } catch { }
    }
    return 'avisar'
}

# `practica.py racha` con tope de tiempo: si no responde, aviso sin racha.
function Leer-Racha {
    if ($Racha) {   # pruebas: 'hecho:dias' (p. ej. '0:5') o 'ninguna'
        if ($Racha -eq 'ninguna') { return $null }
        $x = $Racha -split ':'
        return [pscustomobject]@{ hecho_hoy = ($x[0] -eq '1'); racha = [int]$x[1] }
    }
    if (-not (Test-Path -LiteralPath $python)) { return $null }
    $salida = [System.IO.Path]::GetTempFileName()
    try {
        $p = Start-Process -FilePath $python -ArgumentList @("`"$guion`"", 'racha') `
            -WorkingDirectory $raiz -RedirectStandardOutput $salida -WindowStyle Hidden -PassThru
        if (-not $p.WaitForExit($TopeRacha * 1000)) {
            try { $p.Kill() } catch { }
            return $null
        }
        return (Get-Content -LiteralPath $salida -Raw | ConvertFrom-Json)
    } catch {
        return $null
    } finally {
        Remove-Item -LiteralPath $salida -ErrorAction SilentlyContinue
    }
}

$a = [char]0x00E1; $i = [char]0x00ED; $preg = [char]0x00BF

function Texto-Aviso($dias) {
    if ($null -eq $dias) {
        $lineaRacha = 'Hoy con 2 ya cuenta.'
    } elseif ($dias -eq 1) {
        $lineaRacha = "Llevas 1 d${i}a. Hoy con 2 ya cuenta."
    } elseif ($dias -gt 1) {
        $lineaRacha = "Llevas $dias d${i}as. Hoy con 2 ya cuenta."
    } else {
        $lineaRacha = 'Hoy con 2 ya cuenta.'
    }
    return "Hoy toca c${a}lculo: 5 ejercicios (o 2 el d${i}a m${i}nimo).`n$lineaRacha`n`n${preg}Empiezas ahora?`n`nS${i}: empezar.   No: m${a}s tarde.   Cancelar: hoy no."
}

$estado = Leer-Estado
$datosRacha = Leer-Racha
$hecho = $false
$dias = $null
if ($null -ne $datosRacha) {
    $hecho = [bool]$datosRacha.hecho_hoy
    $dias = [int]$datosRacha.racha
}
$decision = if ($Prueba) { 'avisar' } else { Decidir $estado $hecho }
$texto = Texto-Aviso $dias

if ($decision -ne 'avisar') {
    if ($SoloDecidir) { Write-Output "$decision|$texto" }
    exit 0
}

if (-not $Prueba) {
    $estado.avisos = $estado.avisos + 1
    $estado.ultimo = $momento.ToString('s')
    Guardar-Estado $estado
}

if ($SoloDecidir) {
    $r = $Respuesta
} else {
    # 3 = Si/No/Cancelar, 64 = informacion, 4096 = siempre delante. Se cierra sola a los 10 minutos.
    $r = (New-Object -ComObject WScript.Shell).Popup($texto, 600, 'calculo-diario', 3 + 64 + 4096)
}

if ($r -eq 2 -and -not $Prueba) {
    $estado.hoyno = $hoy
    Guardar-Estado $estado
}
if ($SoloDecidir) {
    Write-Output "avisar|$texto"
    exit 0
}
if ($r -eq 6 -and -not $Prueba) {
    Start-Process -FilePath $bat -WorkingDirectory $raiz
}

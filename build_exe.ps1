$ErrorActionPreference = "Stop"
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectDir

python -m pip install -r requirements.txt
python -m pip install pyinstaller==6.11.1

foreach ($oldExeName in @("NaraAssistant.exe", "ZetaAssistant.exe")) {
    $oldExePath = Join-Path $projectDir "dist\$oldExeName"
    if (Test-Path -LiteralPath $oldExePath) {
        Remove-Item -LiteralPath $oldExePath -Force
    }
}

foreach ($oldBuildName in @("NaraAssistant", "ZetaAssistant")) {
    $oldBuildPath = Join-Path $projectDir "build\$oldBuildName"
    if (Test-Path -LiteralPath $oldBuildPath) {
        Remove-Item -LiteralPath $oldBuildPath -Recurse -Force
    }
}

foreach ($oldSpecName in @("NaraAssistant.spec", "ZetaAssistant.spec")) {
    $oldSpecPath = Join-Path $projectDir $oldSpecName
    if (Test-Path -LiteralPath $oldSpecPath) {
        Remove-Item -LiteralPath $oldSpecPath -Force
    }
}

python -m PyInstaller `
    --clean `
    --noconfirm `
    --onefile `
    --windowed `
    --name MikaAssistant `
    --hidden-import settings_gui `
    --hidden-import tkinter `
    --hidden-import edge_tts `
    --hidden-import pygame `
    --hidden-import pyttsx3.drivers `
    --hidden-import pyttsx3.drivers.sapi5 `
    --hidden-import comtypes.stream `
    tray_assistant.py

Copy-Item -LiteralPath (Join-Path $projectDir "commands.json") -Destination (Join-Path $projectDir "dist\commands.json") -Force

Write-Host ""
Write-Host "EXE selesai dibuat:"
Write-Host (Join-Path $projectDir "dist\MikaAssistant.exe")
Write-Host ""
Write-Host "Catatan: commands.json harus tetap di folder dist agar setting mudah diedit."

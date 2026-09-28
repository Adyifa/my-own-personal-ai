$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$startupDir = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDir "Mika Voice Assistant.lnk"
$oldShortcutPath = Join-Path $startupDir "Nara Voice Assistant.lnk"
$oldZetaShortcutPath = Join-Path $startupDir "Zeta Voice Assistant.lnk"
$exePath = Join-Path $projectDir "dist\MikaAssistant.exe"

if (Test-Path -LiteralPath $oldShortcutPath) {
    Remove-Item -LiteralPath $oldShortcutPath -Force
}
if (Test-Path -LiteralPath $oldZetaShortcutPath) {
    Remove-Item -LiteralPath $oldZetaShortcutPath -Force
}

if (Test-Path -LiteralPath $exePath) {
    $targetPath = $exePath
    $arguments = ""
    $workingDirectory = Split-Path -Parent $exePath
} else {
    $targetPath = Join-Path $env:WINDIR "pyw.exe"
    $scriptPath = Join-Path $projectDir "tray_assistant.py"
    if (-not (Test-Path -LiteralPath $targetPath)) {
        $targetPath = "pythonw.exe"
    }
    $arguments = "`"$scriptPath`""
    $workingDirectory = $projectDir
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $targetPath
$shortcut.Arguments = $arguments
$shortcut.WorkingDirectory = $workingDirectory
$shortcut.IconLocation = "$env:SystemRoot\System32\SHELL32.dll,220"
$shortcut.Save()

Write-Host "Startup shortcut dibuat:"
Write-Host $shortcutPath

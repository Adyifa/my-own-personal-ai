$startupDir = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDir "Mika Voice Assistant.lnk"
$oldShortcutPath = Join-Path $startupDir "Nara Voice Assistant.lnk"
$oldZetaShortcutPath = Join-Path $startupDir "Zeta Voice Assistant.lnk"

if (Test-Path -LiteralPath $shortcutPath) {
    Remove-Item -LiteralPath $shortcutPath -Force
    Write-Host "Startup shortcut dihapus:"
    Write-Host $shortcutPath
} else {
    Write-Host "Startup shortcut tidak ditemukan."
}

if (Test-Path -LiteralPath $oldShortcutPath) {
    Remove-Item -LiteralPath $oldShortcutPath -Force
    Write-Host "Startup shortcut lama juga dihapus:"
    Write-Host $oldShortcutPath
}

if (Test-Path -LiteralPath $oldZetaShortcutPath) {
    Remove-Item -LiteralPath $oldZetaShortcutPath -Force
    Write-Host "Startup shortcut lama juga dihapus:"
    Write-Host $oldZetaShortcutPath
}

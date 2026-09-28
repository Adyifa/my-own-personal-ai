@echo off
if exist "%~dp0dist\MikaAssistant.exe" (
    start "" "%~dp0dist\MikaAssistant.exe"
) else (
    where pyw >nul 2>nul
    if %errorlevel%==0 (
        start "" pyw "%~dp0tray_assistant.py"
    ) else (
        start "" pythonw "%~dp0tray_assistant.py"
    )
)

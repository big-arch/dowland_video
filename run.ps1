# Запуск MediaGrab на Windows.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Создаю виртуальное окружение…"
    py -m venv .venv
}

Write-Host "Устанавливаю зависимости…"
& .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .\.venv\Scripts\python.exe -m pip install --quiet -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item .env.example .env
    Write-Host ""
    Write-Host "Создан .env. Впишите BOT_TOKEN от @BotFather и запустите снова:"
    Write-Host "  notepad .env"
    Write-Host "  .\run.ps1"
    exit 1
}

& .\.venv\Scripts\python.exe -m mediagrab --check
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Проверка не прошла — исправьте замечания выше."
    exit $LASTEXITCODE
}

& .\.venv\Scripts\python.exe -m mediagrab

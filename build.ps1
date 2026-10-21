$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $heartPath = (Resolve-Path -LiteralPath './heart.png').Path
    $calibrationPath = (Resolve-Path -LiteralPath './calibration.json').Path
    python -m PyInstaller --noconfirm --onefile --windowed --name XiaozhanLikeAssistant --add-data "$heartPath;." --add-data "$calibrationPath;." app.py
    if ($LASTEXITCODE -ne 0) { throw 'EXE build failed.' }
    Copy-Item -LiteralPath './dist/XiaozhanLikeAssistant.exe' -Destination './dist/识图点赞助手.exe' -Force
    Write-Output '构建完成：dist/识图点赞助手.exe'
} finally {
    Pop-Location
}

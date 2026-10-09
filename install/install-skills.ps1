# Підключає скіли з папки skills/ до Claude Code та OpenAI Codex (папка проєкту і папка користувача).
# Запуск із кореня репозиторію: .\install\install-skills.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$src  = Join-Path $root "skills"
$targets = @(
    (Join-Path $root ".claude\skills"),
    (Join-Path $root ".agents\skills"),
    (Join-Path $HOME ".claude\skills"),
    (Join-Path $HOME ".agents\skills")
)
foreach ($t in $targets) {
    New-Item -ItemType Directory -Force -Path $t | Out-Null
    Get-ChildItem -Directory $src | ForEach-Object {
        $dst = Join-Path $t $_.Name
        if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
        Copy-Item -Recurse $_.FullName $dst
    }
    Write-Host "Скіли скопійовано в $t"
}
Write-Host "Готово. Перезапустіть агента, щоб він побачив нові скіли."

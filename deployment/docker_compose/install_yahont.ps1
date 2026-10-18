# Установщик Yahont CE для Windows.
#
# Скачивает репозиторий Yahont CE, создаёт файл .env с секретом входа и
# запускает Yahont в Docker Compose. Образы собираются из исходного кода, поэтому
# первая сборка занимает несколько минут. Требуется Docker Desktop для Windows.
#
#   powershell -ExecutionPolicy Bypass -File install_yahont.ps1
#   powershell -ExecutionPolicy Bypass -File install_yahont.ps1 -Lite
#
# Удалённый запуск из PowerShell:
#   irm https://yahont.ai/install_yahont.ps1 | iex
#   & ([scriptblock]::Create((irm https://yahont.ai/install_yahont.ps1))) -Lite
#
# Параметры:
#   -Lite             режим «Лайт»: чат без индексации документов (меньше 1 ГБ памяти)
#   -Dir DIR          каталог установки (по умолчанию .\yahont-ce в текущем каталоге)
#   -Ref REF          ветка или тег репозитория (по умолчанию основная ветка)
#   -Project NAME     имя проекта Docker Compose (по умолчанию yahont): нужно, чтобы
#                     держать две установки рядом
#   -BindLocal PORT   слушать только 127.0.0.1:PORT: для сервера с обратным прокси
#   -NoStart          только подготовить файлы, не запускать контейнеры
#   -Help             эта справка
#
# Переменная окружения:
#   YAHONT_REPO_URL  адрес репозитория (по умолчанию GitHub pipedude/yahont-ce)
#
# Скрипт ничего не устанавливает в систему и не требует прав администратора.
# Существующий файл .env он не перезаписывает.

param(
    [switch]$Lite,
    [string]$Dir = "yahont-ce",
    [string]$Ref = "",
    [string]$Project = "",
    [string]$BindLocal = "",
    [switch]$NoStart,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

$RepoUrl = if ($env:YAHONT_REPO_URL) { $env:YAHONT_REPO_URL } else { "https://github.com/pipedude/yahont-ce.git" }

function Write-Step { param([string]$Message) Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Message) Write-Host "OK  $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "!   $Message" -ForegroundColor Yellow }
function Exit-Error {
    param([string]$Message)
    Write-Host "Ошибка: $Message" -ForegroundColor Red
    exit 1
}

function Show-Help {
    Write-Host @"
Установщик Yahont CE для Windows.

  powershell -ExecutionPolicy Bypass -File install_yahont.ps1
  powershell -ExecutionPolicy Bypass -File install_yahont.ps1 -Lite

Удалённый запуск из PowerShell:
  irm https://yahont.ai/install_yahont.ps1 | iex
  & ([scriptblock]::Create((irm https://yahont.ai/install_yahont.ps1))) -Lite

Параметры:
  -Lite             режим «Лайт»: чат без индексации документов (меньше 1 ГБ памяти)
  -Dir DIR          каталог установки (по умолчанию .\yahont-ce в текущем каталоге)
  -Ref REF          ветка или тег репозитория (по умолчанию основная ветка)
  -Project NAME     имя проекта Docker Compose (по умолчанию yahont): нужно, чтобы
                    держать две установки рядом
  -BindLocal PORT   слушать только 127.0.0.1:PORT: для сервера с обратным прокси
  -NoStart          только подготовить файлы, не запускать контейнеры
  -Help             эта справка

Переменная окружения:
  YAHONT_REPO_URL  адрес репозитория (по умолчанию GitHub pipedude/yahont-ce)
"@
}

if ($Help) {
    Show-Help
    exit 0
}

if ($Project) {
    if ($Project -cnotmatch '^[a-z0-9][a-z0-9_-]*$') {
        Exit-Error "имя проекта $Project должно начинаться с латинской буквы или цифры и содержать только строчные латинские буквы, цифры, «-» и «_»"
    }
}

if ($BindLocal) {
    $bindPortNumber = 0
    if (-not [int]::TryParse($BindLocal, [ref]$bindPortNumber) -or $bindPortNumber -lt 1 -or $bindPortNumber -gt 65535) {
        Exit-Error "порт $BindLocal должен быть числом от 1 до 65535"
    }
}

# Выполняет внешнюю команду и завершает скрипт с сообщением при ненулевом коде.
function Invoke-Native {
    param([scriptblock]$Command, [string]$ErrorMessage)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Command
        if ($LASTEXITCODE -ne 0) { Exit-Error $ErrorMessage }
    } finally { $ErrorActionPreference = $prev }
}

# Пишет текст в UTF-8 без BOM. .NET ищет относительный путь от каталога
# процесса, а не от текущего каталога PowerShell: сначала разрешаем путь.
function Write-TextFile {
    param([string]$Path, [string]$Content)
    $absPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path)
    [System.IO.File]::WriteAllText($absPath, $Content, (New-Object System.Text.UTF8Encoding($false)))
}

# Заменяет строку KEY=... на KEY=VALUE или дописывает её в конец .env.
# Файл читается и пишется в UTF-8 без BOM: env.template содержит кириллицу.
function Set-EnvFileValue {
    param([string]$Path, [string]$Key, [string]$Value)
    $lines = Get-Content $Path -Encoding UTF8
    $found = $false
    $result = foreach ($line in $lines) {
        if ($line -match "^${Key}=") {
            "${Key}=${Value}"
            $found = $true
        } else {
            $line
        }
    }
    if (-not $found) { $result += "${Key}=${Value}" }
    Write-TextFile $Path (($result -join "`n") + "`n")
}

# Значение KEY из .env (последняя незакомментированная строка) или пустая строка.
function Get-EnvFileValue {
    param([string]$Path, [string]$Key)
    $match = Select-String -Path $Path -Pattern "^${Key}=(.*)$" | Select-Object -Last 1
    if ($match) { return $match.Matches[0].Groups[1].Value.Trim().Trim('"', "'") }
    return ""
}

function New-SecureSecret {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return ($bytes | ForEach-Object { $_.ToString("x2") }) -join ''
}

# Истина, если на TCP-порту кто-то слушает.
function Test-PortBusy {
    param([int]$Port)
    $listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
    return [bool]($listeners | Where-Object { $_.Port -eq $Port })
}

# Истина, если версия docker compose не меньше $Minimum (формат 2.24.4). Если
# версию определить нельзя, проверка пропускается.
function Test-ComposeAtLeast {
    param([string]$Minimum)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { $raw = (docker compose version --short 2>$null | Select-Object -First 1) } finally { $ErrorActionPreference = $prev }
    if (-not $raw) { return $true }
    $parsed = $null
    if (-not [version]::TryParse(($raw -replace '^v', '' -replace '[-+].*$', ''), [ref]$parsed)) { return $true }
    return $parsed -ge [version]$Minimum
}

# --- Проверки окружения ------------------------------------------------------

Write-Step "Проверяю окружение"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Exit-Error "не найден git. Установите его и запустите скрипт снова."
}

if (-not $NoStart) {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Exit-Error "не найден docker. Установите Docker Desktop: https://docs.docker.com/desktop/setup/install/windows-install/"
    }
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $null = docker compose version 2>$null
        $composeOk = ($LASTEXITCODE -eq 0)
        $null = docker info 2>$null
        $daemonOk = ($LASTEXITCODE -eq 0)
    } finally { $ErrorActionPreference = $prev }
    if (-not $composeOk) {
        Exit-Error "не найден плагин Docker Compose (команда 'docker compose'). Обновите Docker Desktop."
    }
    if (-not $daemonOk) {
        Exit-Error "Docker не отвечает. Запустите Docker Desktop и дождитесь его готовности."
    }
    Write-Ok "Docker и Docker Compose доступны"
    if ($BindLocal -and -not (Test-ComposeAtLeast "2.24.4")) {
        Exit-Error "для -BindLocal нужен Docker Compose 2.24.4 или новее. Обновите Docker Desktop."
    }
}

# Минимум из документации: 10 ГБ для стандартного режима, 2 ГБ для лайта.
if (-not $NoStart) {
    $memGB = 0
    try {
        $memGB = [math]::Round(
            (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
    } catch { }
    if ($memGB -gt 0) {
        if ($Lite -and $memGB -lt 2) {
            Write-Warn "Памяти ${memGB} ГБ. Для режима «Лайт» нужно не меньше 2 ГБ."
        } elseif (-not $Lite -and $memGB -lt 10) {
            Write-Warn "Памяти ${memGB} ГБ. Для стандартного режима нужно не меньше 10 ГБ (или режим -Lite)."
        }
    }
}

# --- Репозиторий ---------------------------------------------------------------

Write-Step "Получаю Yahont CE в каталог $Dir"

if (Test-Path (Join-Path $Dir ".git")) {
    Invoke-Native { git -C $Dir pull --ff-only } `
        "не удалось обновить $Dir. Проверьте локальные изменения."
    if ($Ref) {
        Invoke-Native { git -C $Dir checkout $Ref } "не удалось перейти на $Ref."
    }
} elseif ((Test-Path $Dir) -and ((Get-ChildItem $Dir -Force | Measure-Object).Count -gt 0)) {
    Exit-Error "каталог $Dir уже есть и это не репозиторий Yahont CE. Укажите другой через -Dir."
} elseif ($Ref) {
    Invoke-Native { git clone --depth 1 --branch $Ref $RepoUrl $Dir } `
        "не удалось скачать $RepoUrl."
} else {
    Invoke-Native { git clone --depth 1 $RepoUrl $Dir } "не удалось скачать $RepoUrl."
}
Write-Ok "Репозиторий готов"

$ComposeDir = Join-Path $Dir "deployment\docker_compose"
if (-not (Test-Path (Join-Path $ComposeDir "docker-compose.yml"))) {
    Exit-Error "в $ComposeDir нет docker-compose.yml. Это не репозиторий Yahont CE?"
}
Push-Location $ComposeDir

try {
    # --- Файл .env ------------------------------------------------------------------

    Write-Step "Готовлю файл .env"

    if (Test-Path ".env") {
        Write-Ok "Файл .env уже есть, оставляю как есть"
    } else {
        Copy-Item "env.template" ".env"
        Write-Ok "Создан .env из env.template"
    }

    if (Select-String -Path ".env" -Pattern '^USER_AUTH_SECRET=("")?$' -Quiet) {
        Set-EnvFileValue ".env" "USER_AUTH_SECRET" (New-SecureSecret)
        Write-Ok "Создан USER_AUTH_SECRET (без него сервер не запускается)"
    }

    if ($Project) {
        Set-EnvFileValue ".env" "COMPOSE_PROJECT_NAME" $Project
        Write-Ok "Имя проекта Docker Compose: $Project"
    }

    if ($BindLocal) {
        if (Test-Path "docker-compose.override.yml") {
            Write-Warn "Файл docker-compose.override.yml уже есть, оставляю как есть. Проверьте в нём привязку порта."
        } else {
            # !override заменяет порты из docker-compose.yml, а не добавляет к ним.
            $overrideYaml = "services:`n  nginx:`n    ports: !override`n      - `"127.0.0.1:${BindLocal}:80`"`n"
            Write-TextFile "docker-compose.override.yml" $overrideYaml
            Write-Ok "Создан docker-compose.override.yml: Yahont слушает только 127.0.0.1:$BindLocal"
        }
    }

    if ($Lite) {
        # Пустой профиль отключает объектное хранилище из env.template: лайт
        # хранит файлы в PostgreSQL. COMPOSE_FILE подключает файл режима «Лайт»
        # ко всем следующим командам docker compose в этом каталоге. Когда
        # COMPOSE_FILE задан, Compose сам не подхватывает docker-compose.override.yml,
        # поэтому он указан в списке явно.
        # Разделитель списка в COMPOSE_FILE зависит от ОС: «;» на Windows, «:» на
        # Linux и macOS (pwsh есть и там).
        $composeFileList = @("docker-compose.yml", "docker-compose.lite.yml")
        if (Test-Path "docker-compose.override.yml") { $composeFileList += "docker-compose.override.yml" }
        Set-EnvFileValue ".env" "COMPOSE_PROFILES" ""
        Set-EnvFileValue ".env" "COMPOSE_FILE" ($composeFileList -join [IO.Path]::PathSeparator)
        Write-Ok "Включён режим «Лайт»"
    }

    # --- Запуск ----------------------------------------------------------------------

    $workDir = (Get-Location).Path

    if (-not $NoStart) {
        # Порты проверяем только на свежем запуске: у работающей установки они заняты ею же.
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try { $running = docker compose ps -q 2>$null } finally { $ErrorActionPreference = $prev }
        if (-not $running) {
            if ($BindLocal) {
                $portsToCheck = @([int]$BindLocal)
            } else {
                $portHttp = Get-EnvFileValue ".env" "HOST_PORT_80"
                $portApp = Get-EnvFileValue ".env" "HOST_PORT"
                $portsToCheck = @($(if ($portHttp) { [int]$portHttp } else { 80 }), $(if ($portApp) { [int]$portApp } else { 3000 }))
            }
            foreach ($port in $portsToCheck) {
                if (Test-PortBusy $port) {
                    Write-Warn "Файлы подготовлены в $workDir."
                    Exit-Error @"
порт $port уже занят: на компьютере может работать другая программа.
    Варианты:
      1. Привязать Yahont к 127.0.0.1 и поставить перед ним обратный прокси:
         запустите скрипт с параметром -BindLocal ПОРТ (см. docs/reverse-proxy.md).
      2. Указать другие порты в $workDir\.env: HOST_PORT_80 и HOST_PORT.
    Потом запустите: cd $workDir; docker compose up -d
"@
                }
            }
        }
        Write-Step "Скачиваю образы из Docker Hub и запускаю Yahont. Время первого запуска зависит от канала связи."
        Invoke-Native { docker compose pull } "docker compose pull не удался."
        Invoke-Native { docker compose up -d } "docker compose up не удался."
        Write-Ok "Контейнеры запущены"
    } else {
        Write-Warn "Запуск пропущен (-NoStart)"
    }

    # --- Что дальше ------------------------------------------------------------------

    Write-Host ""
    if (-not $NoStart) {
        Write-Host "Готово." -ForegroundColor Green
        Write-Host ""
        if ($BindLocal) {
            Write-Host "Адрес: http://127.0.0.1:$BindLocal (только на этом компьютере)."
            Write-Host "Для доступа извне настройте обратный прокси с HTTPS: docs/reverse-proxy.md."
        } else {
            Write-Host "Адрес: http://localhost:3000 на этом компьютере."
        }
        Write-Host "Первый зарегистрированный пользователь становится администратором."
        Write-Host "Затем подключите модель в панели администратора."
    } else {
        Write-Host "Файлы подготовлены, Yahont не запущен." -ForegroundColor Green
        Write-Host ""
        Write-Host "Запустите: cd $workDir; docker compose up -d"
    }
    Write-Host ""
    Write-Host "Каталог:   $workDir"
    Write-Host "Состояние: cd $workDir; docker compose ps"
    Write-Host "Логи:      cd $workDir; docker compose logs <сервис>"
    Write-Host "Остановка: cd $workDir; docker compose stop"
    Write-Host "Обновление: cd $workDir; git pull; docker compose pull; docker compose up -d"
    Write-Host "Образы скачиваются из Docker Hub. Чтобы собрать их из исходного кода, запустите docker compose up -d --build."
    Write-Host ""
    Write-Warn "Пароли по умолчанию в .env (Postgres, S3, OpenSearch) подходят только для проверки."
    Write-Warn "Перед публикацией на сервере смените их и поставьте HTTPS: docs/reverse-proxy.md."
} finally {
    Pop-Location
}

#!/bin/bash

# Установщик Yahont CE.
#
# Скачивает репозиторий Yahont CE, создаёт файл .env с секретом входа и
# запускает Yahont в Docker Compose. Образы собираются из исходного кода, поэтому
# первая сборка занимает несколько минут.
#
#   curl -fsSL https://yahont.ai/install_yahont.sh | bash
#   curl -fsSL https://yahont.ai/install_yahont.sh | bash -s -- --lite
#
# Параметры:
#   --lite              режим «Лайт»: чат без индексации документов (меньше 1 ГБ памяти)
#   --dir DIR           каталог установки (по умолчанию ./yahont-ce в текущем каталоге)
#   --ref REF           ветка или тег репозитория (по умолчанию основная ветка)
#   --project NAME      имя проекта Docker Compose (по умолчанию yahont): нужно, чтобы
#                       держать две установки рядом
#   --bind-local PORT   слушать только 127.0.0.1:PORT: для сервера с обратным прокси
#   --no-start          только подготовить файлы, не запускать контейнеры
#   -h, --help          эта справка
#
# Переменная окружения:
#   YAHONT_REPO_URL  адрес репозитория (по умолчанию GitHub pipedude/yahont-ce)
#
# Скрипт ничего не устанавливает в систему и не требует sudo. Существующий
# файл .env он не перезаписывает.
#
# Скрипт совместим с bash 3.2: macOS поставляется именно с ним.
set -eo pipefail

REPO_URL="${YAHONT_REPO_URL:-https://github.com/pipedude/yahont-ce.git}"
INSTALL_DIR="yahont-ce"
REF=""
PROJECT=""
BIND_PORT=""
LITE=0
START=1

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

info() { printf '%b\n' "${BOLD}==>${NC} $1"; }
ok() { printf '%b\n' "${GREEN}OK${NC}  $1"; }
warn() { printf '%b\n' "${YELLOW}!${NC}   $1"; }
fail() {
    printf '%b\n' "${RED}Ошибка:${NC} $1" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Установщик Yahont CE.

  curl -fsSL https://yahont.ai/install_yahont.sh | bash
  curl -fsSL https://yahont.ai/install_yahont.sh | bash -s -- --lite

Параметры:
  --lite              режим «Лайт»: чат без индексации документов (меньше 1 ГБ памяти)
  --dir DIR           каталог установки (по умолчанию ./yahont-ce в текущем каталоге)
  --ref REF           ветка или тег репозитория (по умолчанию основная ветка)
  --project NAME      имя проекта Docker Compose (по умолчанию yahont): нужно, чтобы
                      держать две установки рядом
  --bind-local PORT   слушать только 127.0.0.1:PORT: для сервера с обратным прокси
  --no-start          только подготовить файлы, не запускать контейнеры
  -h, --help          эта справка

Переменная окружения:
  YAHONT_REPO_URL  адрес репозитория (по умолчанию GitHub pipedude/yahont-ce)
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
    --lite) LITE=1 ;;
    --no-start) START=0 ;;
    --dir)
        [ $# -ge 2 ] || fail "после --dir нужен путь"
        INSTALL_DIR="$2"
        shift
        ;;
    --ref)
        [ $# -ge 2 ] || fail "после --ref нужно имя ветки или тега"
        REF="$2"
        shift
        ;;
    --project)
        [ $# -ge 2 ] || fail "после --project нужно имя проекта"
        PROJECT="$2"
        shift
        ;;
    --bind-local)
        [ $# -ge 2 ] || fail "после --bind-local нужен номер порта"
        BIND_PORT="$2"
        shift
        ;;
    -h | --help)
        usage
        exit 0
        ;;
    *) fail "неизвестный параметр: $1 (справка: --help)" ;;
    esac
    shift
done

if [ -n "$PROJECT" ]; then
    case "$PROJECT" in
    [a-z0-9]*) ;;
    *) fail "имя проекта ${PROJECT} должно начинаться с латинской буквы или цифры" ;;
    esac
    case "$PROJECT" in
    *[!a-z0-9_-]*) fail "имя проекта ${PROJECT} может содержать только строчные латинские буквы, цифры, «-» и «_»" ;;
    esac
fi

if [ -n "$BIND_PORT" ]; then
    case "$BIND_PORT" in
    '' | *[!0-9]*) fail "порт ${BIND_PORT} должен быть числом от 1 до 65535" ;;
    esac
    { [ "$BIND_PORT" -ge 1 ] && [ "$BIND_PORT" -le 65535 ]; } ||
        fail "порт ${BIND_PORT} должен быть числом от 1 до 65535"
fi

# --- Проверки окружения ------------------------------------------------------

info "Проверяю окружение"

command -v git >/dev/null 2>&1 || fail "не найден git. Установите его и запустите скрипт снова."

# Успешно, если версия docker compose не меньше $1 (формат 2.24.4). Если версию
# определить нельзя, проверка пропускается.
compose_at_least() {
    local have
    have="$(docker compose version --short 2>/dev/null | sed 's/^v//; s/[-+].*//')"
    [ -n "$have" ] || return 0
    awk -v have="$have" -v need="$1" 'BEGIN {
        split(have, a, "."); split(need, b, ".")
        for (i = 1; i <= 3; i++) {
            if (a[i] + 0 > b[i] + 0) exit 0
            if (a[i] + 0 < b[i] + 0) exit 1
        }
        exit 0
    }'
}

if [ "$START" -eq 1 ]; then
    command -v docker >/dev/null 2>&1 ||
        fail "не найден docker. Установите Docker: https://docs.docker.com/get-docker/"
    docker compose version >/dev/null 2>&1 ||
        fail "не найден плагин Docker Compose (команда 'docker compose'). Установите его."
    docker info >/dev/null 2>&1 ||
        fail "Docker не отвечает. Запустите службу Docker и проверьте права пользователя."
    ok "Docker и Docker Compose доступны"
    if [ -n "$BIND_PORT" ] && ! compose_at_least 2.24.4; then
        fail "для --bind-local нужен Docker Compose 2.24.4 или новее. Обновите Docker Compose."
    fi
fi

# Минимум из документации: 10 ГБ для стандартного режима, 2 ГБ для лайта. Порог
# ниже на 10 %: система показывает меньше памяти, чем заявлено у виртуальной машины.
if [ "$START" -eq 1 ] && [ -r /proc/meminfo ]; then
    mem_mb=$(awk '/^MemTotal:/ {print int($2 / 1024)}' /proc/meminfo)
    mem_gb=$((mem_mb / 1024))
    if [ "$LITE" -eq 1 ] && [ "$mem_mb" -lt 1800 ]; then
        warn "Памяти около ${mem_gb} ГБ. Для режима «Лайт» нужно не меньше 2 ГБ."
    elif [ "$LITE" -eq 0 ] && [ "$mem_mb" -lt 9000 ]; then
        warn "Памяти около ${mem_gb} ГБ. Для стандартного режима нужно не меньше 10 ГБ (или режим --lite)."
    fi
fi

# --- Репозиторий ---------------------------------------------------------------

info "Получаю Yahont CE в каталог ${INSTALL_DIR}"

if [ -d "${INSTALL_DIR}/.git" ]; then
    git -C "$INSTALL_DIR" pull --ff-only ||
        fail "не удалось обновить ${INSTALL_DIR}. Проверьте локальные изменения."
    if [ -n "$REF" ]; then
        git -C "$INSTALL_DIR" checkout "$REF" ||
            fail "не удалось перейти на ${REF}."
    fi
elif [ -e "$INSTALL_DIR" ] && [ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]; then
    fail "каталог ${INSTALL_DIR} уже есть и это не репозиторий Yahont CE. Укажите другой через --dir."
elif [ -n "$REF" ]; then
    git clone --depth 1 --branch "$REF" "$REPO_URL" "$INSTALL_DIR" ||
        fail "не удалось скачать ${REPO_URL}."
else
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR" ||
        fail "не удалось скачать ${REPO_URL}."
fi
ok "Репозиторий готов"

COMPOSE_DIR="${INSTALL_DIR}/deployment/docker_compose"
[ -f "${COMPOSE_DIR}/docker-compose.yml" ] ||
    fail "в ${COMPOSE_DIR} нет docker-compose.yml. Это не репозиторий Yahont CE?"
cd "$COMPOSE_DIR"

# --- Файл .env ------------------------------------------------------------------

info "Готовлю файл .env"

# Заменяет строку KEY=... на KEY=VALUE или дописывает её в конец .env.
set_env() {
    local key="$1" value="$2" tmp
    tmp=$(mktemp)
    awk -v k="$key" -v v="$value" '
        index($0, k "=") == 1 { print k "=" v; found = 1; next }
        { print }
        END { if (!found) print k "=" v }
    ' .env >"$tmp"
    cat "$tmp" >.env
    rm -f "$tmp"
}

# Значение KEY из .env (последняя незакомментированная строка) или пустая строка.
env_value() {
    grep -E "^$1=" .env | tail -n 1 | cut -d= -f2- | tr -d "\"'" || true
}

new_secret() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex 32
    else
        head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'
    fi
}

if [ -f .env ]; then
    ok "Файл .env уже есть, оставляю как есть"
else
    cp env.template .env
    ok "Создан .env из env.template"
fi

if grep -Eq '^USER_AUTH_SECRET=("")?$' .env; then
    set_env USER_AUTH_SECRET "$(new_secret)"
    ok "Создан USER_AUTH_SECRET (без него сервер не запускается)"
fi

if [ -n "$PROJECT" ]; then
    set_env COMPOSE_PROJECT_NAME "$PROJECT"
    ok "Имя проекта Docker Compose: ${PROJECT}"
fi

if [ -n "$BIND_PORT" ]; then
    if [ -f docker-compose.override.yml ]; then
        warn "Файл docker-compose.override.yml уже есть, оставляю как есть. Проверьте в нём привязку порта."
    else
        # !override заменяет порты из docker-compose.yml, а не добавляет к ним.
        cat >docker-compose.override.yml <<EOF
services:
  nginx:
    ports: !override
      - "127.0.0.1:${BIND_PORT}:80"
EOF
        ok "Создан docker-compose.override.yml: Yahont слушает только 127.0.0.1:${BIND_PORT}"
    fi
fi

if [ "$LITE" -eq 1 ]; then
    # Пустой профиль отключает объектное хранилище из env.template: лайт
    # хранит файлы в PostgreSQL. COMPOSE_FILE подключает файл режима «Лайт»
    # ко всем следующим командам docker compose в этом каталоге. Когда
    # COMPOSE_FILE задан, Compose сам не подхватывает docker-compose.override.yml,
    # поэтому он указан в списке явно.
    compose_files="docker-compose.yml:docker-compose.lite.yml"
    [ -f docker-compose.override.yml ] && compose_files="${compose_files}:docker-compose.override.yml"
    set_env COMPOSE_PROFILES ""
    set_env COMPOSE_FILE "$compose_files"
    ok "Включён режим «Лайт»"
fi

# --- Запуск ----------------------------------------------------------------------

# Успешно, если на TCP-порту кто-то слушает.
port_busy() {
    if command -v ss >/dev/null 2>&1; then
        ss -ltn 2>/dev/null | awk -v p=":$1" '$4 ~ (p "$") { found = 1 } END { exit !found }'
    elif command -v lsof >/dev/null 2>&1; then
        lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
    else
        (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
    fi
}

work_dir="$(pwd)"

if [ "$START" -eq 1 ]; then
    # Порты проверяем только на свежем запуске: у работающей установки они заняты ею же.
    if [ -z "$(docker compose ps -q 2>/dev/null)" ]; then
        if [ -n "$BIND_PORT" ]; then
            ports_to_check="$BIND_PORT"
        else
            port_http="$(env_value HOST_PORT_80)"
            port_app="$(env_value HOST_PORT)"
            ports_to_check="${port_http:-80} ${port_app:-3000}"
        fi
        for port in $ports_to_check; do
            if port_busy "$port"; then
                warn "Файлы подготовлены в ${work_dir}."
                fail "порт ${port} уже занят: на сервере может работать nginx или другая программа.
    Варианты:
      1. Привязать Yahont к 127.0.0.1 и поставить перед ним обратный прокси:
         запустите скрипт с параметром --bind-local ПОРТ (см. docs/reverse-proxy.md).
      2. Указать другие порты в ${work_dir}/.env: HOST_PORT_80 и HOST_PORT.
    Потом запустите: cd ${work_dir} && docker compose up -d"
            fi
        done
    fi
    info "Скачиваю образы из Docker Hub и запускаю Yahont. Время первого запуска зависит от канала связи."
    docker compose pull
    docker compose up -d
    ok "Контейнеры запущены"
else
    warn "Запуск пропущен (--no-start)"
fi

# --- Что дальше ------------------------------------------------------------------

printf '\n'
if [ "$START" -eq 1 ]; then
    printf '%b\n' "${BOLD}Готово.${NC}"
    printf '\n'
    if [ -n "$BIND_PORT" ]; then
        printf '%s\n' "Адрес: http://127.0.0.1:${BIND_PORT} (только на этом компьютере)."
        printf '%s\n' "Для доступа извне настройте обратный прокси с HTTPS: docs/reverse-proxy.md."
    else
        printf '%s\n' "Адрес: http://localhost:3000 на этом компьютере."
        # По SSH одного localhost мало: интерфейс работает на сервере, а не на
        # компьютере пользователя.
        if [ -n "${SSH_CONNECTION:-}${SSH_CLIENT:-}${SSH_TTY:-}" ]; then
            server_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
            if [ -n "$server_ip" ]; then
                printf '%s\n' "Вы запустили скрипт по SSH. С другого компьютера открывайте http://${server_ip}:3000"
            fi
        fi
    fi
    printf '%s\n' "Первый зарегистрированный пользователь становится администратором."
    printf '%s\n' "Затем подключите модель в панели администратора."
else
    printf '%b\n' "${BOLD}Файлы подготовлены, Yahont не запущен.${NC}"
    printf '\n'
    printf '%s\n' "Запустите: cd ${work_dir} && docker compose up -d"
fi
printf '\n'
printf '%s\n' "Каталог:   ${work_dir}"
printf '%s\n' "Состояние: cd ${work_dir} && docker compose ps"
printf '%s\n' "Логи:      cd ${work_dir} && docker compose logs <сервис>"
printf '%s\n' "Остановка: cd ${work_dir} && docker compose stop"
printf '%s\n' "Обновление: cd ${work_dir} && git pull && docker compose pull && docker compose up -d"
printf '%s\n' "Образы скачиваются из Docker Hub. Чтобы собрать их из исходного кода, запустите docker compose up -d --build."
printf '\n'
warn "Пароли по умолчанию в .env (Postgres, S3, OpenSearch) подходят только для проверки."
warn "Перед публикацией на сервере смените их и поставьте HTTPS: docs/reverse-proxy.md."

# Yahont за обратным прокси с HTTPS

Эта инструкция нужна, если вы ставите Yahont CE на сервер с публичным адресом.
Docker Compose из репозитория публикует порты на всех сетевых интерфейсах, а
сертификатов и HTTPS в нём нет. Поэтому перед Yahont ставят обратный прокси.

Здесь описан Nginx на хосте (Debian или Ubuntu) и сертификаты Let's Encrypt. Домен
в примерах: `yahont.example.ru`. Замените его на свой.

## Как это работает

```
Интернет ──443──▶ Nginx на хосте ──▶ 127.0.0.1:3100 ──▶ nginx в Docker Compose ──▶ веб и API
```

- Nginx на хосте принимает порты 80 и 443, расшифровывает HTTPS и проксирует
  запросы на локальный порт.
- Nginx в Docker Compose распределяет запросы между веб-сервером и API.
- Порт `127.0.0.1:3100` не виден снаружи.

## Шаг 1. Привяжите Yahont к локальному адресу

В каталоге `deployment/docker_compose` создайте файл `docker-compose.override.yml`
(нужен Docker Compose 2.24.4 или новее):

```yaml
services:
  nginx:
    ports: !override
      - "127.0.0.1:3100:80"
```

Без `!override` список портов склеится со стандартным, и порты 80 и 3000 останутся
открытыми.

В `.env` укажите адрес сайта:

```
WEB_DOMAIN=https://yahont.example.ru
```

Затем запустите Yahont, как в [README](../README.md): `docker compose up -d`.
Если стек уже запущен, после правки `.env` выполните `docker compose up -d`.

Проверка: `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3100/` должна
вернуть 200.

## Шаг 2. Установите Nginx и Certbot

```bash
apt update && apt install -y nginx certbot python3-certbot-nginx
mkdir -p /var/www/letsencrypt
```

Положите в `/etc/nginx/conf.d/upgrade-map.conf` карту для WebSocket. Файл нужен
один раз для всех сайтов на сервере, и он должен существовать до сайтов,
которые его используют:

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}
```

## Шаг 3. Выпустите сертификат

DNS-запись `A` вашего домена должна указывать на этот сервер. Сначала включите
только HTTP-блок: HTTPS-блок ссылается на сертификат, которого ещё нет, и Nginx
не примет такой конфиг.

`/etc/nginx/sites-available/yahont.example.ru.conf`:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name yahont.example.ru;

    location /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}
```

```bash
ln -s /etc/nginx/sites-available/yahont.example.ru.conf /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
certbot certonly --webroot -w /var/www/letsencrypt -d yahont.example.ru
```

## Шаг 4. Добавьте HTTPS-блок

Допишите в тот же файл:

```nginx
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name yahont.example.ru;

    ssl_certificate     /etc/letsencrypt/live/yahont.example.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yahont.example.ru/privkey.pem;
    ssl_session_timeout 1d;
    ssl_protocols TLSv1.2 TLSv1.3;

    # Не меньше MAX_ALLOWED_UPLOAD_SIZE_MB (по умолчанию 250).
    client_max_body_size 250m;

    location / {
        proxy_pass http://127.0.0.1:3100;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        # Долгие ответы моделей и исследования идут потоком.
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

Если ответы модели обрываются раньше срока, проверьте тайм-ауты и здесь, и в
`.env` (`NGINX_PROXY_READ_TIMEOUT` и соседние переменные для `nginx` в Compose).

```bash
nginx -t && systemctl reload nginx
curl -sI https://yahont.example.ru | head -3
```

Ожидаем `HTTP/2 200` или перенаправление на страницу входа.

## Шаг 5. Включите автопродление сертификатов

После продления Nginx нужно перечитать сертификаты:

```bash
echo 'deploy-hook = systemctl reload nginx' >> /etc/letsencrypt/cli.ini
systemctl status certbot.timer
certbot renew --dry-run
```

Let's Encrypt может временно ответить `rateLimited` при частых пробных запусках
`renew --dry-run`. Это не ошибка настройки: подождите 10–15 минут.

## По желанию: закройте OAuth-провайдер

По нашему разбору кода Onyx публикует адреса `/api/oauth-provider/*`
(регистрация клиентов и выдача токенов), если `WEB_DOMAIN` начинается с `https`.
Переменной, которая бы это отключала, нет. Если вам эти адреса не нужны, закройте
их в блоке `server` до остальных `location`:

```nginx
location ^~ /api/oauth-provider/ {
    return 404;
}
```

Не закрывайте их, если подключаете к Yahont MCP-клиенты с входом через OAuth:
им эти адреса нужны.

## Что ещё проверить

- Смените пароли по умолчанию в `.env` (Postgres, S3, OpenSearch). Подсказки есть
  в самом файле.
- Брандмауэр `ufw` не закрывает порты, которые публикует Docker. Поэтому
  привязка к `127.0.0.1` из шага 1 обязательна.
- Первый зарегистрированный пользователь становится администратором. Зарегистрируйтесь
  сами сразу после запуска.

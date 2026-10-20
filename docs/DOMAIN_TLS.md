# Домен и HTTPS

Адрес портала — `https://hmsrent.netsrv.pw`. **HTTPS на проде включён** (20.10.2026): сертификат `*.netsrv.pw` (GlobalSign,
действует до 20.03.2027) лежит в `certs/` на сервере, порт 8080 снаружи закрыт. TLS заканчивается на nginx фронтенда
(отдельного прокси нет). Включение автоматическое: `scripts/deploy.sh` подключает `docker-compose.tls.yml`, когда на
сервере лежат `certs/fullchain.pem` и `certs/privkey.pem`. Выкатка в целом — `README.md`, раздел «Деплой на сервер».

## Что нужно получить

- Сертификат на `hmsrent.netsrv.pw` вместе с цепочкой (**fullchain**, PEM) и приватный ключ (PEM, без пароля).
- Открытые на сервере порты **80** и **443** (80 только перенаправляет на https).
- В Bouncer для клиента `hms-rent` — адрес возврата  
  `https://hmsrent.netsrv.pw/api/v1/auth/bouncer/callback` (менеджер клиента или админы Bouncer).

## Если сертификат пришёл отдельными файлами

Администраторы обычно присылают лист (`certificate.crt`), цепочку (`certificate_ca.crt`) и ключ (`certificate.key`), иногда
ещё запрос (`.csr`) и общий `.pem` со всем подряд, включая ключ. nginx нужны два файла: `fullchain.pem` (лист, затем
цепочка) и `privkey.pem` (ключ). Перед установкой проверьте, что ключ подходит к сертификату и цепочка собирается:

```bash
awk 1 certificate.crt certificate_ca.crt > fullchain.pem      # сначала свой сертификат, потом цепочка
openssl verify -CAfile certificate_ca.crt certificate.crt      # certificate.crt: OK
[ "$(openssl x509 -in certificate.crt -noout -pubkey | openssl sha256)" = \
  "$(openssl pkey -in certificate.key -pubout | openssl sha256)" ] && echo "ключ подходит"
```

Файлы с ключом, кроме `privkey.pem`, держите вне каталога проекта (например в `/root/` с правами `700`): `certs/` целиком
монтируется в контейнер, а права `644` на ключе открывают его всем пользователям сервера.

## Включение

```bash
cd /opt/hms-rent
sudo mkdir -p certs
sudo install -m 644 /путь/fullchain.pem certs/fullchain.pem
sudo install -m 600 /путь/privkey.pem  certs/privkey.pem     # ключ только для root
sudo nano .env      # PUBLIC_URL=https://hmsrent.netsrv.pw   и   COOKIE_SECURE=true
sudo ./scripts/deploy.sh --redeploy
```

`deploy.sh` проверяет конфигурацию nginx (`nginx -t`: читаются ли файлы и подходит ли ключ к сертификату) **до**
перезапуска; если проверка не прошла, контейнеры не трогаются. После запуска он проверяет и http (`127.0.0.1:8080`),
и https. `PUBLIC_URL` и `COOKIE_SECURE` меняйте вместе с включением HTTPS: с `COOKIE_SECURE=true` вход по http
работать не будет.

Что изменится для пользователей после включения: адрес станет `https://hmsrent.netsrv.pw`, а прямой доступ
`http://<IP>:8080` закроется снаружи (порт слушает только `127.0.0.1` сервера).

Порты можно переопределить в `.env`: `HTTP_REDIRECT_PORT` (80), `HTTPS_PORT` (443), `HTTP_PORT` (8080, только localhost).
Редирект с http на https не знает внешнего порта: при нестандартном `HTTPS_PORT` он ведёт на `https://<домен>/…` без
порта. На проде порты должны быть стандартными (80 и 443), поэтому это важно только для тестовых стендов.

## Проверка

```bash
curl -I http://hmsrent.netsrv.pw/            # 301 на https
curl -s https://hmsrent.netsrv.pw/api/health # {"status":"ok"}
```
В браузере: вход через Bouncer должен вернуть на `https://hmsrent.netsrv.pw/` уже авторизованным.

## Продление сертификата

Положите новые `fullchain.pem` и `privkey.pem` в `certs/` и перечитайте конфигурацию без простоя:

```bash
sudo docker compose -f docker-compose.prod.yml -f docker-compose.tls.yml exec frontend nginx -s reload
```
`deploy.sh` при каждом запуске показывает срок действия сертификата и предупреждает, если до конца меньше 14 дней.

## Вернуться на http

Уберите файлы сертификата (`sudo mv certs certs.off`), верните прежние `PUBLIC_URL` и `COOKIE_SECURE=false` и выполните
`sudo ./scripts/deploy.sh --redeploy`.

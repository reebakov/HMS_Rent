# Общие настройки приложения для всех server-блоков: подключается из http.conf (образ frontend, COPY в Dockerfile) и
# из deploy/nginx/tls.conf (HTTPS, монтируется docker-compose.tls.yml). Единственный источник locations и gzip.
root /usr/share/nginx/html;

# Адрес backend ищется через DNS Docker при запросе, а не при старте nginx: иначе `nginx -t` (проверка в deploy.sh) и
# запуск frontend падают с «host not found», пока контейнер backend не запущен, а после пересоздания backend nginx
# держал бы его старый адрес. Переменная в proxy_pass без URI передаёт путь запроса как есть, как и раньше.
resolver 127.0.0.11 valid=10s ipv6=off;
set $backend http://backend:8000;

# API и Swagger — на backend
location /api/ {
    proxy_pass $backend;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    # последним элементом nginx дописывает реальный адрес клиента — на нём держится блокировка перебора пароля
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 120s;
}

# статика с хэшами в именах — кэшируем надолго
location /assets/ {
    expires 1y;
    add_header Cache-Control "public, immutable";
}

# SPA: все остальные пути отдают index.html
location / {
    try_files $uri $uri/ /index.html;
    add_header Cache-Control "no-cache";
}

gzip on;
gzip_types text/css application/javascript application/json image/svg+xml;

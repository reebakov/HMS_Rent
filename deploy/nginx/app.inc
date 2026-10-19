# Общие настройки приложения для всех server-блоков (подключается из tls.conf). Копия логики frontend/nginx.conf.
root /usr/share/nginx/html;

# API и Swagger — на backend
location /api/ {
    proxy_pass http://backend:8000;
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

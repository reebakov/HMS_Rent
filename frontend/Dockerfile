# --- сборка ---
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install --no-audit --no-fund
COPY . .
# версия сборки (sha коммита) вшивается в бандл: по ней интерфейс сверяет себя с /api/health и замечает обновление
ARG APP_VERSION=dev
ENV VITE_APP_VERSION=$APP_VERSION
# версия сервиса 1.<feat>.<fix> (scripts/release_version.sh): интерфейс показывает её в справке
ARG APP_RELEASE=dev
ENV VITE_APP_RELEASE=$APP_RELEASE
RUN npm run build

# --- раздача статики + прокси на API ---
FROM nginx:1.27-alpine
COPY nginx/http.conf /etc/nginx/conf.d/default.conf
COPY nginx/app.inc /etc/nginx/app.inc
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80

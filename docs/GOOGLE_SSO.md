# Вход сотрудников через Google (SSO)

Сотрудник нажимает «Войти через Google», выбирает рабочий аккаунт — и он в портале. Пароли портал
не хранит; пускает только подтверждённые адреса из `GOOGLE_ALLOWED_DOMAINS`.

## 1. Google Cloud (делает админ Google Workspace, ~10 минут)

1. https://console.cloud.google.com → создать проект **HMS Rent** внутри организации компании.
2. **APIs & Services → OAuth consent screen**:
   * User type — **Internal** (войти смогут только аккаунты вашей организации Google Workspace);
   * название приложения, почта поддержки; scopes — `openid`, `email`, `profile`.
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   * Application type — **Web application**;
   * **Authorized redirect URIs**:
     * `http://localhost:8080/api/v1/auth/google/callback` — для локального запуска;
     * `https://hmsrent.<ваш-домен>/api/v1/auth/google/callback` — для виртуалки.
4. Скопировать **Client ID** и **Client secret** в `.env`.

> ⚠️ Для виртуалки Google требует **https и доменное имя** (не IP и не `.local`).
> Нужна запись вида `hmsrent.marvin-it.com` (может резолвиться только внутри сети) и TLS-сертификат.

## 2. `.env`

```env
PUBLIC_URL=http://localhost:8080
GOOGLE_CLIENT_ID=1234567890-xxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxx
GOOGLE_ALLOWED_DOMAINS=deeplay.io
```

`PUBLIC_URL` должен совпадать с адресом, по которому открывают портал, — из него собирается redirect URI.
При запуске фронтенда через `npm run dev` это `http://localhost:5173` (redirect URI тоже добавьте в Google).

## 3. Администраторы

Два варианта, можно совмещать:

| Вариант | Как | Плюсы |
|---|---|---|
| **Через Google** (основной) | почта в `backend/config/admins.txt`, по одной в строке | личные учётки: в журнале видно, кто из админов что сделал; файл перечитывается на лету — добавили/убрали почту, и права меняются без перезапуска |
| **Локальная учётка** | `docker compose exec backend python -m app.cli create-admin <логин> --name "Имя"` — пароль вводится в консоли | работает, даже если Google недоступен; удобно как «аварийный» вход |

Локальные учётки: `set-password <логин>`, `disable <логин>`, `users` — список всех.
Форма входа для них — «Вход для администраторов» на странице входа (`AUTH_LOCAL_ENABLED=true`).
После 5 неудачных попыток логин блокируется на 10 минут.

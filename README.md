# MediaGrab — Telegram-бот для видео и музыки

Скачивает видео и вытаскивает MP3 по ссылке и отправляет файл прямо в чат.
Один файл `python -m mediagrab`, без веб-хуков и внешних сервисов.

> Нужно, чтобы бот работал без вашего компьютера? См. раздел
> **«GitHub Actions»** ниже — там готовый workflow.

| Площадка | Видео | MP3 | Примечание |
|---|---|---|---|
| ▶️ YouTube | ✅ | ✅ | нужен Node.js или Deno для полного набора форматов; при «подтвердите, что вы не робот» — cookies |
| 📸 Instagram | ✅ | ✅ | Reels/посты; чаще всего нужны cookies |
| 🎵 TikTok | ✅ | ✅ | обычно работает без cookies |
| 🧵 Threads | ✅ | ✅ | собственный парсер `video_versions` + fallback на yt-dlp |
| ✖️ X (Twitter) | ✅ | ✅ | видео из постов; NSFW-аккаунтам нужны cookies |
| 🎥 Rutube | ✅ | ✅ | без cookies |
| 🅥 VK Video | ✅ | ✅ | `vk.com/video...`, `vkvideo.ru`, `video_ext.php` |

Дополнительно: прогресс с процентами и скоростью, отмена, выбор качества,
лимит размера с автоматическим понижением качества, настройки на пользователя,
очередь и ограничение частоты запросов.

---

## Быстрый старт

### Windows

```powershell
cd mediagrab
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

copy .env.example .env
notepad .env          # вставьте BOT_TOKEN от @BotFather

python -m mediagrab --check   # проверка окружения
python -m mediagrab
```

Либо просто: `.\run.ps1` (создаст venv, поставит зависимости и запустит).

### Linux / macOS

```bash
cd mediagrab
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
nano .env             # BOT_TOKEN

python -m mediagrab --check
python -m mediagrab
```

Либо: `bash run.sh`.

### Что должно быть установлено

1. **Python 3.10+**.
2. **ffmpeg** — для MP3, склейки видео и превью.
   - Windows: `winget install Gyan.FFmpeg` (перезапустите терминал).
   - Debian/Ubuntu: `sudo apt install ffmpeg`.
   - macOS: `brew install ffmpeg`.
3. **Node.js 20+** или **Deno** — yt-dlp использует JS-рантайм для YouTube.
   - Windows: `winget install OpenJS.NodeJS.LTS`.
   - Проверка: `node --version`. Если рантайма нет, видео скачивается,
     но YouTube может отдавать не все форматы.

Проверить всё сразу:

```bash
python -m mediagrab --check
```

---

## Токен бота

1. Откройте [@BotFather](https://t.me/BotFather) → `/newbot`.
2. Придумайте имя и username.
3. Скопируйте токен вида `123456789:AAH...` в `.env`:

```dotenv
BOT_TOKEN=123456789:AAH...
```

4. (Необязательно) `/setcommands` в BotFather:

```
start - Начать
settings - Качество по умолчанию
cancel - Отменить загрузку
help - Помощь
```

---

## Настройки `.env`

| Переменная | По умолчанию | Что делает |
|---|---|---|
| `BOT_TOKEN` | — | токен бота, обязателен |
| `MAX_UPLOAD_MB` | `50` | лимит отправки; с локальным API можно `2000` |
| `MAX_CONCURRENT_DOWNLOADS` | `2` | одновременных загрузок |
| `RATE_LIMIT_SECONDS` | `10` | пауза между задачами одного пользователя |
| `DEFAULT_VIDEO_HEIGHT` | `720` | качество видео по умолчанию |
| `DEFAULT_AUDIO_KBPS` | `192` | битрейт MP3 по умолчанию |
| `PROXY_URL` | — | прокси для yt-dlp: `http://user:pass@host:port` |
| `TELEGRAM_LOCAL_API_URL` | — | локальный Bot API, поднимает лимит до 2 ГБ |
| `ALLOWED_USER_IDS` | — | белый список Telegram ID через запятую |
| `ADMIN_IDS` | — | кому доступна `/stats` |
| `COOKIES_DIR` | `cookies` | папка с cookie-файлами |
| `YTDLP_JS_RUNTIME` | `auto` | `node`, `deno`, `bun` или `none` |
| `FFMPEG_PATH` | — | путь к `ffmpeg.exe` или его папке |
| `LOG_LEVEL` | `INFO` | `DEBUG` для диагностики |
| `KEEP_FILES` | `false` | не удалять скачанное (отладка) |
| `DROP_PENDING_UPDATES` | `true` | удалять сообщения, пришедшие пока бот был выключен; для GitHub Actions — `false` |

Свой Telegram ID можно узнать командой `/id` в боте.

---

## Cookies: когда и зачем

Площадки всё чаще требуют авторизацию. Бот ищет файлы в папке `cookies/`:

```
cookies/
├── youtube.txt
├── instagram.txt
├── tiktok.txt
├── x.txt
├── threads.txt
├── rutube.txt
└── vk.txt
```

Формат — **Netscape**, как у расширения
«Get cookies.txt LOCALLY» (Chrome/Firefox). Порядок:

1. Войдите в аккаунт в браузере.
2. Экспортируйте cookies для домена (например, `youtube.com`).
3. Сохраните файл как `cookies/youtube.txt`.
4. Перезапустите бота (файлы читаются при каждой загрузке, перезапуск не обязателен).

Важно:

- Используйте отдельный аккаунт: массовые загрузки могут привести к блокировке.
- Cookies — это пароли от аккаунта. Не коммитьте папку `cookies/` (она в `.gitignore`).
- Если файла нет, бот работает анонимно и сообщает, что нужен вход.

### YouTube: «Sign in to confirm you're not a bot»

1. Экспортируйте cookies с `youtube.com` → `cookies/youtube.txt`.
2. Убедитесь, что установлен Node.js 20+ (или Deno).
3. Перезапустите бота.

Для «возрастных» видео нужны cookies аккаунта 18+.

---

## Файлы больше 50 МБ

Обычный Telegram Bot API разрешает ботам отправлять файлы до **50 МБ**.
Бот сам понижает качество, если файл не влезает, но для больших видео
нужен локальный Bot API server:

1. Получите `api_id` и `api_hash` на [my.telegram.org](https://my.telegram.org).
2. Соберите и запустите [telegram-bot-api](https://github.com/tdlib/telegram-bot-api):

```bash
telegram-bot-api --api-id=12345 --api-hash=abcdef... --local
```

3. Пропишите в `.env`:

```dotenv
TELEGRAM_LOCAL_API_URL=http://127.0.0.1:8081
MAX_UPLOAD_MB=2000
```

Локальный сервер должен работать на той же машине, что и бот
(или быть доступен по сети), и с тем же токеном.

---

## Docker

```bash
cp .env.example .env
# впишите BOT_TOKEN

docker compose up -d --build
docker compose logs -f
```

`docker-compose.yml` монтирует `data/` (настройки и логи), `cookies/` и `downloads/`.
В образ уже включены ffmpeg и Node.js.

---

## GitHub Actions (без своего компьютера)

Бот может работать на серверах GitHub: код лежит в репозитории, токен — в Secrets,
ваш компьютер выключен. Для **публичного** репозитория это бесплатно.

> ⚠️ GitHub Actions — не хостинг 24/7. Один job живёт максимум 6 часов, поэтому
> бот перезапускается по расписанию и работает окнами по 5 ч 45 мин. Между
> окнами возможна пауза 10–30 минут; сообщения не теряются — Telegram
> придерживает их, и бот обрабатывает накопленное при следующем старте.
> Для непрерывной работы нужен VPS или Railway/Fly.io (код всё равно может
> лежать на GitHub).

### 1. Создайте репозиторий

На github.com → **New repository** → имя `mediagrab` → **Public** (для бесплатных
минут Actions) → **без** README и .gitignore → **Create repository**.

### 2. Загрузите код

Из папки проекта:

```bash
git init
git add .
git commit -m "MediaGrab bot"
git branch -M main
git remote add origin https://github.com/ВАШ_ЛОГИН/mediagrab.git
git push -u origin main
```

`.env`, cookies и скачанные файлы в репозиторий не попадают — они в `.gitignore`.

### 3. Добавьте токен

В репозитории: **Settings → Secrets and variables → Actions → New repository secret**:

- **Name:** `BOT_TOKEN`
- **Secret:** токен от [@BotFather](https://t.me/BotFather)

### 4. Запустите

**Actions → MediaGrab bot → Run workflow**. Через минуту бот онлайн.
Дальше он запускается сам каждые 6 часов (`cron: "0 */6 * * *"`).

Проверка: в Telegram отправьте боту `/start`.

### Cookies в GitHub Actions

Cookies не коммитятся. Их можно положить в Secrets в base64:

```bash
# Linux / macOS
base64 -w0 cookies/youtube.txt
```

```powershell
# Windows PowerShell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("cookies\youtube.txt"))
```

Создайте секреты `YOUTUBE_COOKIES_B64`, `INSTAGRAM_COOKIES_B64`,
`TIKTOK_COOKIES_B64` — workflow сам разложит их в `cookies/`.

### Ограничения GitHub Actions

- **6 часов** на job: окна по 5 ч 45 мин и паузы между ними.
- **Публичный репозиторий** — минуты бесплатны. Приватный — 2000 мин/месяц
  (~33 часа), для 24/7 не хватит.
- Настройки пользователей (`data/users.json`) не сохраняются между запусками;
  cookies передаются только через Secrets.
- GitHub отключает scheduled workflows после 60 дней без активности в публичном
  репозитории — включите вручную или сделайте коммит.
- Использование Actions как хостинга бота может нарушать ToS GitHub.
- IP-адреса GitHub (дата-центры) чаще блокируются YouTube/Instagram — cookies
  могут понадобиться сильнее, чем дома.

Если нужен настоящий 24/7 — разверните этот же репозиторий на VPS
(systemd ниже) или Railway/Fly.io; GitHub останется хранилищем кода.

---

## systemd (Linux)

`/etc/systemd/system/mediagrab.service`:

```ini
[Unit]
Description=MediaGrab Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=mediagrab
WorkingDirectory=/opt/mediagrab
ExecStart=/opt/mediagrab/.venv/bin/python -m mediagrab
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mediagrab
journalctl -u mediagrab -f
```

---

## Как пользоваться

1. Пришлите ссылку на видео/пост/трек.
2. Бот покажет карточку и кнопки:
   - **🎬 Видео · 720p** — скачать с качеством по умолчанию;
   - **🎵 MP3 · 192** — только звук;
   - **⚙️ Другое качество** — 1080p/720p/480p/360p, MP3 320/192/128.
3. Наблюдайте прогресс, при необходимости нажмите **⏹ Отменить**.
4. Готовый файл приходит в чат; временные файлы удаляются.

Команды:

- `/start` — приветствие и список площадок;
- `/settings` — качество по умолчанию и режим «отправлять файлом»;
- `/cancel` — отменить текущую загрузку;
- `/id` — ваш Telegram ID;
- `/stats` — статистика (для `ADMIN_IDS`);
- `/help` — справка.

Ограничения:

- плейлисты и карусели — только первый элемент;
- прямые трансляции не поддерживаются;
- фото и текстовые посты не скачиваются.

---

## Структура проекта

```
mediagrab/
├── mediagrab/
│   ├── __main__.py      # запуск, логирование, --check
│   ├── config.py        # .env и настройки
│   ├── links.py         # нормализация ссылок, определение площадки
│   ├── downloader.py    # yt-dlp: форматы, прогресс, лимиты, отмена
│   ├── threads.py       # парсер Threads (video_versions / og:video)
│   ├── runner.py        # очередь, прогресс, отправка в Telegram
│   ├── handlers.py      # команды, кнопки, настройки
│   ├── keyboards.py     # inline-клавиатуры
│   ├── storage.py       # настройки пользователей (JSON)
│   ├── middleware.py    # белый список пользователей
│   ├── texts.py         # тексты и подписи
│   ├── formatting.py    # прогресс-бар
│   ├── errors.py        # пользовательские ошибки
│   └── utils.py         # размеры, длительности, имена файлов
├── .github/workflows/   # bot.yml (GitHub Actions) и tests.yml (CI)
├── tests/               # юнит- и интеграционные тесты
├── requirements.txt
├── .env.example
├── Dockerfile
└── docker-compose.yml
```

---

## Тесты

```bash
pip install -r requirements-dev.txt
pytest
```

Покрыты: нормализация ссылок и определение площадок, парсер Threads,
лестница качеств, выбор формата yt-dlp, лимиты размера, настройки пользователей,
callback-данные и форматирование прогресса. Интеграционный тест поднимает
локальный HTTP-сервер, генерирует видео через ffmpeg и проходит полный путь
скачивания и извлечения MP3.

Если интеграционный тест нужно пропустить (нет ffmpeg):

```bash
pytest -m "not integration"
```

---

## Частые ошибки

| Сообщение | Причина | Решение |
|---|---|---|
| «YouTube просит подтвердить, что вы не робот» | IP/анонимный доступ | cookies `youtube.txt`, Node.js 20+ |
| «Instagram требует вход» | закрытый/ограниченный контент | cookies `instagram.txt` |
| «Не удалось подобрать формат» | в посте только фото или площадка изменилась | обновить `pip install -U yt-dlp` |
| «Файл весит … а лимит …» | > 50 МБ | качество ниже или локальный Bot API |
| `ffmpeg не найден` | нет в PATH | установить ffmpeg / `FFMPEG_PATH` |
| `409 Conflict` при старте | запущено два экземпляра | остановить лишний |
| `Unauthorized` | неверный `BOT_TOKEN` | проверить токен |

Обновление после изменений площадок:

```bash
pip install -U yt-dlp
```

---

## Правовая оговорка

Бот — инструмент для личного использования. Скачивайте только тот контент,
на который у вас есть права, и соблюдайте правила площадок и законодательство
вашей страны. Автор не несёт ответственности за использование бота третьими лицами.

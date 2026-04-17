# Ценовой детектив (WB/Ozon)

Telegram-бот для отслеживания снижения цен на Wildberries и Ozon.

## Быстрый старт

1. Установите зависимости:

```bash
/Users/mac/.local/bin/poetry install
```

2. Создайте env-файл:

```bash
cp env.local.example env.local
```

3. Поднимите PostgreSQL:

```bash
docker compose up -d db
```

4. Примените миграции:

```bash
make migrate
```

5. Запустите бота:

```bash
make bot
```

## Основные команды

```bash
make install
make db-up
make db-logs
make migrate
make revision m="create tracked_items table"
make current
make bot
make server
make openapi
make codestyle
```

## API и здоровье сервиса

- `GET /liveness`
- `GET /api/v1/service/health`

## Codestyle

```bash
./codestyle.sh
```

или на конкретные пути:

```bash
./codestyle.sh app bot migrations
```
# Этот файл создает Docker контейнер для Telegram Bot Service с аудио библиотеками

# services/telegram-bot/Dockerfile
FROM python:3.11-slim

# Установка системных зависимостей для аудио обработки
RUN apt-get update && apt-get install -y \
    ffmpeg \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Создание рабочей директории
WORKDIR /app

# Копирование requirements и установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода приложения
COPY . .

# Создание директории для временных файлов
RUN mkdir -p /app/temp

# Создание пользователя для безопасности
RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import telethon; print('Telegram bot service healthy')" || exit 1

# Команда запуска
CMD ["python", "main.py"]
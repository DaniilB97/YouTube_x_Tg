# Этот файл создает Docker контейнер для File Manager Service с библиотеками для PDF генерации

# services/file-manager/Dockerfile
FROM python:3.11-slim

# Установка системных зависимостей для PDF генерации
RUN apt-get update && apt-get install -y \
    build-essential \
    libfreetype6-dev \
    libjpeg-dev \
    libpng-dev \
    libffi-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Создание рабочей директории
WORKDIR /app

# Копирование requirements и установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода приложения
COPY . .

# Создание директории для хранения файлов
RUN mkdir -p /app/storage

# Создание пользователя для безопасности
RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

# Expose порт для health check
EXPOSE 8003

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import reportlab; import markdown; print('File manager healthy')" || exit 1

# Команда запуска
CMD ["python", "main.py"]
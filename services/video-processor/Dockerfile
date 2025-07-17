# Используем конкретную версию python:3.11-slim для стабильности
FROM python:3.11-slim

# Устанавливаем переменные окружения для Python
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Установка системных зависимостей для OpenCV и видео обработки
# Добавлен флаг --no-install-recommends для уменьшения размера образа
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libgl1-mesa-glx \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Создание рабочей директории
WORKDIR /app

# Копируем только файл с зависимостями для использования кэша Docker
# Этот шаг будет выполняться заново только при изменении requirements.txt
COPY requirements.txt .

# Установка зависимостей Python
# Убедитесь, что в requirements.txt указано numpy<2.0
RUN pip install --no-cache-dir -r requirements.txt

# Копируем остальной код приложения
# Этот слой будет пересобираться при каждом изменении кода,
# но зависимости уже будут установлены и закэшированы.
COPY . .

# Создание директории для хранения (если требуется)
# Этот шаг можно убрать, если директория создается динамически
RUN mkdir -p /app/storage

# Создание пользователя без root-прав для безопасности
RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

# Expose порт (для health check или API)
EXPOSE 8001

# Команда запуска сервиса
CMD ["python", "main.py"]

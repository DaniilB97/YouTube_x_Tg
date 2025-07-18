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

# --- ВОТ ИЗМЕНЕНИЕ ---
# Принудительно обновляем yt-dlp до самой свежей версии
RUN pip install --upgrade yt-dlp

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

### 2. Пояснение по поводу пользователя (USER app)
#Вы правильно делаете, что создаете отдельного пользователя (USER app) — это лучшая практика для безопасности.

#Однако именно это и было причиной нашей самой первой ошибки [Errno 13] Permission denied. Помните, мы решили э#ту проблему, добавив user: "root" в docker-compose.yml?#

#Эта настройка в docker-compose.yml имеет больший приоритет и переопределяет директиву USER app из этого Dockerfile. То есть, ваш контейнер все равно будет запускаться от имени root, пока в docker-compose.yml есть эта строка.

#Для локальной отладки это абсолютно нормально. Просто помните, что сейчас права доступа контролируются docker-compose.yml, а не этим Dockerfile.

#Итог: Внесите изменение с pip install --upgrade yt-dlp, пересоберите образ (docker compose up --build), и ошибка 403 Forbidden должна исчезнуть.

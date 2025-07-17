# Этот файл объединяет database и redis менеджеры для удобного импорта в сервисах

# shared/database/__init__.py
from .database_manager import DatabaseManager, get_database
from .redis_manager import RedisManager, get_redis

__all__ = [
    'DatabaseManager', 
    'get_database', 
    'RedisManager', 
    'get_redis'
]
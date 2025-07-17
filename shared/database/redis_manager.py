# Этот файл создает менеджер Redis для очередей задач и общения между сервисами

# shared/database/redis_manager.py
import os
import json
import logging
from typing import Any, Dict, Optional, Callable
import asyncio
import redis.asyncio as redis
from shared.models import TaskData, TaskStatus
from datetime import datetime

logger = logging.getLogger(__name__)

class RedisManager:
    """Handles Redis operations for task queuing and inter-service communication"""
    
    def __init__(self):
        self.redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
        self.redis = None
        self.subscribers = {}
    
    async def connect(self):
        """Connect to Redis"""
        try:
            self.redis = await redis.from_url(self.redis_url)
            logger.info("✅ Connected to Redis")
        except Exception as e:
            logger.error(f"❌ Failed to connect to Redis: {e}")
            raise
    
    async def disconnect(self):
        """Disconnect from Redis"""
        if self.redis:
            await self.redis.close()
            logger.info("Disconnected from Redis")
    
    # Task Queue Operations
    async def enqueue_task(self, queue_name: str, task_data: TaskData) -> bool:
        """Add task to queue"""
        try:
            await self.redis.lpush(queue_name, json.dumps(task_data.to_dict()))
            logger.info(f"Task {task_data.task_id} added to queue {queue_name}")
            return True
        except Exception as e:
            logger.error(f"Error enqueuing task: {e}")
            return False
    
    async def dequeue_task(self, queue_name: str, timeout: int = 10) -> Optional[TaskData]:
        """Get task from queue (blocking)"""
        try:
            result = await self.redis.brpop(queue_name, timeout=timeout)
            if result:
                queue, task_json = result
                task_data = TaskData.from_dict(json.loads(task_json))
                logger.info(f"Task {task_data.task_id} dequeued from {queue_name}")
                return task_data
            return None
        except Exception as e:
            logger.error(f"Error dequeuing task: {e}")
            return None
    
    async def get_queue_size(self, queue_name: str) -> int:
        """Get number of tasks in queue"""
        try:
            return await self.redis.llen(queue_name)
        except Exception as e:
            logger.error(f"Error getting queue size: {e}")
            return 0
    
    # Task Status Operations
    async def set_task_status(self, task_id: str, status: TaskStatus, result: Optional[Dict] = None, error: Optional[str] = None):
        """Update task status"""
        try:
            task_key = f"task:{task_id}"
            task_data = {
                'status': status.value,
                'updated_at': datetime.now().isoformat()
            }
            
            if result:
                task_data['result'] = json.dumps(result)
            if error:
                task_data['error'] = error
            
            await self.redis.hset(task_key, mapping=task_data)
            await self.redis.expire(task_key, 3600)  # Expire in 1 hour
            
            # Publish status update for real-time notifications
            await self.publish_message(f"task_status:{task_id}", task_data)
            
        except Exception as e:
            logger.error(f"Error setting task status: {e}")
    
    async def get_task_status(self, task_id: str) -> Optional[Dict]:
        """Get task status"""
        try:
            task_key = f"task:{task_id}"
            result = await self.redis.hgetall(task_key)
            if result and result.get('result'):
                result['result'] = json.loads(result['result'])
            return result if result else None
        except Exception as e:
            logger.error(f"Error getting task status: {e}")
            return None
    
    # Pub/Sub Operations for real-time updates
    async def publish_message(self, channel: str, message: Dict):
        """Publish message to channel"""
        try:
            await self.redis.publish(channel, json.dumps(message))
            logger.debug(f"Message published to {channel}")
        except Exception as e:
            logger.error(f"Error publishing message: {e}")
    
    async def subscribe_to_channel(self, channel: str, callback: Callable):
        """Subscribe to channel with callback"""
        try:
            pubsub = self.redis.pubsub()
            await pubsub.subscribe(channel)
            
            self.subscribers[channel] = {
                'pubsub': pubsub,
                'callback': callback
            }
            
            # Start listening in background
            asyncio.create_task(self._listen_to_channel(channel))
            logger.info(f"Subscribed to channel {channel}")
            
        except Exception as e:
            logger.error(f"Error subscribing to channel: {e}")
    
    async def _listen_to_channel(self, channel: str):
        """Listen to channel messages"""
        try:
            pubsub = self.subscribers[channel]['pubsub']
            callback = self.subscribers[channel]['callback']
            
            async for message in pubsub.listen():
                if message['type'] == 'message':
                    try:
                        data = json.loads(message['data'])
                        await callback(channel, data)
                    except Exception as e:
                        logger.error(f"Error processing message from {channel}: {e}")
                        
        except Exception as e:
            logger.error(f"Error listening to channel {channel}: {e}")
    
    # Cache Operations
    async def set_cache(self, key: str, value: Any, expire: int = 3600):
        """Set cache value"""
        try:
            await self.redis.setex(key, expire, json.dumps(value))
        except Exception as e:
            logger.error(f"Error setting cache: {e}")
    
    async def get_cache(self, key: str) -> Optional[Any]:
        """Get cache value"""
        try:
            result = await self.redis.get(key)
            return json.loads(result) if result else None
        except Exception as e:
            logger.error(f"Error getting cache: {e}")
            return None

# Singleton instance for shared access
_redis_manager = None

def get_redis() -> RedisManager:
    """Get shared Redis manager instance"""
    global _redis_manager
    if _redis_manager is None:
        _redis_manager = RedisManager()
    return _redis_manager
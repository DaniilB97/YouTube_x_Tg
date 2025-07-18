# Короткий тест-скрипт для проверки всех подключений в микросервисной архитектуре

import asyncio
import os
import sys
import json
import logging
from datetime import datetime

# Add shared to path
sys.path.append('./shared')

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

async def test_redis_connection():
    """Test Redis connection"""
    try:
        from shared.database import get_redis
        
        redis = get_redis()
        await redis.connect()
        
        # Test basic operations
        await redis.redis.set("test_key", "test_value")
        value = await redis.redis.get("test_key")
        await redis.redis.delete("test_key")
        
        if value == b"test_value":
            logger.info("✅ Redis: Connected and working")
            return True
        else:
            logger.error("❌ Redis: Value mismatch")
            return False
            
    except Exception as e:
        logger.error(f"❌ Redis: {e}")
        return False

async def test_supabase_connection():
    """Test Supabase connection"""
    try:
        from shared.database import get_database
        
        db = get_database()
        
        # Test database connection by trying to get a user
        # This should work even if user doesn't exist
        result = await db.get_user("test_user_123")
        
        logger.info("✅ Supabase: Connected (can query users table)")
        return True
        
    except Exception as e:
        logger.error(f"❌ Supabase: {e}")
        return False

async def test_api_gateway():
    """Test API Gateway"""
    try:
        import aiohttp
        
        async with aiohttp.ClientSession() as session:
            # Test health endpoint
            async with session.get("http://localhost:8000/health") as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info("✅ API Gateway: Healthy")
                    logger.info(f"   Redis: {data.get('redis', 'unknown')}")
                    logger.info(f"   Database: {data.get('database', 'unknown')}")
                    return True
                else:
                    logger.error(f"❌ API Gateway: HTTP {response.status}")
                    return False
                    
    except Exception as e:
        logger.error(f"❌ API Gateway: {e}")
        return False

async def test_ollama_connection():
    """Test Ollama connection"""
    try:
        import aiohttp
        
        ollama_endpoint = os.getenv('OLLAMA_ENDPOINT', 'http://localhost:11434')
        
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{ollama_endpoint}/api/tags", timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    models = [model['name'] for model in data.get('models', [])]
                    
                    if models:
                        logger.info(f"✅ Ollama: Connected with models: {models}")
                        return True
                    else:
                        logger.warning("⚠️ Ollama: Connected but no models loaded")
                        return False
                else:
                    logger.error(f"❌ Ollama: HTTP {response.status}")
                    return False
                    
    except Exception as e:
        logger.error(f"❌ Ollama: {e}")
        return False

async def test_shared_models():
    """Test shared models import"""
    try:
        from shared.models import User, TaskData, VideoSummary, TaskType, TaskStatus
        from shared.utils import generate_task_id, extract_youtube_video_id
        
        # Test model creation
        task_id = generate_task_id()
        video_id = extract_youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        
        if task_id and video_id == "dQw4w9WgXcQ":
            logger.info("✅ Shared Models: All imports working")
            return True
        else:
            logger.error("❌ Shared Models: Function test failed")
            return False
            
    except Exception as e:
        logger.error(f"❌ Shared Models: {e}")
        return False

async def test_task_queue():
    """Test task queue operations"""
    try:
        from shared.database import get_redis
        from shared.models import TaskData, TaskType, TaskStatus
        from shared.utils import generate_task_id
        
        redis = get_redis()
        await redis.connect()
        
        # Create test task
        task_data = TaskData(
            task_id=generate_task_id(),
            task_type=TaskType.AI_CONVERSATION,
            user_id="test_user",
            chat_id=12345,
            status=TaskStatus.PENDING,
            data={"test": "data"}
        )
        
        # Test queue operations
        queue_name = "test_queue"
        success = await redis.enqueue_task(queue_name, task_data)
        
        if success:
            # Try to dequeue
            dequeued_task = await redis.dequeue_task(queue_name, timeout=1)
            if dequeued_task and dequeued_task.task_id == task_data.task_id:
                logger.info("✅ Task Queue: Enqueue/Dequeue working")
                return True
            else:
                logger.error("❌ Task Queue: Dequeue failed")
                return False
        else:
            logger.error("❌ Task Queue: Enqueue failed")
            return False
            
    except Exception as e:
        logger.error(f"❌ Task Queue: {e}")
        return False

async def run_all_tests():
    """Run all connection tests"""
    logger.info("🧪 Starting connection tests...\n")
    
    tests = [
        ("Shared Models", test_shared_models()),
        ("Redis Connection", test_redis_connection()),
        ("Supabase Connection", test_supabase_connection()),
        ("Task Queue", test_task_queue()),
        ("API Gateway", test_api_gateway()),
        ("Ollama Connection", test_ollama_connection()),
    ]
    
    results = []
    for name, test_coro in tests:
        logger.info(f"Testing {name}...")
        result = await test_coro
        results.append((name, result))
        logger.info("")  # Empty line for readability
    
    # Summary
    logger.info("📊 TEST RESULTS:")
    logger.info("=" * 50)
    
    passed = 0
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{name:20} {status}")
        if result:
            passed += 1
    
    logger.info("=" * 50)
    logger.info(f"Total: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("🎉 All tests passed! System ready!")
    else:
        logger.warning("⚠️ Some tests failed. Check the logs above.")
    
    return passed == total

if __name__ == "__main__":
    import sys
    
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    try:
        success = asyncio.run(run_all_tests())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Test runner failed: {e}")
        sys.exit(1)
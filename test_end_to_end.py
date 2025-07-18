# Полное end-to-end тестирование YouTube Summarizer микросервисной системы

import asyncio
import os
import sys
import json
import logging
import time
from datetime import datetime
import aiohttp

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

class EndToEndTester:
    """Complete system testing"""
    
    def __init__(self):
        self.api_gateway_url = "http://localhost:8000"
        self.test_user_id = "a3cae768-9ba5-483b-bf6a-e2f51dd46f3f"  # Your real user
        self.test_chat_id = 123456789
        
    async def test_api_gateway_health(self):
        """Test 1: API Gateway Health Check"""
        logger.info("🔍 Test 1: API Gateway Health Check")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.api_gateway_url}/health") as response:
                    if response.status == 200:
                        data = await response.json()
                        logger.info(f"   ✅ API Gateway: {data['status']}")
                        logger.info(f"   ✅ Redis: {data['redis']}")
                        logger.info(f"   ✅ Database: {data['database']}")
                        
                        # Check queues
                        queues = data.get('queues', {})
                        for queue_name, size in queues.items():
                            logger.info(f"   📋 Queue {queue_name}: {size} tasks")
                        
                        return True
                    else:
                        logger.error(f"   ❌ Health check failed: HTTP {response.status}")
                        return False
                        
        except Exception as e:
            logger.error(f"   ❌ Health check error: {e}")
            return False
    
    async def test_user_exists(self):
        """Test 2: User Management"""
        logger.info("🔍 Test 2: User Management")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.api_gateway_url}/api/v1/user/{self.test_user_id}") as response:
                    if response.status == 200:
                        data = await response.json()
                        logger.info(f"   ✅ User found: {data['username']}")
                        logger.info(f"   ✅ Language: {data['language']}")
                        logger.info(f"   ✅ Subscription: {data['subscription_tier']}")
                        return True
                    elif response.status == 404:
                        logger.error("   ❌ Test user not found in database")
                        return False
                    else:
                        logger.error(f"   ❌ User check failed: HTTP {response.status}")
                        return False
                        
        except Exception as e:
            logger.error(f"   ❌ User check error: {e}")
            return False
    
    async def test_youtube_video_processing(self):
        """Test 3: YouTube Video Processing"""
        logger.info("🔍 Test 3: YouTube Video Processing")
        
        test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"  # Rick Roll - short video
        
        try:
            async with aiohttp.ClientSession() as session:
                # Submit video processing task
                payload = {
                    "user_id": self.test_user_id,
                    "chat_id": self.test_chat_id,
                    "youtube_url": test_url,
                    "processing_type": "text_only",
                    "file_format": "markdown"
                }
                
                logger.info(f"   📤 Submitting video: {test_url}")
                
                async with session.post(
                    f"{self.api_gateway_url}/api/v1/video/process",
                    json=payload
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        task_id = data.get('task_id')
                        logger.info(f"   ✅ Task created: {task_id}")
                        
                        # Poll for completion
                        result = await self.poll_task_completion(task_id, timeout=180)  # 3 minutes
                        
                        if result:
                            logger.info("   ✅ Video processing completed successfully!")
                            
                            # Check if we got a transcript
                            if result.get('transcript'):
                                transcript_length = len(result['transcript'])
                                logger.info(f"   ✅ Transcript extracted: {transcript_length} characters")
                            
                            # Check if we got video info
                            video_info = result.get('video_info', {})
                            if video_info.get('title'):
                                logger.info(f"   ✅ Video title: {video_info['title']}")
                                logger.info(f"   ✅ Duration: {video_info.get('duration', 0)} seconds")
                            
                            return True
                        else:
                            logger.error("   ❌ Video processing failed or timed out")
                            return False
                    else:
                        error_text = await response.text()
                        logger.error(f"   ❌ Video submission failed: HTTP {response.status}")
                        logger.error(f"   ❌ Error: {error_text}")
                        return False
                        
        except Exception as e:
            logger.error(f"   ❌ Video processing error: {e}")
            return False
    
    async def test_ai_conversation(self):
        """Test 4: AI Conversation"""
        logger.info("🔍 Test 4: AI Conversation")
        
        try:
            async with aiohttp.ClientSession() as session:
                # Submit AI conversation task
                payload = {
                    "user_id": self.test_user_id,
                    "chat_id": self.test_chat_id,
                    "message": "Hello! Can you tell me about artificial intelligence?",
                    "context": "End-to-end test conversation"
                }
                
                logger.info("   📤 Submitting AI conversation...")
                
                async with session.post(
                    f"{self.api_gateway_url}/api/v1/ai/conversation",
                    json=payload
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        task_id = data.get('task_id')
                        logger.info(f"   ✅ AI task created: {task_id}")
                        
                        # Poll for completion
                        result = await self.poll_task_completion(task_id, timeout=60)  # 1 minute
                        
                        if result:
                            response_text = result.get('response', '')
                            if response_text and len(response_text.strip()) > 10:
                                logger.info("   ✅ AI conversation completed!")
                                logger.info(f"   ✅ Response length: {len(response_text)} characters")
                                logger.info(f"   ✅ Response preview: {response_text[:100]}...")
                                return True
                            else:
                                logger.error("   ❌ AI response is empty or too short")
                                return False
                        else:
                            logger.error("   ❌ AI conversation failed or timed out")
                            return False
                    else:
                        error_text = await response.text()
                        logger.error(f"   ❌ AI submission failed: HTTP {response.status}")
                        logger.error(f"   ❌ Error: {error_text}")
                        return False
                        
        except Exception as e:
            logger.error(f"   ❌ AI conversation error: {e}")
            return False
    
    async def test_queue_status(self):
        """Test 5: Queue Management"""
        logger.info("🔍 Test 5: Queue Management")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.api_gateway_url}/api/v1/queues/status") as response:
                    if response.status == 200:
                        data = await response.json()
                        queues = data.get('queues', {})
                        
                        logger.info("   ✅ Queue status retrieved:")
                        total_tasks = 0
                        for queue_name, queue_info in queues.items():
                            size = queue_info.get('size', 0)
                            total_tasks += size
                            logger.info(f"     📋 {queue_name}: {size} tasks")
                        
                        logger.info(f"   ✅ Total pending tasks: {total_tasks}")
                        return True
                    else:
                        logger.error(f"   ❌ Queue status failed: HTTP {response.status}")
                        return False
                        
        except Exception as e:
            logger.error(f"   ❌ Queue status error: {e}")
            return False
    
    async def poll_task_completion(self, task_id: str, timeout: int = 120):
        """Poll for task completion"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{self.api_gateway_url}/api/v1/task/{task_id}/status") as response:
                        if response.status == 200:
                            data = await response.json()
                            status = data.get('status')
                            
                            if status == 'completed':
                                return data.get('result')
                            elif status == 'failed':
                                error = data.get('error', 'Unknown error')
                                logger.error(f"   ❌ Task failed: {error}")
                                return None
                            elif status in ['pending', 'processing']:
                                logger.info(f"   ⏳ Task {status}... ({int(time.time() - start_time)}s)")
                            else:
                                logger.warning(f"   ⚠️ Unknown status: {status}")
                        else:
                            logger.warning(f"   ⚠️ Status check failed: HTTP {response.status}")
                
                await asyncio.sleep(5)  # Wait 5 seconds before next check
                
            except Exception as e:
                logger.warning(f"   ⚠️ Error checking task status: {e}")
                await asyncio.sleep(5)
        
        logger.error(f"   ❌ Task timed out after {timeout} seconds")
        return None
    
    async def run_all_tests(self):
        """Run complete test suite"""
        logger.info("🚀 Starting End-to-End Testing...")
        logger.info("=" * 60)
        
        tests = [
            ("API Gateway Health", self.test_api_gateway_health()),
            ("User Management", self.test_user_exists()),
            ("Queue Management", self.test_queue_status()),
            ("AI Conversation", self.test_ai_conversation()),
            ("YouTube Processing", self.test_youtube_video_processing()),
        ]
        
        results = []
        start_time = time.time()
        
        for test_name, test_coro in tests:
            logger.info("")
            test_start = time.time()
            result = await test_coro
            test_duration = time.time() - test_start
            
            results.append((test_name, result, test_duration))
            
            if result:
                logger.info(f"   ⏱️ Completed in {test_duration:.1f}s")
            
            logger.info("-" * 40)
        
        # Final results
        total_duration = time.time() - start_time
        passed = sum(1 for _, result, _ in results if result)
        total = len(results)
        
        logger.info("")
        logger.info("🏁 FINAL RESULTS")
        logger.info("=" * 60)
        
        for test_name, result, duration in results:
            status = "✅ PASS" if result else "❌ FAIL"
            logger.info(f"{test_name:25} {status:8} ({duration:.1f}s)")
        
        logger.info("=" * 60)
        logger.info(f"Total: {passed}/{total} tests passed")
        logger.info(f"Duration: {total_duration:.1f} seconds")
        
        if passed == total:
            logger.info("🎉 ALL TESTS PASSED! System is fully functional!")
        else:
            logger.warning("⚠️ Some tests failed. Check the logs above.")
        
        return passed == total

async def main():
    """Main entry point"""
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    tester = EndToEndTester()
    
    try:
        success = await tester.run_all_tests()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("Testing interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Test runner failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
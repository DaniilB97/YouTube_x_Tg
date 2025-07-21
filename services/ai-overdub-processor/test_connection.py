import asyncio
import aiohttp
import os
import logging
import json
import time

# Configure detailed logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/tmp/ollama_test.log')
    ]
)
logger = logging.getLogger(__name__)

async def test_network_connectivity():
    """Test basic network connectivity"""
    logger.info("🌐 Testing network connectivity...")
    
    try:
        # Test DNS resolution
        import socket
        ollama_host = "ollama"
        ip = socket.gethostbyname(ollama_host)
        logger.info(f"✅ DNS resolution successful: {ollama_host} -> {ip}")
        
        # Test port connectivity
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((ollama_host, 11434))
        sock.close()
        
        if result == 0:
            logger.info("✅ Port 11434 is open on ollama service")
            return True
        else:
            logger.error(f"❌ Port 11434 is closed on ollama service (error code: {result})")
            return False
            
    except socket.gaierror as e:
        logger.error(f"❌ DNS resolution failed: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Network test failed: {e}")
        return False

async def test_ollama_api():
    """Test Ollama API endpoints"""
    ollama_endpoint = os.getenv('OLLAMA_ENDPOINT', 'http://ollama:11434')
    
    logger.info(f"🔍 Testing Ollama API at: {ollama_endpoint}")
    
    test_endpoints = [
        ("/", "Root endpoint"),
        ("/api/tags", "Models list"),
        ("/api/version", "Version info")
    ]
    
    results = {}
    
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            
            for endpoint, description in test_endpoints:
                url = f"{ollama_endpoint}{endpoint}"
                logger.info(f"📡 Testing {description}: {url}")
                
                try:
                    async with session.get(url) as response:
                        logger.info(f"   Status: {response.status}")
                        
                        if response.status == 200:
                            try:
                                data = await response.json()
                                results[endpoint] = data
                                logger.info(f"   ✅ {description} - OK")
                                
                                if endpoint == "/api/tags":
                                    models = data.get('models', [])
                                    if models:
                                        logger.info(f"   📋 Available models: {[m['name'] for m in models]}")
                                    else:
                                        logger.warning(f"   ⚠️ No models available")
                                        
                            except json.JSONDecodeError:
                                text = await response.text()
                                logger.info(f"   📄 Response (text): {text[:200]}")
                                results[endpoint] = text
                        else:
                            error_text = await response.text()
                            logger.warning(f"   ⚠️ {description} - Status {response.status}: {error_text[:200]}")
                            
                except asyncio.TimeoutError:
                    logger.error(f"   ❌ {description} - Timeout")
                except Exception as e:
                    logger.error(f"   ❌ {description} - Error: {e}")
                    
    except Exception as e:
        logger.error(f"❌ Session creation failed: {e}")
        
    return results

async def test_model_interaction():
    """Test actual model interaction"""
    ollama_endpoint = os.getenv('OLLAMA_ENDPOINT', 'http://ollama:11434')
    model_name = os.getenv('OLLAMA_MODEL', 'llama3.1:8b')
    
    logger.info(f"🤖 Testing model interaction with: {model_name}")
    
    # Simple test prompt
    test_prompt = "Hello! Please respond with exactly these words: AI_TEST_SUCCESS"
    
    payload = {
        "model": model_name,
        "prompt": test_prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 50
        }
    }
    
    try:
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            
            url = f"{ollama_endpoint}/api/generate"
            logger.info(f"📡 Sending test prompt to: {url}")
            
            start_time = time.time()
            async with session.post(url, json=payload) as response:
                duration = time.time() - start_time
                
                logger.info(f"   Status: {response.status}")
                logger.info(f"   Duration: {duration:.2f}s")
                
                if response.status == 200:
                    data = await response.json()
                    response_text = data.get('response', '').strip()
                    
                    logger.info(f"   📝 Model response: {response_text}")
                    
                    if 'AI_TEST_SUCCESS' in response_text:
                        logger.info(f"   ✅ Model interaction test - SUCCESS")
                        return True
                    else:
                        logger.warning(f"   ⚠️ Model responded but with unexpected content")
                        return True  # Still working, just different response
                else:
                    error_text = await response.text()
                    logger.error(f"   ❌ Model interaction failed - Status {response.status}: {error_text}")
                    return False
                    
    except asyncio.TimeoutError:
        logger.error(f"   ❌ Model interaction - Timeout (model might be loading)")
        return False
    except Exception as e:
        logger.error(f"   ❌ Model interaction failed: {e}")
        return False

async def pull_model_if_needed():
    """Try to pull the model if it's not available"""
    ollama_endpoint = os.getenv('OLLAMA_ENDPOINT', 'http://ollama:11434')
    model_name = os.getenv('OLLAMA_MODEL', 'llama3.1:8b')
    
    logger.info(f"🔄 Attempting to pull model: {model_name}")
    
    payload = {
        "name": model_name,
        "stream": False
    }
    
    try:
        timeout = aiohttp.ClientTimeout(total=600)  # 10 minutes for model download
        async with aiohttp.ClientSession(timeout=timeout) as session:
            
            url = f"{ollama_endpoint}/api/pull"
            logger.info(f"📡 Pulling model from: {url}")
            
            async with session.post(url, json=payload) as response:
                logger.info(f"   Status: {response.status}")
                
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"   ✅ Model pull successful: {data}")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"   ❌ Model pull failed - Status {response.status}: {error_text}")
                    return False
                    
    except asyncio.TimeoutError:
        logger.error(f"   ❌ Model pull timeout (this is normal for large models)")
        return False
    except Exception as e:
        logger.error(f"   ❌ Model pull failed: {e}")
        return False

async def comprehensive_ollama_test():
    """Run comprehensive Ollama connectivity test"""
    logger.info("=" * 60)
    logger.info("🚀 COMPREHENSIVE OLLAMA CONNECTIVITY TEST")
    logger.info("=" * 60)
    
    test_results = {
        'network': False,
        'api': False,
        'model_available': False,
        'model_interaction': False
    }
    
    # 1. Network connectivity test
    logger.info("\n" + "─" * 40)
    logger.info("1️⃣ NETWORK CONNECTIVITY TEST")
    logger.info("─" * 40)
    test_results['network'] = await test_network_connectivity()
    
    if not test_results['network']:
        logger.error("❌ Network test failed. Cannot proceed with API tests.")
        return test_results
    
    # 2. API endpoints test
    logger.info("\n" + "─" * 40)
    logger.info("2️⃣ API ENDPOINTS TEST")
    logger.info("─" * 40)
    api_results = await test_ollama_api()
    test_results['api'] = bool(api_results)
    
    # 3. Check if model is available
    logger.info("\n" + "─" * 40)
    logger.info("3️⃣ MODEL AVAILABILITY TEST")
    logger.info("─" * 40)
    
    if '/api/tags' in api_results:
        models = api_results['/api/tags'].get('models', [])
        model_name = os.getenv('OLLAMA_MODEL', 'llama3.1:8b')
        available_models = [m['name'] for m in models]
        
        if model_name in available_models:
            logger.info(f"✅ Target model {model_name} is available")
            test_results['model_available'] = True
        elif available_models:
            logger.warning(f"⚠️ Target model {model_name} not found, but other models available: {available_models}")
            # Update the model to use the first available one
            os.environ['OLLAMA_MODEL'] = available_models[0]
            logger.info(f"🔄 Switching to available model: {available_models[0]}")
            test_results['model_available'] = True
        else:
            logger.warning(f"⚠️ No models available. Attempting to pull {model_name}...")
            pull_success = await pull_model_if_needed()
            test_results['model_available'] = pull_success
    
    # 4. Model interaction test
    if test_results['model_available']:
        logger.info("\n" + "─" * 40)
        logger.info("4️⃣ MODEL INTERACTION TEST")
        logger.info("─" * 40)
        test_results['model_interaction'] = await test_model_interaction()
    
    # Final results
    logger.info("\n" + "=" * 60)
    logger.info("📊 TEST RESULTS SUMMARY")
    logger.info("=" * 60)
    
    for test_name, result in test_results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{test_name.upper().replace('_', ' ')}: {status}")
    
    overall_status = all(test_results.values())
    logger.info(f"\n🎯 OVERALL STATUS: {'✅ ALL TESTS PASSED' if overall_status else '❌ SOME TESTS FAILED'}")
    
    if not overall_status:
        logger.info("\n💡 TROUBLESHOOTING TIPS:")
        if not test_results['network']:
            logger.info("   - Check that ollama container is running: docker ps")
            logger.info("   - Verify both containers are on the same network")
        if not test_results['api']:
            logger.info("   - Ollama service might still be starting up")
            logger.info("   - Try: docker logs yt-summarizer-ollama")
        if not test_results['model_available']:
            logger.info("   - Pull model manually: docker exec yt-summarizer-ollama ollama pull llama3.1:8b")
        if not test_results['model_interaction']:
            logger.info("   - Model might be loading into memory")
            logger.info("   - Wait a few minutes and try again")
    
    return test_results

if __name__ == "__main__":
    try:
        import aiohttp
    except ImportError:
        print("❌ Please install aiohttp: pip install aiohttp")
        exit(1)
        
    # Set environment variables if not present
    if not os.getenv('OLLAMA_ENDPOINT'):
        os.environ['OLLAMA_ENDPOINT'] = 'http://ollama:11434'
    if not os.getenv('OLLAMA_MODEL'):
        os.environ['OLLAMA_MODEL'] = 'llama3.1:8b'
        
    asyncio.run(comprehensive_ollama_test())
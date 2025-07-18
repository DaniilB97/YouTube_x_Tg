# services/ai-processor/main.py - УЛУЧШЕННАЯ ВЕРСИЯ
import os
import asyncio
import logging
import tempfile
import shutil
from datetime import datetime
from typing import Optional, Dict, Tuple

# Import shared components
import sys
sys.path.append('/app')
from shared.database import get_redis
from shared.models import TaskData, TaskType, TaskStatus, SummaryType
from shared.utils import generate_task_id

# AI Libraries
import aiohttp
import google.generativeai as genai
import torch
import whisper
from pydub import AudioSegment

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AIProcessor:
    """Handles AI processing with Gemini and Ollama"""
    
    def __init__(self):
        # Initialize Gemini
        try:
            genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
            self.gemini_model = genai.GenerativeModel('gemini-2.0-flash-exp')
            self.gemini_available = True
            logger.info("✅ Gemini API initialized")
        except Exception as e:
            logger.warning(f"Gemini API not available: {e}")
            self.gemini_model = None
            self.gemini_available = False
        
        # Ollama configuration
        self.ollama_endpoint = os.getenv('OLLAMA_ENDPOINT', 'http://ollama:11434')
        self.ollama_model = os.getenv('OLLAMA_MODEL', 'llama3.1:8b')
        self.ollama_available = False
        self.ollama_check_task = None
        
        logger.info(f"🔍 Ollama endpoint: {self.ollama_endpoint}")
        logger.info(f"🔍 Ollama model: {self.ollama_model}")
    
    async def initialize(self):
        """Initialize the AI processor"""
        # Start Ollama availability check
        self.ollama_check_task = asyncio.create_task(self.check_ollama_availability())
        await asyncio.sleep(2)  # Give it a moment to start checking
    
    async def check_ollama_availability(self):
        """Check if Ollama is running and model is available - УЛУЧШЕННАЯ ВЕРСИЯ"""
        max_retries = 30  # Увеличено количество попыток
        retry_count = 0
        initial_delay = 10  # Начальная задержка для старта Ollama
        
        logger.info(f"⏳ Waiting {initial_delay}s for Ollama service to start...")
        await asyncio.sleep(initial_delay)
        
        while retry_count < max_retries:
            try:
                timeout = aiohttp.ClientTimeout(total=15)  # Увеличен timeout
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    logger.info(f"🔄 Checking Ollama connection (attempt {retry_count + 1}/{max_retries})")
                    
                    # Сначала проверим базовую доступность
                    async with session.get(f"{self.ollama_endpoint}/api/tags") as response:
                        if response.status == 200:
                            data = await response.json()
                            models = [model['name'] for model in data.get('models', [])]
                            
                            logger.info(f"📋 Available models: {models}")
                            
                            if self.ollama_model in models:
                                self.ollama_available = True
                                logger.info(f"✅ Ollama ready with model: {self.ollama_model}")
                                return
                            elif models:
                                # Если наша модель недоступна, но есть другие
                                self.ollama_model = models[0]
                                self.ollama_available = True
                                logger.info(f"✅ Using available model: {self.ollama_model}")
                                return
                            else:
                                logger.info(f"⏳ Ollama running but no models loaded yet...")
                                # Попробуем загрузить модель
                                await self.try_pull_model(session)
                        else:
                            logger.warning(f"⚠️ Ollama responded with status {response.status}")
                            
            except aiohttp.ClientConnectorError as e:
                logger.info(f"⏳ Waiting for Ollama service... (attempt {retry_count + 1}/{max_retries})")
                if retry_count < 5:  # Показываем детали только первые несколько раз
                    logger.debug(f"Connection details: {e}")
            except asyncio.TimeoutError:
                logger.info(f"⏳ Ollama connection timeout (attempt {retry_count + 1}/{max_retries})")
            except Exception as e:
                logger.warning(f"⚠️ Ollama check error: {e}")
            
            retry_count += 1
            if retry_count < max_retries:
                # Экспоненциальная задержка с максимумом
                delay = min(5 + (retry_count * 2), 30)
                await asyncio.sleep(delay)
        
        logger.error(f"❌ Failed to connect to Ollama after {max_retries} attempts")
        logger.error("💡 Try: docker exec -it yt-summarizer-ollama ollama pull llama3.1:8b")
    
    async def try_pull_model(self, session):
        """Попытка загрузить модель в Ollama"""
        try:
            logger.info(f"🔄 Attempting to pull model {self.ollama_model}...")
            payload = {
                "name": self.ollama_model,
                "stream": False
            }
            async with session.post(
                f"{self.ollama_endpoint}/api/pull", 
                json=payload,
                timeout=aiohttp.ClientTimeout(total=300)  # 5 минут на загрузку
            ) as response:
                if response.status == 200:
                    logger.info(f"✅ Model {self.ollama_model} pulled successfully")
                else:
                    logger.warning(f"⚠️ Failed to pull model: {response.status}")
        except Exception as e:
            logger.warning(f"⚠️ Error pulling model: {e}")
    
    async def generate_summary(self, transcript: str, summary_type: str, title: str, language: str = 'en') -> str:
        """Generate summary using available AI service"""
        
        # Convert string to SummaryType enum
        if summary_type == 'short':
            summary_enum = SummaryType.SHORT
        elif summary_type == 'medium':
            summary_enum = SummaryType.MEDIUM
        elif summary_type == 'detailed':
            summary_enum = SummaryType.DETAILED
        else:
            summary_enum = SummaryType.SHORT
        
        # Try Ollama first (faster, local, free)
        if self.ollama_available:
            try:
                logger.info("🤖 Generating summary with Ollama...")
                summary = await self._generate_with_ollama(transcript, summary_enum, title, language)
                if summary and len(summary.strip()) > 10:
                    logger.info("✅ Generated summary with Ollama")
                    return summary
                else:
                    logger.warning("⚠️ Ollama returned empty/short summary")
            except Exception as e:
                logger.error(f"❌ Ollama failed: {e}")
                self.ollama_available = False  # Пометить как недоступный
        
        # Fallback to Gemini
        if self.gemini_available:
            try:
                logger.info("🤖 Generating summary with Gemini...")
                summary = await self._generate_with_gemini(transcript, summary_enum, title, language)
                if summary and len(summary.strip()) > 10:
                    logger.info("✅ Generated summary with Gemini")
                    return summary
            except Exception as e:
                logger.error(f"❌ Gemini failed: {e}")
        
        # If both fail, return error message
        logger.warning("⚠️ All AI services failed, using fallback")
        return self._get_fallback_summary(transcript, summary_enum, title)
    
    async def _generate_with_ollama(self, transcript: str, summary_type: SummaryType, title: str, language: str) -> str:
        """Generate summary using Ollama API - УЛУЧШЕННАЯ ВЕРСИЯ"""
        
        if not self.ollama_available:
            raise Exception("Ollama service not available")
        
        prompts = self._get_ollama_prompts(language)
        
        # Ограничиваем длину транскрипта в зависимости от модели
        max_length = 6000 if 'llama3.1:8b' in self.ollama_model else 4000
        transcript_truncated = transcript[:max_length]
        
        prompt_text = prompts[summary_type].format(
            title=title,
            transcript=transcript_truncated
        )
        
        payload = {
            "model": self.ollama_model,
            "prompt": prompt_text,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9,
                "num_predict": self._get_max_tokens(summary_type),
                "stop": ["</summary>", "[END]", "\n\nUser:", "\n\nHuman:"],
                "repeat_penalty": 1.1
            }
        }
        
        timeout = aiohttp.ClientTimeout(total=180)  # 3 минуты timeout
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{self.ollama_endpoint}/api/generate", 
                json=payload
            ) as response:
                
                if response.status == 200:
                    data = await response.json()
                    result = data.get('response', '').strip()
                    
                    # Проверка качества ответа
                    if len(result) < 20:
                        raise Exception(f"Response too short: {result}")
                    
                    return result
                else:
                    error_text = await response.text()
                    raise Exception(f"Ollama API error {response.status}: {error_text}")
    
    def _get_ollama_prompts(self, language: str) -> dict:
        """Get language-specific prompts for Ollama - УЛУЧШЕННЫЕ ПРОМПТЫ"""
        
        if language == 'ru':
            return {
                SummaryType.SHORT: """Ты - профессиональный редактор. Создай краткое резюме YouTube видео на русском языке.

Название: {title}

Транскрипт:
{transcript}

Требования:
- 2-3 предложения
- Основные идеи
- Четкий русский язык

Краткое резюме:""",
                
                SummaryType.MEDIUM: """Ты - аналитик контента. Создай подробное резюме YouTube видео на русском языке.

Название: {title}

Транскрипт:
{transcript}

Требования:
- 1-2 абзаца
- Ключевые моменты и выводы
- Структурированно

Подробное резюме:""",
                
                SummaryType.DETAILED: """Ты - эксперт по анализу контента. Создай детальный анализ YouTube видео.

Название: {title}

Транскрипт:
{transcript}

Создай структурированный анализ включающий:
- Основную тему
- Ключевые аргументы
- Практические выводы

Детальный анализ:"""
            }
        else:  # English
            return {
                SummaryType.SHORT: """You are a professional content editor. Create a brief summary of this YouTube video.

Title: {title}

Transcript:
{transcript}

Requirements:
- 2-3 sentences
- Main ideas only
- Clear and concise

Brief Summary:""",
                
                SummaryType.MEDIUM: """You are a content analyst. Create a comprehensive summary of this YouTube video.

Title: {title}

Transcript:
{transcript}

Requirements:
- 1-2 paragraphs
- Key points and insights
- Well structured

Comprehensive Summary:""",
                
                SummaryType.DETAILED: """You are a content analysis expert. Create a detailed analysis of this YouTube video.

Title: {title}

Transcript:
{transcript}

Create a structured analysis including:
- Main topic
- Key arguments
- Practical takeaways

Detailed Analysis:"""
            }
    
    def _get_max_tokens(self, summary_type: SummaryType) -> int:
        """Get max tokens based on summary type"""
        return {
            SummaryType.SHORT: 100,
            SummaryType.MEDIUM: 300,
            SummaryType.DETAILED: 600
        }[summary_type]
    
    async def _generate_with_gemini(self, transcript: str, summary_type: SummaryType, title: str, language: str) -> str:
        """Generate summary using Gemini API"""
        if not self.gemini_available:
            raise Exception("Gemini not available")
            
        prompts = {
            SummaryType.SHORT: f"""
            Create a concise summary of this YouTube video transcript in 2-3 sentences.
            
            Video Title: {title}
            Language: {language}
            
            Transcript:
            {transcript}
            
            Summary:
            """,
            
            SummaryType.MEDIUM: f"""
            Create a comprehensive summary of this YouTube video transcript in 1-2 paragraphs.
            
            Video Title: {title}
            Language: {language}
            
            Transcript:
            {transcript}
            
            Summary:
            """,
            
            SummaryType.DETAILED: f"""
            Create a detailed analysis of this YouTube video transcript.
            
            Video Title: {title}
            Language: {language}
            
            Transcript:
            {transcript}
            
            Detailed Analysis:
            """
        }
        
        response = await asyncio.to_thread(
            self.gemini_model.generate_content,
            prompts[summary_type]
        )
        
        return response.text
    
    def _get_fallback_summary(self, transcript: str, summary_type: SummaryType, title: str) -> str:
        """Generate a basic fallback summary when AI services fail"""
        
        words = transcript.split()
        word_count = len(words)
        
        sentences = transcript.split('.')[:3]
        basic_summary = '. '.join(sentences) + '.'
        
        return f"""[AI Service Unavailable - Basic Summary]

Title: {title}
Duration: ~{word_count // 150} minutes (estimated)

Basic Content Preview:
{basic_summary[:500]}...

Note: AI summarization services are currently unavailable."""

class AudioProcessor:
    """Process audio files with Whisper"""
    
    def __init__(self):
        self.whisper_models = {
            'base': None,
            'small': None,
            'medium': None
        }
        self.current_model_name = 'base'
        self.current_model = None
    
    def load_whisper_model(self, model_name: str = 'base'):
        """Load Whisper model"""
        try:
            if model_name not in self.whisper_models:
                model_name = 'base'
            
            if self.whisper_models[model_name] is None:
                logger.info(f"Loading Whisper model: {model_name}")
                device = "cuda" if torch.cuda.is_available() else "cpu"
                logger.info(f"Using device: {device}")
                self.whisper_models[model_name] = whisper.load_model(model_name, device=device)
            
            self.current_model = self.whisper_models[model_name]
            self.current_model_name = model_name
            return True
            
        except Exception as e:
            logger.error(f"Error loading Whisper model {model_name}: {e}")
            return False
    
    async def transcribe_audio(self, audio_path: str) -> Optional[Tuple[str, str, int]]:
        """Transcribe audio file"""
        try:
            if not self.current_model:
                if not self.load_whisper_model('base'):
                    raise Exception("Failed to load Whisper model")
            
            logger.info(f"Transcribing with Whisper model: {self.current_model_name}")
            
            # Get audio duration
            audio = AudioSegment.from_file(audio_path)
            duration = len(audio) // 1000  # Convert to seconds
            
            # Transcribe
            result = self.current_model.transcribe(audio_path)
            
            return result["text"], result["language"], duration
            
        except Exception as e:
            logger.error(f"Error transcribing audio: {e}")
            return None, None, 0

class AIProcessorService:
    """Main AI processing service"""
    
    def __init__(self):
        self.redis = get_redis()
        self.ai_processor = AIProcessor()
        self.audio_processor = AudioProcessor()
        self.queue_name = 'ai_processing_queue'
    
    async def start(self):
        """Start the AI processing service"""
        await self.redis.connect()
        logger.info("✅ AI Processor Service starting...")
        
        # --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
        # Мы больше не запускаем проверку в фоне, а ЖДЕМ ее завершения.
        # Метод initialize() больше не нужен, если он только запускал фоновую задачу.
        logger.info("⏳ Initializing AI providers... This may take a moment.")
        await self.ai_processor.check_ollama_availability()
        
        # Этот лог теперь будет означать, что ВСЕ готово, включая Ollama.
        logger.info("✅ AI Processor Service fully ready. Starting task processing.")
        
        # Start processing loop
        while True:
            try:
                await self.process_tasks()
            except Exception as e:
                logger.error(f"Error in processing loop: {e}")
                await asyncio.sleep(5)
    
    async def process_tasks(self):
        """Process AI tasks from queue"""
        try:
            task_data = await self.redis.dequeue_task(self.queue_name, timeout=30)
            
            if task_data:
                logger.info(f"Processing AI task {task_data.task_id}")
                await self.process_ai_task(task_data)
            
        except Exception as e:
            logger.error(f"Error processing tasks: {e}")
    
    async def process_ai_task(self, task_data: TaskData):
        """Process a single AI task"""
        try:
            await self.redis.set_task_status(task_data.task_id, TaskStatus.PROCESSING)
            
            if task_data.task_type == TaskType.AI_CONVERSATION:
                result = await self.process_conversation(task_data)
            elif task_data.task_type == TaskType.AUDIO_PROCESSING:
                result = await self.process_audio(task_data)
            else:
                result = await self.process_summary_generation(task_data)
            
            await self.redis.set_task_status(
                task_data.task_id, 
                TaskStatus.COMPLETED, 
                result=result
            )
            
            logger.info(f"✅ Completed AI task {task_data.task_id}")
            
        except Exception as e:
            logger.error(f"Error processing AI task: {e}")
            await self.redis.set_task_status(
                task_data.task_id, 
                TaskStatus.FAILED, 
                error=str(e)
            )
    
    async def process_conversation(self, task_data: TaskData) -> Dict:
        """Process AI conversation"""
        message = task_data.data.get('message')
        context = task_data.data.get('context', '')
        language = task_data.data.get('user_language', 'en')
        
        # Simple conversation for now
        response = await self.ai_processor.generate_summary(
            f"Context: {context}\nUser message: {message}", 
            'short', 
            "Conversation", 
            language
        )
        
        return {
            'response': response,
            'conversation_id': task_data.data.get('conversation_id'),
            'timestamp': datetime.now().isoformat()
        }
    
    async def process_audio(self, task_data: TaskData) -> Dict:
        """Process audio transcription"""
        file_path = task_data.data.get('file_path')
        
        if not file_path or not os.path.exists(file_path):
            raise Exception("Audio file not found")
        
        transcript, language, duration = await self.audio_processor.transcribe_audio(file_path)
        
        if not transcript:
            raise Exception("Failed to transcribe audio")
        
        return {
            'transcript': transcript,
            'language': language,
            'duration': duration,
            'file_path': file_path
        }
    
    async def process_summary_generation(self, task_data: TaskData) -> Dict:
        """Process summary generation"""
        transcript = task_data.data.get('transcript')
        title = task_data.data.get('title', 'Video')
        language = task_data.data.get('language', 'en')
        
        if not transcript:
            raise Exception("No transcript provided")
        
        # Generate all three types of summaries
        summaries = {}
        for summary_type in ['short', 'medium', 'detailed']:
            summary = await self.ai_processor.generate_summary(
                transcript, summary_type, title, language
            )
            summaries[f'summary_{summary_type}'] = summary
        
        return summaries

async def main():
    """Main entry point"""
    service = AIProcessorService()
    await service.start()

if __name__ == "__main__":
    asyncio.run(main())
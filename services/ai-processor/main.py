# Этот файл создает AI Processing Service ТОЛЬКО для AI функций - Ollama, Gemini, Summary Generation

# services/ai-processor/main.py
import os
import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, List, Tuple 

# Import shared components
import sys
sys.path.append('/app')
from shared.database import get_redis
from shared.models import TaskData, TaskType, TaskStatus, SummaryType
from shared.utils import generate_task_id

# AI Libraries ONLY
import aiohttp
import google.generativeai as genai

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AIProcessor:
    """Handles ONLY AI processing with Gemini and Ollama - NO AUDIO"""
    
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
        self.ollama_model = os.getenv('OLLAMA_MODEL', 'llama3.1:latest')
        self.ollama_available = False
        self.ollama_check_task = None
        
        logger.info(f"🔍 Ollama endpoint: {self.ollama_endpoint}")
        logger.info(f"🔍 Ollama model: {self.ollama_model}")
    
    async def initialize(self):
        """Initialize the AI processor"""
        logger.info("⏳ Initializing AI providers... This may take a moment.")
        
        # Start Ollama availability check
        self.ollama_check_task = asyncio.create_task(self.check_ollama_availability())
        await asyncio.sleep(2)  # Give it a moment to start checking
    
    async def check_ollama_availability(self):
        """Check if Ollama is running and model is available"""
        max_retries = 30
        retry_count = 0
        initial_delay = 10
        
        logger.info(f"⏳ Waiting {initial_delay}s for Ollama service to start...")
        await asyncio.sleep(initial_delay)
        
        while retry_count < max_retries:
            try:
                timeout = aiohttp.ClientTimeout(total=15)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    logger.info(f"🔄 Checking Ollama connection (attempt {retry_count + 1}/{max_retries})")
                    
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
                                self.ollama_model = models[0]
                                self.ollama_available = True
                                logger.info(f"✅ Using available model: {self.ollama_model}")
                                return
                            else:
                                logger.info(f"⏳ Ollama running but no models loaded yet...")
                                await self.try_pull_model(session)
                        else:
                            logger.warning(f"⚠️ Ollama responded with status {response.status}")
                            
            except aiohttp.ClientConnectorError:
                logger.info(f"⏳ Waiting for Ollama service... (attempt {retry_count + 1}/{max_retries})")
            except asyncio.TimeoutError:
                logger.info(f"⏳ Ollama connection timeout (attempt {retry_count + 1}/{max_retries})")
            except Exception as e:
                logger.warning(f"⚠️ Ollama check error: {e}")
            
            retry_count += 1
            if retry_count < max_retries:
                delay = min(5 + (retry_count * 2), 30)
                await asyncio.sleep(delay)
        
        logger.error(f"❌ Failed to connect to Ollama after {max_retries} attempts")
    
    async def try_pull_model(self, session):
        """Try to pull model in Ollama"""
        try:
            logger.info(f"🔄 Attempting to pull model {self.ollama_model}...")
            payload = {"name": self.ollama_model, "stream": False}
            async with session.post(
                f"{self.ollama_endpoint}/api/pull", 
                json=payload,
                timeout=aiohttp.ClientTimeout(total=300)
            ) as response:
                if response.status == 200:
                    logger.info(f"✅ Model {self.ollama_model} pulled successfully")
                else:
                    logger.warning(f"⚠️ Failed to pull model: {response.status}")
        except Exception as e:
            logger.warning(f"⚠️ Error pulling model: {e}")
    
    async def generate_summary(self, transcript: str, summary_type: str, title: str, language: str = 'en', visual_context: str = "") -> str:
        """Generate summary using available AI service with optional visual context"""
        
        # 🔥 ДОБАВИТЬ ОБРАБОТКУ ВИЗУАЛЬНОГО КОНТЕКСТА:
        if visual_context:
            enhanced_transcript = f"""
    {visual_context}

    АУДИО ТРАНСКРИПТ:
    {transcript}
    """
            logger.info("🎬 Including visual context in summary generation")
        else:
            enhanced_transcript = transcript
        
        # Convert string to SummaryType enum
        if summary_type == 'short':
            summary_enum = SummaryType.SHORT
        elif summary_type == 'medium':
            summary_enum = SummaryType.MEDIUM
        elif summary_type == 'detailed':
            summary_enum = SummaryType.DETAILED
        else:
            summary_enum = SummaryType.SHORT
        
        # 🔥 ЗАМЕНИТЬ transcript НА enhanced_transcript В ВЫЗОВАХ:
        if self.gemini_available:
            try:
                logger.info("🤖 Generating summary with Gemini...")
                summary = await self._generate_with_gemini(enhanced_transcript, summary_enum, title, language)
                if summary and len(summary.strip()) > 10:
                    logger.info("✅ Generated summary with Gemini")
                    return summary
                else:
                    logger.warning("⚠️ Gemini returned empty/short summary")
            except Exception as e:
                logger.error(f"❌ Gemini failed: {e}")
                self.gemini_available = False

        # Fallback to Ollama
        if self.ollama_available:
            try:
                logger.info("🤖 Generating summary with Ollama...")
                summary = await self._generate_with_ollama(enhanced_transcript, summary_enum, title, language)
                if summary and len(summary.strip()) > 10:
                    logger.info("✅ Generated summary with Ollama")
                    return summary
            except Exception as e:
                logger.error(f"❌ Ollama failed: {e}")

        # If both fail, return error message
        logger.warning("⚠️ All AI services failed, using fallback")
        return self._get_fallback_summary(enhanced_transcript, summary_enum, title)
    
    async def _generate_with_ollama(self, transcript: str, summary_type: SummaryType, title: str, language: str) -> str:
        """Generate summary using Ollama API"""
        
        if not self.ollama_available:
            raise Exception("Ollama service not available")
        
        prompts = self._get_ollama_prompts(language)
        
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
        
        timeout = aiohttp.ClientTimeout(total=180)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{self.ollama_endpoint}/api/generate", 
                json=payload
            ) as response:
                
                if response.status == 200:
                    data = await response.json()
                    result = data.get('response', '').strip()
                    
                    if len(result) < 20:
                        raise Exception(f"Response too short: {result}")
                    
                    return result
                else:
                    error_text = await response.text()
                    raise Exception(f"Ollama API error {response.status}: {error_text}")
    
    def _get_ollama_prompts(self, language: str) -> dict:
        """Get language-specific prompts for Ollama"""
        
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

class AIProcessorService:
    """Main AI processing service - ONLY AI FUNCTIONS"""
    
    def __init__(self):
        self.redis = get_redis()
        self.ai_processor = AIProcessor()
        self.queue_name = 'ai_processing_queue'
    
    async def start(self):
        """Start the AI processing service"""
        await self.redis.connect()
        logger.info("✅ AI Processor Service starting...")
        
        # Initialize AI processor
        await self.ai_processor.initialize()
        
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
                await self.redis.set_task_status(
                    task_data.task_id, 
                    TaskStatus.COMPLETED, 
                    result=result
                )
                
            elif task_data.task_type == TaskType.SUMMARY_GENERATION:
                # Генерируем саммари
                result = await self.process_summary_generation(task_data)
                
                # Создаем File Manager задачу
                await self.create_file_manager_task(task_data, result)
                
            else:
                # Legacy обработка
                result = await self.process_summary_generation(task_data)
                await self.redis.set_task_status(
                    task_data.task_id, 
                    TaskStatus.COMPLETED, 
                    result=result
                )
            
            logger.info(f"✅ Completed AI task {task_data.task_id}")
            
        except Exception as e:
            logger.error(f"❌ Error processing AI task: {e}")
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
        
        # Simple conversation
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
    
    async def process_summary_generation(self, task_data: TaskData) -> Dict:
        """Process summary generation"""
        transcript = task_data.data.get('transcript')
        title = task_data.data.get('title', 'Video')
        language = task_data.data.get('language', 'en')
        processing_type = task_data.data.get('processing_type', 'text_only')  # 🔥 ДОБАВИТЬ
        frames_data = task_data.data.get('frames_data', [])  # 🔥 ДОБАВИТЬ
        
        if not transcript:
            raise Exception("No transcript provided")
        
        # 🔥 НОВОЕ: Анализ кадров для полного анализа
        visual_context = ""
        if processing_type == 'full_analysis' and frames_data:
            logger.info(f"🎬 Analyzing {len(frames_data)} frames for visual context")
            visual_context = await self.analyze_video_frames(frames_data, title)
        
        # Generate all three types of summaries with visual context
        summaries = {}
        for summary_type in ['short', 'medium', 'detailed']:
            # 🔥 ПЕРЕДАЕМ ВИЗУАЛЬНЫЙ КОНТЕКСТ
            summary = await self.ai_processor.generate_summary(
                transcript, 
                summary_type, 
                title, 
                language,
                visual_context=visual_context  # 🔥 НОВЫЙ ПАРАМЕТР
            )
            summaries[f'summary_{summary_type}'] = summary
        
        return summaries
    
    async def analyze_video_frames(self, frames_data: List[Dict], title: str) -> str:
        """Analyze video frames and generate visual context"""
        try:
            if not frames_data:
                return ""
            
            logger.info(f"🎬 Starting frame analysis for {len(frames_data)} frames")
            
            # Группируем кадры по типу контента
            text_frames = [f for f in frames_data if f.get('analysis', {}).get('has_text', False)]
            chart_frames = [f for f in frames_data if f.get('analysis', {}).get('has_charts', False)]
            key_frames = [f for f in frames_data if f.get('is_key_frame', False)]
            
            visual_insights = []
            
            # Анализируем ключевые кадры
            if key_frames:
                visual_insights.append(f"📸 Обнаружено {len(key_frames)} ключевых визуальных сцен")
            
            # Анализируем текстовый контент
            if text_frames:
                visual_insights.append(f"📝 Найдено {len(text_frames)} кадров с текстом/презентациями")
            
            # Анализируем графики и диаграммы
            if chart_frames:
                visual_insights.append(f"📊 Обнаружено {len(chart_frames)} кадров с графиками/диаграммами")
            
            # Временная разметка
            if frames_data:
                timestamps = [f.get('timestamp', 0) for f in frames_data]
                total_duration = max(timestamps) if timestamps else 0
                visual_insights.append(f"⏱️ Визуальный анализ покрывает {total_duration:.1f} секунд видео")
            
            # Формируем контекст для AI
            if visual_insights:
                visual_context = f"""
    ВИЗУАЛЬНЫЙ КОНТЕКСТ ВИДЕО "{title}":
    {chr(10).join(visual_insights)}

    Дополнительные детали:
    - Общее количество проанализированных кадров: {len(frames_data)}
    - Кадры с высокой сложностью (много деталей): {len([f for f in frames_data if f.get('analysis', {}).get('edge_density', 0) > 0.1])}
    - Яркие кадры (хорошее освещение): {len([f for f in frames_data if f.get('analysis', {}).get('brightness', 0) > 100])}

    ИНСТРУКЦИЯ: Используй этот визуальный контекст для создания более полного и точного анализа видео.
    """
                return visual_context
            
            return ""
            
        except Exception as e:
            logger.error(f"❌ Error analyzing frames: {e}")
            return ""

    def match_frames_with_transcript(self, frames_data: list, transcript: str) -> list:
        """Match video frames with corresponding transcript segments"""
        try:
            # Парсим транскрипт на сегменты с временными метками
            # (если есть метки) или разбиваем равномерно
            
            enhanced_frames = []
            for frame in frames_data:
                timestamp = frame.get('timestamp', 0)
                
                # Находим текст для этого временного отрезка (±5 сек)
                start_time = max(0, timestamp - 5)
                end_time = timestamp + 5
                
                # Извлекаем соответствующий сегмент текста
                segment_text = self.extract_transcript_segment(
                    transcript, start_time, end_time, timestamp
                )
                
                enhanced_frame = {
                    **frame,
                    'transcript_segment': segment_text,
                    'formatted_timestamp': self.format_timestamp(timestamp)
                }
                
                enhanced_frames.append(enhanced_frame)
            
            return enhanced_frames
            
        except Exception as e:
            logger.error(f"Error matching frames with transcript: {e}")
            return frames_data

    async def create_file_manager_task(self, original_task: TaskData, summaries: Dict):
        """Create File Manager task after generating summaries"""
        try:
            from shared.utils import generate_task_id
            
            # Create new task for File Manager
            file_task_id = generate_task_id()

            # 🔥 EXTRACT frames_data from original task
            frames_data = original_task.data.get('frames_data', [])
            
            file_task_data = TaskData(
                task_id=file_task_id,
                task_type=TaskType.FILE_GENERATION,  # New task type
                user_id=original_task.user_id,
                chat_id=original_task.chat_id,
                status=TaskStatus.PENDING,
                priority=original_task.priority,
                message_id=original_task.message_id,
                data={
                    "original_task_id": original_task.task_id,  # Link back to original
                    "summaries": summaries,
                    "title": original_task.data.get('title', 'Summary'),
                    "file_format": original_task.data.get('file_format', 'both'),  # pdf, markdown, both
                    "user_language": original_task.data.get('user_language', 'en'),
                    "frames_data": frames_data,  # this fix for correct pipeline, so frames will go to FileManager
                    "processing_type": original_task.data.get('processing_type', 'text_only') 
                }
            )
            
            # Add to file management queue
            success = await self.redis.enqueue_task('file_management_queue', file_task_data)
            
            if success:
                logger.info(f"✅ Created File Manager task {file_task_id} for original task {original_task.task_id}")
                logger.info(f"🔍 Passed {len(frames_data)} frames to File Manager") # more debugs

                # Update original task status to indicate it's being processed further
                await self.redis.set_task_status(
                    original_task.task_id,
                    TaskStatus.PROCESSING,
                    result={"message": "Generating files...", "file_task_id": file_task_id}
                )
            else:
                logger.error(f"Failed to create File Manager task for {original_task.task_id}")
                # Complete with summaries only as fallback
                await self.redis.set_task_status(
                    original_task.task_id,
                    TaskStatus.COMPLETED,
                    result=summaries
                )
            
        except Exception as e:
            logger.error(f"Error creating File Manager task: {e}")
            # Complete with summaries only as fallback
            await self.redis.set_task_status(
                original_task.task_id,
                TaskStatus.COMPLETED,
                result=summaries
            )

async def main():
    """Main entry point"""
    service = AIProcessorService()
    await service.start()

if __name__ == "__main__":
    asyncio.run(main())
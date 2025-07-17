# Этот файл создает AI Processing Service для Ollama, Gemini и Whisper обработки

# services/ai-processor/main.py
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
        
        # Check Ollama availability
        asyncio.create_task(self.check_ollama_availability())
    
    async def check_ollama_availability(self):
        """Check if Ollama is running and model is available"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.ollama_endpoint}/api/tags", timeout=5) as response:
                    if response.status == 200:
                        data = await response.json()
                        models = [model['name'] for model in data.get('models', [])]
                        
                        if self.ollama_model in models:
                            self.ollama_available = True
                            logger.info(f"✅ Ollama available with model: {self.ollama_model}")
                        else:
                            logger.warning(f"⚠️ Ollama model {self.ollama_model} not found. Available: {models}")
                            if models:
                                self.ollama_model = models[0]
                                self.ollama_available = True
                                logger.info(f"✅ Using available model: {self.ollama_model}")
                    else:
                        logger.warning("⚠️ Ollama not responding")
                        
        except Exception as e:
            logger.warning(f"⚠️ Ollama not available: {e}")
    
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
                summary = await self._generate_with_ollama(transcript, summary_enum, title, language)
                if summary and len(summary.strip()) > 10:
                    logger.info("✅ Generated summary with Ollama")
                    return summary
            except Exception as e:
                logger.error(f"Ollama failed: {e}")
        
        # Fallback to Gemini
        if self.gemini_available:
            try:
                summary = await self._generate_with_gemini(transcript, summary_enum, title, language)
                if summary and len(summary.strip()) > 10:
                    logger.info("✅ Generated summary with Gemini")
                    return summary
            except Exception as e:
                logger.error(f"Gemini failed: {e}")
        
        # If both fail, return error message
        return self._get_fallback_summary(transcript, summary_enum, title)
    
    async def _generate_with_ollama(self, transcript: str, summary_type: SummaryType, title: str, language: str) -> str:
        """Generate summary using Ollama API"""
        
        prompts = self._get_ollama_prompts(language)
        
        prompt_text = prompts[summary_type].format(
            title=title,
            transcript=transcript[:8000]  # Limit transcript length for Ollama
        )
        
        payload = {
            "model": self.ollama_model,
            "prompt": prompt_text,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9,
                "max_tokens": self._get_max_tokens(summary_type),
                "stop": ["</summary>", "[END]"]
            }
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.ollama_endpoint}/api/generate", 
                json=payload,
                timeout=60
            ) as response:
                
                if response.status == 200:
                    data = await response.json()
                    return data.get('response', '').strip()
                else:
                    error_text = await response.text()
                    raise Exception(f"Ollama API error {response.status}: {error_text}")
    
    def _get_ollama_prompts(self, language: str) -> dict:
        """Get language-specific prompts for Ollama"""
        
        if language == 'ru':
            return {
                SummaryType.SHORT: """Создай краткое резюме этого YouTube видео на русском языке в 2-3 предложениях.

Название видео: {title}

Транскрипт:
{transcript}

Краткое резюме:""",
                
                SummaryType.MEDIUM: """Создай подробное резюме этого YouTube видео на русском языке в 1-2 абзацах.

Название видео: {title}

Транскрипт:
{transcript}

Подробное резюме:""",
                
                SummaryType.DETAILED: """Создай детальный анализ этого YouTube видео на русском языке.

Название видео: {title}

Транскрипт:
{transcript}

Детальный анализ:"""
            }
        else:  # English
            return {
                SummaryType.SHORT: """Create a brief summary of this YouTube video in 2-3 sentences.

Video Title: {title}

Transcript:
{transcript}

Brief Summary:""",
                
                SummaryType.MEDIUM: """Create a comprehensive summary of this YouTube video in 1-2 paragraphs.

Video Title: {title}

Transcript:
{transcript}

Comprehensive Summary:""",
                
                SummaryType.DETAILED: """Create a detailed analysis of this YouTube video.

Video Title: {title}

Transcript:
{transcript}

Detailed Analysis:"""
            }
    
    def _get_max_tokens(self, summary_type: SummaryType) -> int:
        """Get max tokens based on summary type"""
        return {
            SummaryType.SHORT: 150,
            SummaryType.MEDIUM: 500,
            SummaryType.DETAILED: 1000
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
                self.load_whisper_model('base')
            
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
        logger.info("✅ AI Processor Service started")
        
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
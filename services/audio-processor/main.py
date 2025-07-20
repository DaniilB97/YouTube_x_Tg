# Этот файл создает Audio Processor Service для обработки аудио с Whisper, TTS, voice cloning

# services/audio-processor/main.py
import os
import asyncio
import logging
import tempfile
import shutil
from datetime import datetime
from typing import Optional, Dict, Tuple
import subprocess
import json

# Import shared components
import sys
sys.path.append('/app')
from shared.database import get_redis
from shared.models import TaskData, TaskType, TaskStatus
from shared.utils import generate_task_id

# Audio processing libraries
import torch
import whisper
from pydub import AudioSegment

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WhisperProcessor:
    """Process audio files with Whisper for transcription"""
    
    def __init__(self):
        self.whisper_models = {
            'tiny': None,
            'base': None,
            'small': None,
            'medium': None
        }
        self.current_model_name = 'tiny'
        self.current_model = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"🎵 Whisper will use device: {self.device}")
    
    def load_whisper_model(self, model_name: str = 'tiny'):
        """Load Whisper model safely"""
        try:
            if model_name not in self.whisper_models:
                model_name = 'tiny'
            
            if self.whisper_models[model_name] is None:
                logger.info(f"📥 Loading Whisper model: {model_name}")
                self.whisper_models[model_name] = whisper.load_model(model_name, device=self.device)
                logger.info(f"✅ Whisper model {model_name} loaded successfully")
            
            self.current_model = self.whisper_models[model_name]
            self.current_model_name = model_name
            return True
            
        except Exception as e:
            logger.error(f"❌ Error loading Whisper model {model_name}: {e}")
            return False
    
    async def transcribe_audio_safe(self, audio_path: str) -> Tuple[str, str, int]:
        """Transcribe audio file using subprocess for isolation"""
        try:
            logger.info(f"🎵 Starting Whisper transcription: {audio_path}")
            
            # Get audio duration safely
            try:
                audio = AudioSegment.from_file(audio_path)
                duration = len(audio) // 1000  # Convert to seconds
                logger.info(f"📊 Audio duration: {duration} seconds")
            except Exception as e:
                logger.warning(f"Could not get audio duration: {e}")
                duration = 0
            
            # Create isolated Whisper script
            whisper_script = f'''
import whisper
import json
import sys
import warnings
warnings.filterwarnings("ignore")

try:
    model = whisper.load_model("tiny")
    result = model.transcribe("{audio_path}")
    
    output = {{
        "text": result["text"],
        "language": result["language"],
        "success": True
    }}
    
    print(json.dumps(output))
    
except Exception as e:
    output = {{
        "text": "",
        "language": "en",
        "success": False,
        "error": str(e)
    }}
    print(json.dumps(output))
'''
            
            # Run Whisper in subprocess for isolation
            logger.info("🔄 Running Whisper in isolated subprocess...")
            
            process = await asyncio.create_subprocess_exec(
                'python', '-c', whisper_script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # Wait for completion with timeout
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), 
                    timeout=300  # 5 minutes timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                logger.error("⏰ Whisper transcription timed out")
                return "Transcription timed out", "en", duration
            
            if process.returncode == 0:
                # Parse result
                try:
                    result_data = json.loads(stdout.decode())
                    
                    if result_data.get('success'):
                        text = result_data.get('text', '').strip()
                        language = result_data.get('language', 'en')
                        
                        if len(text) > 10:  # Valid transcription
                            logger.info(f"✅ Whisper transcription successful: {len(text)} characters")
                            return text, language, duration
                        else:
                            logger.warning("⚠️ Whisper returned very short text")
                            return "Audio transcription produced minimal text", language, duration
                    else:
                        error = result_data.get('error', 'Unknown error')
                        logger.error(f"❌ Whisper transcription failed: {error}")
                        return f"Transcription failed: {error}", "en", duration
                        
                except json.JSONDecodeError as e:
                    logger.error(f"❌ Could not parse Whisper output: {e}")
                    logger.error(f"Raw output: {stdout.decode()}")
                    return "Transcription output parsing failed", "en", duration
            else:
                error_output = stderr.decode()
                logger.error(f"❌ Whisper subprocess failed with code {process.returncode}")
                logger.error(f"Error output: {error_output}")
                return f"Transcription subprocess failed", "en", duration
            
        except Exception as e:
            logger.error(f"❌ Error in Whisper transcription: {e}")
            return f"Transcription error: {str(e)}", "en", 0
    
    async def transcribe_audio_simple(self, audio_path: str) -> Tuple[str, str, int]:
        """Simple transcription for testing without subprocess"""
        try:
            if not self.current_model:
                if not self.load_whisper_model('tiny'):
                    return "Failed to load Whisper model", "en", 0
            
            logger.info(f"🎵 Transcribing with Whisper model: {self.current_model_name}")
            
            # Get duration
            try:
                audio = AudioSegment.from_file(audio_path)
                duration = len(audio) // 1000
            except:
                duration = 0
            
            # Transcribe in thread to avoid blocking
            result = await asyncio.to_thread(self.current_model.transcribe, audio_path)
            
            text = result["text"].strip()
            language = result["language"]
            
            if len(text) > 5:
                logger.info(f"✅ Transcription successful: {len(text)} characters")
                return text, language, duration
            else:
                return "Audio transcription produced minimal content", language, duration
            
        except Exception as e:
            logger.error(f"❌ Transcription error: {e}")
            return f"Transcription failed: {str(e)}", "en", 0

class TTSProcessor:
    """Text-to-Speech processing (placeholder for future implementation)"""
    
    def __init__(self):
        logger.info("🔊 TTS Processor initialized (placeholder)")
    
    async def generate_speech(self, text: str, voice: str = "default") -> Optional[str]:
        """Generate speech from text (placeholder)"""
        logger.info("🔊 TTS generation requested (not implemented yet)")
        return None

class VoiceCloningProcessor:
    """Voice cloning functionality (placeholder for future implementation)"""
    
    def __init__(self):
        logger.info("🎭 Voice Cloning Processor initialized (placeholder)")
    
    async def clone_voice(self, source_audio: str, target_text: str) -> Optional[str]:
        """Clone voice for text (placeholder)"""
        logger.info("🎭 Voice cloning requested (not implemented yet)")
        return None

class AudioProcessorService:
    """Main Audio Processing Service"""
    
    def __init__(self):
        self.redis = get_redis()
        self.whisper_processor = WhisperProcessor()
        self.tts_processor = TTSProcessor()
        self.voice_cloning_processor = VoiceCloningProcessor()
        self.queue_name = 'audio_processing_queue'
        
        # Audio processing settings
        self.use_subprocess = os.getenv('WHISPER_USE_SUBPROCESS', 'true').lower() == 'true'
        logger.info(f"🔧 Whisper subprocess mode: {self.use_subprocess}")
    
    async def start(self):
        """Start the Audio Processing service"""
        await self.redis.connect()
        logger.info("✅ Audio Processor Service started")
        # Получаем имя модели

        if not self.use_subprocess:
            model_name = os.getenv('WHISPER_MODEL_NAME', 'tiny')
            logger.info(f"📥 Pre-loading Whisper model: {model_name}...")
            self.whisper_processor.load_whisper_model(model_name)
        
        logger.info("🎵 Audio Processor Service ready for tasks")
        
        # Start processing loop
        while True:
            try:
                await self.process_tasks()
            # 🕵️‍♂️ Ловим абсолютно все исключения, чтобы увидеть скрытые проблемы
            except BaseException as e:
                logger.error(f"❌ CRITICAL ERROR in processing loop: {type(e).__name__}: {e}", exc_info=True)
                logger.exception("Full traceback:") # Выводим полный стектрейс для диагностики
                await asyncio.sleep(5)
    
    async def process_tasks(self):
        """Process audio tasks from queue"""
        try:
            task_data = await self.redis.dequeue_task(self.queue_name, timeout=30)
            
            if task_data:
                logger.info(f"🎵 Processing audio task {task_data.task_id}")
                await self.process_audio_task(task_data)
            
        except Exception as e:
            logger.error(f"Error processing tasks: {e}")
    
    async def process_audio_task(self, task_data: TaskData):
        """Process a single audio task"""
        try:
            await self.redis.set_task_status(task_data.task_id, TaskStatus.PROCESSING)
            
            audio_type = task_data.data.get('audio_type', 'voice_message')
            file_path = task_data.data.get('file_path')
            title = task_data.data.get('title', 'Audio File')
            
            if audio_type in ['voice_message', 'audio_file', 'youtube_audio']:
                # Transcription task
                result = await self.process_transcription(task_data, file_path, title)
            elif audio_type == 'tts':
                # Text-to-Speech task
                result = await self.process_tts(task_data)
            elif audio_type == 'voice_clone':
                # Voice cloning task
                result = await self.process_voice_cloning(task_data)
            else:
                raise Exception(f"Unknown audio type: {audio_type}")
            
            #await self.redis.set_task_status(
             #   task_data.task_id,
                #TaskStatus.COMPLETED,
             #   result=result
            #)
            
            logger.info(f"✅ Completed audio task {task_data.task_id}")
            
        except Exception as e:
            logger.error(f"❌ Error processing audio task {task_data.task_id}: {e}")
            await self.redis.set_task_status(
                task_data.task_id,
                TaskStatus.FAILED,
                error=str(e)
            )
    
    async def process_transcription(self, task_data: TaskData, file_path: str, title: str) -> Dict:
        """Process audio transcription"""
        if not file_path or not os.path.exists(file_path):
            raise Exception(f"Audio file not found: {file_path}")
        
        logger.info(f"🎵 Starting transcription for: {title}")
        
        # Choose transcription method
        if self.use_subprocess:
            transcript, language, duration = await self.whisper_processor.transcribe_audio_safe(file_path)
        else:
            transcript, language, duration = await self.whisper_processor.transcribe_audio_simple(file_path)
        
        if not transcript or len(transcript.strip()) < 5:
            raise Exception("Transcription failed or produced no content")
        
        result = {
            'transcript': transcript,
            'language': language,
            'duration': duration,
            'file_path': file_path,
            'title': title,
            'audio_type': task_data.data.get('audio_type'),
            'processing_method': 'subprocess' if self.use_subprocess else 'direct'
        }
        
        # Check if we need to create AI summary task
       # if task_data.data.get('create_summary', True):
        await self.create_ai_summary_task(task_data, result)
        
        return result
    
    async def create_ai_summary_task(self, task_data, result):
        """Создать задачу для AI суммаризации"""
        try:
            ai_task_data = TaskData(
                task_id=task_data.task_id,  # ТОТ ЖЕ task_id!
                task_type=TaskType.SUMMARY_GENERATION,
                user_id=task_data.user_id,
                chat_id=task_data.chat_id,
                status=TaskStatus.PENDING,
                priority=task_data.priority,
                message_id=task_data.message_id,
                data={
                    'transcript': result['transcript'],
                    'language': result['language'],
                    'title': result['title'],
                    'file_format': task_data.data.get('file_format', 'both'),
                    'user_language': task_data.data.get('user_language', 'en')
                }
            )
            
            # Отправляем в AI очередь
            success = await self.redis.enqueue_task('ai_processing_queue', ai_task_data)
            
            if success:
                logger.info(f"✅ Created AI task for {task_data.task_id}")
            else:
                logger.error(f"❌ Failed to create AI task for {task_data.task_id}")
                
        except Exception as e:
            logger.error(f"❌ Error creating AI task: {e}")
    
    async def process_tts(self, task_data: TaskData) -> Dict:
        """Process Text-to-Speech (placeholder)"""
        text = task_data.data.get('text', '')
        voice = task_data.data.get('voice', 'default')
        
        logger.info(f"🔊 TTS requested for {len(text)} characters")
        
        # Placeholder implementation
        audio_file = await self.tts_processor.generate_speech(text, voice)
        
        return {
            'audio_file': audio_file,
            'text': text,
            'voice': voice,
            'status': 'TTS not implemented yet'
        }
    
    async def process_voice_cloning(self, task_data: TaskData) -> Dict:
        """Process voice cloning (placeholder)"""
        source_audio = task_data.data.get('source_audio')
        target_text = task_data.data.get('target_text')
        
        logger.info(f"🎭 Voice cloning requested")
        
        # Placeholder implementation
        cloned_audio = await self.voice_cloning_processor.clone_voice(source_audio, target_text)
        
        return {
            'cloned_audio': cloned_audio,
            'source_audio': source_audio,
            'target_text': target_text,
            'status': 'Voice cloning not implemented yet'
        }
    
async def main():
    """Main entry point"""
    service = AudioProcessorService()
    await service.start()

if __name__ == "__main__":
    asyncio.run(main())
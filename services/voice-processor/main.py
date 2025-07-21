# services/voice-processor/main.py
import os
import asyncio
import logging
import tempfile
import shutil
from datetime import datetime
from typing import Optional, Dict, List
import subprocess

# Import shared components
import sys
sys.path.append('/app')
from shared.database import get_redis
from shared.models import TaskData, TaskType, TaskStatus
from shared.utils import generate_task_id

# Voice processing libraries
import edge_tts
import pydub
from googletrans import Translator

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class VoiceProcessor:
    """Handle voice translation and TTS"""
    
    def __init__(self):
        self.translator = Translator()
        self.temp_dir = tempfile.mkdtemp(prefix="voice_processing_")
        
        # Voice mapping for different languages
        self.voice_mapping = {
            'ru': 'ru-RU-SvetlanaNeural',  # Женский голос
            'en': 'en-US-AriaNeural',      # Женский голос
            'es': 'es-ES-ElviraNeural',    # Женский голос  
            'fr': 'fr-FR-DeniseNeural'     # Женский голос
        }
    
    async def translate_text(self, text: str, target_language: str) -> str:
        """Translate text to target language"""
        try:
            # Разбиваем текст на части для лучшего перевода
            sentences = text.split('. ')
            translated_sentences = []
            
            for sentence in sentences:
                if len(sentence.strip()) > 0:
                    translated = self.translator.translate(
                        sentence.strip(), 
                        dest=target_language
                    )
                    translated_sentences.append(translated.text)
            
            result = '. '.join(translated_sentences)
            logger.info(f"✅ Translated {len(text)} chars to {target_language}")
            return result
            
        except Exception as e:
            logger.error(f"Translation error: {e}")
            return text  # Fallback to original
    
    async def generate_speech(self, text: str, target_language: str, output_path: str) -> bool:
        """Generate speech from text using Edge-TTS"""
        try:
            voice = self.voice_mapping.get(target_language, 'en-US-AriaNeural')
            
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(output_path)
            
            logger.info(f"✅ Generated speech: {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"TTS error: {e}")
            return False
    
    async def replace_audio_in_video(self, video_path: str, audio_path: str, output_path: str) -> bool:
        """Replace audio in video file"""
        try:
            # Используем FFmpeg для замены аудио
            cmd = [
                'ffmpeg', '-y',
                '-i', video_path,      # Исходное видео
                '-i', audio_path,      # Новое аудио
                '-c:v', 'copy',        # Копируем видео без изменений
                '-c:a', 'aac',         # Кодируем аудио в AAC
                '-map', '0:v:0',       # Берем видео из первого файла
                '-map', '1:a:0',       # Берем аудио из второго файла
                output_path
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.wait()
            
            if process.returncode == 0:
                logger.info(f"✅ Video with new audio: {output_path}")
                return True
            else:
                logger.error(f"FFmpeg error: {stderr.decode()}")
                return False
                
        except Exception as e:
            logger.error(f"Video processing error: {e}")
            return False

class VoiceProcessorService:
    """Main Voice Processing Service"""
    
    def __init__(self):
        self.redis = get_redis()
        self.voice_processor = VoiceProcessor()
        self.queue_name = 'voice_processing_queue'
        self.storage_dir = os.getenv('STORAGE_DIR', '/app/storage')
    
    async def start(self):
        """Start the Voice Processing service"""
        await self.redis.connect()
        logger.info("✅ Voice Processor Service started")
        
        # Start processing loop
        while True:
            try:
                await self.process_tasks()
            except Exception as e:
                logger.error(f"Error in processing loop: {e}")
                await asyncio.sleep(5)
    
    async def process_tasks(self):
        """Process voice tasks from queue"""
        try:
            task_data = await self.redis.dequeue_task(self.queue_name, timeout=30)
            
            if task_data:
                logger.info(f"🎙️ Processing voice task {task_data.task_id}")
                await self.process_voice_task(task_data)
            
        except Exception as e:
            logger.error(f"Error processing tasks: {e}")
    
    async def process_voice_task(self, task_data: TaskData):
        """Process a single voice overdub task"""
        try:
            await self.redis.set_task_status(task_data.task_id, TaskStatus.PROCESSING)
            
            # Extract data
            transcript = task_data.data.get('transcript', '')
            target_language = task_data.data.get('target_language', 'ru')
            title = task_data.data.get('title', 'YouTube Video')
            video_path = task_data.data.get('video_path')  # Путь к скачанному видео
            
            if not transcript:
                raise Exception("No transcript provided for voice overdub")
            
            # Step 1: Translate transcript
            logger.info(f"🌐 Translating to {target_language}")
            translated_text = await self.voice_processor.translate_text(transcript, target_language)
            
            # Step 2: Generate speech
            logger.info(f"🎙️ Generating speech in {target_language}")
            audio_filename = f"voice_{task_data.task_id}_{target_language}.wav"
            audio_path = os.path.join(self.voice_processor.temp_dir, audio_filename)
            
            speech_success = await self.voice_processor.generate_speech(
                translated_text, target_language, audio_path
            )
            
            if not speech_success:
                raise Exception("Failed to generate speech")
            
            # Step 3: Replace audio in video (if video available)
            if video_path and os.path.exists(video_path):
                output_filename = f"overdubbed_{task_data.task_id}_{target_language}.mp4"
                output_path = os.path.join(self.storage_dir, output_filename)
                
                video_success = await self.voice_processor.replace_audio_in_video(
                    video_path, audio_path, output_path
                )
                
                if video_success:
                    result = {
                        'translated_text': translated_text,
                        'audio_path': audio_path,
                        'video_path': output_path,
                        'target_language': target_language,
                        'title': title,
                        'message': f'Voice overdub completed in {target_language}'
                    }
                else:
                    # Audio only if video processing failed
                    result = {
                        'translated_text': translated_text,
                        'audio_path': audio_path,
                        'target_language': target_language,
                        'title': title,
                        'message': f'Audio translation completed in {target_language}'
                    }
            else:
                # Audio only
                result = {
                    'translated_text': translated_text,
                    'audio_path': audio_path,
                    'target_language': target_language,
                    'title': title,
                    'message': f'Audio translation completed in {target_language}'
                }
            
            # Complete task
            await self.redis.set_task_status(
                task_data.task_id,
                TaskStatus.COMPLETED,
                result=result
            )
            
            logger.info(f"✅ Voice overdub completed for {task_data.task_id}")
            
        except Exception as e:
            logger.error(f"❌ Voice processing failed: {e}")
            await self.redis.set_task_status(
                task_data.task_id,
                TaskStatus.FAILED,
                error=str(e)
            )

async def main():
    """Main entry point"""
    service = VoiceProcessorService()
    await service.start()

if __name__ == "__main__":
    asyncio.run(main())
# services/ai-overdub-processor/main.py - НОВЫЙ МИКРОСЕРВИС для AI Over Dub
import os
import asyncio
import logging
import tempfile
from datetime import datetime
from typing import Optional, Dict, List
import subprocess
import aiohttp

# Import shared components
import sys
sys.path.append('/app')
from shared.database import get_redis
from shared.models import TaskData, TaskType, TaskStatus
from shared.utils import generate_task_id

# AI и TTS libraries
import google.generativeai as genai
from deep_translator import GoogleTranslator
import edge_tts
import pydub
from pydub import AudioSegment

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AITranslator:
    """🧠 Рабочий №2: Переводчик - Большая Языковая Модель для контекстного перевода"""
    
    def __init__(self):
        # Initialize Gemini for intelligent translation
        try:
            genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
            self.gemini_model = genai.GenerativeModel('gemini-2.0-flash-exp')
            self.gemini_available = True
            logger.info("✅ Gemini AI Translator initialized")
        except Exception as e:
            logger.warning(f"Gemini not available, falling back to Google Translate: {e}")
            self.gemini_model = None
            self.gemini_available = False
    
    async def translate_segments(self, frames_data: List[Dict], target_language: str, context: str = "") -> List[Dict]:
        """Переводит сегменты с сохранением контекста и синхронизации"""
        try:
            logger.info(f"🌐 Starting AI translation of {len(frames_data)} segments to {target_language}")
            
            if self.gemini_available:
                return await self._translate_with_ai(frames_data, target_language, context)
            else:
                return await self._translate_with_google(frames_data, target_language)
                
        except Exception as e:
            logger.error(f"❌ Translation failed: {e}")
            # Fallback to simple translation
            return await self._translate_with_google(frames_data, target_language)
    
    async def _translate_with_ai(self, frames_data: List[Dict], target_language: str, context: str) -> List[Dict]:
        """Умный перевод с помощью Gemini AI с сохранением контекста"""
        try:
            # Создаем батчи для эффективной обработки
            batch_size = 10
            translated_frames = []
            
            for i in range(0, len(frames_data), batch_size):
                batch = frames_data[i:i + batch_size]
                
                # Формируем промпт для батча
                texts_to_translate = []
                for j, frame in enumerate(batch):
                    text = frame.get('text', '').strip()
                    if text:
                        texts_to_translate.append(f"{j+1}. {text}")
                
                if not texts_to_translate:
                    translated_frames.extend(batch)
                    continue
                
                prompt = f"""Переведи следующие фразы на {target_language}, сохраняя:
- Естественность речи для озвучки
- Эмоциональный тон оригинала  
- Длину фразы близкой к оригиналу
- Контекст: {context}

Фразы для перевода:
{chr(10).join(texts_to_translate)}

Ответь только переводами в том же порядке, каждый перевод с новой строки в формате "1. перевод", "2. перевод" и т.д."""

                response = await asyncio.to_thread(
                    self.gemini_model.generate_content,
                    prompt
                )
                
                # Парсим ответ
                translations = self._parse_gemini_response(response.text)
                
                # Применяем переводы к фреймам
                for j, frame in enumerate(batch):
                    new_frame = frame.copy()
                    if j < len(translations) and translations[j]:
                        new_frame['text'] = translations[j]
                        new_frame['translated'] = True
                        logger.info(f"🎯 AI Translated: '{frame.get('text', '')}' → '{translations[j]}'")
                    else:
                        # Fallback to Google Translate for this frame
                        fallback_translation = GoogleTranslator(source='auto', target=target_language).translate(frame.get('text', ''))
                        new_frame['text'] = fallback_translation
                        new_frame['translated'] = True
                        logger.warning(f"⚠️ Fallback translation: '{frame.get('text', '')}' → '{fallback_translation}'")
                    
                    translated_frames.append(new_frame)
                
                # Небольшая пауза между батчами
                await asyncio.sleep(0.5)
            
            logger.info(f"✅ AI translation completed: {len(translated_frames)} segments")
            return translated_frames
            
        except Exception as e:
            logger.error(f"❌ AI translation failed: {e}")
            return await self._translate_with_google(frames_data, target_language)
    
    def _parse_gemini_response(self, response_text: str) -> List[str]:
        """Парсит ответ Gemini и извлекает переводы"""
        try:
            lines = response_text.strip().split('\n')
            translations = []
            
            for line in lines:
                line = line.strip()
                if line and ('.' in line):
                    # Убираем номер "1. " в начале
                    if line[0].isdigit() and '. ' in line:
                        translation = line.split('. ', 1)[1]
                        translations.append(translation)
                    else:
                        translations.append(line)
            
            return translations
            
        except Exception as e:
            logger.error(f"Error parsing Gemini response: {e}")
            return []
    
    async def _translate_with_google(self, frames_data: List[Dict], target_language: str) -> List[Dict]:
        """Простой перевод с помощью Google Translate"""
        try:
            translated_frames = []
            
            for frame in frames_data:
                new_frame = frame.copy()
                text = frame.get('text', '').strip()
                
                if text:
                    try:
                        translated = GoogleTranslator(source='auto', target=target_language).translate(text)
                        new_frame['text'] = translated
                        new_frame['translated'] = True
                        logger.info(f"📝 Google Translated: '{text}' → '{translated}'")
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to translate '{text}': {e}")
                        new_frame['translated'] = False
                
                translated_frames.append(new_frame)
            
            logger.info(f"✅ Google translation completed: {len(translated_frames)} segments")
            return translated_frames
            
        except Exception as e:
            logger.error(f"❌ Google translation failed: {e}")
            return frames_data

class TTSGenerator:
    """🗣️ Рабочий №3: Диктор - ИИ для синтеза речи с синхронизацией"""
    
    def __init__(self):
        self.temp_dir = tempfile.mkdtemp(prefix="ai_overdub_tts_")
        
        # Voice mapping for different languages
        self.voice_mapping = {
            'ru': 'ru-RU-SvetlanaNeural',
            'en': 'en-US-AriaNeural',
            'es': 'es-ES-ElviraNeural',
            'fr': 'fr-FR-DeniseNeural'
        }
        
        logger.info(f"🎙️ TTS Generator initialized with temp dir: {self.temp_dir}")
    
    async def generate_synchronized_audio(self, translated_frames: List[Dict], target_language: str) -> List[Dict]:
        """Генерирует синхронизированные аудиофайлы для каждого сегмента"""
        try:
            logger.info(f"🎙️ Generating synchronized audio for {len(translated_frames)} segments in {target_language}")
            
            voice = self.voice_mapping.get(target_language, 'en-US-AriaNeural')
            audio_frames = []
            
            for i, frame in enumerate(translated_frames):
                text = frame.get('text', '').strip()
                start_time = frame.get('start', 0)
                end_time = frame.get('end', start_time + 1)
                original_duration = end_time - start_time
                
                if not text:
                    # Создаем тишину для пустых сегментов
                    audio_frames.append({
                        **frame,
                        'audio_path': None,
                        'is_silence': True
                    })
                    continue
                
                # Генерируем аудио для сегмента
                audio_filename = f"segment_{i:04d}_{start_time:.2f}s.wav"
                audio_path = os.path.join(self.temp_dir, audio_filename)
                
                success = await self._generate_segment_audio(text, voice, audio_path, original_duration)
                
                if success:
                    audio_frames.append({
                        **frame,
                        'audio_path': audio_path,
                        'audio_filename': audio_filename,
                        'is_silence': False,
                        'generated_duration': self._get_audio_duration(audio_path)
                    })
                    logger.info(f"🎵 Generated audio for segment {i+1}/{len(translated_frames)}: {text[:30]}...")
                else:
                    logger.warning(f"⚠️ Failed to generate audio for segment {i+1}: {text}")
                    audio_frames.append({
                        **frame,
                        'audio_path': None,
                        'is_silence': True
                    })
            
            logger.info(f"✅ Audio generation completed: {len(audio_frames)} segments")
            return audio_frames
            
        except Exception as e:
            logger.error(f"❌ Audio generation failed: {e}")
            return translated_frames
    
    async def _generate_segment_audio(self, text: str, voice: str, output_path: str, target_duration: float) -> bool:
        """Генерирует аудио для одного сегмента с учетом целевой длительности"""
        try:
            # Используем Edge TTS для высококачественного синтеза
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(output_path)
            
            # Проверяем длительность и корректируем если нужно
            actual_duration = self._get_audio_duration(output_path)
            
            if actual_duration > 0:
                # Если сгенерированное аудио значительно длиннее оригинала, ускоряем
                if actual_duration > target_duration * 1.2:
                    speed_factor = actual_duration / target_duration
                    await self._adjust_audio_speed(output_path, speed_factor)
                    logger.info(f"🏃 Adjusted audio speed by {speed_factor:.2f}x for better sync")
                
                return True
            else:
                logger.error(f"Generated audio file is empty: {output_path}")
                return False
                
        except Exception as e:
            logger.error(f"Error generating segment audio: {e}")
            return False
    
    def _get_audio_duration(self, audio_path: str) -> float:
        """Получает длительность аудиофайла"""
        try:
            audio = AudioSegment.from_file(audio_path)
            return len(audio) / 1000.0  # Convert to seconds
        except Exception as e:
            logger.error(f"Error getting audio duration: {e}")
            return 0.0
    
    async def _adjust_audio_speed(self, audio_path: str, speed_factor: float):
        """Корректирует скорость аудио для лучшей синхронизации"""
        try:
            audio = AudioSegment.from_file(audio_path)
            # Изменяем скорость воспроизведения
            adjusted_audio = audio.speedup(playback_speed=speed_factor)
            adjusted_audio.export(audio_path, format="wav")
            logger.info(f"✅ Audio speed adjusted by {speed_factor:.2f}x")
        except Exception as e:
            logger.error(f"Error adjusting audio speed: {e}")
    
    def cleanup(self):
        """Очистка временных файлов"""
        try:
            import shutil
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            logger.info("✅ TTS temp files cleaned up")
        except Exception as e:
            logger.warning(f"Error cleaning up TTS files: {e}")

class VideoSynchronizer:
    """🎬 Рабочий №4: Монтажёр - Финальная сборка видео с синхронизированной озвучкой"""
    
    def __init__(self):
        self.temp_dir = tempfile.mkdtemp(prefix="ai_overdub_video_")
        logger.info(f"🎬 Video Synchronizer initialized with temp dir: {self.temp_dir}")
    
    async def create_overdubbed_video(self, video_path: str, audio_frames: List[Dict], output_path: str) -> bool:
        """Создает финальное видео с AI Over Dub"""
        try:
            logger.info(f"🎬 Starting video synchronization with {len(audio_frames)} audio segments")
            
            # Сначала создаем единую аудиодорожку из сегментов
            combined_audio_path = await self._combine_audio_segments(audio_frames)
            
            if not combined_audio_path:
                logger.error("❌ Failed to combine audio segments")
                return False
            
            # Заменяем аудио в видео
            success = await self._replace_video_audio(video_path, combined_audio_path, output_path)
            
            if success:
                logger.info(f"✅ AI Over Dub video created: {output_path}")
                return True
            else:
                logger.error("❌ Failed to replace video audio")
                return False
            
        except Exception as e:
            logger.error(f"❌ Video synchronization failed: {e}")
            return False
    
    async def _combine_audio_segments(self, audio_frames: List[Dict]) -> Optional[str]:
        """Объединяет сегменты аудио в единую дорожку с правильным таймингом"""
        try:
            logger.info(f"🔗 Combining {len(audio_frames)} audio segments")
            
            # Создаем пустую аудиодорожку
            combined_audio = AudioSegment.empty()
            last_end_time = 0.0
            
            for i, frame in enumerate(audio_frames):
                start_time = frame.get('start', 0) * 1000  # Convert to milliseconds
                end_time = frame.get('end', start_time/1000 + 1) * 1000
                audio_path = frame.get('audio_path')
                
                # Добавляем тишину до начала сегмента если нужно
                if start_time > last_end_time:
                    silence_duration = start_time - last_end_time
                    silence = AudioSegment.silent(duration=silence_duration)
                    combined_audio += silence
                    logger.debug(f"Added {silence_duration}ms silence before segment {i+1}")
                
                # Добавляем аудиосегмент
                if audio_path and os.path.exists(audio_path) and not frame.get('is_silence', False):
                    try:
                        segment_audio = AudioSegment.from_file(audio_path)
                        
                        # Обрезаем или растягиваем под нужную длительность
                        target_duration = end_time - start_time
                        if len(segment_audio) != target_duration:
                            # Простое растягивание/сжатие
                            if len(segment_audio) > target_duration:
                                segment_audio = segment_audio[:target_duration]
                            else:
                                # Добавляем тишину в конец если аудио короче
                                padding = target_duration - len(segment_audio)
                                segment_audio += AudioSegment.silent(duration=padding)
                        
                        combined_audio += segment_audio
                        logger.debug(f"Added audio segment {i+1}: {len(segment_audio)}ms")
                        
                    except Exception as e:
                        logger.warning(f"Error adding segment {i+1}: {e}, adding silence")
                        silence = AudioSegment.silent(duration=end_time - start_time)
                        combined_audio += silence
                else:
                    # Добавляем тишину для пустых сегментов
                    silence_duration = end_time - start_time
                    silence = AudioSegment.silent(duration=silence_duration)
                    combined_audio += silence
                    logger.debug(f"Added silence for segment {i+1}: {silence_duration}ms")
                
                last_end_time = end_time
            
            # Сохраняем объединенную аудиодорожку
            combined_audio_path = os.path.join(self.temp_dir, "combined_overdub.wav")
            combined_audio.export(combined_audio_path, format="wav")
            
            logger.info(f"✅ Combined audio created: {len(combined_audio)/1000:.2f}s, {combined_audio_path}")
            return combined_audio_path
            
        except Exception as e:
            logger.error(f"Error combining audio segments: {e}")
            return None
    
    async def _replace_video_audio(self, video_path: str, audio_path: str, output_path: str) -> bool:
        """Заменяет аудио в видео используя FFmpeg"""
        try:
            cmd = [
                'ffmpeg', '-y',
                '-i', video_path,      # Исходное видео
                '-i', audio_path,      # Новое аудио
                '-c:v', 'copy',        # Копируем видео без изменений
                '-c:a', 'aac',         # Кодируем аудио в AAC
                '-map', '0:v:0',       # Берем видео из первого файла
                '-map', '1:a:0',       # Берем аудио из второго файла
                '-shortest',           # Ограничиваем длительность короткой дорожкой
                output_path
            ]
            
            logger.info(f"🎬 Running FFmpeg: {' '.join(cmd)}")
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                logger.info(f"✅ Video with AI Over Dub created: {output_path}")
                return True
            else:
                logger.error(f"FFmpeg error: {stderr.decode()}")
                return False
                
        except Exception as e:
            logger.error(f"Video processing error: {e}")
            return False
    
    def cleanup(self):
        """Очистка временных файлов"""
        try:
            import shutil
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            logger.info("✅ Video sync temp files cleaned up")
        except Exception as e:
            logger.warning(f"Error cleaning up video files: {e}")

class AIOverDubProcessorService:
    """🎭 Главный сервис AI Over Dub - координирует всю команду ИИ-рабочих"""
    
    def __init__(self):
        self.redis = get_redis()
        
        # Инициализируем всю команду ИИ-рабочих
        self.ai_translator = AITranslator()        # 🧠 Рабочий №2: Переводчик
        self.tts_generator = TTSGenerator()        # 🗣️ Рабочий №3: Диктор
        self.video_synchronizer = VideoSynchronizer()  # 🎬 Рабочий №4: Монтажёр
        
        self.queue_name = 'ai_overdub_processing_queue'
        self.storage_dir = os.getenv('STORAGE_DIR', '/app/storage')
    
    async def start(self):
        """Start the AI Over Dub Processing service"""
        await self.redis.connect()
        logger.info("✅ AI Over Dub Processor Service started")
        logger.info("🎭 AI Over Dub team ready: Translator, TTS Generator, Video Synchronizer")
        
        # Start processing loop
        while True:
            try:
                await self.process_tasks()
            except Exception as e:
                logger.error(f"Error in processing loop: {e}")
                await asyncio.sleep(5)
    
    async def process_tasks(self):
        """Process AI Over Dub tasks from queue"""
        try:
            task_data = await self.redis.dequeue_task(self.queue_name, timeout=30)
            
            if task_data:
                logger.info(f"🎭 Processing AI Over Dub task {task_data.task_id}")
                await self.process_ai_overdub_task(task_data)
            
        except Exception as e:
            logger.error(f"Error processing tasks: {e}")
    
    async def process_ai_overdub_task(self, task_data: TaskData):
        """🎭 Главный конвейер AI Over Dub - координирует всех рабочих"""
        try:
            await self.redis.set_task_status(task_data.task_id, TaskStatus.PROCESSING)
            
            # Извлекаем данные
            frames_data = task_data.data.get('frames_data', [])
            target_language = task_data.data.get('target_language', 'ru')
            title = task_data.data.get('title', 'YouTube Video')
            video_path = task_data.data.get('video_path')
            transcript = task_data.data.get('transcript', '')
            
            if not frames_data:
                raise Exception("No frame data provided for AI Over Dub synchronization")
            
            logger.info(f"🎭 Starting AI Over Dub pipeline for: {title}")
            logger.info(f"🎬 Segments to process: {len(frames_data)}")
            logger.info(f"🌐 Target language: {target_language}")
            
            # 🧠 ШАГ 1: AI Переводчик работает над сегментами
            logger.info("🧠 Step 1: AI Translator working...")
            await self.redis.set_task_status(
                task_data.task_id, 
                TaskStatus.PROCESSING,
                result={"stage": "translation", "progress": 25}
            )
            
            translated_frames = await self.ai_translator.translate_segments(
                frames_data, target_language, context=title
            )
            
            if not translated_frames:
                raise Exception("Translation failed")
            
            logger.info(f"✅ Step 1 complete: {len(translated_frames)} segments translated")
            
            # 🗣️ ШАГ 2: TTS Генератор создает озвучку
            logger.info("🗣️ Step 2: TTS Generator working...")
            await self.redis.set_task_status(
                task_data.task_id, 
                TaskStatus.PROCESSING,
                result={"stage": "tts_generation", "progress": 50}
            )
            
            audio_frames = await self.tts_generator.generate_synchronized_audio(
                translated_frames, target_language
            )
            
            if not audio_frames:
                raise Exception("TTS generation failed")
            
            logger.info(f"✅ Step 2 complete: {len(audio_frames)} audio segments generated")
            
            # 🎬 ШАГ 3: Video Synchronizer собирает финальное видео
            if video_path and os.path.exists(video_path):
                logger.info("🎬 Step 3: Video Synchronizer working...")
                await self.redis.set_task_status(
                    task_data.task_id, 
                    TaskStatus.PROCESSING,
                    result={"stage": "video_sync", "progress": 75}
                )
                
                output_filename = f"ai_overdub_{task_data.task_id}_{target_language}.mp4"
                output_path = os.path.join(self.storage_dir, output_filename)
                
                video_success = await self.video_synchronizer.create_overdubbed_video(
                    video_path, audio_frames, output_path
                )
                
                if video_success:
                    logger.info(f"✅ Step 3 complete: AI Over Dub video created")
                    
                    # Создаем также отдельный аудиофайл
                    audio_filename = f"ai_overdub_audio_{task_data.task_id}_{target_language}.wav"
                    audio_path = os.path.join(self.storage_dir, audio_filename)
                    await self._create_standalone_audio(audio_frames, audio_path)
                    
                    result = {
                        'overdub_video_path': output_path,
                        'overdub_audio_path': audio_path,
                        'target_language': target_language,
                        'title': title,
                        'segments_processed': len(audio_frames),
                        'message': f'AI Over Dub completed successfully in {target_language}'
                    }
                else:
                    # Если видео не получилось, хотя бы возвращаем аудио
                    audio_filename = f"ai_overdub_audio_{task_data.task_id}_{target_language}.wav"
                    audio_path = os.path.join(self.storage_dir, audio_filename)
                    await self._create_standalone_audio(audio_frames, audio_path)
                    
                    result = {
                        'overdub_audio_path': audio_path,
                        'target_language': target_language,
                        'title': title,
                        'segments_processed': len(audio_frames),
                        'message': f'AI Over Dub audio completed in {target_language} (video failed)'
                    }
            else:
                # Только аудио если видео недоступно
                logger.info("🎵 Creating audio-only AI Over Dub")
                audio_filename = f"ai_overdub_audio_{task_data.task_id}_{target_language}.wav"
                audio_path = os.path.join(self.storage_dir, audio_filename)
                await self._create_standalone_audio(audio_frames, audio_path)
                
                result = {
                    'overdub_audio_path': audio_path,
                    'target_language': target_language,
                    'title': title,
                    'segments_processed': len(audio_frames),
                    'message': f'AI Over Dub audio completed in {target_language}'
                }
            
            # Завершаем задачу
            await self.redis.set_task_status(
                task_data.task_id,
                TaskStatus.COMPLETED,
                result=result
            )
            
            logger.info(f"🎉 AI Over Dub completed successfully for {task_data.task_id}")
            
        except Exception as e:
            logger.error(f"❌ AI Over Dub failed: {e}")
            await self.redis.set_task_status(
                task_data.task_id,
                TaskStatus.FAILED,
                error=f"AI Over Dub failed: {str(e)}"
            )
        finally:
            # Очистка временных файлов
            self.tts_generator.cleanup()
            self.video_synchronizer.cleanup()
    
    async def _create_standalone_audio(self, audio_frames: List[Dict], output_path: str):
        """Создает отдельный аудиофайл из сегментов"""
        try:
            # Используем тот же метод объединения что и в видео
            combined_audio = AudioSegment.empty()
            last_end_time = 0.0
            
            for frame in audio_frames:
                start_time = frame.get('start', 0) * 1000
                end_time = frame.get('end', start_time/1000 + 1) * 1000
                audio_path = frame.get('audio_path')
                
                # Добавляем тишину до сегмента
                if start_time > last_end_time:
                    silence = AudioSegment.silent(duration=start_time - last_end_time)
                    combined_audio += silence
                
                # Добавляем аудиосегмент
                if audio_path and os.path.exists(audio_path) and not frame.get('is_silence', False):
                    segment_audio = AudioSegment.from_file(audio_path)
                    combined_audio += segment_audio
                else:
                    silence = AudioSegment.silent(duration=end_time - start_time)
                    combined_audio += silence
                
                last_end_time = end_time
            
            # Сохраняем
            combined_audio.export(output_path, format="wav")
            logger.info(f"✅ Standalone audio created: {output_path}")
            
        except Exception as e:
            logger.error(f"Error creating standalone audio: {e}")

async def main():
    """Main entry point"""
    service = AIOverDubProcessorService()
    await service.start()

if __name__ == "__main__":
    asyncio.run(main())
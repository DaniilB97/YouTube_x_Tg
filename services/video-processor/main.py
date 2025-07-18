# Этот файл создает сервис обработки YouTube видео - извлекает YouTubeProcessor и VideoFrameExtractor

# services/video-processor/main.py
import os
import asyncio
import logging
import tempfile
import shutil
from datetime import datetime
from typing import Optional, Dict, List, Tuple
from urllib.parse import urlparse, parse_qs
import re

# Import shared components
import sys
sys.path.append('/app')
from shared.database import get_redis
from shared.models import TaskData, TaskType, TaskStatus
from shared.utils import extract_youtube_video_id, generate_task_id

# External libraries for video processing
import cv2
import numpy as np
from youtube_transcript_api import YouTubeTranscriptApi
from pytube import YouTube
import yt_dlp

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class YouTubeProcessor:
    """Handles YouTube video processing and transcript extraction"""
    
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
    
    async def get_video_info(self, video_id: str) -> Optional[Dict]:
        """Get video information with fallback"""
        try:
            # Try pytube first
            yt = YouTube(f"https://www.youtube.com/watch?v={video_id}")
            return {
                'title': yt.title,
                'duration': yt.length,
                'author': yt.author,
                'description': yt.description,
                'publish_date': yt.publish_date,
                'views': yt.views
            }
        except Exception as e:
            logger.warning(f"Pytube failed for {video_id}: {e}")
            
            # Fallback - yt-dlp
            try:
                ydl_opts = {'quiet': True, 'no_warnings': True}
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
                    
                    return {
                        'title': info.get('title', f'YouTube Video {video_id}'),
                        'duration': info.get('duration', 0),
                        'author': info.get('uploader', 'Unknown'),
                        'description': info.get('description', ''),
                        'publish_date': None,
                        'views': info.get('view_count', 0)
                    }
            except Exception as e2:
                logger.error(f"Both pytube and yt-dlp failed for {video_id}: {e2}")
                
                # Final fallback
                return {
                    'title': f'YouTube Video {video_id}',
                    'duration': 0,
                    'author': 'Unknown',
                    'description': '',
                    'publish_date': None,
                    'views': 0
                }
    
    async def get_transcript(self, video_id: str) -> Optional[Tuple[str, str]]:
        """Get transcript - try YouTube API first, fallback to Whisper"""
        try:
            # Try YouTube Transcript API first (FAST)
            logger.info(f"Trying YouTube Transcript API for {video_id}")
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            
            # Try preferred languages
            languages = ['en', 'en-US', 'en-GB', 'ru']
            transcript = None
            language = 'en'
            
            for lang in languages:
                try:
                    transcript = transcript_list.find_transcript([lang])
                    language = lang
                    logger.info(f"Found {lang} transcript via API")
                    break
                except Exception as lang_error:
                    logger.debug(f"Language {lang} not found: {lang_error}")
                    continue
            
            # If no preferred language, get any available
            if not transcript:
                try:
                    all_transcripts = list(transcript_list)
                    if all_transcripts:
                        transcript = all_transcripts[0]
                        language = transcript.language_code
                        logger.info(f"Found {language} transcript via API")
                except Exception as e:
                    logger.debug(f"No transcripts available: {e}")
            
            if transcript:
                try:
                    transcript_data = transcript.fetch()
                    full_transcript = ' '.join([item['text'] for item in transcript_data])
                    
                    if len(full_transcript.strip()) > 10:  # Valid transcript
                        logger.info(f"✅ YouTube API transcript: {len(full_transcript)} chars")
                        return full_transcript, language
                    else:
                        logger.warning("Empty or too short transcript from API")
                        
                except Exception as fetch_error:
                    logger.warning(f"Error fetching transcript data: {fetch_error}")
                
        except Exception as e:
            logger.warning(f"YouTube Transcript API failed for {video_id}: {e}")
        
        # FALLBACK: Signal that Whisper is needed (handled by AI service)
        logger.info(f"No transcript available via API for {video_id}, Whisper needed")
        return None, None

class VideoFrameExtractor:
    """Extract and analyze frames from YouTube videos"""
    
    def __init__(self):
        self.temp_dir = tempfile.mkdtemp(prefix="video_frames_")
        self.extracted_frames = []
        
    def download_video_for_analysis(self, video_id: str) -> Optional[str]:
        """Download video in lower quality for frame extraction"""
        try:
            url = f"https://www.youtube.com/watch?v={video_id}"
            
            # Download video in lower quality for faster processing
            ydl_opts = {
                'format': 'worst[height<=480]/worst',  # Lower quality
                'outtmpl': f'{self.temp_dir}/video_{video_id}.%(ext)s',
                'quiet': True,
                'no_warnings': True,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                },
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            # Find the downloaded file
            for file in os.listdir(self.temp_dir):
                if file.startswith(f'video_{video_id}'):
                    video_path = os.path.join(self.temp_dir, file)
                    logger.info(f"✅ Downloaded video for analysis: {video_path}")
                    return video_path
            
            return None
            
        except Exception as e:
            logger.error(f"Error downloading video for analysis: {e}")
            return None
    
    def extract_key_frames(self, video_path: str, max_frames: int = 15) -> List[Dict]:
        """Extract key frames from video using scene detection"""
        try:
            cap = cv2.VideoCapture(video_path)
            
            if not cap.isOpened():
                logger.error("Could not open video file")
                return []
            
            # Get video properties
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = total_frames / fps if fps > 0 else 0
            
            logger.info(f"Video info: {total_frames} frames, {fps:.2f} fps, {duration:.2f}s")
            
            frames_data = []
            prev_frame = None
            frame_count = 0
            
            # Calculate interval to get evenly distributed frames
            interval = max(1, total_frames // max_frames)
            
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                # Process every nth frame
                if frame_count % interval == 0:
                    # Calculate timestamp
                    timestamp = frame_count / fps if fps > 0 else 0
                    
                    # Detect if this is a significant frame
                    is_key_frame = self.is_significant_frame(frame, prev_frame)
                    
                    if is_key_frame or len(frames_data) < 5:  # Always keep some frames
                        # Save frame
                        frame_filename = f"frame_{frame_count:06d}_{timestamp:.2f}s.jpg"
                        frame_path = os.path.join(self.temp_dir, frame_filename)
                        
                        cv2.imwrite(frame_path, frame)
                        
                        # Analyze frame content
                        frame_analysis = self.analyze_frame_content(frame, timestamp)
                        
                        frame_data = {
                            'frame_number': frame_count,
                            'timestamp': timestamp,
                            'path': frame_path,
                            'filename': frame_filename,
                            'is_key_frame': is_key_frame,
                            'analysis': frame_analysis
                        }
                        
                        frames_data.append(frame_data)
                        prev_frame = frame.copy()
                        
                        if len(frames_data) >= max_frames:
                            break
                
                frame_count += 1
            
            cap.release()
            self.extracted_frames = frames_data
            
            logger.info(f"✅ Extracted {len(frames_data)} key frames")
            return frames_data
            
        except Exception as e:
            logger.error(f"Error extracting frames: {e}")
            return []
    
    def is_significant_frame(self, current_frame, prev_frame) -> bool:
        """Detect if frame is significantly different from previous"""
        if prev_frame is None:
            return True
        
        try:
            # Convert to grayscale for comparison
            current_gray = cv2.cvtColor(current_frame, cv2.COLOR_BGR2GRAY)
            prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
            
            # Calculate histogram difference
            hist_current = cv2.calcHist([current_gray], [0], None, [256], [0, 256])
            hist_prev = cv2.calcHist([prev_gray], [0], None, [256], [0, 256])
            
            # Compare histograms
            correlation = cv2.compareHist(hist_current, hist_prev, cv2.HISTCMP_CORREL)
            
            # If correlation is low, it's a significant change
            return correlation < 0.85
            
        except Exception as e:
            logger.warning(f"Error in frame comparison: {e}")
            return True
    
    def analyze_frame_content(self, frame, timestamp: float) -> Dict:
        """Analyze frame content for charts, text, etc."""
        try:
            analysis = {
                'timestamp': timestamp,
                'has_text': False,
                'has_charts': False,
                'brightness': 0,
                'edge_density': 0
            }
            
            # Convert to grayscale
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # Calculate brightness
            analysis['brightness'] = np.mean(gray)
            
            # Simple edge detection for complexity
            edges = cv2.Canny(gray, 50, 150)
            analysis['edge_density'] = np.sum(edges > 0) / edges.size
            
            # Basic text detection (look for rectangular regions)
            contours, _ = cv2.findContours(gray, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            text_like_regions = 0
            
            for contour in contours:
                area = cv2.contourArea(contour)
                if 100 < area < 5000:  # Reasonable size for text
                    x, y, w, h = cv2.boundingRect(contour)
                    aspect_ratio = w / h if h > 0 else 0
                    if 0.2 < aspect_ratio < 8:  # Text-like aspect ratio
                        text_like_regions += 1
            
            analysis['has_text'] = text_like_regions > 5
            
            # Basic chart detection (look for straight lines)
            lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=50, minLineLength=100, maxLineGap=10)
            analysis['has_charts'] = lines is not None and len(lines) > 10
            
            return analysis
            
        except Exception as e:
            logger.warning(f"Error analyzing frame: {e}")
            return {
                'timestamp': timestamp,
                'has_text': False,
                'has_charts': False,
                'brightness': 0,
                'edge_density': 0
            }
    
    def cleanup(self):
        """Clean up temporary files"""
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            logger.info("✅ Cleaned up temporary files")
        except Exception as e:
            logger.warning(f"Error cleaning up: {e}")

class VideoProcessorService:
    """Main video processing service"""
    
    def __init__(self):
        self.redis = get_redis()
        
        # 1. First, define the output directory path.
        self.output_dir = "/app/temp_audio"
        
        # 2. Now you can safely use self.output_dir to initialize other classes.
        self.youtube_processor = YouTubeProcessor(output_dir=self.output_dir)
        
        self.frame_extractor = VideoFrameExtractor()
        self.queue_name = 'video_processing_queue'
    
    async def start(self):
        """Start the video processing service"""
        await self.redis.connect()
        logger.info("✅ Video Processor Service started")
        
        # Start processing loop
        while True:
            try:
                await self.process_tasks()
            except Exception as e:
                logger.error(f"Error in processing loop: {e}")
                await asyncio.sleep(5)
    
    async def process_tasks(self):
        """Process video tasks from queue"""
        try:
            # Get task from queue
            task_data = await self.redis.dequeue_task(self.queue_name, timeout=30)
            
            if task_data:
                logger.info(f"Processing task {task_data.task_id}")
                await self.process_video_task(task_data)
            
        except Exception as e:
            logger.error(f"Error processing tasks: {e}")
    
    async def process_video_task(self, task_data: TaskData):
        """
        Обрабатывает одну задачу: пытается получить транскрипт,
        а если не удается - скачивает аудио и передает эстафету.
        """
        video_id = task_data.data.get('video_id')
        
        try:
            # Сообщаем системе, что мы начали обработку
            await self.redis.set_task_status(task_data.task_id, TaskStatus.PROCESSING)

            # 1. Сначала пытаемся получить готовый транскрипт через API (это быстро)
            transcript, lang = self._get_transcript_via_api(video_id)

            if transcript:
                # УСПЕХ: Транскрипт найден! Создаем задачу на САММАРИЗАЦИЮ.
                logger.info(f"✅ Transcript found for {video_id}. Enqueuing for summarization.")
                
                summary_task = TaskData(
                    task_id=task_data.task_id,
                    user_id=task_data.user_id,
                    chat_id=task_data.chat_id,      # ✅ Добавить
                    status=TaskStatus.PENDING, 
                    task_type=TaskType.SUMMARY_GENERATION, # Задача на создание выжимки
                    data={
                        'transcript': transcript,
                        'language': lang,
                        'title': task_data.data.get('title', f'YouTube Video {video_id}')
                    }
                )
                await self.redis.enqueue_task('ai_processing_queue', summary_task)

            else:
                # ПЛАН Б: Готового транскрипта нет. Скачиваем аудио для Whisper.
                logger.info(f"No transcript for {video_id}. Downloading audio for Whisper.")
                audio_path = self._download_audio(video_id)

                if audio_path:
                    # УСПЕХ: Аудио скачано. Создаем задачу на ТРАНСКРИБАЦИЮ.
                    logger.info(f"✅ Audio downloaded for {video_id}. Enqueuing for transcription.")
                    
                    transcription_task = TaskData(
                        task_id=task_data.task_id,
                        user_id=task_data.user_id,
                        chat_id=task_data.chat_id,      # ✅ Добавить
                        status=TaskStatus.PENDING,
                        task_type=TaskType.AUDIO_PROCESSING, # Задача на распознавание речи
                        data={
                            'file_path': audio_path,
                            'title': task_data.data.get('title', f'YouTube Video {video_id}')
                        }
                    )
                    await self.redis.enqueue_task('audio_processing_queue', transcription_task)
                else:
                    # ПРОВАЛ: Не удалось даже скачать аудио
                    raise Exception("Failed to get transcript from API and failed to download audio.")

        except Exception as e:
            # Глобальная обработка ошибок: если что-то пошло не так, сообщаем об этом
            logger.error(f"❌ Failed to process video task {task_data.task_id}: {e}")
            await self.redis.set_task_status(
                task_data.task_id,
                TaskStatus.FAILED,
                error=f"Video processing failed: {e}"
            )

    def _get_transcript_via_api(self, video_id: str) -> Optional[Tuple[str, str]]:
        """Пытается получить транскрипт через YouTubeTranscriptApi."""
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            # Ищем сначала на предпочитаемых языках
            for lang_code in ['ru', 'en', 'en-US']:
                try:
                    transcript = transcript_list.find_transcript([lang_code])
                    text = ' '.join([item['text'] for item in transcript.fetch()])
                    if len(text.strip()) > 10:
                        return text, transcript.language_code
                except Exception:
                    continue
            # Если ничего не нашли в цикле, возвращаем два значения
            return None, None
        except Exception as e:
            logger.warning(f"Could not get transcript via API for {video_id}: {e}")
            # И в случае любой другой ошибки тоже возвращаем два значения
            return None, None

    def _download_audio(self, video_id: str) -> Optional[str]:
        """Скачивает аудио с помощью yt-dlp с оптимальными настройками для Whisper."""
        try:
            url = f"https://www.youtube.com/watch?v={video_id}"
            output_path = os.path.join(self.output_dir, f"{video_id}.wav")

            # Настройки, как в вашем надежном монолите
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(self.output_dir, f"{video_id}.%(ext)s"),
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'wav',
                }],
                'postprocessor_args': ['-ar', '16000'], # 16kHz - идеально для Whisper
                'quiet': True,
                'no_warnings': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            if os.path.exists(output_path):
                return output_path
            
            return None
        except Exception as e:
            logger.error(f"Error downloading audio for {video_id}: {e}")
            return None

async def main():
    """Main entry point"""
    service = VideoProcessorService()
    await service.start()

if __name__ == "__main__":
    asyncio.run(main())
# Этот файл создает File Manager Service для генерации PDF и Markdown файлов

# services/file-manager/main.py
import os
import asyncio
import logging
import tempfile
import shutil
from datetime import datetime
from typing import Optional, Dict, List, Tuple
from pathlib import Path
import uuid

# Import shared components
import sys
sys.path.append('/app')
from shared.database import get_redis
from shared.models import TaskData, TaskType, TaskStatus
from shared.utils import generate_task_id

# File generation libraries
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
import markdown
from markdown.extensions import toc, tables, fenced_code

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TXTGenerator:
    """Generate plain text files from text content"""
    
    def __init__(self):
        pass
    
    async def generate_txt(self, summaries: Dict, title: str, file_path: str, frames_data: list = None) -> bool:
        """Generate TXT file from summaries with optional frames"""
        try:
            content_lines = []
            
            # Title and metadata
            content_lines.append(f"{title}")
            content_lines.append("=" * len(title))
            content_lines.append(f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            content_lines.append("by YouTube Summarizer Bot")
            content_lines.append("-" * 50)
            content_lines.append("")
            
            # Table of contents
            content_lines.append("TABLE OF CONTENTS")
            content_lines.append("-" * 17)
            content_lines.append("1. Short Summary")
            content_lines.append("2. Medium Summary") 
            content_lines.append("3. Detailed Analysis")
            
            # 🔥 ДОБАВИТЬ КАДРЫ В СОДЕРЖАНИЕ:
            section_num = 4
            if frames_data:
                content_lines.append(f"{section_num}. Video Frames")
                section_num += 1
                
            if summaries.get('transcript'):
                content_lines.append(f"{section_num}. Original Transcript")
            content_lines.append("")
            content_lines.append("-" * 50)
            content_lines.append("")
            
            # Short Summary
            if summaries.get('summary_short'):
                content_lines.append("1. SHORT SUMMARY")
                content_lines.append("-" * 16)
                content_lines.append(summaries['summary_short'])
                content_lines.append("")
                content_lines.append("-" * 50)
                content_lines.append("")
            
            # Medium Summary
            if summaries.get('summary_medium'):
                content_lines.append("2. MEDIUM SUMMARY")
                content_lines.append("-" * 17)
                content_lines.append(summaries['summary_medium'])
                content_lines.append("")
                content_lines.append("-" * 50)
                content_lines.append("")
            
            # Detailed Analysis
            if summaries.get('summary_detailed'):
                content_lines.append("3. DETAILED ANALYSIS")
                content_lines.append("-" * 20)
                content_lines.append(summaries['summary_detailed'])
                content_lines.append("")
                content_lines.append("-" * 50)
                content_lines.append("")
            
            # 🔥 ДОБАВИТЬ СЕКЦИЮ КАДРОВ:
            if frames_data:
                content_lines.append("4. VIDEO FRAMES")
                content_lines.append("-" * 14)
                content_lines.append("Key moments from the video with corresponding content:")
                content_lines.append("")
                
                for i, frame in enumerate(frames_data, 1):
                    timestamp = frame.get('formatted_timestamp', '00:00')
                    segment = frame.get('transcript_segment', 'No transcript available')
                    filename = frame.get('filename', f'frame_{i}.jpg')
                    
                    content_lines.append(f"FRAME {i} - {timestamp}")
                    content_lines.append(f"File: {filename}")
                    content_lines.append(f"Context: {segment}")
                    content_lines.append("")
                    content_lines.append("-" * 30)
                    content_lines.append("")
            
            # Original transcript
            if summaries.get('transcript'):
                section_title = f"{section_num}. ORIGINAL TRANSCRIPT" if frames_data else "4. ORIGINAL TRANSCRIPT"
                content_lines.append(section_title)
                content_lines.append("-" * len(section_title))
                transcript = summaries['transcript']
                if len(transcript) > 3000:
                    transcript = transcript[:3000] + "... [truncated]"
                content_lines.append(transcript)
                content_lines.append("")
                content_lines.append("-" * 50)
                content_lines.append("")
            
            # Footer
            content_lines.append("Generated by YouTube Summarizer Bot - Microservices Architecture")
            
            # Write to file
            content = "\n".join(content_lines)
            await asyncio.to_thread(self._write_file, file_path, content)
            
            logger.info(f"✅ TXT generated: {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error generating TXT: {e}")
            return False
    
    def _write_file(self, file_path: str, content: str):
        """Write content to file (sync operation)"""
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)

class PDFGenerator:
    """Generate professional PDF files from text content"""
    
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self.setup_custom_styles()
    
    def setup_custom_styles(self):
        """Setup custom paragraph styles"""
        # Title style
        self.title_style = ParagraphStyle(
            'CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=18,
            spaceAfter=30,
            alignment=TA_CENTER,
            textColor=colors.darkblue
        )
        
        # Header style
        self.header_style = ParagraphStyle(
            'CustomHeader',
            parent=self.styles['Heading2'],
            fontSize=14,
            spaceAfter=20,
            spaceBefore=20,
            textColor=colors.darkblue
        )
        
        # Body style
        self.body_style = ParagraphStyle(
            'CustomBody',
            parent=self.styles['Normal'],
            fontSize=11,
            spaceAfter=12,
            alignment=TA_JUSTIFY,
            leftIndent=20,
            rightIndent=20
        )
        
        # Summary style
        self.summary_style = ParagraphStyle(
            'CustomSummary',
            parent=self.styles['Normal'],
            fontSize=10,
            spaceAfter=15,
            alignment=TA_JUSTIFY,
            leftIndent=30,
            rightIndent=30,
            backColor=colors.lightgrey
        )
    
    async def generate_pdf(self, summaries: Dict, title: str, file_path: str, frames_data: list = None) -> bool:
        """Generate PDF file from summaries with optional frames"""
        try:
            # Create document
            doc = SimpleDocTemplate(
                file_path,
                pagesize=A4,
                rightMargin=72,
                leftMargin=72,
                topMargin=72,
                bottomMargin=18
            )
            
            # Build content
            story = []
            
            # Title
            story.append(Paragraph(title, self.title_style))
            story.append(Spacer(1, 12))
            
            # Generation info
            generation_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            info_text = f"Generated on {generation_time} by YouTube Summarizer Bot"
            story.append(Paragraph(info_text, self.styles['Normal']))
            story.append(Spacer(1, 20))
            
            # Table of contents
            story.append(Paragraph("Table of Contents", self.header_style))
            toc_data = [
                ['Section', 'Page'],
                ['Short Summary', '2'],
                ['Medium Summary', '2'],
                ['Detailed Analysis', '3']
            ]
            
            # 🔥 ДОБАВИТЬ КАДРЫ В СОДЕРЖАНИЕ:
            if frames_data:
                toc_data.append(['Video Frames', '4'])
            
            toc_table = Table(toc_data, colWidths=[4*inch, 1*inch])
            toc_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(toc_table)
            story.append(Spacer(1, 30))
            
            # Short Summary
            if summaries.get('summary_short'):
                story.append(Paragraph("📝 Short Summary", self.header_style))
                story.append(Paragraph(summaries['summary_short'], self.body_style))
                story.append(Spacer(1, 20))
            
            # Medium Summary  
            if summaries.get('summary_medium'):
                story.append(Paragraph("📖 Medium Summary", self.header_style))
                story.append(Paragraph(summaries['summary_medium'], self.body_style))
                story.append(Spacer(1, 20))
            
            # Detailed Analysis
            if summaries.get('summary_detailed'):
                story.append(Paragraph("🔍 Detailed Analysis", self.header_style))
                story.append(Paragraph(summaries['summary_detailed'], self.body_style))
                story.append(Spacer(1, 20))
            
            # 🔥 ДОБАВИТЬ СЕКЦИЮ КАДРОВ:
            if frames_data:
                from reportlab.lib.utils import ImageReader
                from reportlab.platypus import Image
                
                story.append(Paragraph("🎬 Video Frames", self.header_style))
                story.append(Paragraph("Key moments from the video with corresponding content:", self.body_style))
                story.append(Spacer(1, 15))
                
                for i, frame in enumerate(frames_data, 1):
                    timestamp = frame.get('formatted_timestamp', '00:00')
                    segment = frame.get('transcript_segment', 'No transcript available')
                    frame_path = frame.get('path')
                    
                    # Frame title
                    frame_title = f"Frame {i} - {timestamp}"
                    story.append(Paragraph(frame_title, self.header_style))
                    
                    # Add image if exists
                    if frame_path and os.path.exists(frame_path):
                        try:
                            # Resize image to fit page
                            img = Image(frame_path, width=4*inch, height=3*inch)
                            story.append(img)
                            story.append(Spacer(1, 10))
                        except Exception as img_error:
                            logger.warning(f"Could not add image {frame_path}: {img_error}")
                            story.append(Paragraph(f"[Image: {frame.get('filename', 'frame.jpg')}]", self.body_style))
                            story.append(Spacer(1, 10))
                    
                    # Add context text
                    story.append(Paragraph(f"<b>Context:</b> {segment}", self.body_style))
                    story.append(Spacer(1, 15))
            
            # Additional info
            if summaries.get('transcript'):
                story.append(Paragraph("📄 Original Transcript", self.header_style))
                # Truncate very long transcripts
                transcript = summaries['transcript']
                if len(transcript) > 2000:
                    transcript = transcript[:2000] + "... [truncated]"
                story.append(Paragraph(transcript, self.summary_style))
            
            # Footer
            story.append(Spacer(1, 30))
            footer_text = "Generated by YouTube Summarizer Bot - Microservices Architecture"
            story.append(Paragraph(footer_text, self.styles['Normal']))
            
            # Build PDF
            await asyncio.to_thread(doc.build, story)
            
            logger.info(f"✅ PDF generated: {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error generating PDF: {e}")
            return False

class MarkdownGenerator:
    """Generate Markdown files from text content"""
    
    def __init__(self):
        pass
    
    async def generate_markdown(self, summaries: Dict, title: str, file_path: str, frames_data: list = None) -> bool:
        """Generate Markdown file from summaries with optional frames"""
        try:
            content_lines = []
            
            # Title and metadata
            content_lines.append(f"# {title}\n")
            content_lines.append(f"*Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n")
            content_lines.append("*by YouTube Summarizer Bot*\n")
            content_lines.append("---\n")
            
            # Table of contents
            content_lines.append("## Table of Contents\n")
            content_lines.append("- [📝 Short Summary](#short-summary)")
            content_lines.append("- [📖 Medium Summary](#medium-summary)")
            content_lines.append("- [🔍 Detailed Analysis](#detailed-analysis)")
            
            # 🔥 ДОБАВИТЬ КАДРЫ В СОДЕРЖАНИЕ:
            if frames_data:
                content_lines.append("- [🎬 Video Frames](#video-frames)")
                
            if summaries.get('transcript'):
                content_lines.append("- [📄 Original Transcript](#original-transcript)")
            content_lines.append("\n---\n")
            
            # Short Summary
            if summaries.get('summary_short'):
                content_lines.append("## 📝 Short Summary\n")
                content_lines.append(f"{summaries['summary_short']}\n")
                content_lines.append("---\n")
            
            # Medium Summary
            if summaries.get('summary_medium'):
                content_lines.append("## 📖 Medium Summary\n")
                content_lines.append(f"{summaries['summary_medium']}\n")
                content_lines.append("---\n")
            
            # Detailed Analysis
            if summaries.get('summary_detailed'):
                content_lines.append("## 🔍 Detailed Analysis\n")
                content_lines.append(f"{summaries['summary_detailed']}\n")
                content_lines.append("---\n")
            
            # 🔥 ДОБАВИТЬ СЕКЦИЮ КАДРОВ:
            if frames_data:
                content_lines.append("## 🎬 Video Frames\n")
                content_lines.append("*Key moments from the video with corresponding content:*\n")
                
                for i, frame in enumerate(frames_data, 1):
                    timestamp = frame.get('formatted_timestamp', '00:00')
                    segment = frame.get('transcript_segment', 'No transcript available')
                    filename = frame.get('filename', f'frame_{i}.jpg')
                    
                    content_lines.append(f"### Frame {i} - {timestamp}\n")
                    content_lines.append(f"![Frame {i}]({filename})\n")
                    content_lines.append(f"**Context:** {segment}\n")
                    content_lines.append("---\n")
            
            # Original transcript (if available)
            if summaries.get('transcript'):
                content_lines.append("## 📄 Original Transcript\n")
                content_lines.append("```")
                transcript = summaries['transcript']
                if len(transcript) > 3000:
                    transcript = transcript[:3000] + "... [truncated]"
                content_lines.append(transcript)
                content_lines.append("```\n")
            
            # Footer
            content_lines.append("---")
            content_lines.append("*Generated by YouTube Summarizer Bot - Microservices Architecture*")
            
            # Write to file
            content = "\n".join(content_lines)
            await asyncio.to_thread(self._write_file, file_path, content)
            
            logger.info(f"✅ Markdown generated: {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error generating Markdown: {e}")
            return False
    
    def _write_file(self, file_path: str, content: str):
        """Write content to file (sync operation)"""
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)

class FileManagerService:
    """Main File Manager Service"""
    
    def __init__(self):
        self.redis = get_redis()
        self.pdf_generator = PDFGenerator()
        self.markdown_generator = MarkdownGenerator()
        self.txt_generator = TXTGenerator() 
        self.queue_name = 'file_management_queue'
        
        # Storage directory
        self.storage_dir = os.getenv('STORAGE_DIR', '/app/storage')
        self.ensure_storage_directory()
    
    def ensure_storage_directory(self):
        """Ensure storage directory exists"""
        try:
            Path(self.storage_dir).mkdir(parents=True, exist_ok=True)
            logger.info(f"✅ Storage directory ready: {self.storage_dir}")
        except Exception as e:
            logger.error(f"Failed to create storage directory: {e}")
            raise
    
    def process_frames_with_transcript(self, frames_data: list, summaries: dict) -> list:
        """Process frames and match with transcript segments"""
        if not frames_data:
            return []
        
        try:
            # Получаем транскрипт из саммари
            transcript = ""
            for key in ['summary_detailed', 'summary_medium', 'summary_short']:
                if key in summaries:
                    transcript = summaries[key]
                    break
            
            enhanced_frames = []
            total_length = len(transcript.split()) if transcript else 100
            
            for frame in frames_data:
                timestamp = frame.get('timestamp', 0)
                
                # Примерно сопоставляем текст по времени
                # Простая логика: разбиваем текст пропорционально времени
                if transcript and total_length > 0:
                    # Предполагаем что видео идет последовательно
                    word_per_second = total_length / max(timestamp + 30, 60)  # примерная скорость речи
                    start_word = max(0, int((timestamp - 10) * word_per_second))
                    end_word = min(total_length, int((timestamp + 10) * word_per_second))
                    
                    words = transcript.split()
                    segment = ' '.join(words[start_word:end_word])
                    
                    # Ограничиваем длину сегмента
                    if len(segment) > 200:
                        segment = segment[:200] + "..."
                else:
                    segment = f"Кадр в момент {self.format_timestamp(timestamp)}"
                
                enhanced_frame = {
                    **frame,
                    'transcript_segment': segment,
                    'formatted_timestamp': self.format_timestamp(timestamp)
                }
                
                enhanced_frames.append(enhanced_frame)
            
            logger.info(f"✅ Processed {len(enhanced_frames)} frames with transcript segments")
            return enhanced_frames
            
        except Exception as e:
            logger.error(f"Error processing frames: {e}")
            return frames_data

    def format_timestamp(self, seconds: float) -> str:
        """Format timestamp as MM:SS"""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes:02d}:{secs:02d}"

    async def start(self):
        """Start the File Manager service"""
        await self.redis.connect()
        logger.info("✅ File Manager Service started")
        
        # Start processing loop
        while True:
            try:
                await self.process_tasks()
            except Exception as e:
                logger.error(f"Error in processing loop: {e}")
                await asyncio.sleep(5)
    
    async def process_tasks(self):
        """Process file generation tasks from queue"""
        try:
            task_data = await self.redis.dequeue_task(self.queue_name, timeout=30)
            
            if task_data:
                logger.info(f"Processing file generation task {task_data.task_id}")
                await self.process_file_task(task_data)
            
        except Exception as e:
            logger.error(f"Error processing tasks: {e}")
    
    async def process_file_task(self, task_data: TaskData):
        """Process a single file generation task"""
        try:
            await self.redis.set_task_status(task_data.task_id, TaskStatus.PROCESSING)
            
            # Extract data
            summaries = task_data.data.get('summaries', {})
            title = task_data.data.get('title', 'YouTube Video Summary')
            file_format = task_data.data.get('file_format', 'both')
            original_task_id = task_data.data.get('original_task_id')

            # 🔥 ДОБАВИТЬ ОБРАБОТКУ КАДРОВ:
            frames_data = task_data.data.get('frames_data', [])
            enhanced_frames = []

            logger.info(f"🔍 DEBUG: frames_data type: {type(frames_data)}")
            logger.info(f"🔍 DEBUG: frames_data length: {len(frames_data) if frames_data else 0}")
            logger.info(f"🔍 DEBUG: task_data.data keys: {list(task_data.data.keys())}")
            
            if frames_data:
                logger.info(f"📸 Processing {len(frames_data)} frames for file generation")
                enhanced_frames = self.process_frames_with_transcript(frames_data, summaries)
                logger.info(f"🔍 DEBUG: enhanced_frames length: {len(enhanced_frames)}")
            else:
                logger.info("⚠️ No frames_data found in task")
            
            # Generate unique filename
            file_id = str(uuid.uuid4())[:8]
            safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
            safe_title = safe_title.replace(' ', '_')[:50]  # Limit length
            
            generated_files = []
            # Generate TXT 
            if file_format in ['txt', 'both', 'all']:
                txt_filename = f"{safe_title}_{file_id}.txt"
                txt_path = os.path.join(self.storage_dir, txt_filename)
                
                if await self.txt_generator.generate_txt(summaries, title, txt_path, enhanced_frames):
                    generated_files.append({
                        'type': 'txt',
                        'filename': txt_filename,
                        'path': txt_path,
                        'size': os.path.getsize(txt_path) if os.path.exists(txt_path) else 0
                    })


            # Generate PDF
            if file_format in ['pdf', 'both', 'all']:
                pdf_filename = f"{safe_title}_{file_id}.pdf"
                pdf_path = os.path.join(self.storage_dir, pdf_filename)
                
                if await self.pdf_generator.generate_pdf(summaries, title, pdf_path, enhanced_frames):
                    generated_files.append({
                        'type': 'pdf',
                        'filename': pdf_filename,
                        'path': pdf_path,
                        'size': os.path.getsize(pdf_path) if os.path.exists(pdf_path) else 0
                    })
            
            # Generate Markdown
            if file_format in ['markdown', 'both', 'all']:
                md_filename = f"{safe_title}_{file_id}.md"
                md_path = os.path.join(self.storage_dir, md_filename)
                
                if await self.markdown_generator.generate_markdown(summaries, title, md_path, enhanced_frames):
                    generated_files.append({
                        'type': 'markdown',
                        'filename': md_filename,
                        'path': md_path,
                        'size': os.path.getsize(md_path) if os.path.exists(md_path) else 0
                    })
            
            if generated_files:
                # Complete the ORIGINAL task with file info
                result = {
                    'files': generated_files,
                    'summaries': summaries,
                    'title': title,
                    'message': f"Generated {len(generated_files)} file(s) successfully"
                }
                
                # Mark ORIGINAL task as completed
                if original_task_id:
                    await self.redis.set_task_status(
                        original_task_id,
                        TaskStatus.COMPLETED,
                        result=result
                    )
                    logger.info(f"✅ Completed original task {original_task_id} with files")
                
                # Also complete this file task
                await self.redis.set_task_status(
                    task_data.task_id,
                    TaskStatus.COMPLETED,
                    result=result
                )
                
                logger.info(f"✅ Generated {len(generated_files)} files for task {task_data.task_id}")
            else:
                raise Exception("No files were generated successfully")
                    
            
        except Exception as e:
            logger.error(f"Error processing file task: {e}")
            
            # Fail both tasks
            await self.redis.set_task_status(
                task_data.task_id,
                TaskStatus.FAILED,
                error=str(e)
            )
            
            original_task_id = task_data.data.get('original_task_id')
            if original_task_id:
                await self.redis.set_task_status(
                    original_task_id,
                    TaskStatus.FAILED,
                    error=f"File generation failed: {str(e)}"
                )

async def main():
    """Main entry point"""
    service = FileManagerService()
    await service.start()

if __name__ == "__main__":
    asyncio.run(main())
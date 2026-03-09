#!/usr/bin/env python3
"""
Daily Podcast Briefing System
Fetches, transcribes, summarizes, and emails tech/AI podcast digests
"""
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import feedparser
import requests
import pathlib
import datetime as dt
import sqlite3
import os
import asyncio
import uuid
import smtplib
import logging
from urllib.parse import urlparse
from email.message import EmailMessage
from dotenv import load_dotenv

# OpenAI imports
from openai import OpenAI

# ElevenLabs TTS import
from elevenlabs import ElevenLabs

# Faster Whisper import for transcription
from faster_whisper import WhisperModel

# Load environment variables
load_dotenv()

# Use existing logging configuration (set up by the application entry point).
# Avoid calling logging.basicConfig here – it would add duplicate handlers when
# this module is imported inside a Celery worker that already configured logging.
logger = logging.getLogger(__name__)

# Configuration
DB_PATH = pathlib.Path('podbrief.db')
AUDIO_DIR = pathlib.Path('audio')
VOICE_DIR = pathlib.Path('voice')
TRANSCRIPT_DIR = pathlib.Path('transcripts')
DIGEST_DIR = pathlib.Path('digests')

# Create directories if they don't exist
for dir_path in [AUDIO_DIR, VOICE_DIR, TRANSCRIPT_DIR, DIGEST_DIR]:
    dir_path.mkdir(exist_ok=True)

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv('OPENROUTER_API_KEY'), base_url="https://openrouter.ai/api/v1")

# Initialize ElevenLabs client
elevenlabs_client = ElevenLabs(
    api_key=os.getenv("ELEVENLABS_API_KEY"),
)

# Database functions
def init_db():
    """Initialize SQLite database for tracking processed episodes"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            feed_url TEXT NOT NULL,
            audio_url TEXT NOT NULL,
            published TIMESTAMP NOT NULL,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            transcript_path TEXT,
            summary TEXT,
            UNIQUE(audio_url)
        )
    ''')
    conn.commit()
    conn.close()

def get_last_check_time():
    """Get the timestamp of the last processed episode"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT MAX(published) FROM episodes')
    result = cursor.fetchone()
    conn.close()
    
    if result and result[0]:
        return dt.datetime.fromisoformat(result[0])
    # Default to 7 days ago if no episodes processed yet
    return dt.datetime.now() - dt.timedelta(days=7)

def save_episode(title, feed_url, audio_url, published, transcript_path, summary):
    """Save processed episode to database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO episodes (title, feed_url, audio_url, published, transcript_path, summary)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (title, feed_url, audio_url, published.isoformat(), str(transcript_path), summary))
        conn.commit()
    except sqlite3.IntegrityError:
        logger.warning(f"Episode already processed: {title}")
    finally:
        conn.close()

# Podcast fetching functions
def fetch_latest_episodes(feed_url, since_timestamp):
    """Fetch episodes published after the given timestamp"""
    try:
        logger.info(f"Fetching feed: {feed_url}")
        feed = feedparser.parse(feed_url)
        
        for entry in feed.entries:
            # Parse publication date
            if hasattr(entry, 'published_parsed'):
                pub_date = dt.datetime(*entry.published_parsed[:6])
            else:
                logger.warning(f"No publication date for: {entry.title}")
                continue
            
            # Skip if older than threshold
            if pub_date <= since_timestamp:
                continue
            
            # Find audio enclosure
            audio_url = None
            for enclosure in getattr(entry, 'enclosures', []):
                if enclosure.get('type', '').startswith('audio'):
                    audio_url = enclosure.get('href')
                    break
            
            if audio_url:
                yield {
                    'title': entry.title,
                    'audio_url': audio_url,
                    'published': pub_date,
                    'feed_url': feed_url
                }
            else:
                logger.warning(f"No audio found for: {entry.title}")
                
    except Exception as e:
        logger.error(f"Error fetching feed {feed_url}: {e}")

def download_audio(url, dest_folder):
    """Download audio file with streaming to handle large files"""
    try:
        # Generate filename from URL
        parsed_url = urlparse(url)
        filename = pathlib.Path(parsed_url.path).name
        if not filename or not filename.endswith(('.mp3', '.mp4', '.m4a')):
            filename = f"{uuid.uuid4().hex}.mp3"
        
        file_path = dest_folder / filename
        
        # Skip if already downloaded
        if file_path.exists():
            logger.info(f"Audio already downloaded: {filename}")
            return file_path
        
        logger.info(f"Downloading: {filename}")
        
        # Stream download to avoid memory issues
        with requests.get(url, stream=True, timeout=60) as response:
            response.raise_for_status()
            
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=1024*32):
                    if chunk:
                        f.write(chunk)
        
        logger.info(f"Downloaded: {filename}")
        return file_path
        
    except Exception as e:
        logger.error(f"Error downloading {url}: {e}")
        return None

# --- Transcription and summarization ---

def transcribe_audio(audio_path):
    """
    Transcribe audio using faster-whisper.
    Returns (transcript_text, transcript_path) or (None, None) on error.
    """
    try:
        logger.info(f"Transcribing (faster-whisper): {audio_path.name}")

        # Use CUDA when torch is available and reports a usable GPU; otherwise
        # fall back to CPU instead of failing the whole transcription step.
        device = "cpu"
        if os.environ.get("USE_CUDA", "1") == "1":
            try:
                import torch  # type: ignore

                if getattr(torch, "cuda", None) and torch.cuda.is_available():
                    device = "cuda"
            except Exception:
                logger.info("Torch unavailable, using CPU transcription")
        compute_type = "float16" if device == "cuda" else "int8"

        # Load the model (large-v3 for high accuracy; use 'base' for faster but less accurate)
        model_size = "large-v3"
        model = WhisperModel(model_size, device=device, compute_type=compute_type)

        # Transcribe the audio file
        segments, info = model.transcribe(str(audio_path), beam_size=5)

        logger.info(f"Detected language: {info.language} with probability {info.language_probability:.2f}")

        transcript_lines = []
        for segment in segments:
            line = f"[{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}"
            transcript_lines.append(line)
            logger.debug(line)

        transcript_text = "\n".join(transcript_lines)

        # Write the transcript to a file
        transcript_path = TRANSCRIPT_DIR / f"{audio_path.stem}.txt"
        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write(transcript_text)

        logger.info(f"Transcription saved: {transcript_path.name}")

        return transcript_text, transcript_path

    except Exception as e:
        logger.error(f"Error in faster-whisper transcription: {e}")
        return None, None

def summarize_transcript(transcript_text, episode_title):
    """Generate concise summary using GPT-3.5-turbo"""
    try:
        logger.info(f"Summarizing: {episode_title}")
        
        # Truncate to avoid token limits
        max_chars = 120000
        if len(transcript_text) > max_chars:
            transcript_text = transcript_text[:max_chars]
        
        system_prompt = """You are an expert podcast analyst. Provide a concise bullet digest (≤350 words) 
        of the transcript. Focus on key insights, announcements, and technical discussions. 
        Format as 5-10 clear bullet points."""
        
        response = client.chat.completions.create(
            model="minimax/minimax-m2.5",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Episode: {episode_title}\n\nTranscript:\n{transcript_text}"}
            ],
        )
        print(response)
        summary = response.choices[0].message.content 
        logger.info(f"Summary generated for: {episode_title}")
        return summary
        
    except Exception as e:
        logger.error(f"Error summarizing {episode_title}: {e}")
        return None

# Text-to-speech using ElevenLabs
async def text_to_speech(text, output_dir):
    """Convert text to speech using ElevenLabs API"""
    try:
        output_file = output_dir / f"digest-{uuid.uuid4().hex}.mp3"
        # ElevenLabs API call
        audio_response = elevenlabs_client.text_to_speech.convert(
            voice_id="1SM7GgM6IMuvQlz2BwM3",
            output_format="mp3_44100_128",
            text=text,
            model_id="eleven_multilingual_v2",
        )
        # Save the audio to file
        with open(output_file, "wb") as f:
            f.write(audio_response)
        logger.info(f"TTS generated: {output_file.name}")
        return output_file
    except Exception as e:
        logger.error(f"Error generating TTS: {e}")
        return None

# Email functions
def create_digest_email(summaries, date):
    """Create formatted email body from summaries"""
    email_body = f"# Daily Tech Podcast Briefing - {date:%B %d, %Y}\n\n"
    
    for summary in summaries:
        email_body += f"## {summary['title']}\n"
        email_body += f"*Published: {summary['published']:%B %d at %I:%M %p}*\n\n"
        email_body += f"{summary['summary']}\n\n"
        email_body += "---\n\n"
    
    email_body += "\n*Generated by Daily Podcast Briefing System*"
    
    return email_body

def send_digest_email(text_body, audio_path):
    """Send email with text digest and audio attachment"""
    try:
        msg = EmailMessage()
        msg['Subject'] = f"Daily Tech Podcast Briefing – {dt.date.today():%b %d}"
        msg['From'] = os.getenv('MAIL_FROM')
        msg['To'] = os.getenv('MAIL_TO')
        
        # Set plain text content
        msg.set_content(text_body)
        
        # Attach audio file if provided
        if audio_path and audio_path.exists():
            with open(audio_path, 'rb') as f:
                audio_data = f.read()
                msg.add_attachment(
                    audio_data,
                    maintype='audio',
                    subtype='mpeg',
                    filename=f"podcast-digest-{dt.date.today():%Y%m%d}.mp3"
                )
        
        # Send email
        smtp_host = os.getenv('SMTP_HOST')
        smtp_user = os.getenv('SMTP_USER')
        smtp_pass = os.getenv('SMTP_PASS')
        
        with smtplib.SMTP_SSL(smtp_host, 465) as server:
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        
        logger.info("Email sent successfully")
        
    except Exception as e:
        logger.error(f"Error sending email: {e}")

# Main workflow
async def process_podcasts():
    """Main workflow to process all podcasts"""
    # Initialize database
    init_db()
    
    # Get RSS feeds from environment
    rss_feeds = os.getenv('RSS_FEEDS', '').split(',')
    rss_feeds = [feed.strip() for feed in rss_feeds if feed.strip()]
    
    if not rss_feeds:
        logger.error("No RSS feeds configured in .env file")
        return
    
    # Get last check time
    since_timestamp = get_last_check_time()
    logger.info(f"Checking for episodes since: {since_timestamp}")
    
    # Collect all new episodes
    all_summaries = []
    
    for feed_url in rss_feeds:
        for episode in fetch_latest_episodes(feed_url, since_timestamp):
            logger.info(f"Processing: {episode['title']}")
            
            # Download audio
            audio_path = download_audio(episode['audio_url'], AUDIO_DIR)
            if not audio_path:
                continue
            
            # Transcribe
            transcript_text, transcript_path = transcribe_audio(audio_path)
            if not transcript_text:
                continue
            
            # Summarize
            summary = summarize_transcript(transcript_text, episode['title'])
            if not summary:
                continue
            
            # Save to database
            save_episode(
                episode['title'],
                episode['feed_url'],
                episode['audio_url'],
                episode['published'],
                transcript_path,
                summary
            )
            
            # Add to summaries list
            all_summaries.append({
                'title': episode['title'],
                'published': episode['published'],
                'summary': summary
            })
            
            # Rate limiting
            await asyncio.sleep(2)
    
    # If we have new summaries, create and send digest
    if all_summaries:
        logger.info(f"Creating digest for {len(all_summaries)} episodes")
        
        # Sort by publication date
        all_summaries.sort(key=lambda x: x['published'], reverse=True)
        
        # Create email body
        email_body = create_digest_email(all_summaries, dt.date.today())
        
        # Save digest to file
        digest_path = DIGEST_DIR / f"digest-{dt.date.today():%Y%m%d}.md"
        with open(digest_path, 'w', encoding='utf-8') as f:
            f.write(email_body)
        
        # Generate audio digest
        audio_summary = "\n\n".join([f"{s['title']}. {s['summary']}" for s in all_summaries])
        audio_path = await text_to_speech(audio_summary, VOICE_DIR)
        
        # Send email
        send_digest_email(email_body, audio_path)
        
        logger.info("Daily podcast briefing complete!")
    else:
        logger.info("No new episodes found")

# Cleanup old files
def cleanup_old_files(days=14):
    """Remove files older than specified days"""
    cutoff_date = dt.datetime.now() - dt.timedelta(days=days)
    
    for directory in [AUDIO_DIR, VOICE_DIR, TRANSCRIPT_DIR]:
        for file_path in directory.glob('*'):
            if file_path.is_file():
                file_mtime = dt.datetime.fromtimestamp(file_path.stat().st_mtime)
                if file_mtime < cutoff_date:
                    file_path.unlink()
                    logger.info(f"Deleted old file: {file_path.name}")

# Main entry point
def main():
    """Main entry point for the script"""
    try:
        logger.info("Starting daily podcast briefing")
        
        # Run cleanup first
        cleanup_old_files()
        
        # Run main workflow
        asyncio.run(process_podcasts())
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise

if __name__ == "__main__":
    main()

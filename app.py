import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from deep_translator import GoogleTranslator
from moviepy.editor import VideoFileClip, CompositeVideoClip, VideoClip
import tempfile
from flask import Flask
from threading import Thread
import requests
import gc
from PIL import Image, ImageDraw, ImageFont
import numpy as np

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Bot is running with Groq!"

@app.route('/health')
def health():
    return "OK", 200

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 שלום! אני בוט תרגום כתוביות (Powered by Groq ⚡)\n\n"
        "שלח לי סרטון עם אודיו באנגלית,\n"
        "ואני אחזיר לך את הסרטון עם כתוביות בעברית! 🇮🇱\n\n"
        "📹 פשוט שלח סרטון ואני אתחיל...\n\n"
        "⚠️ מגבלות:\n"
        "• סרטון עד 10 דקות\n"
        "• גודל עד 50MB\n\n"
        "⚡ מהיר פי 10 מהגרסה הקודמת!"
    )

def transcribe_with_groq(audio_path):
    """תמלול אודיו באמצעות Groq API"""
    GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
    
    if not GROQ_API_KEY:
        raise Exception("GROQ_API_KEY לא מוגדר!")
    
    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}"
    }
    
    with open(audio_path, 'rb') as audio_file:
        files = {
            'file': audio_file,
            'model': (None, 'whisper-large-v3'),
            'language': (None, 'en'),
            'response_format': (None, 'verbose_json'),
            'timestamp_granularities[]': (None, 'segment')
        }
        
        response = requests.post(url, headers=headers, files=files, timeout=300)
    
    if response.status_code != 200:
        raise Exception(f"Groq API Error: {response.text}")
    
    return response.json()

def make_text_image(text, width, height):
    """יצירת תמונה עם טקסט עברי - עוקף את בעיית moviepy"""
    img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    try:
        # נסה להשתמש בפונט DejaVu שתומך בעברית
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
    except:
        try:
            # אם לא עובד, נסה FreeSans
            font = ImageFont.truetype("/usr/share/fonts/truetype/freefont/FreeSans.ttf", 36)
        except:
            try:
                # נסה פונט נוסף
                font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 36)
            except:
                # אחרון - פונט ברירת מחדל
                font = ImageFont.load_default()
    
    # מדידת גודל הטקסט
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    # מרכוז הטקסט
    x = (width - text_width) // 2
    y = (height - text_height) // 2
    
    # רקע שחור מתחת לטקסט
    padding = 15
    draw.rectangle(
        [x - padding, y - padding, x + text_width + padding, y + text_height + padding],
        fill=(0, 0, 0, 220)
    )
    
    # טקסט לבן
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))
    
    return np.array(img)

def create_hebrew_subtitle_clip(text, start, duration, video_size):
    """יצירת קליפ כתובית עברית"""
    width, height = video_size
    subtitle_height = 120
    
    def make_frame(t):
        return make_text_image(text, width, subtitle_height)
    
    clip = VideoClip(make_frame, duration=duration)
    clip = clip.set_start(start)
    clip = clip.set_position(('center', height - subtitle_height - 40))
    
    return clip

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    video_path = None
    audio_path = None
    output_path = None
    video = None
    
    try:
        if update.message.video.file_size > 50 * 1024 * 1024:
            await update.message.reply_text("❌ הסרטון גדול מדי! מקסימום 50MB")
            return
        
        status_msg = await update.message.reply_text("⏳ מעבד את הסרטון... (עם Groq זה מהיר!)")
        
        video_file = await update.message.video.get_file()
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as temp_video:
            await video_file.download_to_drive(temp_video.name)
            video_path = temp_video.name
        
        await status_msg.edit_text("🎤 מחלץ אודיו...")
        
        video = VideoFileClip(video_path)
        
        if video.duration > 600:
            await update.message.reply_text("❌ הסרטון ארוך מדי! מקסימום 10 דקות")
            video.close()
            os.remove(video_path)
            return
        
        audio_path = video_path.replace('.mp4', '.mp3')
        video.audio.write_audiofile(audio_path, verbose=False, logger=None)
        
        video_size = video.size
        video.close()
        video = None
        gc.collect()
        
        await status_msg.edit_text("🗣️ מתמלל דיבור עם Groq (מהיר!)...")
        
        result = transcribe_with_groq(audio_path)
        segments = result.get('segments', [])
        
        if not segments:
            await update.message.reply_text("❌ לא נמצא דיבור באודיו")
            return
        
        gc.collect()
        
        await status_msg.edit_text("🌍 מתרגם לעברית...")
        
        translator = GoogleTranslator(source='en', target='iw')
        subtitles = []
        
        for seg in segments:
            text = seg.get('text', '').strip()
            if text and len(text) > 2:
                try:
                    translated = translator.translate(text)
                    subtitles.append({
                        'start': seg['start'],
                        'end': seg['end'],
                        'text': translated
                    })
                except:
                    continue
        
        if not subtitles:
            await update.message.reply_text("❌ לא נמצא טקסט לתרגום")
            return
        
        await status_msg.edit_text("🎨 מוסיף כתוביות לסרטון...")
        
        video = VideoFileClip(video_path)
        
        txt_clips = []
        for sub in subtitles:
            try:
                clip = create_hebrew_subtitle_clip(
                    sub['text'],
                    sub['start'],
                    sub['end'] - sub['start'],
                    video_size
                )
                txt_clips.append(clip)
            except Exception as e:
                logger.error(f"Failed to create subtitle clip: {e}")
                continue
        
        final_video = CompositeVideoClip([video] + txt_clips)
        output_path = video_path.replace('.mp4', '_subtitled.mp4')
        
        final_video.write_videofile(
            output_path,
            codec='libx264',
            audio_codec='aac',
            preset='ultrafast',
            threads=2,
            verbose=False,
            logger=None
        )
        
        final_video.close()
        video.close()
        gc.collect()
        
        await status_msg.edit_text("📤 שולח את הסרטון...")
        
        with open(output_path, 'rb') as video_file_to_send:
            await update.message.reply_video(
                video=video_file_to_send,
                caption="✅ הנה הסרטון שלך עם כתוביות בעברית!\n⚡ Powered by Groq",
                read_timeout=60,
                write_timeout=60
            )
        
        await status_msg.delete()
        
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(f"❌ שגיאה: {str(e)}")
        
    finally:
        try:
            if video:
                video.close()
        except:
            pass
        
        for file_path in [video_path, audio_path, output_path]:
            try:
                if file_path and os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                logger.error(f"Failed to delete {file_path}: {e}")
        
        gc.collect()

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception: {context.error}")

def run_bot():
    TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
    
    if not TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN לא מוגדר!")
        return
    
    GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
    if not GROQ_API_KEY:
        logger.error("❌ GROQ_API_KEY לא מוגדר!")
        return
    
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.VIDEO, handle_video))
    application.add_error_handler(error_handler)
    
    logger.info("🤖 הבוט מתחיל לרוץ עם Groq...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

def run_flask():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    run_bot()

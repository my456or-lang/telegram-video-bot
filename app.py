import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import whisper
from deep_translator import GoogleTranslator
from moviepy.editor import VideoFileClip, TextClip, CompositeVideoClip
import tempfile
from flask import Flask
from threading import Thread

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# טעינת מודל Whisper
model = whisper.load_model("base")

# Flask app לשמירת השרת פעיל
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Bot is running!"

@app.route('/health')
def health():
    return "OK", 200

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 שלום! אני בוט תרגום כתוביות\n\n"
        "שלח לי סרטון עם אודיו באנגלית,\n"
        "ואני אחזיר לך את הסרטון עם כתוביות בעברית! 🇮🇱\n\n"
        "📹 פשוט שלח סרטון ואני אתחיל...\n\n"
        "⚠️ מגבלות:\n"
        "• סרטון עד 10 דקות\n"
        "• גודל עד 50MB"
    )

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # בדיקת גודל קובץ
        if update.message.video.file_size > 50 * 1024 * 1024:
            await update.message.reply_text("❌ הסרטון גדול מדי! מקסימום 50MB")
            return
        
        status_msg = await update.message.reply_text("⏳ מעבד את הסרטון... אנא המתן (זה יכול לקחת 2-5 דקות)")
        
        video_file = await update.message.video.get_file()
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as temp_video:
            await video_file.download_to_drive(temp_video.name)
            video_path = temp_video.name
        
        await status_msg.edit_text("🎤 מחלץ אודיו...")
        
        video = VideoFileClip(video_path)
        audio_path = video_path.replace('.mp4', '.wav')
        video.audio.write_audiofile(audio_path, verbose=False, logger=None)
        
        await status_msg.edit_text("🗣️ מתמלל דיבור...")
        
        result = model.transcribe(audio_path, language='en')
        segments = result['segments']
        
        await status_msg.edit_text("🌍 מתרגם לעברית...")
        
        translator = GoogleTranslator(source='en', target='he')
        subtitles = []
        
        for seg in segments:
            text = seg['text'].strip()
            if text:
                translated = translator.translate(text)
                subtitles.append({
                    'start': seg['start'],
                    'end': seg['end'],
                    'text': translated
                })
        
        await status_msg.edit_text("🎨 מוסיף כתוביות לסרטון...")
        
        txt_clips = []
        for sub in subtitles:
            txt_clip = (TextClip(
                sub['text'],
                fontsize=24,
                color='white',
                bg_color='black',
                font='DejaVu-Sans',
                method='caption',
                size=(video.w * 0.9, None)
            )
            .set_position(('center', video.h * 0.85))
            .set_start(sub['start'])
            .set_duration(sub['end'] - sub['start']))
            
            txt_clips.append(txt_clip)
        
        final_video = CompositeVideoClip([video] + txt_clips)
        output_path = video_path.replace('.mp4', '_subtitled.mp4')
        
        final_video.write_videofile(
            output_path,
            codec='libx264',
            audio_codec='aac',
            verbose=False,
            logger=None
        )
        
        await status_msg.edit_text("📤 שולח את הסרטון...")
        
        with open(output_path, 'rb') as video_file:
            await update.message.reply_video(
                video=video_file,
                caption="✅ הנה הסרטון שלך עם כתוביות בעברית!"
            )
        
        await status_msg.delete()
        
        # ניקוי קבצים
        video.close()
        os.remove(video_path)
        os.remove(audio_path)
        os.remove(output_path)
        
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(f"❌ שגיאה בעיבוד הסרטון: {str(e)}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception: {context.error}")

def run_bot():
    TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
    
    if not TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN לא מוגדר!")
        return
    
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.VIDEO, handle_video))
    application.add_error_handler(error_handler)
    
    logger.info("🤖 הבוט מתחיל לרוץ...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

def run_flask():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    # הרצת Flask בתהליך נפרד
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # הרצת הבוט
    run_bot()

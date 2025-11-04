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
import gc

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask app
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
        "• סרטון עד 5 דקות\n"
        "• גודל עד 20MB"
    )

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    video_path = None
    audio_path = None
    output_path = None
    video = None
    
    try:
        # בדיקת גודל - הקטנו ל-20MB
        if update.message.video.file_size > 20 * 1024 * 1024:
            await update.message.reply_text("❌ הסרטון גדול מדי! מקסימום 20MB")
            return
        
        status_msg = await update.message.reply_text("⏳ מעבד את הסרטון... אנא המתן")
        
        video_file = await update.message.video.get_file()
        
        # שימוש ב-tempfile עם ניקוי אוטומטי
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as temp_video:
            await video_file.download_to_drive(temp_video.name)
            video_path = temp_video.name
        
        await status_msg.edit_text("🎤 מחלץ אודיו...")
        
        # חילוץ אודיו
        video = VideoFileClip(video_path)
        
        # בדיקת אורך סרטון
        if video.duration > 300:  # 5 דקות
            await update.message.reply_text("❌ הסרטון ארוך מדי! מקסימום 5 דקות")
            video.close()
            os.remove(video_path)
            return
        
        audio_path = video_path.replace('.mp4', '.wav')
        video.audio.write_audiofile(audio_path, verbose=False, logger=None)
        
        # סגירת הסרטון כדי לפנות זיכרון
        video.close()
        video = None
        gc.collect()  # ניקוי זיכרון
        
        await status_msg.edit_text("🗣️ מתמלל דיבור...")
        
        # טעינת מודל Whisper רק כשצריך
        model = whisper.load_model("tiny")  # שימוש במודל קטן יותר!
        result = model.transcribe(audio_path, language='en', fp16=False)
        segments = result['segments']
        
        # מחיקת המודל מהזיכרון
        del model
        gc.collect()
        
        await status_msg.edit_text("🌍 מתרגם לעברית...")
        
        translator = GoogleTranslator(source='en', target='he')
        subtitles = []
        
        # תרגום בחלקים קטנים
        for seg in segments:
            text = seg['text'].strip()
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
        
        # פתיחה מחדש של הסרטון
        video = VideoFileClip(video_path)
        
        txt_clips = []
        for sub in subtitles:
            txt_clip = (TextClip(
                sub['text'],
                fontsize=22,  # פונט קצת יותר קטן
                color='white',
                bg_color='black',
                font='Arial',  # פונט פשוט יותר
                method='caption',
                size=(video.w * 0.85, None)
            )
            .set_position(('center', video.h * 0.85))
            .set_start(sub['start'])
            .set_duration(sub['end'] - sub['start']))
            
            txt_clips.append(txt_clip)
        
        final_video = CompositeVideoClip([video] + txt_clips)
        output_path = video_path.replace('.mp4', '_subtitled.mp4')
        
        # כתיבת וידאו עם הגדרות נמוכות יותר
        final_video.write_videofile(
            output_path,
            codec='libx264',
            audio_codec='aac',
            preset='ultrafast',  # מהיר יותר, פחות זיכרון
            threads=2,  # הגבלת threads
            verbose=False,
            logger=None
        )
        
        # סגירה וניקוי
        final_video.close()
        video.close()
        gc.collect()
        
        await status_msg.edit_text("📤 שולח את הסרטון...")
        
        # שליחת הקובץ
        with open(output_path, 'rb') as video_file_to_send:
            await update.message.reply_video(
                video=video_file_to_send,
                caption="✅ הנה הסרטון שלך עם כתוביות בעברית!",
                read_timeout=60,
                write_timeout=60
            )
        
        await status_msg.delete()
        
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(f"❌ שגיאה בעיבוד הסרטון: {str(e)}\n\nנסה סרטון קטן יותר.")
        
    finally:
        # ניקוי קבצים - תמיד!
        try:
            if video:
                video.close()
        except:
            pass
        
        for file_path in [video_path, audio_path, output_path]:
            try:
                if file_path and os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"Deleted: {file_path}")
            except Exception as e:
                logger.error(f"Failed to delete {file_path}: {e}")
        
        gc.collect()  # ניקוי סופי

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
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    run_bot()

FROM python:3.11-slim

# התקנת תלויות מערכת
RUN apt-get update && apt-get install -y \
    ffmpeg \
    fonts-dejavu-core \
    fonts-dejavu-extra \
    imagemagick \
    && rm -rf /var/lib/apt/lists/*

# הגדרת תיקיית עבודה
WORKDIR /app

# העתקה והתקנת תלויות Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# העתקת כל הקוד
COPY . .

# הפעלת הבוט
CMD ["python", "bot.py"]

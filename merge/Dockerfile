FROM python:3.11-slim

# ffmpeg สำหรับ merge video+audio+subtitles
RUN apt-get update && apt-get install -y \
    ffmpeg wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy font
COPY font.ttf .

COPY server.py .

EXPOSE 8080

CMD ["python", "server.py"]

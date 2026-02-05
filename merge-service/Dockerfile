FROM python:3.11-slim

# Install ffmpeg, sox, and yt-dlp
RUN apt-get update && apt-get install -y \
    ffmpeg \
    sox \
    curl \
    python3-pip \
    && pip3 install --break-system-packages yt-dlp \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create persistent data directory
RUN mkdir -p /app/data/videos

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Cache bust: 2026-02-05T17:59
COPY . .

# Copy cookies for XHS login (yt-dlp will use this)
COPY cookies.txt /app/cookies.txt

EXPOSE 80

CMD ["python", "server.py"]

FROM python:3.11-slim

# Install ffmpeg, sox, yt-dlp and playwright deps
RUN apt-get update && apt-get install -y \
    ffmpeg \
    sox \
    curl \
    python3-pip \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 \
    && pip3 install --break-system-packages yt-dlp \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create persistent data directory
RUN mkdir -p /app/data/videos

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright and browser
RUN pip install playwright httpx && playwright install chromium

COPY . .
COPY cookies.txt /app/cookies.txt

EXPOSE 80

CMD ["python", "server.py"]

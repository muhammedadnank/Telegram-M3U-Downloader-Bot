# Use lightweight Python image
FROM python:3.11-slim

# Avoid Python buffering issues
ENV PYTHONUNBUFFERED=1

# Install system dependencies (yt-dlp + ffmpeg)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install yt-dlp (latest)
RUN curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
    -o /usr/local/bin/yt-dlp && \
    chmod a+rx /usr/local/bin/yt-dlp

# Set working directory
WORKDIR /app

# Copy requirements first (for caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files
COPY . .

# Set working directory to src for running
WORKDIR /app/src

# Run bot
CMD ["python", "bot.py"]
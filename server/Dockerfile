FROM python:3.12-slim

# Keep Python output unbuffered so logs appear in real time
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the script
COPY spotify_albums.py .

# /data is where the CSV and cached token will live (mount a volume here)
VOLUME ["/data"]

# OAuth callback port
EXPOSE 8888

CMD ["python", "spotify_albums.py"]

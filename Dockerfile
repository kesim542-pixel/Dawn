FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        fontconfig \
        fonts-dejavu-core \
        fonts-dejavu-extra \
        libx264-dev && \
    fc-cache -fv && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Tell Railway which port the web server listens on
EXPOSE 8000

ENV PORT=8000

CMD ["python", "main.py"]

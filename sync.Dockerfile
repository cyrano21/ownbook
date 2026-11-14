FROM python:3.11-alpine

WORKDIR /app

COPY scripts/calibre-sync.py /app/calibre-sync.py
RUN chmod +x /app/calibre-sync.py

ENV PYTHONUNBUFFERED=1

CMD ["python3", "-u", "/app/calibre-sync.py"]

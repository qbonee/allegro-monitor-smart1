# Playwright z przeglądarkami w wersji zgodnej z 1.54.x
FROM mcr.microsoft.com/playwright/python:v1.54.0-jammy

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "worker_loop.py"]

# Playwright z przeglądarkami w wersji zgodnej z 1.54.x
FROM mcr.microsoft.com/playwright/python:v1.54.0-jammy

# logi bez buforowania (od razu widać w Render)
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# zależności Pythona
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# cały kod aplikacji
COPY . .

# uruchamiamy pętlę workera
CMD ["python", "worker_loop.py"]

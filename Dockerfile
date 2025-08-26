FROM mcr.microsoft.com/playwright/python:v1.46.0-jammy

ENV TZ=Europe/Warsaw
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "runner.py"]

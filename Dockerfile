FROM mcr.microsoft.com/playwright/python:v1.54.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# (opcjonalnie) gdybyś usunął playwright z requirements, przeglądarki i tak są już w tym obrazie
# RUN playwright install --with-deps chromium

COPY . .

CMD ["python", "worker_loop.py"]

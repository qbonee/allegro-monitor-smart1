# dopasowany do 1.54.0
FROM mcr.microsoft.com/playwright/python:v1.54.0-jammy

WORKDIR /app

# jeśli trzymasz playwright w requirements, przypnij do 1.54.0
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# (opcjonalnie) gdybyś usunął playwright z requirements,
# przeglądarki i tak są już w tym obrazie
# RUN playwright install --with-deps chromium

COPY . .

# jeśli nie ustawiasz Start Command w Renderze,
# odpal pętlę workerową tutaj:
# CMD ["python", "worker_loop.py"]

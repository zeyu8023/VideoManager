FROM python:3.10-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/data /app/assets /app/temp_uploads
EXPOSE 10309
CMD ["uvicorn", "backend.main:main_app", "--host", "0.0.0.0", "--port", "10309"]
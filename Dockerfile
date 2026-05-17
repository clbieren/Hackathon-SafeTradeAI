# 3.13 yerine 3.12 kullanıyoruz, taş gibi çalışır.
FROM python:3.12-slim

WORKDIR /code

# PostgreSQL için gerekli sistem kütüphanesi (binary sürücü için şart)
RUN apt-get update && apt-get install -y libpq-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
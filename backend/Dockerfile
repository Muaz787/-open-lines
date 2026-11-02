FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# exec replaces the shell, so uvicorn receives Railway's SIGTERM and shuts down
# gracefully. Without it the shell kept the signal and the app was killed.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]

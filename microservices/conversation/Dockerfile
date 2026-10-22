FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home service
COPY conversation_service ./conversation_service
USER service
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "conversation_service.app:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home service
COPY identity_service ./identity_service
USER service
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "identity_service.app:app", "--host", "0.0.0.0", "--port", "8000"]

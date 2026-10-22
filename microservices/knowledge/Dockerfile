FROM python:3.12-slim
WORKDIR /app
ENV HF_HOME=/home/service/.cache/huggingface
COPY requirements.txt .
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch && pip install --no-cache-dir -r requirements.txt && useradd --create-home service
RUN mkdir -p /home/service/.cache/huggingface && chown -R service:service /home/service/.cache
COPY knowledge_service ./knowledge_service
USER service
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "knowledge_service.app:app", "--host", "0.0.0.0", "--port", "8000"]

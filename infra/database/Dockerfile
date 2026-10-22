FROM python:3.12-slim
RUN pip install --no-cache-dir psycopg[binary]==3.3.6
WORKDIR /bootstrap
COPY bootstrap.py .
CMD ["python", "bootstrap.py"]

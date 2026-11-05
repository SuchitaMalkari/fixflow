FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FIXFLOW_DB_PATH=/app/var/fixflow.db

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY fixflow ./fixflow
COPY data ./data
RUN mkdir -p /app/var && useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "fixflow.api:app", "--host", "0.0.0.0", "--port", "8000"]

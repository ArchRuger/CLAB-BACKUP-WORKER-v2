FROM python:3.12-slim
WORKDIR /service
RUN pip install --no-cache-dir 'fastapi>=0.115,<1' 'uvicorn>=0.30,<1' 'httpx>=0.27,<1' 'websockets>=15,<16'
COPY clab-backup-ui/app/__init__.py clab-backup-ui/app/capture.py clab-backup-ui/app/capture_sessions.py clab-backup-ui/app/capture_service.py ./app/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["uvicorn", "app.capture_service:create_app", "--factory", "--host", "0.0.0.0", "--port", "5801", "--workers", "1", "--no-access-log"]

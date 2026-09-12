FROM python:3.12-slim
LABEL org.opencontainers.image.version="1.19.1"
RUN apt-get update \
 && apt-get install -y --no-install-recommends git openssh-client tini \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt collections.yml /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
 && ansible-galaxy collection install -p /usr/share/ansible/collections -r /tmp/collections.yml \
 && pip freeze > /opt/python-packages.txt \
 && ansible-galaxy collection list > /opt/ansible-collections.txt
RUN groupadd --gid 10001 worker \
 && useradd --create-home --uid 10001 --gid 10001 worker \
 && mkdir /data \
 && chown worker:worker /data \
 && chmod 700 /data
WORKDIR /opt/nos-backup
COPY app/ ./app/
COPY VERSION ./VERSION
RUN python -c 'from pathlib import Path; from app import __version__; expected = Path("VERSION").read_text().strip(); assert __version__ == expected, "VERSION and app.__version__ do not match"'
ENV DATA_DIR=/data PYTHONUNBUFFERED=1 ANSIBLE_COLLECTIONS_PATH=/usr/share/ansible/collections
USER worker
EXPOSE 8081
ENTRYPOINT ["/usr/bin/tini", "-g", "--"]
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8081", "--workers", "1"]

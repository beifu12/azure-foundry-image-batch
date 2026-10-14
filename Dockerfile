FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /workspace
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home workspace
COPY image_batch.py app_setup.py web_app.py ./
COPY web ./web
USER 10001
EXPOSE 8767
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8767/healthz', timeout=3)"
CMD ["python", "-X", "utf8", "web_app.py", "--host", "0.0.0.0", "--port", "8767"]

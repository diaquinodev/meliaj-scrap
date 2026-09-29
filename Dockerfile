FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements-case.txt .
RUN pip install --no-cache-dir -r requirements-case.txt \
    && useradd --create-home --uid 10001 appuser
COPY intelligence ./intelligence
USER 10001
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health/live', timeout=2)"
CMD ["uvicorn", "intelligence.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8001"]

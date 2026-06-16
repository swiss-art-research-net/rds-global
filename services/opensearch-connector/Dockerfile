FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn httpx pyyaml python-multipart
COPY app.py /app/app.py
EXPOSE 8000
ENTRYPOINT ["python", "app.py"]
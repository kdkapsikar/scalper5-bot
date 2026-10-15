FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY scalpbot ./scalpbot
VOLUME ["/app/.state"]
CMD ["python", "-m", "scalpbot.bot"]

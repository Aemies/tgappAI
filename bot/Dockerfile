FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY radar_bot radar_bot
CMD ["python", "-m", "radar_bot"]

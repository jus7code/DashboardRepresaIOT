FROM python:3.12-slim
WORKDIR /devices
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./
COPY data ./data
ENV PYTHONUNBUFFERED=1
CMD ["python", "twins.py"]

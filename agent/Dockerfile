FROM python:3.13-slim

WORKDIR /app

# Install dependencies using only pre-built wheels (no compilation)
COPY requirements.txt .
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt

# Copy agent code
COPY main.py .
COPY tools/ tools/

EXPOSE 8080

CMD ["python", "main.py"]

FROM python:3.13-slim

WORKDIR /app

# Install only pre-compiled wheels (no source builds needed)
COPY requirements.txt .
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt

# Copy agent code
COPY . .

EXPOSE 8080

CMD ["python", "main.py"]

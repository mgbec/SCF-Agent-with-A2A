FROM python:3.13-slim

WORKDIR /app

# Copy pre-downloaded ARM64 wheels and install from local files (no network, no emulation overhead)
COPY wheels/ /tmp/wheels/
RUN pip install --no-cache-dir --no-index --find-links=/tmp/wheels/ strands-agents boto3 \
    && rm -rf /tmp/wheels/

# Copy agent code
COPY main.py .
COPY tools/ tools/

EXPOSE 8080

CMD ["python", "main.py"]

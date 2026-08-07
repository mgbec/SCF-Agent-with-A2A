FROM python:3.13-slim

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent code
COPY . .

# AgentCore Runtime expects the agent to listen on port 8080
EXPOSE 8080

CMD ["python", "main.py"]

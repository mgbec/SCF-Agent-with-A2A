# SCF Compliance Agent - Streamlit frontend
# Runs on AWS App Runner (linux/amd64). See terraform/frontend.tf.

FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STREAMLIT_SERVER_HEADLESS=true

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code + shared auth helper + sub-pages + base Streamlit config.
# NOTE: no secrets.toml is baked in - entrypoint.sh writes .streamlit/secrets.toml
# from environment variables at container start (App Runner runtime secrets).
COPY app.py auth.py entrypoint.sh ./
COPY pages/ ./pages/
COPY .streamlit/config.toml ./.streamlit/config.toml

# Normalise line endings (the file may be authored on Windows) and make executable.
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

EXPOSE 8501

# Invoke via bash explicitly so a missing exec bit / shebang quirk can't break startup.
ENTRYPOINT ["bash", "/app/entrypoint.sh"]

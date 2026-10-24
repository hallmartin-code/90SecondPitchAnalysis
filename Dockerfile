# 90-Second Pitch Test - Streamlit web app (Railway builds this automatically).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PITCH90_SOFFICE_PATH=/usr/bin/soffice

# LibreOffice: legacy .ppt conversion and PPTX slide rendering for visual review.
# Fonts: metric-compatible substitutes so converted slides lay out like the originals.
# libgl1/libglib2.0-0: required by OpenCV, which the local OCR engine uses.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-impress libreoffice-draw \
        fonts-crosextra-carlito fonts-crosextra-caladea fonts-liberation fonts-dejavu-core \
        libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 app
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=app:app . .
USER app
ENV HOME=/home/app

EXPOSE 8501
# Railway injects PORT; default to 8501 for local `docker run`.
CMD streamlit run app.py \
    --server.port=${PORT:-8501} \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --browser.gatherUsageStats=false

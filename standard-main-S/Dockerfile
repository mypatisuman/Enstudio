# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/app/backend:/app/sdk:/app/sdk/ympl-parser

# Install system dependencies
# Node.js and npm are required for ympl.js bridge.
# libgl1 and libglib2.0-0 are required for OpenCV (classical image handling).
# sqlite3 is required for the SQLite database.
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs \
    npm \
    libgl1 \
    libglib2.0-0 \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy the Node dependency files for ympl-sdk and install
COPY sdk/ympl-sdk/package*.json ./sdk/ympl-sdk/
RUN cd sdk/ympl-sdk && npm install

# No PyTorch. Detection in this application is performed by a vision LLM:
# there is no YOLOv8, no U-Net and no RapidOCR, and no fallback to any of
# them, so the torch/torchvision install that used to live here is gone.
# It was the largest layer in the image. See services/detection_router.py.

# Copy backend python requirements and install
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy the application code and shared SDKs
COPY backend/ ./backend/
COPY sdk/ ./sdk/

# Expose the FastAPI port
EXPOSE 8000

# Set the working directory to the backend folder where main.py resides
WORKDIR /app/backend

# Start the FastAPI ASGI app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

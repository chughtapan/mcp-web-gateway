FROM python:3.9-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Download BuildYourOwnRapidAPIServer
RUN mkdir -p build && cd build && \
    echo "Downloading BuildYourOwnRapidAPIServer.zip..." && \
    wget -q --show-progress "https://drive.google.com/uc?export=download&id=1JdbHkL2D8as1docfHyfLWhrhlSP9rZhf" -O BuildYourOwnRapidAPIServer.zip && \
    echo "Extracting BuildYourOwnRapidAPIServer..." && \
    unzip -q BuildYourOwnRapidAPIServer.zip

# Setup server files
RUN echo "Setting up server files..." && \
    cp build/BuildYourOwnRapidAPIServer/utils.py utils.py && \
    rm -rf build

# Copy our modified main file
COPY toolbench_main.py .

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY server.py .

# Create required files
RUN echo "test_key" > user_keys.txt && \
    echo "dummy_key" > rapidapi_keys.txt

# Expose port
EXPOSE 8080

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Run the server
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8080"]
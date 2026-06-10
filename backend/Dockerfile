FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all backend code
COPY . .

# Default command (overridden per service in fly.toml)
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

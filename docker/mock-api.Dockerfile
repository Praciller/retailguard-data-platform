FROM python:3.11-slim

WORKDIR /app
COPY src ./src
RUN pip install --no-cache-dir "fastapi>=0.115,<1" "uvicorn[standard]>=0.34,<1"

EXPOSE 8000
CMD ["uvicorn", "retailguard.mock_api:app", "--app-dir", "/app/src", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12.4-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Build-time flag: set BUGGY_BUILD=true for api:v2-bad
ARG BUGGY_BUILD=false
ENV BUGGY_BUILD=${BUGGY_BUILD}

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "warning"]

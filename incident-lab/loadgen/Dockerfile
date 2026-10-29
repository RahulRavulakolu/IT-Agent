FROM python:3.12.4-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY locustfile.py .

# Run headless with 2 users targeting web-service (~5 req/s with 0.4-0.6s wait)
CMD ["locust", "--headless", \
     "--host", "http://web-service", \
     "--users", "2", \
     "--spawn-rate", "1", \
     "--loglevel", "WARNING"]

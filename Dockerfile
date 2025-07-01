FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Create volume for database persistence
VOLUME ["/app/data"]

EXPOSE 5000

# Start both scheduler and web server
CMD python scheduler.py & python app.py

FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY indexer.py server.py ./
COPY docs ./docs
COPY tests ./tests

# Build the search index at image build time; the server only loads it.
RUN python indexer.py

ENV PORT=8001
EXPOSE 8001
CMD ["python", "server.py"]

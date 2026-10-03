FROM python:3.12-slim
WORKDIR /app
COPY services/api /app/services/api
COPY services/intelligence /app/services/intelligence
COPY web /app/web
COPY knowledge /app/knowledge
RUN mkdir -p /app/data /app/runtime && useradd --uid 10001 --create-home brain && chown -R brain:brain /app
USER brain
ENV BRAIN_HOST=0.0.0.0 BRAIN_PORT=8080 BRAIN_DB=/app/data/brain.sqlite3 BRAIN_MODEL=/app/runtime/model.json
EXPOSE 8080
VOLUME ["/app/data", "/app/runtime"]
CMD ["python3", "services/api/app.py"]

FROM python:3.12-slim
WORKDIR /app
COPY services/intelligence/ /app/services/intelligence/
COPY knowledge/ /app/knowledge/
RUN useradd --uid 10001 --create-home brain && mkdir -p /app/runtime && chown brain:brain /app/runtime
USER brain
ENV BRAIN_INTELLIGENCE_HOST=0.0.0.0 BRAIN_INTELLIGENCE_PORT=8083
EXPOSE 8083
CMD ["python", "services/intelligence/server.py", "--reference"]

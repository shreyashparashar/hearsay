# Works on Hugging Face Spaces (Docker SDK, free CPU), Render, Railway, Fly.io or your own machine.
FROM python:3.12-slim
RUN useradd -m -u 1000 user
WORKDIR /app
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=user . .
USER user
ENV PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "uvicorn crowdsim.server:app --host 0.0.0.0 --port ${PORT}"]

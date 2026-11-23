FROM python:3.12-slim
WORKDIR /app
COPY simulator.py benchmark_compression.py /app/
CMD ["python3", "-u", "/app/simulator.py", "--scenario", "normal", "--players", "30"]

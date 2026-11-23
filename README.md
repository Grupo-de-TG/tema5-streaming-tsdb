# Tema 5 (P2) — Telemetria de Reprodução, Buffer e Métricas de Stream (TSDB)

Stack containerizada em Docker para o **Sistema 2 (Plataforma de Streaming de Vídeo)** — Seminário Final (P2) de Laboratório de Banco de Dados.

## Componentes
- **InfluxDB v1.8 (`:8089`)**: Database `stream_telemetry` com Retention Policies (`raw_7d` 1s e `agg_1y` 1m) e Continuous Query `cq_stream_1m` (downsampling).
- **Ingest API (`:8091`)**: `POST /api/v1/telemetry` (CORS `*`), `GET /api/v1/telemetry/health`, `GET /api/v1/telemetry/session/{session_id}`.
- **Grafana (`:3006`)**: Dashboard pré-provisionado `Tema 5 — Telemetria de Reprodução, Buffer e Stream`.
- **Simulador & Benchmark (`--profile mock`)**: `simulator/simulator.py` e `simulator/benchmark_compression.py`.
- **Ponte Jellyfin (`jellyfin_bridge.py`)**: Coletor sob demanda para testes com sessões reais do Jellyfin.

## Uso Rápido
```bash
docker network create streaming_net 2>/dev/null || true
docker compose up -d

# Simular 40 players com queda de rede por 60s
docker compose --profile mock run --rm tema5-simulator \
  python3 -u /app/simulator.py --players 40 --scenario network_drop --duration 60

# Benchmark de inserção e compressão (100.000 pontos)
docker compose --profile mock run --rm tema5-simulator \
  python3 -u /app/benchmark_compression.py --points 100000
```

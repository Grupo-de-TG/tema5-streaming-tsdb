# Tema 5 (P2) — Telemetria de Reprodução, Buffer e Métricas de Stream (TSDB)

Stack containerizada em Docker para o **Sistema 2 (Plataforma de Streaming de Vídeo)** — Seminário Final (P2) de Laboratório de Banco de Dados.

## Arquitetura & Portas Reservadas

Todos os serviços rodam na rede Docker externa **`streaming_net`**:

| Container | Serviço | Porta Host | Porta Interna | Observação |
| :--- | :--- | :---: | :---: | :--- |
| `tema5-ingest` | API de Ingestão HTTP (CORS `*`) | `8091` | `8091` | Recebe telemetria e expõe snapshots |
| `tema5-influxdb` | InfluxDB v1.8 (TSDB) | `8089` | `8086` | DB `stream_telemetry` (`raw_7d` + `agg_1y`) |
| `tema5-grafana` | Grafana Dashboard | `3006` | `3000` | Acesso anônimo Viewer habilitado |
| `tema5-simulator` | Simulador Mock (`--profile mock`) | — | — | Gera fluxo 1s/player e benchmark TSM |

---

## Contrato de Integração entre os Grupos (Sistema 2)

### 1. O que cada grupo precisa padronizar

| Grupo | Obrigatório | Opcional (agrega na demo) |
| :--- | :--- | :--- |
| **Tema 1 (SQL)** | Definir formato de `user_id` (ex.: `"user-42"` ou `int`) e repassar no login. | Enviar `plan_tier` (`"basic"`, `"hd"` ou `"4k"`) para cruzar queda de bitrate por plano. |
| **Tema 2 (Grafos)** | Usar o mesmo `media_id` do Tema 4 ao devolver recomendações para o player. | — |
| **Tema 3 (Chave-Valor)** | Gerar e retornar o `session_id` (UUID/string) quando o usuário dá play. | — |
| **Tema 4 (Documentos)** | Definir o formato do `media_id` (ex.: `"filme-101"`) no catálogo. | — |
| **Frontend / Player** | Disparar `POST` a cada **1s** (e nos eventos `waiting`, `stalled`, `error`) com o JSON abaixo para `TELEMETRY_URL`. | Consumir `GET /api/v1/telemetry/session/{session_id}` para exibir qualidade ao vivo na tela. |

### 2. URL de envio e CORS (`TELEMETRY_URL`)

- **Envio direto do navegador (JS do `<video>`):** `http://localhost:8091/api/v1/telemetry` *(CORS `*` já habilitado na API)*.
- **Envio via backend/BFF na rede `streaming_net`:** `http://tema5-ingest:8091/api/v1/telemetry`.

### 3. Contrato do Payload JSON (`POST /api/v1/telemetry`)

O player deve enviar as chaves abaixo (se não conseguir ler alguma métrica do navegador, como `cdn_node` ou `latency_ms`, enviar valor padrão fixo ex.: `"edge-sp"` e `20` em vez de `null` ou omitir):

```json
{
  "session_id": "sess-abc-123",
  "user_id": "user-42",
  "media_id": "filme-101",
  "plan_tier": "4k",
  "device": "web",
  "network": "wifi",
  "cdn_node": "edge-sp",
  "bitrate_kbps": 8500,
  "buffer_health_s": 18.4,
  "rebuffer_ms": 0,
  "dropped_frames": 0,
  "latency_ms": 24,
  "resolution": "1080p",
  "status": "playing"
}
```

> Valores esperados para `status`: `"playing" | "buffering" | "dropped" | "ended"`.

### 4. Endpoints de Consulta ao Vivo

- `GET /api/v1/telemetry/health` — Status da API e contadores (`received`, `written`, `dropped`, `errors`).
- `GET /api/v1/telemetry/session/{session_id}` — Última métrica da sessão + total de `buffer_events` e `connection_drops`.
- `GET /api/v1/telemetry/overview` — Lista resumida das sessões ativas.

---

## Retenção, Downsampling e Uso Rápido

- **Retenção:** `raw_7d` (7 dias para dados brutos de 1s) e `agg_1y` (365 dias).
- **Downsampling:** Continuous Query `cq_stream_1m` agrega janelas de `1m` (`mean_bitrate_kbps`, `min_buffer_health_s`, `p95_latency_ms`, `buffer_events`, `connection_drops`) em `agg_1y.stream_metrics_1m`.

```bash
# 1. Criar rede compartilhada (uma única vez) e subir a stack
docker network create streaming_net 2>/dev/null || true
docker compose up -d

# 2. Simular 40 players com queda de rede (ABR + buffering) por 60s
docker compose --profile mock run --rm tema5-simulator \
  python3 -u /app/simulator.py --players 40 --scenario network_drop --duration 60

# 3. Benchmark de alto volume e compressão TSM (100.000 pontos)
docker compose --profile mock run --rm tema5-simulator \
  python3 -u /app/benchmark_compression.py --points 100000
```

#!/usr/bin/env python3
"""
tema5-ingest — API de Ingestao de Telemetria de Streaming (Tema 5 - P2)
Recebe POST /api/v1/telemetry do Player/Frontend (ou Simulador), aplica CORS,
armazena em lote no InfluxDB (Retention Policy raw_7d) e expoe consulta ao vivo por session_id.
"""

import json
import os
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List

PORT = int(os.getenv("INGEST_PORT", "8091"))
INFLUX_WRITE_URL = os.getenv(
    "INFLUX_WRITE_URL",
    "http://tema5-influxdb:8086/write?db=stream_telemetry&u=admin&p=adminpass",
)
INFLUX_QUERY_URL = os.getenv(
    "INFLUX_QUERY_URL",
    "http://tema5-influxdb:8086/query?db=stream_telemetry&u=admin&p=adminpass",
)

_write_queue: "queue.Queue[str]" = queue.Queue(maxsize=20000)
_sessions_lock = threading.Lock()
_sessions: Dict[str, Dict[str, Any]] = {}
_stats = {"received": 0, "written": 0, "dropped": 0, "errors": 0}


def _esc_tag(v: Any) -> str:
    return str(v).replace(",", "\\,").replace("=", "\\=").replace(" ", "\\ ") or "unknown"


def _to_line(item: Dict[str, Any]) -> str:
    session_id = str(item.get("session_id") or "sess-unknown")
    user_id = str(item.get("user_id") or "user-unknown")
    media_id = str(item.get("media_id") or "media-unknown")
    plan_tier = str(item.get("plan_tier") or "standard")
    device = str(item.get("device") or "web")
    network = str(item.get("network") or "wifi")
    cdn_node = str(item.get("cdn_node") or "edge-sp")
    resolution = str(item.get("resolution") or "1080p")
    status = str(item.get("status") or "playing").lower()

    bitrate_kbps = float(item.get("bitrate_kbps") if item.get("bitrate_kbps") is not None else 0.0)
    buffer_health_s = float(item.get("buffer_health_s") if item.get("buffer_health_s") is not None else 0.0)
    rebuffer_ms = int(item.get("rebuffer_ms") if item.get("rebuffer_ms") is not None else 0)
    dropped_frames = int(item.get("dropped_frames") if item.get("dropped_frames") is not None else 0)
    latency_ms = float(item.get("latency_ms") if item.get("latency_ms") is not None else 20.0)

    is_buffer_event = 1 if (status == "buffering" or rebuffer_ms > 0) else 0
    is_drop_event = 1 if status == "dropped" else 0

    ts_ns = item.get("timestamp_ns")
    if ts_ns is None:
        ts_ns = time.time_ns()

    with _sessions_lock:
        prev = _sessions.get(session_id, {})
        buf_count = prev.get("buffer_events", 0) + is_buffer_event
        drop_count = prev.get("connection_drops", 0) + is_drop_event
        _sessions[session_id] = {
            "session_id": session_id,
            "user_id": user_id,
            "media_id": media_id,
            "plan_tier": plan_tier,
            "device": device,
            "network": network,
            "cdn_node": cdn_node,
            "resolution": resolution,
            "status": status,
            "bitrate_kbps": bitrate_kbps,
            "buffer_health_s": buffer_health_s,
            "rebuffer_ms": rebuffer_ms,
            "dropped_frames": dropped_frames,
            "latency_ms": latency_ms,
            "buffer_events": buf_count,
            "connection_drops": drop_count,
            "updated_at": time.time(),
        }

    tags = (
        f"session_id={_esc_tag(session_id)},"
        f"user_id={_esc_tag(user_id)},"
        f"media_id={_esc_tag(media_id)},"
        f"plan_tier={_esc_tag(plan_tier)},"
        f"device={_esc_tag(device)},"
        f"network={_esc_tag(network)},"
        f"cdn_node={_esc_tag(cdn_node)},"
        f"resolution={_esc_tag(resolution)},"
        f"status={_esc_tag(status)}"
    )
    fields = (
        f"bitrate_kbps={bitrate_kbps:.2f},"
        f"buffer_health_s={buffer_health_s:.2f},"
        f"rebuffer_ms={rebuffer_ms}i,"
        f"dropped_frames={dropped_frames}i,"
        f"latency_ms={latency_ms:.2f},"
        f"is_buffer_event={is_buffer_event}i,"
        f"is_drop_event={is_drop_event}i"
    )
    return f"stream_metrics,{tags} {fields} {int(ts_ns)}"


def _flush_worker() -> None:
    while True:
        try:
            first = _write_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        batch: List[str] = [first]
        while len(batch) < 500:
            try:
                batch.append(_write_queue.get_nowait())
            except queue.Empty:
                break
        payload = ("\n".join(batch) + "\n").encode("utf-8")
        req = urllib.request.Request(
            INFLUX_WRITE_URL,
            data=payload,
            method="POST",
            headers={"Content-Type": "text/plain; charset=utf-8"},
        )
        try:
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                if 200 <= resp.status < 300:
                    _stats["written"] += len(batch)
                else:
                    _stats["errors"] += len(batch)
        except Exception:
            _stats["errors"] += len(batch)


class TelemetryHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def send_json(self, data: Any, code: int = 200) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path in ["/health", "/api/v1/telemetry/health"]:
            self.send_json({
                "status": "ok",
                "service": "tema5-ingest",
                "active_sessions": len(_sessions),
                "stats": _stats,
                "queue_size": _write_queue.qsize(),
            })
        elif path.startswith("/api/v1/telemetry/session/"):
            sid = path.rsplit("/", 1)[-1]
            with _sessions_lock:
                snap = _sessions.get(sid)
            if snap:
                self.send_json(snap)
            else:
                self.send_json({"error": "session_not_found", "session_id": sid}, 404)
        elif path == "/api/v1/telemetry/overview":
            with _sessions_lock:
                items = list(_sessions.values())
            self.send_json({"sessions_count": len(items), "sessions": items[:50]})
        else:
            self.send_json({"error": "not_found", "path": path}, 404)

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path != "/api/v1/telemetry":
            self.send_json({"error": "not_found", "path": path}, 404)
            return

        length = int(self.headers.get("Content-Length", "0"))
        try:
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
        except Exception as e:
            self.send_json({"error": f"invalid_json: {e}"}, 400)
            return

        items = payload if isinstance(payload, list) else [payload]
        accepted = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                line = _to_line(item)
                _write_queue.put_nowait(line)
                _stats["received"] += 1
                accepted += 1
            except queue.Full:
                _stats["dropped"] += 1

        self.send_json({"status": "accepted", "count": accepted}, 202)


def _ensure_influx_policies() -> None:
    """Garante de forma idempotente que o DB, RPs (raw_7d/agg_1y) e CQ existam."""
    base_query_url = INFLUX_QUERY_URL.split("?")[0]
    auth_qs = urllib.parse.urlencode({"u": "admin", "p": "adminpass"})
    queries = [
        'CREATE DATABASE "stream_telemetry"',
        'CREATE RETENTION POLICY "raw_7d" ON "stream_telemetry" DURATION 7d REPLICATION 1 DEFAULT',
        'CREATE RETENTION POLICY "agg_1y" ON "stream_telemetry" DURATION 365d REPLICATION 1',
        (
            'CREATE CONTINUOUS QUERY "cq_stream_1m" ON "stream_telemetry" BEGIN '
            'SELECT mean("bitrate_kbps") AS "mean_bitrate_kbps", '
            'min("buffer_health_s") AS "min_buffer_health_s", '
            'sum("rebuffer_ms") AS "sum_rebuffer_ms", '
            'sum("dropped_frames") AS "sum_dropped_frames", '
            'mean("latency_ms") AS "mean_latency_ms", '
            'percentile("latency_ms", 95) AS "p95_latency_ms", '
            'sum("is_buffer_event") AS "buffer_events", '
            'sum("is_drop_event") AS "connection_drops" '
            'INTO "stream_telemetry"."agg_1y"."stream_metrics_1m" '
            'FROM "stream_telemetry"."raw_7d"."stream_metrics" '
            'GROUP BY time(1m), "cdn_node", "network", "resolution" END'
        ),
    ]
    for attempt in range(15):
        try:
            for q in queries:
                data = urllib.parse.urlencode({"q": q}).encode("utf-8")
                req = urllib.request.Request(f"{base_query_url}?{auth_qs}", data=data, method="POST")
                with urllib.request.urlopen(req, timeout=3.0):
                    pass
            print("[tema5-ingest] InfluxDB RPs (raw_7d, agg_1y) e CQ (cq_stream_1m) verificadas.", flush=True)
            return
        except Exception as e:
            if attempt == 14:
                print(f"[tema5-ingest] Aviso ao inicializar RPs do InfluxDB: {e}", flush=True)
            time.sleep(2.0)


def main() -> None:
    t = threading.Thread(target=_flush_worker, daemon=True)
    t.start()
    threading.Thread(target=_ensure_influx_policies, daemon=True).start()
    print(f"[tema5-ingest] Listening on 0.0.0.0:{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), TelemetryHandler).serve_forever()


if __name__ == "__main__":
    main()

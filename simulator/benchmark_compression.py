#!/usr/bin/env python3
"""
benchmark_compression.py — Prova pratica de alto volume de insercao e compressao TSM (Tema 5).
Insere N pontos em lote direto no InfluxDB e mede throughput (pts/s) e bytes/ponto.
"""

import argparse
import os
import random
import time
import urllib.request

INFLUX_WRITE_URL = os.getenv(
    "INFLUX_WRITE_URL",
    "http://tema5-influxdb:8086/write?db=stream_telemetry&u=admin&p=adminpass",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--points", type=int, default=100000)
    parser.add_argument("--batch-size", type=int, default=5000)
    args = parser.parse_args()

    base_ns = time.time_ns() - (args.points * 1_000_000_000 // 50)
    total_raw_bytes = 0
    t_start = time.monotonic()

    sent = 0
    while sent < args.points:
        n = min(args.batch_size, args.points - sent)
        lines = []
        for i in range(n):
            idx = sent + i
            ts = base_ns + idx * 20_000_000  # 50 pts/s simulado
            pid = (idx % 50) + 1
            bitrate = 8000.0 + (idx % 500)
            buf = 18.0 + (idx % 10) * 0.1
            lat = 20.0 + (idx % 15)
            lines.append(
                f"stream_metrics,session_id=bench-{pid:02d},user_id=u-{pid:02d},media_id=filme-101,"
                f"plan_tier=hd,device=web,network=wifi,cdn_node=edge-sp,resolution=1080p,status=playing "
                f"bitrate_kbps={bitrate:.2f},buffer_health_s={buf:.2f},rebuffer_ms=0i,dropped_frames=0i,"
                f"latency_ms={lat:.2f},is_buffer_event=0i,is_drop_event=0i {ts}"
            )
        payload = ("\n".join(lines) + "\n").encode("utf-8")
        total_raw_bytes += len(payload)
        req = urllib.request.Request(INFLUX_WRITE_URL, data=payload, method="POST")
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            assert 200 <= resp.status < 300
        sent += n

    dt = time.monotonic() - t_start
    print(f"Pontos inseridos : {sent:,}")
    print(f"Tempo total      : {dt:.2f} s")
    print(f"Throughput       : {sent / dt:,.0f} pontos/s")
    print(f"Payload bruto    : {total_raw_bytes / (1024*1024):.2f} MB ({total_raw_bytes / sent:.1f} bytes/ponto)")


if __name__ == "__main__":
    main()

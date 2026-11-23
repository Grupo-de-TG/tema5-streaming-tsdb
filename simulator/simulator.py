#!/usr/bin/env python3
"""
simulator.py — Simulador Mock de Players Segundo-a-Segundo (Tema 5)
Envia telemetria no mesmo contrato JSON acordado com o Frontend para POST /api/v1/telemetry.
Cenarios: normal | network_drop | server_bottleneck | mixed
"""

import argparse
import json
import os
import random
import time
import urllib.request

DEFAULT_URL = os.getenv("TELEMETRY_URL", "http://tema5-ingest:8091/api/v1/telemetry")

MEDIA_CATALOG = ["filme-101", "filme-102", "serie-201-e01", "serie-201-e02", "anime-305-e12"]
PLANS = ["hd", "4k", "basic"]
DEVICES = ["web", "smart-tv", "mobile"]
NETWORKS = ["fiber", "wifi", "4g"]
CDNS = ["edge-sp", "edge-rj", "edge-mg"]


def build_players(n: int):
    players = []
    for i in range(1, n + 1):
        plan = random.choice(PLANS)
        players.append({
            "session_id": f"sess-mock-{i:03d}",
            "user_id": f"user-{i:03d}",
            "media_id": random.choice(MEDIA_CATALOG),
            "plan_tier": plan,
            "device": random.choice(DEVICES),
            "network": random.choice(NETWORKS),
            "cdn_node": random.choice(CDNS),
            "buffer_health_s": random.uniform(12.0, 25.0),
            "dropped_total": 0,
        })
    return players


def step_player(p: dict, scenario: str, tick: int) -> dict:
    base_bitrate = 14000.0 if p["plan_tier"] == "4k" else (7500.0 if p["plan_tier"] == "hd" else 3000.0)
    resolution = "2160p" if p["plan_tier"] == "4k" else ("1080p" if p["plan_tier"] == "hd" else "720p")
    latency = random.uniform(14.0, 32.0)
    rebuffer_ms = 0
    dropped_frames = 0
    status = "playing"

    if scenario == "network_drop" and p["network"] in ("4g", "wifi"):
        # Queda progressiva de banda e ABR derrubando bitrate
        p["buffer_health_s"] = max(0.0, p["buffer_health_s"] - random.uniform(2.5, 5.0))
        base_bitrate = random.uniform(700.0, 1400.0)
        resolution = "480p"
        latency = random.uniform(180.0, 480.0)
        if p["buffer_health_s"] <= 0.5:
            status = "dropped" if random.random() < 0.15 else "buffering"
            rebuffer_ms = random.randint(350, 950)
    elif scenario == "server_bottleneck":
        # Gargalo global no CDN edge-sp ou no servidor de entrega
        if p["cdn_node"] == "edge-sp" or random.random() < 0.6:
            latency = random.uniform(140.0, 360.0)
            dropped_frames = random.randint(2, 14)
            p["buffer_health_s"] = max(0.0, p["buffer_health_s"] - random.uniform(1.5, 4.0))
            base_bitrate *= 0.45
            resolution = "720p"
            if p["buffer_health_s"] <= 1.0:
                status = "buffering"
                rebuffer_ms = random.randint(250, 800)
        else:
            p["buffer_health_s"] = min(25.0, p["buffer_health_s"] + 0.5)
    else:
        # Normal com pequenas flutuacoes realistas
        p["buffer_health_s"] = min(30.0, max(8.0, p["buffer_health_s"] + random.uniform(-0.8, 1.0)))
        base_bitrate *= random.uniform(0.92, 1.08)
        if random.random() < 0.01:
            status = "buffering"
            rebuffer_ms = random.randint(100, 250)

    return {
        "session_id": p["session_id"],
        "user_id": p["user_id"],
        "media_id": p["media_id"],
        "plan_tier": p["plan_tier"],
        "device": p["device"],
        "network": p["network"],
        "cdn_node": p["cdn_node"],
        "bitrate_kbps": round(base_bitrate, 2),
        "buffer_health_s": round(p["buffer_health_s"], 2),
        "rebuffer_ms": rebuffer_ms,
        "dropped_frames": dropped_frames,
        "latency_ms": round(latency, 2),
        "resolution": resolution,
        "status": status,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock Player Telemetry Simulator (Tema 5)")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--players", type=int, default=30)
    parser.add_argument("--scenario", choices=["normal", "network_drop", "server_bottleneck"], default="normal")
    parser.add_argument("--duration", type=int, default=0, help="Segundos (0 = infinito)")
    args = parser.parse_args()

    players = build_players(args.players)
    print(f"[simulator] Sending {args.players} players/sec -> {args.url} (scenario={args.scenario})", flush=True)
    tick = 0
    while True:
        t0 = time.monotonic()
        batch = [step_player(p, args.scenario, tick) for p in players]
        data = json.dumps(batch).encode("utf-8")
        req = urllib.request.Request(args.url, data=data, method="POST", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                if tick % 10 == 0:
                    print(f"[simulator] tick={tick} sent={len(batch)} status={resp.status}", flush=True)
        except Exception as e:
            print(f"[simulator] error at tick={tick}: {e}", flush=True)
        tick += 1
        if args.duration > 0 and tick >= args.duration:
            break
        elapsed = time.monotonic() - t0
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)


if __name__ == "__main__":
    main()

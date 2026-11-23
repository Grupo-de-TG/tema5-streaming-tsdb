#!/usr/bin/env python3
"""
jellyfin_bridge.py — Ponte sob demanda (apenas para testes) entre o Jellyfin real (:8096)
e a API de ingestao do Tema 5 (http://127.0.0.1:8091/api/v1/telemetry).
Nao modifica nada no Jellyfin nem na stack de producao.
"""

import argparse
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, "/home/ryse/scripts")
import stack_env  # noqa: E402

JELLYFIN_URL = os.getenv("JELLYFIN_URL", "http://127.0.0.1:8096/jellyfin")
JELLYFIN_TOKEN = stack_env.require("JELLYFIN_TOKEN")
INGEST_URL = os.getenv("TELEMETRY_URL", "http://127.0.0.1:8091/api/v1/telemetry")


def _extract_resolution(item: dict, transcode: dict) -> str:
    height = transcode.get("Height")
    if not height:
        for stream in item.get("MediaStreams", []) or []:
            if stream.get("Type") == "Video":
                height = stream.get("Height")
                break
    if not height:
        return "1080p"
    if height >= 2000:
        return "2160p"
    if height >= 1000:
        return "1080p"
    if height >= 700:
        return "720p"
    return "480p"


def _extract_bitrate_kbps(item: dict, transcode: dict) -> float:
    if transcode and transcode.get("Bitrate"):
        return round(float(transcode["Bitrate"]) / 1000.0, 2)
    for stream in item.get("MediaStreams", []) or []:
        if stream.get("Type") == "Video" and stream.get("BitRate"):
            return round(float(stream["BitRate"]) / 1000.0, 2)
    return 5000.0


def fetch_sessions():
    t0 = time.monotonic()
    req = urllib.request.Request(
        f"{JELLYFIN_URL}/Sessions",
        headers={"Authorization": f'MediaBrowser Client="Tema5Bridge", Device="Fedora", DeviceId="tema5-1", Version="1.0.0", Token="{JELLYFIN_TOKEN}"'},
    )
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    latency_ms = round((time.monotonic() - t0) * 1000.0, 2)
    return data, latency_ms


def main() -> None:
    parser = argparse.ArgumentParser(description="Jellyfin -> Tema 5 Telemetry Bridge")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--once", action="store_true", help="Executa apenas 1 ciclo e encerra")
    args = parser.parse_args()

    print(f"[jellyfin-bridge] Reading {JELLYFIN_URL}/Sessions -> {INGEST_URL}", flush=True)
    while True:
        try:
            sessions, latency_ms = fetch_sessions()
            payload = []
            for s in sessions:
                item = s.get("NowPlayingItem")
                if not item:
                    continue
                play_state = s.get("PlayState") or {}
                transcode = s.get("TranscodingInfo") or {}
                is_paused = bool(play_state.get("IsPaused"))
                play_method = play_state.get("PlayMethod") or "DirectPlay"
                payload.append({
                    "session_id": f"jf-{s.get('Id', 'unknown')[:12]}",
                    "user_id": s.get("UserName") or s.get("UserId") or "jellyfin-user",
                    "media_id": item.get("SeriesName") or item.get("Name") or item.get("Id") or "media",
                    "plan_tier": "4k" if _extract_resolution(item, transcode) == "2160p" else "hd",
                    "device": s.get("Client") or s.get("DeviceName") or "jellyfin-client",
                    "network": "lan-tailscale",
                    "cdn_node": f"jellyfin-{play_method.lower()}",
                    "bitrate_kbps": _extract_bitrate_kbps(item, transcode),
                    "buffer_health_s": 0.0 if is_paused else 20.0,
                    "rebuffer_ms": 0,
                    "dropped_frames": 0,
                    "latency_ms": latency_ms,
                    "resolution": _extract_resolution(item, transcode),
                    "status": "paused" if is_paused else "playing",
                })

            if payload:
                req = urllib.request.Request(
                    INGEST_URL,
                    data=json.dumps(payload).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=2.0) as resp:
                    print(f"[jellyfin-bridge] forwarded {len(payload)} active session(s) -> {resp.status}", flush=True)
            else:
                print("[jellyfin-bridge] no active playback sessions", flush=True)
        except Exception as e:
            print(f"[jellyfin-bridge] error: {e}", flush=True)

        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()

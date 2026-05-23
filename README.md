# Hermes Portal

A small FastAPI web portal, deployed on Railway, that lets you remotely control a Chrome **CDP** (Chrome DevTools Protocol) browser running on a local PC. Railway and the local PC are connected through **Tailscale**, so the portal reaches the browser at `100.113.104.72:19222` (Tailscale IP → WSL → mirrored Chrome `:9222`).

## Stack
- Python 3.11+ managed with **[uv](https://docs.astral.sh/uv/)**
- **FastAPI** + Uvicorn web portal
- **httpx** as the CDP HTTP client
- Signed-cookie session login (`itsdangerous`)
- Deployed via **Nixpacks** on **Railway**, joined to your tailnet using Railway's Tailscale integration

## Env vars
| Name | Default | Purpose |
|------|---------|---------|
| `PORTAL_USER` | `admin` | Portal login username |
| `PORTAL_PASS` | `change-me` | Portal login password |
| `SECRET_KEY` | random | Session cookie signing key |
| `CDP_HOST` | `100.113.104.72` | Tailscale IP of local PC |
| `CDP_PORT` | `19222` | CDP port exposed on tailnet |
| `PORT` | (Railway) | Public HTTP port |

## Topology
```
user-browser  →  https://<railway-app>  →  Railway service (Tailscale subnet)
                                          │
                                          ▼
                            100.113.104.72:19222 (WSL on local Windows, mirrored to Chrome :9222)
```

## Local run
```bash
uv sync
uv run uvicorn main:app --reload
```

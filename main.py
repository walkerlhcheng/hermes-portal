"""Hermes Portal — Web app that controls a remote CDP browser via Tailscale.

Architecture:
  Browser (user) -> Railway (this FastAPI app, on Tailscale) -> Local PC (Tailscale 100.113.104.72:19222) -> Chrome CDP (port 9222 mirrored)

Login: simple username/password (env vars) backed by signed-session cookies.
"""
from __future__ import annotations

import os
import secrets
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from itsdangerous import BadSignature, URLSafeSerializer

CDP_HOST = os.getenv("CDP_HOST", "100.113.104.72")
CDP_PORT = int(os.getenv("CDP_PORT", "19222"))
CDP_BASE = f"http://{CDP_HOST}:{CDP_PORT}"

PORTAL_USER = os.getenv("PORTAL_USER", "admin")
PORTAL_PASS = os.getenv("PORTAL_PASS", "change-me")
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(32))

signer = URLSafeSerializer(SECRET_KEY, salt="hermes-session")
SESSION_COOKIE = "hermes_session"

app = FastAPI(title="Hermes Portal")


def current_user(request: Request) -> str:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login required")
    try:
        data = signer.loads(token)
    except BadSignature:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="bad session")
    return data["u"]


def require_login(request: Request) -> str:
    try:
        return current_user(request)
    except HTTPException:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})


LOGIN_HTML = """<!doctype html><html><head><meta charset='utf-8'><title>Hermes Login</title>
<style>body{font-family:system-ui;background:#0b1020;color:#eee;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
form{background:#151a32;padding:2rem;border-radius:12px;min-width:300px;box-shadow:0 10px 40px rgba(0,0,0,.4)}
h1{margin-top:0}input{display:block;width:100%;padding:.6rem;margin:.4rem 0;background:#0b1020;border:1px solid #2a3160;color:#eee;border-radius:6px;box-sizing:border-box}
button{width:100%;padding:.7rem;background:#5b6bff;color:white;border:0;border-radius:6px;font-weight:600;cursor:pointer}
.err{color:#ff7a7a;font-size:.9rem;min-height:1.1em}</style></head><body>
<form method='post' action='/login'><h1>Hermes Portal</h1>
<div class='err'>{err}</div>
<input name='username' placeholder='username' autofocus required>
<input name='password' type='password' placeholder='password' required>
<button>Sign in</button></form></body></html>"""


DASH_HTML = """<!doctype html><html><head><meta charset='utf-8'><title>Hermes Portal</title>
<style>body{font-family:system-ui;background:#0b1020;color:#eee;margin:0;padding:1rem}
header{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #2a3160;padding-bottom:.6rem;margin-bottom:1rem}
.card{background:#151a32;padding:1rem;border-radius:10px;margin-bottom:1rem}
input,button{padding:.55rem;background:#0b1020;color:#eee;border:1px solid #2a3160;border-radius:6px}
button{background:#5b6bff;cursor:pointer;border-color:#5b6bff}button.alt{background:#222a55;border-color:#2a3160}
pre{background:#080c1a;padding:.7rem;border-radius:6px;max-height:260px;overflow:auto;white-space:pre-wrap;word-break:break-all}
table{width:100%;border-collapse:collapse}td,th{padding:.4rem;border-bottom:1px solid #2a3160;text-align:left;font-size:.9rem;vertical-align:top}
a{color:#9fb0ff}</style></head><body>
<header><div><b>Hermes Portal</b> &middot; signed in as {user}</div>
<form method='post' action='/logout' style='margin:0'><button class='alt'>Logout</button></form></header>

<div class='card'><b>Remote CDP Target</b><br>
Configured: <code>{cdp_base}</code> &middot; <span id='status'>checking...</span>
<div style='margin-top:.6rem'>
<button onclick='loadTargets()'>List Tabs</button>
<button class='alt' onclick='openNew()'>Open New Tab</button>
<input id='url' placeholder='https://example.com' style='width:50%'>
</div></div>

<div class='card'><b>Tabs</b><div id='targets'>—</div></div>
<div class='card'><b>Result</b><pre id='out'>(none)</pre></div>

<script>
async function api(path, opts){const r=await fetch(path,opts||{});const j=await r.json();document.getElementById('out').textContent=JSON.stringify(j,null,2);return j;}
async function refreshStatus(){try{const j=await(await fetch('/api/version')).json();document.getElementById('status').textContent=j.ok?('OK — '+(j.version?.Browser||'connected')):('ERR: '+j.error);}catch(e){document.getElementById('status').textContent='ERR: '+e;}}
async function loadTargets(){const j=await api('/api/targets');const rows=(j.targets||[]).map(t=>`<tr><td>${t.type}</td><td>${t.title||''}</td><td><a href='${t.url}' target='_blank'>${t.url}</a></td><td><button onclick="closeTab('${t.id}')">Close</button> <button class='alt' onclick="activate('${t.id}')">Activate</button></td></tr>`).join('');document.getElementById('targets').innerHTML='<table><tr><th>Type</th><th>Title</th><th>URL</th><th></th></tr>'+rows+'</table>';}
async function openNew(){const url=document.getElementById('url').value||'about:blank';await api('/api/new?url='+encodeURIComponent(url),{method:'POST'});loadTargets();}
async function closeTab(id){await api('/api/close/'+id,{method:'POST'});loadTargets();}
async function activate(id){await api('/api/activate/'+id,{method:'POST'});}
refreshStatus();loadTargets();
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    try:
        user = current_user(request)
    except HTTPException:
        return RedirectResponse("/login", status_code=302)
    return HTMLResponse(DASH_HTML.replace("{user}", user).replace("{cdp_base}", CDP_BASE))


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return HTMLResponse(LOGIN_HTML.replace("{err}", ""))


@app.post("/login")
async def login(username: str = Form(...), password: str = Form(...)):
    if secrets.compare_digest(username, PORTAL_USER) and secrets.compare_digest(password, PORTAL_PASS):
        token = signer.dumps({"u": username})
        resp = RedirectResponse("/", status_code=302)
        resp.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", secure=True)
        return resp
    return HTMLResponse(LOGIN_HTML.replace("{err}", "Invalid credentials"), status_code=401)


@app.post("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


async def cdp_get(path: str) -> Any:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{CDP_BASE}{path}")
        r.raise_for_status()
        return r.json()


async def cdp_put(path: str) -> Any:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.put(f"{CDP_BASE}{path}")
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {"ok": True}


@app.get("/api/version")
async def api_version(user: str = Depends(current_user)):
    try:
        data = await cdp_get("/json/version")
        return {"ok": True, "version": data}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)


@app.get("/api/targets")
async def api_targets(user: str = Depends(current_user)):
    try:
        data = await cdp_get("/json/list")
        return {"ok": True, "targets": data}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)


@app.post("/api/new")
async def api_new(url: str = "about:blank", user: str = Depends(current_user)):
    try:
        data = await cdp_put(f"/json/new?{url}")
        return {"ok": True, "target": data}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)


@app.post("/api/close/{tid}")
async def api_close(tid: str, user: str = Depends(current_user)):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{CDP_BASE}/json/close/{tid}")
        return {"ok": True, "status": r.status_code, "body": r.text}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)


@app.post("/api/activate/{tid}")
async def api_activate(tid: str, user: str = Depends(current_user)):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{CDP_BASE}/json/activate/{tid}")
        return {"ok": True, "status": r.status_code}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)


@app.get("/healthz")
async def healthz():
    return {"ok": True}

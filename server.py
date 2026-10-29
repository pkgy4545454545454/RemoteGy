
import asyncio
import io
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import mss
import pyautogui
import pyperclip
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from PIL import Image, ImageDraw

BASE = Path(__file__).parent
PORT = int(os.getenv("PORT", "8765"))

# Commande de ton IA. Le prompt est envoyé sur l'entrée standard (stdin).
# Exemples : "claude -p"   |   "ollama run llama3"   |   "python mon_agent.py"
AI_CMD = os.getenv("AI_CMD", "ollama run llama3.2")

# Dossier de travail des commandes / de l'IA (par défaut : ton dossier utilisateur)
WORKDIR = os.getenv("WORKDIR", str(Path.home()))

# Token secret (créé au premier lancement, stocké dans token.txt)
TOKEN_FILE = BASE / "token.txt"
if TOKEN_FILE.exists():
    TOKEN = TOKEN_FILE.read_text().strip()
else:
    TOKEN = secrets.token_urlsafe(12)
    TOKEN_FILE.write_text(TOKEN)

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

app = FastAPI()


@app.get("/")
def index():
    return HTMLResponse((BASE / "index.html").read_text(encoding="utf-8"))


def grab(scale: float, quality: int) -> bytes:
    """Capture l'écran principal et renvoie un JPEG (avec le curseur en rouge)."""
    with (getattr(mss, "MSS", None) or mss.mss)() as sct:
        shot = sct.grab(sct.monitors[1])
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    try:
        sw, sh = pyautogui.size()
        cx, cy = pyautogui.position()
        px, py = cx / sw * img.width, cy / sh * img.height
        ImageDraw.Draw(img).ellipse((px - 8, py - 8, px + 8, py + 8), outline="red", width=30)
    except Exception:
        pass
    if scale < 1:
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.BILINEAR)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def do_input(m: dict):
    t = m["t"]
    if t == "move":
        pyautogui.moveRel(m["dx"], m["dy"])
    elif t == "moveabs":
        w, h = pyautogui.size()
        pyautogui.moveTo(m["x"] * w, m["y"] * h)
    elif t == "click":
        pyautogui.click(button=m.get("b", "left"), clicks=2 if m.get("double") else 1)
    elif t == "down":
        pyautogui.mouseDown()
    elif t == "up":
        pyautogui.mouseUp()
    elif t == "scroll":
        pyautogui.scroll(int(m["dy"]))
    elif t == "key":
        pyautogui.press(m["key"])
    elif t == "hotkey":
        pyautogui.hotkey(*m["keys"])
    elif t == "text":
        # Via le presse-papiers pour gérer les accents / emojis
        pyperclip.copy(m["text"])
        pyautogui.hotkey("command" if sys.platform == "darwin" else "ctrl", "v")


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket, token: str = ""):
    if not secrets.compare_digest(token, TOKEN):
        await ws.close(code=4401)
        return
    await ws.accept()

    lock = asyncio.Lock()

    async def send_json(obj):
        async with lock:
            await ws.send_text(json.dumps(obj))

    async def send_bytes(b):
        async with lock:
            await ws.send_bytes(b)

    state = {"screen": None, "proc": None}

    async def screen_loop(fps, scale, quality):
        period = 1 / fps
        loop = asyncio.get_event_loop()
        while True:
            t0 = loop.time()
            frame = await asyncio.to_thread(grab, scale, quality)
            await send_bytes(frame)
            await asyncio.sleep(max(0, period - (loop.time() - t0)))

    async def run_proc(rid, cmd, stdin_text=None):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdin=asyncio.subprocess.PIPE if stdin_text is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=WORKDIR,
                env=env,
            )
        except Exception as e:
            await send_json({"t": "out", "id": rid, "data": f"Erreur : {e}\n"})
            await send_json({"t": "done", "id": rid, "code": -1})
            return
        state["proc"] = proc
        if stdin_text is not None:
            proc.stdin.write(stdin_text.encode())
            await proc.stdin.drain()
            proc.stdin.close()
        while True:
            chunk = await proc.stdout.read(1024)
            if not chunk:
                break
            await send_json({"t": "out", "id": rid, "data": chunk.decode(errors="replace")})
        code = await proc.wait()
        state["proc"] = None
        await send_json({"t": "done", "id": rid, "code": code})

    def kill_proc():
        p = state["proc"]
        if p and p.returncode is None:
            try:
                p.kill()
            except Exception:
                pass

    w, h = pyautogui.size()
    await send_json({"t": "hello", "w": w, "h": h, "ai": AI_CMD})

    try:
        while True:
            m = json.loads(await ws.receive_text())
            t = m.get("t")
            try:
                if t == "screen":
                    if state["screen"]:
                        state["screen"].cancel()
                        state["screen"] = None
                    if m.get("on"):
                        state["screen"] = asyncio.create_task(
                            screen_loop(
                                max(1, min(30, m.get("fps", 10))),
                                max(0.2, min(1, m.get("scale", 0.6))),
                                max(20, min(90, m.get("q", 50))),
                            )
                        )
                elif t == "shell":
                    kill_proc()
                    asyncio.create_task(run_proc(m["id"], m["text"]))
                elif t == "ai":
                    kill_proc()
                    asyncio.create_task(run_proc(m["id"], AI_CMD, stdin_text=m["text"]))
                elif t == "stop":
                    kill_proc()
                else:
                    await asyncio.to_thread(do_input, m)
            except Exception as e:
                await send_json({"t": "err", "msg": str(e)})
    except WebSocketDisconnect:
        pass
    finally:
        if state["screen"]:
            state["screen"].cancel()
        kill_proc()


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


SERVE_PORT = int(os.getenv("SERVE_PORT", "8899"))


def tailscale_exe():
    p = shutil.which("tailscale")
    if p:
        return p
    for c in (
        r"C:\Program Files\Tailscale\tailscale.exe",
        "/usr/bin/tailscale",
        "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
    ):
        if os.path.exists(c):
            return c
    return None


def tailscale_info():
    """Active le proxy Tailscale (port SERVE_PORT -> PORT) et renvoie (nom_machine, ip) ou None."""
    exe = tailscale_exe()
    if not exe:
        return None
    try:
        subprocess.run(
            [exe, "serve", "--bg", f"--http={SERVE_PORT}", f"http://127.0.0.1:{PORT}"],
            capture_output=True, timeout=20,
        )
        out = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=15).stdout
        me = json.loads(out)["Self"]
        host = (me.get("DNSName") or "").rstrip(".")
        ips = me.get("TailscaleIPs") or []
        ip = next((i for i in ips if "." in i), None)
        if not (host or ip):
            return None
        return host, ip
    except Exception:
        return None


def show_qr(url: str):
    try:
        import qrcode

        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.print_ascii(invert=True)
    except Exception:
        pass


if __name__ == "__main__":
    print("\n=== PC Remote ===")
    print(f"Sur le PC : http://localhost:{PORT}/?token={TOKEN}")
    print(f"IA lancée avec : {AI_CMD}  (dossier : {WORKDIR})")

    ts = tailscale_info()
    if ts:
        host, ip = ts
        main_url = f"http://{host or ip}:{SERVE_PORT}/?token={TOKEN}"
        print("\n>>> MOBILE (Tailscale, marche partout) : scanne ce QR code")
        print(f"    {main_url}")
        show_qr(main_url)
    else:
        lan_url = f"http://{lan_ip()}:{PORT}/?token={TOKEN}"
        print("\n>>> MOBILE (Wi-Fi local, Tailscale non trouvé) :")
        print(f"    {lan_url}")
        show_qr(lan_url)
    print()
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
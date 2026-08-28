# Shizuku3 Web GUI サーバ
# 起動: python server.py → ブラウザで http://127.0.0.1:8000 が自動で開く
# 事前にShizuku3.exe（エミュレータ）を起動しておくこと
import asyncio
import json
import webbrowser
from collections import deque
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from shizuku3client import Shizuku3Client

BASE = Path(__file__).parent
app = FastAPI()
app.mount("/web", StaticFiles(directory=BASE / "web"), name="web")

emu = None
history = deque(maxlen=1440)  #グラフ用（シミュレーション時刻が進んだ点のみ）
clients = set()


def poll_once():
    """全ポイントを読み、SVGのID名→表示文字列の辞書と、グラフ用生値を返す"""
    r = {nm: emu.read(nm) for nm in [
        "外気温度", "外気相対湿度", "外気ダンパ開度", "外気導入量", "全熱交バイパス",
        "ファン回転数比", "ファン電力", "弁開度", "冷温水流量", "冷温水入口温度",
        "給気温度", "給気相対湿度", "給気風量", "加湿作動",
        "室温", "室相対湿度", "CO2", "在室人数", "PMV",
        "エネルギー積算", "PPD積算", "在室時間", "CO2超過時間", "加速度"]}
    tstr = emu.read("現在時刻")  # "yyyy/MM/dd HH:mm:ss"
    date, time = tstr.split(" ")
    d = {
        "sim_date": date, "sim_time": time[:5],
        "outdoor_temp": f"{r['外気温度']:.1f}", "outdoor_rh": f"{r['外気相対湿度']:.0f}",
        "damper_pos": f"{100 * r['外気ダンパ開度']:.0f}", "oa_flow": f"{r['外気導入量']:.0f}",
        "hex_state": "Bypass" if r["全熱交バイパス"] else "Active",
        "fan_ratio": f"{100 * r['ファン回転数比']:.0f}", "fan_kw": f"{r['ファン電力']:.1f}",
        "valve_pos": f"{100 * r['弁開度']:.0f}", "water_flow": f"{r['冷温水流量']:.1f}",
        "water_temp": f"{r['冷温水入口温度']:.1f}",
        "sa_temp": f"{r['給気温度']:.1f}", "sa_rh": f"{r['給気相対湿度']:.0f}",
        "sa_flow": f"{r['給気風量']:.0f}", "humid_state": "On" if r["加湿作動"] else "Off",
        "room_temp": f"{r['室温']:.1f}", "room_rh": f"{r['室相対湿度']:.0f}",
        "co2": f"{r['CO2']:.0f}", "occupants": f"{r['在室人数']:.0f}",
        "pmv": f"{r['PMV']:+.1f}", "energy": f"{r['エネルギー積算']:.0f}",
        "ppd_ave": f"{r['PPD積算'] / r['在室時間']:.0f}" if 0 < r["在室時間"] else "-",
        "co2_excess": f"{r['CO2超過時間']:.1f}", "acc": f"{r['加速度']:.0f}",
    }
    point = {"label": time[:5], "full": tstr,
             "room_temp": r["室温"], "sa_temp": r["給気温度"], "outdoor_temp": r["外気温度"],
             "co2": r["CO2"], "room_rh": r["室相対湿度"], "sa_rh": r["給気相対湿度"],
             "outdoor_rh": r["外気相対湿度"]}
    return d, point


async def poll_loop():
    last_full = None
    while True:
        try:
            d, point = await asyncio.to_thread(poll_once)
            new_point = None
            if point["full"] != last_full:
                last_full = point["full"]
                history.append(point)
                new_point = point
            msg = json.dumps({"type": "update", "data": d, "point": new_point})
        except Exception as ex:
            msg = json.dumps({"type": "error", "message": f"{type(ex).__name__}: {ex}"})
        for ws in list(clients):
            try:
                await ws.send_text(msg)
            except Exception:
                clients.discard(ws)
        await asyncio.sleep(1)


def handle_command(m):
    cmd = m.get("cmd")
    if cmd == "write":
        emu.write(m["name"], m["value"])
    elif cmd == "play":
        emu.run(acceleration=max(1, int(m["value"])))
    elif cmd == "stop":
        emu.stop()
    elif cmd == "reset":
        emu.reset()


poll_task = None


@app.on_event("startup")
async def startup():
    global emu, poll_task
    emu = await asyncio.to_thread(Shizuku3Client)
    poll_task = asyncio.create_task(poll_loop())


@app.on_event("shutdown")
async def shutdown():
    if poll_task is not None:
        poll_task.cancel()
    for ws in list(clients):
        try:
            await ws.close()
        except Exception:
            pass
    try:
        emu.close()
    except Exception:
        pass


@app.get("/")
async def index():
    return FileResponse(BASE / "web" / "index.html")


@app.get("/gui.svg")
async def svg():
    return FileResponse(BASE / "gui.svg")


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    await ws.send_text(json.dumps({"type": "history", "data": list(history)}))
    try:
        while True:
            m = json.loads(await ws.receive_text())
            await asyncio.to_thread(handle_command, m)
    except WebSocketDisconnect:
        clients.discard(ws)


if __name__ == "__main__":
    import sys
    if "--no-browser" not in sys.argv:
        webbrowser.open("http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info",
                timeout_graceful_shutdown=3)

# Shizuku3エミュレータの学生向けクライアントライブラリ
#
# BACnet(bacpypes3)の詳細を隠蔽し、同期的な read/write/step だけで
# エミュレータを操作できるようにするラッパー。
#
# 使用例:
#   from shizuku3client import Shizuku3Client
#   emu = Shizuku3Client()
#   print(emu.read("室温"))
#   emu.write("弁開度", 0.6)
#   emu.step(minutes=5)       # シミュレーションを5分進めて停止する
#   emu.close()
import asyncio
import threading
from datetime import datetime, timedelta

from bacpypes3.app import Application
from bacpypes3.argparse import SimpleArgumentParser
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import ObjectIdentifier

# ポイント表: 名称 → (オブジェクト種別, インスタンス番号, 書込可)
# 日本語名と英語名の両方を受け付ける
_POINTS = {
    # 操作量
    "弁開度":        ("analog-value", 101, True),
    "ファン回転数比": ("analog-value", 102, True),
    "外気ダンパ開度": ("analog-value", 103, True),
    "発停":          ("binary-value", 104, True),
    "冷暖モード":     ("analog-value", 105, True),  # 0=自動,1=冷房,2=暖房
    "全熱交バイパス": ("binary-value", 106, True),
    "加湿有効":      ("binary-value", 107, True),
    "加湿設定湿度":   ("analog-value", 108, True),
    "加湿差動":      ("analog-value", 109, True),
    # 計測量
    "室温":          ("analog-value", 201, False),
    "室相対湿度":     ("analog-value", 202, False),
    "CO2":           ("analog-value", 203, False),
    "PMV":           ("analog-value", 204, False),
    "PPD":           ("analog-value", 205, False),
    "在室人数":       ("analog-value", 206, False),
    "給気温度":       ("analog-value", 211, False),
    "給気相対湿度":   ("analog-value", 212, False),
    "在室時間":       ("analog-value", 235, False),
    "給気風量":       ("analog-value", 213, False),
    "外気導入量":     ("analog-value", 214, False),
    "冷温水入口温度": ("analog-value", 217, False),
    "冷温水流量":     ("analog-value", 218, False),
    "コイル熱量":     ("analog-value", 219, False),
    "ファン電力":     ("analog-value", 220, False),
    "外気温度":       ("analog-value", 221, False),
    "外気相対湿度":   ("analog-value", 222, False),
    "加湿作動":      ("binary-value", 224, False),
    # KPI
    "エネルギー積算":  ("analog-value", 231, False),
    "PPD積算":       ("analog-value", 232, False),
    "人数重みPPD積算": ("analog-value", 233, False),
    "CO2超過時間":    ("analog-value", 234, False),
    # シミュレーション管理
    "加速度":        ("analog-value", 301, True),
    "一時停止時刻":   ("characterstring-value", 302, True),
    "現在時刻":       ("characterstring-value", 303, False),
    "リセット":       ("binary-value", 304, True),
}

_ALIASES = {
    "WaterValvePosition": "弁開度", "FanSpeedRatio": "ファン回転数比",
    "OADamperPosition": "外気ダンパ開度", "AHUOnOff": "発停", "OperationMode": "冷暖モード",
    "HEXBypass": "全熱交バイパス", "HumidifierEnabled": "加湿有効",
    "HumiditySetPoint": "加湿設定湿度", "HumidityDeadband": "加湿差動",
    "RoomTemperature": "室温", "RoomRelativeHumidity": "室相対湿度", "RoomCO2Level": "CO2",
    "RoomPMV": "PMV", "RoomPPD": "PPD", "OccupantCount": "在室人数",
    "SupplyAirTemperature": "給気温度", "SupplyAirFlowRate": "給気風量",
    "OutdoorAirFlowRate": "外気導入量", "WaterInletTemperature": "冷温水入口温度",
    "WaterFlowRate": "冷温水流量", "CoilLoad": "コイル熱量", "FanElectricity": "ファン電力",
    "OutdoorTemperature": "外気温度", "OutdoorRelativeHumidity": "外気相対湿度",
    "HumidifierStatus": "加湿作動", "IntegratedEnergy": "エネルギー積算",
    "IntegratedPPD": "PPD積算", "IntegratedOccupantWeightedPPD": "人数重みPPD積算",
    "CO2ExcessTime": "CO2超過時間", "AccelerationRate": "加速度",
    "PauseAtDateTime": "一時停止時刻", "CurrentDateTime": "現在時刻", "Reinitialize": "リセット",
}

_TIME_FORMAT = "%Y/%m/%d %H:%M:%S"


class Shizuku3Client:
    """Shizuku3エミュレータへのBACnet接続を隠蔽した同期クライアント"""

    def __init__(self, host="127.0.0.1", port=47809,
                 local_ip="127.0.0.1", local_port=47810, timeout=5.0):
        self._timeout = timeout
        self._device = Address(f"{host}:{port}")
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        #ローカルポートが使用中の場合は+1しながら最大10ポート試す
        #（bacpypes3はバインド失敗を例外にせず内部リトライするため、事前に自前で空きを検査する）
        import socket as _socket
        for lp in range(local_port, local_port + 10):
            probe = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
            try:
                probe.bind((local_ip, lp))
                probe.close()
            except OSError:
                probe.close()
                continue
            fut = asyncio.run_coroutine_threadsafe(
                self._setup(local_ip, lp), self._loop)
            fut.result(timeout)
            self.local_port = lp
            break
        else:
            raise RuntimeError(
                f"ローカルポート{local_port}～{local_port + 9}がすべて使用中です。"
                "他のクライアント（旧server.py等）が残っていないか確認してください")

    async def _setup(self, local_ip, local_port):
        args = SimpleArgumentParser().parse_args(
            ["--address", f"{local_ip}/32:{local_port}",
             "--instance", "3999", "--name", "Shizuku3Client"])
        self._app = Application.from_args(args)

    # ---- 基本操作 ----------------------------------------------------

    def _resolve(self, name):
        name = _ALIASES.get(name, name)
        if name not in _POINTS:
            raise KeyError(f"未知のポイント名: {name}")
        return name, _POINTS[name]

    def read(self, name):
        """ポイントの現在値を読む"""
        _, (otype, inst, _) = self._resolve(name)
        fut = asyncio.run_coroutine_threadsafe(
            self._app.read_property(self._device,
                                    ObjectIdentifier(f"{otype},{inst}"), "present-value"),
            self._loop)
        val = fut.result(self._timeout)
        if otype == "binary-value":
            return int(val) != 0
        if otype == "characterstring-value":
            return str(val)
        return float(val)

    def write(self, name, value):
        """ポイントに値を書く"""
        nm, (otype, inst, writable) = self._resolve(name)
        if not writable:
            raise ValueError(f"{nm} は読み取り専用")
        if otype == "binary-value":
            value = 1 if value else 0
        elif otype == "analog-value":
            value = float(value)
        else:
            value = str(value)
        fut = asyncio.run_coroutine_threadsafe(
            self._app.write_property(self._device,
                                     ObjectIdentifier(f"{otype},{inst}"), "present-value", value),
            self._loop)
        fut.result(self._timeout)

    # ---- 時間管理 ----------------------------------------------------

    def current_time(self):
        """現在のシミュレーション時刻を返す"""
        return datetime.strptime(self.read("現在時刻"), _TIME_FORMAT)

    def step(self, minutes=5.0, acceleration=1200, timeout=60.0):
        """シミュレーションを指定分数だけ進めて停止する（ステップ実行）"""
        import time
        pause_at = self.current_time() + timedelta(minutes=minutes)
        self.write("一時停止時刻", pause_at.strftime(_TIME_FORMAT))
        self.write("加速度", acceleration)
        limit = time.time() + timeout
        while time.time() < limit:
            if self.read("加速度") == 0:
                return self.current_time()
            time.sleep(0.05)
        raise TimeoutError("指定時間内に一時停止しなかった")

    def run(self, acceleration=600):
        """一時停止を解除して連続実行する（停止はstop()または一時停止時刻で）"""
        far = self.current_time() + timedelta(days=365)
        self.write("一時停止時刻", far.strftime(_TIME_FORMAT))
        self.write("加速度", acceleration)

    def stop(self):
        """計算を一時停止する"""
        self.write("加速度", 0)

    def reset(self):
        """setting.iniを再読込して初期状態に戻す（数秒かかる）"""
        self.write("リセット", True)

    def close(self):
        self._loop.call_soon_threadsafe(self._app.close)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(2)


if __name__ == "__main__":
    # 簡易動作確認（エミュレータを起動しておくこと）
    emu = Shizuku3Client()
    print("現在時刻:", emu.current_time())
    print("室温[C]:", emu.read("室温"), "/ CO2[ppm]:", emu.read("CO2"))
    emu.write("弁開度", 0.6)
    t = emu.step(minutes=5, acceleration=600)
    print("5分ステップ後:", t, "/ 室温[C]:", emu.read("室温"), "/ 弁開度:", emu.read("弁開度"))
    emu.close()
    print("動作確認OK")

# Shizuku3エミュレータの操作GUI（サンプル）
#
# 起動: python gui.py
# 事前にShizuku3.exe（BACnetサーバ）を起動しておくこと。
# 左側: 操作（加速度・ステップ実行・弁/ファン/ダンパのスライダ等）
# 右側: 時系列グラフ（温度・CO2）と主要指標
import threading
import tkinter as tk
from collections import deque
from datetime import timedelta
from tkinter import messagebox, ttk

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib import rcParams

from shizuku3client import Shizuku3Client

rcParams["font.family"] = ["MS Gothic", "sans-serif"]  #日本語表示（Windows）

POLL_MSEC = 1000     #ポーリング周期[ms]
HISTORY_LEN = 2880   #グラフ保持点数


class Shizuku3GUI:

    def __init__(self, root):
        self.root = root
        root.title("Shizuku3 操作パネル")
        #全体のフォントを大きめに設定
        import tkinter.font as tkfont
        for fname in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            tkfont.nametofont(fname).configure(family="Meiryo UI", size=12)
        rcParams["font.size"] = 11
        self.emu = Shizuku3Client()
        self.hist = deque(maxlen=HISTORY_LEN)  #(時刻, 室温, 給気, 外気, CO2)
        self.latest = {}
        self.lock = threading.Lock()
        self.build_ui()
        self.polling = True
        threading.Thread(target=self.poll_loop, daemon=True).start()
        root.after(POLL_MSEC, self.refresh_ui)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---- UI構築 ------------------------------------------------------

    def build_ui(self):
        left = ttk.Frame(self.root, padding=8)
        left.grid(row=0, column=0, sticky="ns")
        right = ttk.Frame(self.root, padding=8)
        right.grid(row=0, column=1, sticky="nsew")
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        #時刻・加速度
        self.timeVar = tk.StringVar(value="--")
        ttk.Label(left, text="シミュレーション時刻").pack(anchor="w")
        ttk.Label(left, textvariable=self.timeVar, font=("Meiryo UI", 17, "bold")).pack(anchor="w", pady=(0, 6))

        timeFrame = ttk.LabelFrame(left, text="時間制御", padding=4)
        timeFrame.pack(fill="x", pady=4)
        btnRow = ttk.Frame(timeFrame)
        btnRow.pack(fill="x", pady=2)
        ttk.Button(btnRow, text="▶ 再生", width=8, command=self.do_play).pack(side="left", padx=2)
        ttk.Button(btnRow, text="■ 停止", width=8,
                   command=lambda: self.do_async(self.emu.stop)).pack(side="left", padx=2)
        accRow = ttk.Frame(timeFrame)
        accRow.pack(fill="x", pady=2)
        ttk.Label(accRow, text="加速度", width=6).pack(side="left")
        self.accVar = tk.StringVar()
        ttk.Label(accRow, textvariable=self.accVar, width=6).pack(side="right")
        #対数スケール（1～3600倍。低倍率も選びやすくする）
        self.accSlider = tk.Scale(accRow, from_=0.0, to=3.5563, resolution=0.01,
                                  orient="horizontal", showvalue=False, length=160,
                                  command=lambda v: self.accVar.set(f"×{self.current_acc()}"))
        self.accSlider.set(2.78)  #≒600倍
        self.accSlider.pack(side="left", fill="x", expand=True)
        self.accSlider.bind("<ButtonRelease-1>", lambda e: self.on_acc_changed())

        #操作スライダ（つまみを離したときに書き込む）
        ctrlFrame = ttk.LabelFrame(left, text="操作量", padding=4)
        ctrlFrame.pack(fill="x", pady=4)
        self.sliders = {}
        for name, lo, hi, init in [("弁開度", 0.0, 1.0, 0.0),
                                   ("ファン回転数比", 0.4, 1.0, 1.0),
                                   ("外気ダンパ開度", 0.0, 1.0, 1.0)]:
            row = ttk.Frame(ctrlFrame)
            row.pack(fill="x", pady=2)
            valVar = tk.StringVar(value=f"{init:.2f}")
            ttk.Label(row, text=name, width=12).pack(side="left")
            ttk.Label(row, textvariable=valVar, width=5).pack(side="right")
            sld = tk.Scale(row, from_=lo, to=hi, resolution=0.01, orient="horizontal",
                           showvalue=False, length=160,
                           command=lambda v, vv=valVar: vv.set(f"{float(v):.2f}"))
            sld.set(init)
            sld.pack(side="left", fill="x", expand=True)
            sld.bind("<ButtonRelease-1>",
                     lambda e, nm=name, s=sld: self.do_async(lambda: self.emu.write(nm, s.get())))
            self.sliders[name] = sld

        #モード・機器
        devFrame = ttk.LabelFrame(left, text="モード・機器", padding=4)
        devFrame.pack(fill="x", pady=4)
        self.modeVar = tk.IntVar(value=0)
        for label, v in [("自動", 0), ("冷房", 1), ("暖房", 2)]:
            ttk.Radiobutton(devFrame, text=label, value=v, variable=self.modeVar,
                            command=lambda: self.do_async(lambda: self.emu.write("冷暖モード", self.modeVar.get()))
                            ).pack(side="left")
        self.onVar = tk.BooleanVar(value=True)
        self.bypassVar = tk.BooleanVar(value=False)
        row2 = ttk.Frame(devFrame)
        row2.pack(fill="x")
        ttk.Checkbutton(devFrame, text="AHU運転", variable=self.onVar,
                        command=lambda: self.do_async(lambda: self.emu.write("発停", self.onVar.get()))
                        ).pack(side="left")
        ttk.Checkbutton(devFrame, text="HEXバイパス", variable=self.bypassVar,
                        command=lambda: self.do_async(lambda: self.emu.write("全熱交バイパス", self.bypassVar.get()))
                        ).pack(side="left")

        ttk.Button(left, text="リセット（初期状態に戻す）", command=self.do_reset).pack(fill="x", pady=8)

        #主要指標
        self.kpiVar = tk.StringVar(value="")
        ttk.Label(left, textvariable=self.kpiVar, justify="left").pack(anchor="w", pady=4)

        #グラフ
        self.fig, (self.axT, self.axC) = plt.subplots(2, 1, figsize=(7, 5), sharex=True)
        self.fig.subplots_adjust(hspace=0.15, right=0.97, top=0.95)
        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    # ---- ポーリング・描画 --------------------------------------------

    def poll_loop(self):
        names = ["室温", "給気温度", "外気温度", "CO2", "PPD", "在室人数",
                 "エネルギー積算", "加速度"]
        while self.polling:
            try:
                t = self.emu.current_time()
                vals = {nm: self.emu.read(nm) for nm in names}
                with self.lock:
                    self.latest = {"時刻": t, **vals}
                    if not self.hist or self.hist[-1][0] != t:
                        self.hist.append((t, vals["室温"], vals["給気温度"],
                                          vals["外気温度"], vals["CO2"]))
            except Exception as ex:
                import traceback
                msg = f"{type(ex).__name__}: {ex}"
                if msg != getattr(self, "_lastErr", None):
                    self._lastErr = msg
                    traceback.print_exc()  #原因究明用にコンソールへ完全表示
                with self.lock:
                    self.latest = {"エラー": msg}
            threading.Event().wait(POLL_MSEC / 1000)

    def refresh_ui(self):
        with self.lock:
            latest = dict(self.latest)
            hist = list(self.hist)
        if "エラー" in latest:
            if "TimeoutError" in latest["エラー"]:
                self.timeVar.set("応答なし: Shizuku3.exe（エミュレータ）を先に起動してください")
            else:
                self.timeVar.set(f"通信エラー: {latest['エラー'][:80]}")
        elif latest:
            state = f"▶ ×{latest['加速度']:.0f}" if 0 < latest["加速度"] else "■ 停止中"
            self.timeVar.set(f"{latest['時刻']:%m/%d %H:%M}  {state}")
            self.kpiVar.set(
                f"CO2: {latest['CO2']:.0f} ppm / PPD: {latest['PPD']:.0f} %\n"
                f"在室: {latest['在室人数']:.0f} 人\n"
                f"エネルギー積算: {latest['エネルギー積算']:.1f} kWh")
        if 2 <= len(hist):
            #表示は直近24時間分に限定（過去の特異値で縦軸が固定されるのを防ぐ）
            cut = hist[-1][0] - timedelta(hours=24)
            hist = [h for h in hist if cut <= h[0]]
            ts = [h[0] for h in hist]
            self.axT.clear()
            self.axT.plot(ts, [h[1] for h in hist], label="室温")
            self.axT.plot(ts, [h[2] for h in hist], label="給気")
            self.axT.plot(ts, [h[3] for h in hist], label="外気")
            self.axT.set_ylabel("温度[C]")
            self.axT.legend(loc="upper left", fontsize=8)
            self.axT.grid(True, alpha=0.3)
            self.axC.clear()
            self.axC.plot(ts, [h[4] for h in hist], color="tab:green")
            self.axC.axhline(1000, color="tab:red", linestyle="--", linewidth=0.8)
            self.axC.set_ylabel("CO2[ppm]")
            self.axC.grid(True, alpha=0.3)
            self.axC.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
            self.canvas.draw_idle()
        self.root.after(POLL_MSEC, self.refresh_ui)

    # ---- 操作 --------------------------------------------------------

    def current_acc(self):
        """加速度スライダの値（対数スケール）を倍率に変換する"""
        return max(1, min(3600, round(10 ** self.accSlider.get())))

    def do_play(self):
        """現在のスライダ倍率で連続実行する"""
        acc = self.current_acc()
        self.do_async(lambda: self.emu.run(acceleration=acc))

    def on_acc_changed(self):
        """再生中にスライダを動かした場合は新しい倍率を即時反映する"""
        with self.lock:
            running = 0 < self.latest.get("加速度", 0)
        if running:
            acc = self.current_acc()
            self.do_async(lambda: self.emu.write("加速度", acc))

    def do_async(self, fn):
        """書込み系の操作をワーカースレッドで実行する（UIをブロックしない）"""
        threading.Thread(target=lambda: self._safe(fn), daemon=True).start()

    def _safe(self, fn):
        try:
            fn()
        except Exception as ex:
            print("操作エラー:", ex)

    def do_reset(self):
        if messagebox.askokcancel("リセット", "setting.iniを再読込して初期状態に戻します。よろしいですか？"):
            with self.lock:
                self.hist.clear()
            self.do_async(self.emu.reset)

    def on_close(self):
        self.polling = False
        try:
            self.emu.close()
        finally:
            self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    Shizuku3GUI(root)
    root.mainloop()

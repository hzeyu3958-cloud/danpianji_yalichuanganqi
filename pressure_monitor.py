import csv
import math
import queue
import random
import threading
import time
import tkinter as tk
from collections import deque
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import serial
import serial.tools.list_ports


BAUD = 115200
MAX_POINTS = 600

class PulseDetector:
    """50 Hz pulse detector using detrending, adaptive threshold and refractory period."""
    def __init__(self):
        self.baseline = None; self.envelope = 0.0; self.last_peak = None
        self.last_value = 0.0; self.intervals = deque(maxlen=8)

    def update(self, stamp, value):
        if self.baseline is None: self.baseline = value
        self.baseline += 0.02 * (value - self.baseline)
        ac = value - self.baseline
        self.envelope += 0.08 * (abs(ac) - self.envelope)
        smooth = 0.25 * ac + 0.75 * self.last_value
        if smooth > max(8.0, 0.55 * self.envelope) and smooth >= self.last_value:
            if self.last_peak is None or stamp - self.last_peak >= 0.30:
                if self.last_peak is not None and 0.30 <= stamp - self.last_peak <= 1.50:
                    self.intervals.append(stamp - self.last_peak)
                self.last_peak = stamp
        self.last_value = smooth
        bpm = None
        if len(self.intervals) >= 2:
            ordered = sorted(self.intervals)
            bpm = 60.0 / ordered[len(ordered) // 2]
        quality = "等待信号" if self.envelope <= 5 else ("偏弱" if not self.intervals else "良好")
        return bpm, quality


class PressureMonitor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("压力传感器实时监测")
        self.geometry("1180x720")
        self.minsize(900, 600)
        self.configure(bg="#eef1f4")
        self.protocol("WM_DELETE_WINDOW", self.close_app)

        self.port = None
        self.reader = None
        self.stop_event = threading.Event()
        self.rx_queue = queue.Queue()
        self.simulating = False
        self.recording = False
        self.csv_file = None
        self.csv_writer = None
        self.start_time = time.monotonic()
        self.times = deque(maxlen=MAX_POINTS)
        self.values = deque(maxlen=MAX_POINTS)
        self.raw_values = deque(maxlen=20)
        self.last_sample_time = 0.0
        self.sample_count = 0
        self.tare_g = 0.0
        self.pulse = PulseDetector()

        self.port_var = tk.StringVar()
        self.status_var = tk.StringVar(value="未连接")
        self.raw_var = tk.StringVar(value="--")
        self.mv_var = tk.StringVar(value="-- mV")
        self.g_var = tk.StringVar(value="-- mS")
        self.force_var = tk.StringVar(value="-- N")
        self.bpm_var = tk.StringVar(value="-- BPM")
        self.quality_var = tk.StringVar(value="脉搏信号质量：等待信号")
        self.rate_var = tk.StringVar(value="0 Hz")
        self.p1_var = tk.StringVar(value="1.000")
        self.p2_var = tk.StringVar(value="0.000")
        self.rref_var = tk.StringVar(value="10.0")
        self.vcc_var = tk.StringVar(value="3300")
        self.filter_var = tk.IntVar(value=5)

        self._build_ui()
        self.refresh_ports()
        self.after(30, self.process_queue)

    def _build_ui(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#eef1f4")
        style.configure("Panel.TFrame", background="white")
        style.configure("TLabel", background="#eef1f4", foreground="#26323d")
        style.configure("Panel.TLabel", background="white", foreground="#43515d")
        style.configure("Value.TLabel", background="white", foreground="#111820", font=("Microsoft YaHei UI", 20, "bold"))
        style.configure("Title.TLabel", background="#eef1f4", foreground="#17212b", font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("Accent.TButton", font=("Microsoft YaHei UI", 10, "bold"))

        header = ttk.Frame(self, padding=(20, 15, 20, 10))
        header.pack(fill="x")
        ttk.Label(header, text="柔性压力传感器监测", style="Title.TLabel").pack(side="left")
        self.dot = tk.Canvas(header, width=14, height=14, bg="#eef1f4", highlightthickness=0)
        self.dot.create_oval(2, 2, 12, 12, fill="#aeb7bf", outline="", tags="dot")
        self.dot.pack(side="right", padx=(8, 0))
        ttk.Label(header, textvariable=self.status_var).pack(side="right")

        body = ttk.Frame(self, padding=(20, 0, 20, 18))
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        side = ttk.Frame(body, style="Panel.TFrame", padding=16, width=255)
        side.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        side.grid_propagate(False)
        ttk.Label(side, text="串口连接", style="Panel.TLabel", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        port_row = ttk.Frame(side, style="Panel.TFrame")
        port_row.pack(fill="x", pady=(10, 6))
        self.port_box = ttk.Combobox(port_row, textvariable=self.port_var, state="readonly", width=18)
        self.port_box.pack(side="left", fill="x", expand=True)
        ttk.Button(port_row, text="刷新", width=6, command=self.refresh_ports).pack(side="left", padx=(6, 0))
        self.connect_btn = ttk.Button(side, text="连接", style="Accent.TButton", command=self.toggle_connection)
        self.connect_btn.pack(fill="x", pady=4)
        self.sim_btn = ttk.Button(side, text="模拟数据", command=self.toggle_simulation)
        self.sim_btn.pack(fill="x", pady=4)

        ttk.Separator(side).pack(fill="x", pady=14)
        ttk.Label(side, text="换算参数", style="Panel.TLabel", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        self._field(side, "分压电阻 (kΩ)", self.rref_var)
        self._field(side, "供电电压 (mV)", self.vcc_var)
        self._field(side, "线性参数 p1", self.p1_var)
        self._field(side, "线性参数 p2", self.p2_var)
        ttk.Label(side, text="F = p1 × G + p2\nG 单位为 mS，F 单位为 N", style="Panel.TLabel").pack(anchor="w", pady=(5, 8))
        ttk.Label(side, text="平滑点数", style="Panel.TLabel").pack(anchor="w")
        ttk.Scale(side, from_=1, to=20, variable=self.filter_var, orient="horizontal").pack(fill="x")

        ttk.Separator(side).pack(fill="x", pady=14)
        ttk.Button(side, text="去皮 / 当前置零", command=self.tare).pack(fill="x", pady=3)
        self.record_btn = ttk.Button(side, text="开始保存 CSV", command=self.toggle_recording)
        self.record_btn.pack(fill="x", pady=3)
        ttk.Button(side, text="清空曲线", command=self.clear_plot).pack(fill="x", pady=3)

        main = ttk.Frame(body)
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        metrics = ttk.Frame(main)
        metrics.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        for i in range(5): metrics.columnconfigure(i, weight=1)
        self._metric(metrics, 0, "压力 / 力", self.force_var, "#e34b38")
        self._metric(metrics, 1, "电导", self.g_var, "#16846b")
        self._metric(metrics, 2, "传感器电压", self.mv_var, "#2673b8")
        self._metric(metrics, 3, "ADC 原始值", self.raw_var, "#5d6570")
        self._metric(metrics, 4, "脉搏心率", self.bpm_var, "#b13c92")
        ttk.Label(main, textvariable=self.quality_var).grid(row=2, column=0, sticky="e", pady=(5, 0))

        chart_panel = ttk.Frame(main, style="Panel.TFrame", padding=12)
        chart_panel.grid(row=1, column=0, sticky="nsew")
        chart_panel.rowconfigure(1, weight=1)
        chart_panel.columnconfigure(0, weight=1)
        chart_head = ttk.Frame(chart_panel, style="Panel.TFrame")
        chart_head.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(chart_head, text="实时变化曲线", style="Panel.TLabel", font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
        ttk.Label(chart_head, textvariable=self.rate_var, style="Panel.TLabel").pack(side="right")
        self.canvas = tk.Canvas(chart_panel, bg="#ffffff", highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda _e: self.draw_plot())

    def _field(self, parent, label, variable):
        ttk.Label(parent, text=label, style="Panel.TLabel").pack(anchor="w", pady=(8, 2))
        ttk.Entry(parent, textvariable=variable).pack(fill="x")

    def _metric(self, parent, col, title, variable, color):
        card = ttk.Frame(parent, style="Panel.TFrame", padding=14)
        card.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 4, 0 if col == 3 else 4))
        ttk.Label(card, text=title, style="Panel.TLabel").pack(anchor="w")
        label = ttk.Label(card, textvariable=variable, style="Value.TLabel")
        label.configure(foreground=color)
        label.pack(anchor="w", pady=(4, 0))

    def refresh_ports(self):
        ports = list(serial.tools.list_ports.comports())
        labels = [f"{p.device}  {p.description}" for p in ports if "Auxiliary" not in p.description]
        self.port_box["values"] = labels
        preferred = next((x for x in labels if "Application/User UART" in x), labels[0] if labels else "")
        if not self.port_var.get() or self.port_var.get() not in labels:
            self.port_var.set(preferred)

    def toggle_connection(self):
        if self.port:
            self.disconnect()
            return
        name = self.port_var.get().split()[0] if self.port_var.get() else ""
        if not name:
            messagebox.showwarning("没有串口", "未找到可用串口，请连接开发板后刷新。")
            return
        try:
            self.port = serial.Serial(name, BAUD, timeout=0.2)
        except serial.SerialException as exc:
            messagebox.showerror("连接失败", str(exc))
            self.port = None
            return
        self.stop_event.clear()
        self.reader = threading.Thread(target=self.read_serial, daemon=True)
        self.reader.start()
        self.connect_btn.configure(text="断开")
        self.set_status(f"已连接 {name}", "#22a06b")

    def disconnect(self):
        self.stop_event.set()
        if self.port:
            try: self.port.close()
            except serial.SerialException: pass
        self.port = None
        self.connect_btn.configure(text="连接")
        self.set_status("未连接", "#aeb7bf")

    def read_serial(self):
        while not self.stop_event.is_set() and self.port:
            try:
                line = self.port.readline().decode("ascii", errors="ignore").strip()
                if line: self.parse_line(line)
            except serial.SerialException as exc:
                self.rx_queue.put(("error", str(exc)))
                break

    def parse_line(self, line):
        # Firmware format: P,milliseconds,raw_adc,millivolts
        parts = line.split(",")
        try:
            if len(parts) == 4 and parts[0] == "P":
                self.rx_queue.put(("sample", int(parts[1]) / 1000.0, int(parts[2]), float(parts[3])))
            elif len(parts) >= 2:
                raw = int(float(parts[-1]))
                self.rx_queue.put(("sample", time.monotonic() - self.start_time, raw, raw * 3300.0 / 4095.0))
        except ValueError:
            pass

    def toggle_simulation(self):
        self.simulating = not self.simulating
        self.sim_btn.configure(text="停止模拟" if self.simulating else "模拟数据")
        if self.simulating:
            self.set_status("模拟数据运行中", "#d18b12")
            self.after(20, self.sim_tick)
        elif not self.port:
            self.set_status("未连接", "#aeb7bf")

    def sim_tick(self):
        if not self.simulating: return
        t = time.monotonic() - self.start_time
        pulse = max(0.0, math.sin(t * 1.35)) ** 3
        raw = int(180 + 2600 * pulse + random.gauss(0, 22))
        self.rx_queue.put(("sample", t, max(0, min(4095, raw)), raw * 3300.0 / 4095.0))
        self.after(20, self.sim_tick)

    def process_queue(self):
        processed = False
        try:
            while True:
                item = self.rx_queue.get_nowait()
                if item[0] == "sample":
                    self.add_sample(*item[1:]); processed = True
                elif item[0] == "error":
                    self.disconnect(); messagebox.showerror("串口中断", item[1])
        except queue.Empty:
            pass
        if processed: self.draw_plot()
        self.after(30, self.process_queue)

    def add_sample(self, stamp, raw, mv):
        try:
            rref = float(self.rref_var.get())
            vcc = float(self.vcc_var.get())
            p1 = float(self.p1_var.get())
            p2 = float(self.p2_var.get())
        except ValueError:
            return
        self.raw_values.append((raw, mv))
        n = max(1, min(len(self.raw_values), int(self.filter_var.get())))
        raw_avg = sum(x[0] for x in list(self.raw_values)[-n:]) / n
        mv_avg = sum(x[1] for x in list(self.raw_values)[-n:]) / n
        # Wiring: 3V3 -- sensor -- ADC -- Rref -- GND
        sensor_r_kohm = rref * max(vcc - mv_avg, 0.001) / max(mv_avg, 0.001)
        conductance_ms = 1.0 / max(sensor_r_kohm, 0.000001)
        force = p1 * max(0.0, conductance_ms - self.tare_g) + p2
        self.times.append(stamp)
        self.values.append(force)
        self.raw_var.set(f"{raw_avg:.0f}")
        self.mv_var.set(f"{mv_avg:.1f} mV")
        self.g_var.set(f"{conductance_ms:.4f} mS")
        self.force_var.set(f"{force:.3f} N")
        bpm, quality = self.pulse.update(stamp, raw_avg)
        self.bpm_var.set(f"{bpm:.0f} BPM" if bpm else "-- BPM")
        self.quality_var.set(f"脉搏信号质量：{quality}")
        self.sample_count += 1
        now = time.monotonic()
        if now - self.last_sample_time >= 1.0:
            self.rate_var.set(f"{self.sample_count / max(now - self.last_sample_time, 0.001):.1f} Hz")
            self.sample_count = 0; self.last_sample_time = now
        if self.recording and self.csv_writer:
            self.csv_writer.writerow([datetime.now().isoformat(timespec="milliseconds"), f"{stamp:.3f}", f"{raw_avg:.1f}", f"{mv_avg:.2f}", f"{conductance_ms:.6f}", f"{force:.6f}"])
            self.csv_file.flush()

    def tare(self):
        if not self.raw_values: return
        try: rref, vcc = float(self.rref_var.get()), float(self.vcc_var.get())
        except ValueError: return
        mv = sum(x[1] for x in self.raw_values) / len(self.raw_values)
        self.tare_g = 1.0 / (rref * max(vcc - mv, .001) / max(mv, .001))

    def toggle_recording(self):
        if self.recording:
            self.recording = False
            self.record_btn.configure(text="开始保存 CSV")
            if self.csv_file: self.csv_file.close()
            self.csv_file = self.csv_writer = None
            return
        default = f"pressure_{datetime.now():%Y%m%d_%H%M%S}.csv"
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile=default, filetypes=[("CSV", "*.csv")])
        if not path: return
        self.csv_file = open(path, "w", newline="", encoding="utf-8-sig")
        self.csv_writer = csv.writer(self.csv_file)
        self.csv_writer.writerow(["电脑时间", "设备时间_s", "ADC", "电压_mV", "电导_mS", "力_N"])
        self.recording = True
        self.record_btn.configure(text="停止保存")

    def clear_plot(self):
        self.times.clear(); self.values.clear(); self.raw_values.clear(); self.pulse = PulseDetector()
        self.bpm_var.set("-- BPM"); self.quality_var.set("脉搏信号质量：等待信号"); self.draw_plot()

    def draw_plot(self):
        c = self.canvas; c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 100 or h < 100: return
        left, top, right, bottom = 66, 20, w - 20, h - 42
        vals = list(self.values); ts = list(self.times)
        ymax = max(1.0, max(vals, default=1.0) * 1.15); ymin = min(0.0, min(vals, default=0.0))
        for i in range(6):
            y = top + (bottom - top) * i / 5
            value = ymax - (ymax - ymin) * i / 5
            c.create_line(left, y, right, y, fill="#e5e9ed")
            c.create_text(left - 8, y, text=f"{value:.2f}", anchor="e", fill="#65727e", font=("Segoe UI", 9))
        c.create_text(13, (top + bottom) / 2, text="力 (N)", angle=90, fill="#52606c")
        if len(vals) > 1:
            tmin, tmax = ts[0], max(ts[-1], ts[0] + 0.001)
            points = []
            for t, v in zip(ts, vals):
                x = left + (t - tmin) / (tmax - tmin) * (right - left)
                y = bottom - (v - ymin) / max(ymax - ymin, 1e-6) * (bottom - top)
                points.extend((x, y))
            c.create_line(*points, fill="#e34b38", width=2, smooth=False)
            c.create_text(left, bottom + 20, text=f"{tmin:.1f}s", anchor="w", fill="#65727e")
            c.create_text(right, bottom + 20, text=f"{tmax:.1f}s", anchor="e", fill="#65727e")
        else:
            c.create_text((left + right) / 2, (top + bottom) / 2, text="连接开发板或启动模拟数据", fill="#8b969f", font=("Microsoft YaHei UI", 12))

    def set_status(self, text, color):
        self.status_var.set(text); self.dot.itemconfigure("dot", fill=color)

    def close_app(self):
        self.simulating = False; self.disconnect()
        if self.csv_file: self.csv_file.close()
        self.destroy()


if __name__ == "__main__":
    PressureMonitor().mainloop()

import json
import time
import tkinter as tk
from tkinter import messagebox, ttk

import matplotlib.pyplot as plt
import numpy as np
import paho.mqtt.client as mqtt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


class ScanTestGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("MQTT Scan Client Tester")

        self.controller_connected = tk.StringVar(value="Disconnected")
        self.create_widgets()

        self.client = mqtt.Client()
        self.client.connect("localhost")
        self.client.loop_start()
        self.client.on_message = self.on_message
        self.client.subscribe("scan/status")
        self.client.subscribe("scan/result")
        self.client.subscribe("scan/error")

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_close(self):
        try:
            self.client.loop_stop()
            time.sleep(0.1)  # Let the loop settle
            self.client.disconnect()
        except Exception as e:
            print(f"MQTT disconnect error: {e}")
        finally:
            self.root.quit()
            self.root.destroy()

    def create_widgets(self):
        frame = ttk.Frame(self.root, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        # Status label
        ttk.Label(frame, text="Controller Status:").grid(row=0, column=0, sticky=tk.W)
        self.status_label = ttk.Label(
            frame, textvariable=self.controller_connected, foreground="red"
        )
        self.status_label.grid(row=0, column=1, sticky=tk.W)

        # Parameters
        self.param_entries = {}
        for i, (label, default) in enumerate(
            [
                ("Rate", "10000"),
                ("Frequency (Hz)", "10"),
                ("Amplitude (V)", "1.0"),
                ("Points", "1000"),
                ("ADC Channels (comma-separated)", "0"),
            ]
        ):
            ttk.Label(frame, text=label + ":").grid(row=i + 1, column=0, sticky=tk.W)
            entry = ttk.Entry(frame)
            entry.insert(0, default)
            entry.grid(row=i + 1, column=1, sticky=tk.EW)
            self.param_entries[label] = entry

        # Buttons
        button_frame = ttk.Frame(frame)
        button_frame.grid(row=6, column=0, columnspan=2, pady=10)
        ttk.Button(button_frame, text="Initialize", command=self.send_init).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(button_frame, text="Start Scan", command=self.send_start).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(button_frame, text="Abort Scan", command=self.send_abort).pack(
            side=tk.LEFT, padx=5
        )

        # Plot
        self.fig, self.ax = plt.subplots(figsize=(6, 3))
        self.ax.set_title("ADC Data")
        self.ax.set_xlabel("Sample")
        self.ax.set_ylabel("Value")
        self.canvas = FigureCanvasTkAgg(self.fig, master=frame)
        self.canvas.get_tk_widget().grid(row=7, column=0, columnspan=2, pady=10)

        # Output
        self.output_text = tk.Text(frame, height=10)
        self.output_text.grid(row=8, column=0, columnspan=2, pady=10)

        for i in range(2):
            frame.columnconfigure(i, weight=1)

    def send_init(self):
        try:
            rate = int(self.param_entries["Rate"].get())
            freq = float(self.param_entries["Frequency (Hz)"].get())
            amp = float(self.param_entries["Amplitude (V)"].get())
            points = int(self.param_entries["Points"].get())
            adc_chans = [
                int(ch)
                for ch in self.param_entries["ADC Channels (comma-separated)"]
                .get()
                .split(",")
            ]

            t = np.arange(points) / rate
            sin_wave = amp * np.sin(2 * np.pi * freq * t)
            dac0 = sin_wave.tolist()
            dac1 = (-sin_wave).tolist()

            payload = {
                "rate": rate,
                "dac_waveforms": {"0": dac0, "1": dac1},
                "adc_channels": adc_chans,
            }
            self.client.publish("scan/init", json.dumps(payload))
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def send_start(self):
        self.client.publish("scan/start", json.dumps({}))

    def send_abort(self):
        self.client.publish("scan/abort", json.dumps({}))

    def on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode()
        self.output_text.insert(tk.END, f"{topic}: {payload}\n")
        self.output_text.see(tk.END)

        if topic == "scan/status":
            try:
                data = json.loads(payload)
                if "connected" in data:
                    if data["connected"]:
                        self.controller_connected.set("Connected")
                        self.status_label.configure(foreground="green")
                    else:
                        self.controller_connected.set("Disconnected")
                        self.status_label.configure(foreground="red")
            except Exception:
                pass

        if topic == "scan/result":
            try:
                data = json.loads(payload)
                self.plot_data(data)
            except Exception as e:
                self.output_text.insert(tk.END, f"Plot error: {e}\n")

    def plot_data(self, data):
        self.ax.clear()
        self.ax.set_title("ADC Data")
        self.ax.set_xlabel("Sample")
        self.ax.set_ylabel("Value")
        data = list(zip(*data))  # Transpose to separate channels
        for i, ch_data in enumerate(data):
            self.ax.plot(ch_data, label=f"ADC {i}")
        self.ax.legend()
        self.canvas.draw()


if __name__ == "__main__":
    root = tk.Tk()
    app = ScanTestGUI(root)
    root.mainloop()

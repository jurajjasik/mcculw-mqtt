import json
import logging
import threading
import time
from ctypes import POINTER, c_double, c_ushort, cast

import paho.mqtt.client as mqtt
from mcculw import ul
from mcculw.device_info import DaqDeviceInfo
from mcculw.enums import (
    ChannelType,
    DigitalPortType,
    FunctionType,
    ScanOptions,
    Status,
    TriggerEvent,
    TriggerSensitivity,
    TriggerSource,
    ULRange,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ScanController:
    def __init__(self, board_num=0, mqtt_broker="localhost", base_topic="scan"):
        self.board_num = board_num
        self.base_topic = base_topic

        self.client = mqtt.Client()
        self.client.will_set(
            f"{self.base_topic}/status", json.dumps({"connected": False}), retain=True
        )
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect(mqtt_broker)

        self.daq_dev_info = None
        self.ao_mem = None
        self.ai_mem = None
        self.ai_data = None
        self.points_per_channel = 0
        self.ao_total = 0
        self.ao_range = None
        self.ao_chans = []
        self.adc_chans = []
        self.scan_running = False
        self.status_thread = None
        self.scan_rate = 10000

        self.device_check_thread = threading.Thread(
            target=self.device_check_loop, daemon=True
        )
        self.device_check_thread.start()

    def check_device_available(self):
        try:
            self.daq_dev_info = DaqDeviceInfo(self.board_num)
            self.client.publish(
                f"{self.base_topic}/device",
                json.dumps({"device_available": True}),
                retain=True,
            )
        except Exception:
            self.client.publish(
                f"{self.base_topic}/device",
                json.dumps({"device_available": False}),
                retain=True,
            )

    def device_check_loop(self):
        while True:
            self.check_device_available()
            time.sleep(10)

    def on_connect(self, client, userdata, flags, rc):
        topics = ["init", "start", "abort"]
        for t in topics:
            client.subscribe(f"{self.base_topic}/{t}")
        logger.info("Connected and subscribed to scan control topics.")
        client.publish(
            f"{self.base_topic}/status", json.dumps({"connected": True}), retain=True
        )

    def on_message(self, client, userdata, msg):
        topic = msg.topic.split("/")[-1]
        try:
            payload = json.loads(msg.payload.decode())
        except Exception as e:
            self.client.publish(
                f"{self.base_topic}/error", json.dumps({"error": f"Invalid JSON: {e}"})
            )
            return

        try:
            if topic == "init":
                self.handle_init(payload)
            elif topic == "start":
                self.handle_start()
            elif topic == "abort":
                self.handle_abort()
        except Exception as e:
            self.client.publish(
                f"{self.base_topic}/error", json.dumps({"error": str(e)})
            )

    def handle_init(self, payload):
        try:
            rate = payload["rate"]
            waveforms = payload["dac_waveforms"]
            self.adc_chans = payload["adc_channels"]
            if not isinstance(rate, int) or rate <= 0:
                raise ValueError("Invalid rate")
            if len(waveforms) != 2:
                raise ValueError("Exactly 2 DAC channels are required")

            self.scan_rate = rate
            self.points_per_channel = len(next(iter(waveforms.values())))
            self.ao_chans = sorted([int(ch) for ch in waveforms.keys()])

            # ul.release_daq_device(self.board_num)
            self.daq_dev_info = DaqDeviceInfo(self.board_num)
            ao_info = self.daq_dev_info.get_ao_info()
            self.ao_range = ao_info.supported_ranges[0]

            self.ao_total = len(self.ao_chans) * self.points_per_channel
            self.ao_mem = ul.win_buf_alloc(self.ao_total)
            ctypes_array = cast(self.ao_mem, POINTER(c_ushort))

            for i in range(self.points_per_channel):
                for ch_idx, ch in enumerate(self.ao_chans):
                    val = waveforms[str(ch)][i]
                    raw = ul.from_eng_units(self.board_num, self.ao_range, val)
                    ctypes_array[i * len(self.ao_chans) + ch_idx] = raw

            logger.info("Scan initialized.")
        except Exception as e:
            raise RuntimeError(f"Initialization error: {e}")

    def handle_start(self):
        try:
            self.configure_trigger()
            self.start_adc_scan()
            self.start_dac_scan()
            self.trigger()
            self.scan_running = True

            self.status_thread = threading.Thread(target=self.publish_status_loop)
            self.status_thread.start()
        except Exception as e:
            raise RuntimeError(f"Start error: {e}")

    def configure_trigger(self):
        ul.d_config_port(self.board_num, DigitalPortType.AUXPORT, 1)  # 1 = Output
        ul.d_bit_out(self.board_num, DigitalPortType.AUXPORT, 0, 0)  # Set DIO0 LOW
        ul.daq_set_trigger(
            self.board_num,
            TriggerSource.EXTTTL,
            TriggerSensitivity.RISING_EDGE,
            0,
            ChannelType.DIGITAL,
            ULRange.NOTUSED,
            0.0,
            0.0,
            TriggerEvent.START,
        )

    def start_adc_scan(self):
        chan_list = self.adc_chans
        chan_type_list = [ChannelType.ANALOG_DIFF] * len(chan_list)
        gain_list = [ULRange.BIP10VOLTS] * len(chan_list)
        total_count = self.points_per_channel * len(chan_list)
        self.ai_mem = ul.scaled_win_buf_alloc(total_count)
        self.ai_data = cast(self.ai_mem, POINTER(c_double))

        ul.daq_in_scan(
            self.board_num,
            chan_list,
            chan_type_list,
            gain_list,
            len(chan_list),
            self.scan_rate,
            0,
            total_count,
            self.ai_mem,
            ScanOptions.BACKGROUND | ScanOptions.SCALEDATA | ScanOptions.EXTTRIGGER,
        )

    def start_dac_scan(self):
        ul.daq_out_scan(
            self.board_num,
            self.ao_chans,
            [ChannelType.ANALOG] * len(self.ao_chans),
            [self.ao_range] * len(self.ao_chans),
            len(self.ao_chans),
            self.scan_rate,
            self.ao_total,
            self.ao_mem,
            ScanOptions.BACKGROUND | ScanOptions.EXTTRIGGER,
        )

    def trigger(self):
        time.sleep(0.1)
        ul.d_bit_out(self.board_num, DigitalPortType.AUXPORT, 0, 1)
        time.sleep(0.01)
        ul.d_bit_out(self.board_num, DigitalPortType.AUXPORT, 0, 0)
        logger.info("Triggered scan.")

    def publish_status_loop(self):
        while self.scan_running:
            try:
                status, _, _ = ul.get_status(self.board_num, FunctionType.DAQIFUNCTION)
                if status == Status.IDLE:
                    self.scan_running = False
                    self.publish_result()
                    break
                self.client.publish(
                    f"{self.base_topic}/status", json.dumps({"running": True})
                )
                time.sleep(1)
            except Exception as e:
                self.client.publish(
                    f"{self.base_topic}/error",
                    json.dumps({"error": f"Status check error: {e}"}),
                )
                break

    def publish_result(self):
        try:
            assert self.ai_data is not None
            results = []
            for i in range(self.points_per_channel):
                sample = []
                for j in range(len(self.adc_chans)):
                    idx = i * len(self.adc_chans) + j
                    sample.append(self.ai_data[idx])
                results.append(sample)
            self.client.publish(f"{self.base_topic}/result", json.dumps(results))
        except Exception as e:
            self.client.publish(
                f"{self.base_topic}/error",
                json.dumps({"error": f"Result publish error: {e}"}),
            )

    def handle_abort(self):
        try:
            ul.stop_background(self.board_num, FunctionType.DAQIFUNCTION)
            ul.stop_background(self.board_num, FunctionType.DAQOFUNCTION)
            self.scan_running = False
            self.client.publish(
                f"{self.base_topic}/status", json.dumps({"running": False})
            )
        except Exception as e:
            self.client.publish(
                f"{self.base_topic}/error", json.dumps({"error": f"Abort error: {e}"})
            )

    def run(self):
        self.client.loop_forever()


if __name__ == "__main__":
    controller = ScanController()
    controller.run()

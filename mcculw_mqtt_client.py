import argparse
import json
import logging
import re
import threading
import time
from datetime import datetime

import paho.mqtt.client as mqtt
import yaml
from mcculw import ul
from mcculw.enums import ULRange

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# --- Utility Functions ---


def load_config(file_path):
    with open(file_path, "r") as f:
        return yaml.safe_load(f)


def parse_ulrange(range_name):
    try:
        return getattr(ULRange, range_name)
    except AttributeError:
        raise ValueError(f"Invalid ULRange name: {range_name}")


def build_ranges(range_config):
    result = {}
    for key, range_name in range_config.items():
        board_num, channel = map(int, key.split(","))
        result[(board_num, channel)] = parse_ulrange(range_name)
    return result


def timestamp():
    return datetime.now().isoformat() + "Z"


# --- Voltage Limiting Helpers ---


def limit_voltage(voltage, ul_range: ULRange):
    return max(ul_range.range_min, min(ul_range.range_max, voltage))


def lookup_range(board_num, channel, ranges):
    if (board_num, channel) in ranges:
        return ranges[(board_num, channel)]
    else:
        raise ValueError(
            f"Board {board_num}, Channel {channel} not found in ranges dictionary!"
        )


# --- MQTT Callback Handlers ---


def on_connect(client, userdata, flags, rc):
    logger.info("Connected with result code " + str(rc))
    # Subscribe to wildcard topics
    client.subscribe("daq/dac/+/+/set")
    client.subscribe("daq/adc/+/+/request")


def on_message(client, userdata, msg):
    topic = msg.topic
    payload = msg.payload.decode()

    # Match topics with regex
    dac_match = re.match(r"daq/dac/(\d+)/(\d+)/set", topic)
    adc_match = re.match(r"daq/adc/(\d+)/(\d+)/request", topic)

    if dac_match:
        board_num = int(dac_match.group(1))
        channel = int(dac_match.group(2))
        handle_dac_command(board_num, channel, payload)

    elif adc_match:
        board_num = int(adc_match.group(1))
        channel = int(adc_match.group(2))
        handle_adc_request(board_num, channel)


# --- DAC Control Function ---
def handle_dac_command(board_num, channel, payload):
    try:
        data = json.loads(payload)
        voltage = data.get("voltage")
        if voltage is None:
            raise ValueError("No voltage provided in payload!")

        range = lookup_range(board_num, channel, RANGES_DAC)

        # Limit voltage to valid range
        voltage = float(voltage)
        voltage = limit_voltage(voltage, range)

        logger.debug(
            f"Setting DAC - Board {board_num}, Channel {channel} to {voltage} V"
        )
        ul.v_out(
            board_num=board_num, channel=channel, ul_range=range, data_value=voltage
        )

        # Success acknowledgment
        response_topic = f"daq/dac/{board_num}/{channel}/response"
        response = {"status": "success", "voltage": voltage, "timestamp": timestamp()}
        mqtt_client.publish(response_topic, json.dumps(response), retain=True)

    except Exception as e:
        logger.error(f"DAC command error: {e}")
        error_topic = f"daq/dac/{board_num}/{channel}/error"
        error_message = {"status": "error", "message": str(e), "timestamp": timestamp()}
        mqtt_client.publish(error_topic, json.dumps(error_message))


# --- ADC Read Function ---
def handle_adc_request(board_num, channel):
    try:
        voltage = adc_read_voltage(board_num, channel)

        logger.debug(f"Read ADC - Board {board_num}, Channel {channel}: {voltage} V")

        response_topic = f"daq/adc/{board_num}/{channel}/response"
        response = {
            "board_num": board_num,
            "channel": channel,
            "voltage": voltage,
            "timestamp": timestamp(),
        }

        mqtt_client.publish(response_topic, json.dumps(response), retain=True)

    except Exception as e:
        logger.error(f"ADC read error: {e}")
        error_topic = f"daq/adc/{board_num}/{channel}/error"
        error_message = {"status": "error", "message": str(e), "timestamp": timestamp()}
        mqtt_client.publish(error_topic, json.dumps(error_message))


def adc_read_voltage(board_num, channel):
    adc_range = lookup_range(board_num=board_num, channel=channel, ranges=RANGES_ADC)
    value = ul.a_in(board_num=board_num, channel=channel, ul_range=adc_range)
    voltage = ul.to_eng_units(board_num=board_num, ul_range=adc_range, data_value=value)
    return voltage


# --- Periodic ADC Sampling Thread ---
def periodic_adc_sampling():
    while True:
        for board_num, channel in MONITORED_ADC_CHANNELS:
            try:
                voltage = adc_read_voltage(board_num, channel)

                logger.debug(
                    f"[Periodic] ADC Board {board_num} Channel {channel}: {voltage} V"
                )

                response_topic = f"daq/adc/{board_num}/{channel}/response"
                response = {
                    "board_num": board_num,
                    "channel": channel,
                    "voltage": voltage,
                    "timestamp": timestamp(),
                }

                mqtt_client.publish(response_topic, json.dumps(response), retain=True)

            except Exception as e:
                logger.error(f"[Periodic] ADC read error: {e}")
                error_topic = f"daq/adc/{board_num}/{channel}/error"
                error_message = {
                    "status": "error",
                    "message": str(e),
                    "timestamp": timestamp(),
                }
                mqtt_client.publish(error_topic, json.dumps(error_message))

        time.sleep(SAMPLING_INTERVAL)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MQTT Client for MCC DAQ")
    parser.add_argument(
        "-c", "--config", default="config.yaml", help="Path to YAML config file"
    )
    args = parser.parse_args()

    # Load configuration
    config = load_config(args.config)

    # Apply configuration to globals
    BROKER_ADDRESS = config["mqtt"]["broker_address"]
    BROKER_PORT = config["mqtt"]["broker_port"]
    CLIENT_ID = config["mqtt"].get("client_id", "mcc_daq_client")

    SAMPLING_INTERVAL = config.get("sampling_interval", 1)

    MONITORED_ADC_CHANNELS = []
    if config["adc"]["monitored_channels"]:
        MONITORED_ADC_CHANNELS = [
            tuple(pair) for pair in config["adc"]["monitored_channels"]
        ]

    RANGES_ADC = build_ranges(config["adc"]["ranges"])
    RANGES_DAC = build_ranges(config["dac"]["ranges"])

    # MQTT Setup
    mqtt_client = mqtt.Client(client_id=CLIENT_ID)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message

    mqtt_client.connect(BROKER_ADDRESS, BROKER_PORT, 60)

    mqtt_client.loop_start()

    # Start periodic sampling thread
    sampling_thread = threading.Thread(target=periodic_adc_sampling, daemon=True)
    sampling_thread.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Exiting...")
        mqtt_client.loop_stop()
        mqtt_client.disconnect()

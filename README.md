# mcculw-mqtt

**MQTT-based control and data acquisition for MCC DAQ devices using Python and mcculw.**  
This project provides a lightweight MQTT client for remote control and monitoring of Measurement Computing (MCC) DAQ devices via the `mcculw` Python library.

## Features

✅ Remote control of **DAC outputs** via MQTT  
✅ On-demand and periodic **ADC data acquisition**  
✅ **Voltage limit** checks to prevent hardware damage  
✅ Real-time **success/error feedback** through MQTT topics  
✅ **Retained messages** for the latest ADC readings  
✅ Easy integration with home automation, industrial systems, or data logging pipelines (e.g., Node-RED, InfluxDB)

---

## How It Works

The MQTT client subscribes to DAC and ADC topics, parses board and channel information directly from the topic structure, and interacts with MCC DAQ devices using `mcculw`.

### Topic Structure

| **Topic Example**                   | **Action**                            |
|-------------------------------------|---------------------------------------|
| `daq/dac/0/1/set`                   | Set DAC on board `0`, channel `1`    |
| `daq/dac/0/1/response` *(retained)* | Last success response from DAC        |
| `daq/dac/0/1/error`                 | Error messages from DAC commands      |
| `daq/adc/0/2/request`               | Request ADC read on board `0`, channel `2` |
| `daq/adc/0/2/response` *(retained)* | Last known ADC reading                |
| `daq/adc/0/2/error`                 | Error messages from ADC reads         |

---

## Getting Started

### Prerequisites

- Python 3.7+
- MCC DAQ hardware (e.g., USB-1208FS, USB-1608G, etc.)
- MCC DAQ drivers and `mcculw` installed (Universal Library for Windows)
- MQTT broker (e.g., Mosquitto)

### Installation

1. Clone this repo:

   ```bash
   git clone https://github.com/yourusername/mcculw-mqtt.git
   cd mcculw-mqtt
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Run the client:

   ```bash
   python mcculw_mqtt_client.py
   ```

---

## Configuration

Edit the `config.yaml` file to customize the MQTT broker settings, DAQ device configuration, and other parameters.

```yaml
mqtt:
  broker: localhost
  port: 1883

---

## Example MQTT Messages

### DAC Command

- **Topic**: `daq/dac/0/1/set`  
- **Payload**:

  ```json
  { "voltage": 2.5 }
  ```

### ADC Request

- **Topic**: `daq/adc/0/2/request`  
- **Payload**: (empty or any trigger message)

## Contributing

Contributions are welcome! Please open an issue or submit a pull request to help improve this project.

---

## License

MIT License. See `LICENSE` for details.

---

## Credits

- [Measurement Computing](https://www.mccdaq.com/) for their DAQ devices  
- [`mcculw`](https://github.com/MeasurementComputing/mcculw) for Python integration  
- [`paho-mqtt`](https://github.com/eclipse/paho.mqtt.python) for MQTT messaging

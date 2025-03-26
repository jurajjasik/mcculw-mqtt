from __future__ import absolute_import, division, print_function

import logging
from ctypes import POINTER, c_double, c_ushort, cast
from math import pi, sin
from time import sleep

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

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(levelname)s [%(filename)s:%(lineno)d]: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

try:
    from console_examples_util import config_first_detected_device
except ImportError:
    from .console_examples_util import config_first_detected_device


def setup_device(board_num=0, dev_id_list=None):
    if dev_id_list is None:
        dev_id_list = [318]  # RedLab 1808X
    config_first_detected_device(board_num, dev_id_list)
    return DaqDeviceInfo(board_num)


def configure_dio0_output(board_num):
    ul.d_config_port(board_num, DigitalPortType.AUXPORT, 1)  # 1 = Output
    ul.d_bit_out(board_num, DigitalPortType.AUXPORT, 0, 0)  # Set DIO0 LOW
    logger.info("DIO0 configured as output and set LOW.")


def pulse_dio0(board_num, delay=0.01):
    ul.d_bit_out(board_num, DigitalPortType.AUXPORT, 0, 1)  # Set HIGH
    sleep(delay)
    ul.d_bit_out(board_num, DigitalPortType.AUXPORT, 0, 0)  # Back to LOW
    logger.info("DIO0 pulse generated (HIGH → LOW).")


def dio_high(board_num):
    ul.d_bit_out(board_num, DigitalPortType.AUXPORT, 0, 1)  # Set HIGH
    logger.info("DIO0 set HIGH.")


def dio_low(board_num):
    ul.d_bit_out(board_num, DigitalPortType.AUXPORT, 0, 0)  # Set LOW
    logger.info("DIO0 set LOW.")


def prepare_dac_waveform(
    board_num, ao_info, rate, points_per_channel, low_chan=0, high_chan=1
):
    ao_range = ao_info.supported_ranges[0]
    num_chans = high_chan - low_chan + 1
    total_count = num_chans * points_per_channel
    memhandle = ul.win_buf_alloc(total_count)
    if not memhandle:
        raise Exception("Failed to allocate DAC buffer")
    ctypes_array = cast(memhandle, POINTER(c_ushort))

    amplitude = (ao_range.range_max - ao_range.range_min) / 2
    y_offset = (amplitude + ao_range.range_min) / 2
    freqs = [(ch + 1) / (points_per_channel / rate) * 10 for ch in range(num_chans)]

    idx = 0
    for pt in range(points_per_channel):
        for ch in range(num_chans):
            val = amplitude * sin(2 * pi * freqs[ch] * pt / rate) + y_offset
            raw_val = ul.from_eng_units(board_num, ao_range, val)
            ctypes_array[idx] = raw_val
            idx += 1

    return memhandle, total_count, ao_range, [low_chan, high_chan]


def configure_trigger(board_num):
    ul.daq_set_trigger(
        board_num,
        TriggerSource.EXTTTL,
        TriggerSensitivity.RISING_EDGE,
        0,  # DIO0
        ChannelType.DIGITAL,
        ULRange.NOTUSED,
        0.0,  # trigger level (ignored for EXTTTL)
        0.0,  # variance
        TriggerEvent.START,
    )
    logger.info("Trigger configured: EXTTTL on DIO0, rising edge.")


def start_adc_scan(board_num, rate, points_per_channel):
    chan_list = [0, DigitalPortType.AUXPORT, 0]
    chan_type_list = [ChannelType.ANALOG_DIFF, ChannelType.DIGITAL, ChannelType.CTR]
    gain_list = [ULRange.BIP10VOLTS, ULRange.NOTUSED, ULRange.NOTUSED]

    num_chans = len(chan_list)
    total_count = num_chans * points_per_channel
    memhandle = ul.scaled_win_buf_alloc(total_count)
    if not memhandle:
        raise Exception("Failed to allocate ADC buffer")
    data = cast(memhandle, POINTER(c_double))

    actual_rate, actual_pretrig_count, actual_total_count = ul.daq_in_scan(
        board_num,
        chan_list,
        chan_type_list,
        gain_list,
        num_chans,
        rate,
        0,
        total_count,
        memhandle,
        ScanOptions.BACKGROUND | ScanOptions.SCALEDATA | ScanOptions.EXTTRIGGER,
    )
    logger.info(
        f"ADC scan armed in background (waiting for trigger). rate={actual_rate}, pretrig_count={actual_pretrig_count}, total_count={actual_total_count}"
    )
    # sleep(1)  # Ensure scan is waiting for trigger
    return memhandle, data, chan_list, chan_type_list, points_per_channel


def start_dac_scan(board_num, rate, total_count, memhandle, ao_range, chan_list):
    rate_set = ul.daq_out_scan(
        board_num,
        chan_list,
        [ChannelType.ANALOG] * len(chan_list),
        [ao_range] * len(chan_list),
        len(chan_list),
        rate,
        total_count,
        memhandle,
        ScanOptions.BACKGROUND | ScanOptions.EXTTRIGGER,
    )
    logger.info(
        f"DAC scan armed in background (waiting for trigger). rate_set={rate_set}"
    )
    # sleep(1)  # Ensure scan is waiting for trigger


def wait_for_scan_completion(board_num, func_type):
    logger.info(f"Waiting for {func_type.name} scan to complete")
    status = Status.RUNNING
    while status != Status.IDLE:
        sleep(1)
        status, _, cur_index = ul.get_status(board_num, func_type)
        logger.info(
            f"Waiting for {func_type.name} scan to complete. Status: {status.name}, cur_index: {cur_index}"
        )
    logger.info(f"{func_type.name} scan complete.")


def print_scan_data(data, chan_list, chan_type_list, points_per_channel):
    num_chans = len(chan_list)
    row_fmt = "{:>5}" + "{:>10}" * num_chans
    headers = ["Idx"]

    for i, ch_type in enumerate(chan_type_list):
        label = {
            ChannelType.ANALOG_DIFF: lambda: f"AI{chan_list[i]}",
            ChannelType.DIGITAL: lambda: chan_list[i].name,
            ChannelType.CTR: lambda: f"CI{chan_list[i]}",
        }[ch_type]()
        headers.append(label)
    print(row_fmt.format(*headers))

    idx = 0
    for i in range(points_per_channel):
        row = [f"{i}"]
        for j in range(num_chans):
            val = data[idx]
            row.append(
                f"{int(val) if chan_type_list[j] in (ChannelType.DIGITAL, ChannelType.CTR) else f'{val:.3f}'}"
            )
            idx += 1
        print(row_fmt.format(*row))


def cleanup(board_num, *memhandles):
    for m in memhandles:
        if m:
            ul.win_buf_free(m)
    ul.release_daq_device(board_num)


def run_ext_triggered_adc_dac(board_num, rate, points_per_channel):
    ao_mem = ai_mem = None

    try:
        dev_info = setup_device(board_num)
        ao_info = dev_info.get_ao_info()

        configure_dio0_output(board_num)
        configure_trigger(board_num)

        ao_mem, ao_total, ao_range, ao_chans = prepare_dac_waveform(
            board_num, ao_info, rate, points_per_channel
        )

        ai_mem, ai_data, chan_list, chan_type_list, ppc = start_adc_scan(
            board_num, rate, points_per_channel
        )

        start_dac_scan(board_num, rate, ao_total, ao_mem, ao_range, ao_chans)

        pulse_dio0(board_num)  # Trigger both scans

        wait_for_scan_completion(board_num, FunctionType.DAQIFUNCTION)
        wait_for_scan_completion(board_num, FunctionType.DAQOFUNCTION)

        logger.info("Scan complete.")
        print_scan_data(ai_data, chan_list, chan_type_list, ppc)

    except Exception as e:
        logger.error("Error: %s", e)
        import traceback

        logger.error(traceback.format_exc())
    finally:
        cleanup(board_num, ao_mem, ai_mem)


if __name__ == "__main__":
    run_ext_triggered_adc_dac(board_num=0, rate=1000, points_per_channel=10000)

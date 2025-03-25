from __future__ import absolute_import, division, print_function

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
    ULRange,
)

try:
    from console_examples_util import config_first_detected_device
except ImportError:
    from .console_examples_util import config_first_detected_device


def setup_device(board_num=0, dev_id_list=None):
    if dev_id_list is None:
        dev_id_list = [318]  # RedLab 1808X
    config_first_detected_device(board_num, dev_id_list)
    daq_dev_info = DaqDeviceInfo(board_num)
    print(f"Using DAQ device: {daq_dev_info.product_name} ({daq_dev_info.unique_id})")
    return daq_dev_info


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

    index = 0
    for pt in range(points_per_channel):
        for ch in range(num_chans):
            val = amplitude * sin(2 * pi * freqs[ch] * pt / rate) + y_offset
            raw_val = ul.from_eng_units(board_num, ao_range, val)
            ctypes_array[index] = raw_val
            index += 1

    return memhandle, total_count, ao_range, low_chan, high_chan, freqs


def start_dac_scan(
    board_num, low_chan, high_chan, total_count, rate, ao_range, memhandle
):
    ul.a_out_scan(
        board_num,
        low_chan,
        high_chan,
        total_count,
        rate,
        ao_range,
        memhandle,
        ScanOptions.BACKGROUND,
    )
    print("DAC scan started in background.")


def run_adc_scan(board_num, rate, points_per_channel):
    # Configure channels
    chan_list = [0, DigitalPortType.AUXPORT, 0]  # Analog diff, digital, counter
    chan_type_list = [ChannelType.ANALOG_DIFF, ChannelType.DIGITAL, ChannelType.CTR]
    gain_list = [ULRange.BIP10VOLTS, ULRange.NOTUSED, ULRange.NOTUSED]
    num_chans = len(chan_list)
    total_count = num_chans * points_per_channel

    memhandle = ul.scaled_win_buf_alloc(total_count)
    if not memhandle:
        raise Exception("Failed to allocate ADC buffer")
    data = cast(memhandle, POINTER(c_double))

    ul.daq_in_scan(
        board_num,
        chan_list,
        chan_type_list,
        gain_list,
        num_chans,
        rate,
        0,
        total_count,
        memhandle,
        ScanOptions.FOREGROUND | ScanOptions.SCALEDATA,
    )

    print("ADC scan complete. Sample data:")
    print_formatted_scan(data, chan_list, chan_type_list, points_per_channel)

    return memhandle


def print_formatted_scan(data, chan_list, chan_type_list, points_per_channel):
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
            if chan_type_list[j] in (ChannelType.DIGITAL, ChannelType.CTR):
                row.append(f"{int(val)}")
            else:
                row.append(f"{val:.3f}")
            idx += 1
        print(row_fmt.format(*row))


def wait_for_dac_completion(board_num):
    print("\nWaiting for DAC scan to complete", end="")
    status = Status.RUNNING
    while status != Status.IDLE:
        sleep(0.5)
        status, _, _ = ul.get_status(board_num, FunctionType.AOFUNCTION)
        print(".", end="")
    print(" done.")


def cleanup(board_num, *memhandles):
    for m in memhandles:
        if m:
            ul.win_buf_free(m)
    ul.release_daq_device(board_num)


def run_synchronous_test():
    board_num = 0
    rate = 10000
    points_per_channel = 1000

    ao_mem = ai_mem = None

    try:
        dev_info = setup_device(board_num)
        ao_info = dev_info.get_ao_info()

        ao_mem, ao_total, ao_range, low_chan, high_chan, freqs = prepare_dac_waveform(
            board_num, ao_info, rate, points_per_channel
        )
        start_dac_scan(board_num, low_chan, high_chan, ao_total, rate, ao_range, ao_mem)
        ai_mem = run_adc_scan(board_num, rate, points_per_channel)
        wait_for_dac_completion(board_num)

    except Exception as e:
        print("Error:", e)
    finally:
        cleanup(board_num, ao_mem, ai_mem)


if __name__ == "__main__":
    run_synchronous_test()

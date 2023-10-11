#!/usr/bin/python3

from VBusSpecReader import VbusSpec
from VBusReader import VbusReader, VbusSerialReader, VbusMessage1v0, VbusDatagram2v0, VbusTelegram3v0, VbusTelegram3v1
import serial
import time
import argparse

vbs = None
lang = "EN"

def dev_name(addr, lang = "EN"):
    if vbs is None:
        return "<unknown>"
    
    dev = vbs.get_device(addr)
    if dev is not None:
        return dev.name[lang]

    return "<unknown>"

def on_message(reader, msg):
    print("-----------------")
    print(f"  SRC: 0x{msg.addr_src:04X} - {dev_name(msg.addr_src, lang)}")
    print(f"  DST: 0x{msg.addr_dst:04X} - {dev_name(msg.addr_dst, lang)}")

    print(f"  RAW: ")
    chunklen = 16
    for chunk in range(0, int(len(msg.msg_buff) / chunklen) + 1):
        offset = chunk * chunklen
        print("    " + " ".join(['%02X' % x for x in msg.msg_buff[offset: offset + chunklen]]))

    if msg.checksum_ok == False:
        print("  CHECKSUM NOT OK, SKIPPED")

    if isinstance(msg, VbusMessage1v0):
        print("  Checksum ok")
        print("  VER: v1.0 message")
        print(f"  CMD: 0x{msg.command:04X}")
        print("  Fields:")

        if vbs:
            packet = vbs.get_packet(msg.addr_src, msg.addr_dst, msg.command)
            decoded = packet.decode_message(msg.payload)
            for item in decoded:
                val = item[1]
                if isinstance(item[1], float):
                    val = f"{val:0.2f}"
                print(f"    {item[0].full_id}\t{item[0].name[lang]}\t{val} {item[0].unit.text_text}")
    elif isinstance(msg, VbusDatagram2v0):
        print("  Checksum ok")
        print("  VER: v2.0 Datagram")
        print(f"  CMD: 0x{msg.command_int:04X} - {msg.command.name}")
        print(f"  ID: {msg.id}")
        print(f"  VAL: 0x{msg.value:08X} == {msg.value}")
    elif isinstance(msg, VbusTelegram3v0):
        print("  VER: v3.0 Telegram")
    elif isinstance(msg, VbusTelegram3v1):
        print("  VER: v3.1 Telegram")

def main():
    parser = argparse.ArgumentParser(description="Reads and interpretes VBus data from a serial port")
    parser.add_argument("-p", "--port", required=True, help="serial port")
    parser.add_argument("-b", "--baudrate", required=False, default="9600", help="baud rate")
    parser.add_argument("-v", "--vsf", required=False, default="vbus_specification.vsf", help="VBus specification file, used to decode data")
    parser.add_argument("-l", "--lang", required=False, default="EN", choices=["EN", "DE", "FR"], help="Language for text fields and descriptions")

    args = parser.parse_args()

    global vbs
    global lang

    lang = args.lang

    import os
    if os.path.isfile(args.vsf):
        try:
            vbs = VbusSpec()
            vbs.load_vsf(args.vsf)
        except:
            print("VSF file could not be loaded.")
    else:
        print("VSF file could not be found.")

    serialport = None

    try:
        serialport = serial.Serial(args.port, int(args.baudrate))
    except:
        print("Serial port could not be opened. Is it used by another application?")
        return

    vsr = VbusSerialReader(serialport, on_message)

    while True:
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            vsr.stop()
            serialport.close()
            exit()

if __name__ == "__main__":
    main()

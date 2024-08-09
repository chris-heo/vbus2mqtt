import time
import logging
from enum import Enum
import threading
from typing import Any, Union
import serial
import struct
from VBusSpecReader import VbusPacketField

logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.ERROR)

logger = logging.getLogger(__name__)
logger.level = logging.ERROR

class VbusMessage():
    def __init__(self, start_time, end_time, msg_buff) -> None:
        self.start_time = start_time
        self.end_time = end_time
        self.msg_buff = msg_buff
        
        self.addr_dst = VbusReader.buff_get_dst_addr(msg_buff)
        self.addr_src = VbusReader.buff_get_src_addr(msg_buff)
        self.command = None
        self.checksum_ok = False

    @property
    def full_id(self) -> str:
        return f"00_{self.addr_dst:04X}_{self.addr_src:04X}_??_{self.command:04X}"

class VbusMessageGarbage():
    def __init__(self, start_time, end_time, msg_buff) -> None:
        self.start_time = start_time
        self.end_time = end_time
        self.msg_buff = msg_buff
        #super().__init__(start_time, end_time, msg_buff)

class VbusMessage1v0(VbusMessage):
    HEADER_ID = 0x10
    HEADER_LEN = 10
    FRAME_LEN = 6

    @staticmethod
    def buff_get_cmd(buff) -> int:
        assert len(buff) >= 6
        return (buff[6] << 0) | (buff[7] << 8)
    
    @staticmethod
    def buff_get_payload_frames(buff) -> int:
        assert len(buff) >= 7
        return buff[8]
    
    @staticmethod
    def buff_get_checksum(buff) -> int:
        assert len(buff) >= 8
        return buff[9]

    def __init__(self, start_time, end_time, msg_buff) -> None:
        super().__init__(start_time, end_time, msg_buff)

        # at this stage, the header checksum is alread ok, no need to recalc
        self.command = self.buff_get_cmd(self.msg_buff)

        self.payload = bytearray()
        self.checksum_ok = True
        payload_frames = self.buff_get_payload_frames(self.msg_buff)
        
        for i in range(payload_frames):
            offset = 10 + i * self.FRAME_LEN
            frame_raw = msg_buff[offset : offset + self.FRAME_LEN]
            #frame_rawstr = " ".join([f"{x:02X}" for x in frame_raw])
            #logger.debug(f"frame {i} raw: {frame_rawstr}")

            checksum_frame = frame_raw[-1]
            checksum_calc = VbusReader.calc_checksum(frame_raw[0:-1])
            #logger.debug(f"  checksum frame: 0x{checksum_frame:02X}, calc: 0x{checksum_calc:02X}")

            if checksum_frame != checksum_calc:
                self.checksum_ok = False

            frame_payload = VbusReader.septett_deflate(frame_raw[0:-1])
            #frame_payloadstr = " ".join([f"{x:02X}" for x in frame_payload])
            #logger.debug(f"  frame {i} payload: {frame_payloadstr}")
            self.payload.extend(frame_payload)
        
        logger.debug("payload: {0}".format(" ".join([f"{x:02X}" for x in self.payload])))

    @property
    def full_id(self) -> str:
        return f"00_{self.addr_dst:04X}_{self.addr_src:04X}_10_{self.command:04X}"

    def decode(self, vbus_spec) -> Union[None, tuple[VbusPacketField, Union[int, float]]]:
        if vbus_spec is None:
            return None
        packet = vbus_spec.get_packet(self.addr_src, self.addr_dst, self.command)
        if packet is None:
            return None
        return packet.decode_message(self.payload)

class VbusDatagram2v0Command(Enum):
    MODULE_ANSWER = 0x0100
    WRITE_VALUE_ACKREQ = 0x0200
    READ_VALUE_ACKREQ = 0x0300
    WRITE_VALUE_ACKREQ2 = 0x0400
    BUS_CLEAR_MASTER = 0x0500
    BUS_CLEAR_SLAVE = 0x0600
    UNKNOWN = None

    @classmethod
    def _missing_(cls, value: object) -> Any:
        return cls.UNKNOWN

class VbusDatagram2v0(VbusMessage):
    HEADER_ID = 0x20
    DATAGRAM_LEN = 16

    @staticmethod
    def buff_get_cmd(buff):
        assert len(buff) >= 6
        return (buff[6] << 0) | (buff[7] << 8)

    def __init__(self, start_time, end_time, msg_buff) -> None:
        super().__init__(start_time, end_time, msg_buff)

        assert len(msg_buff) == 16

        #ignore destination, source address protocol version
        _, _, _, self.command_int, self.id, val_sept, checksum_frame = struct.unpack('<xhhBhh5sB', msg_buff)

        self.command = VbusDatagram2v0Command(self.command_int)
        checksum_calc = VbusReader.calc_checksum(msg_buff[1:-1])
        self.checksum_ok = checksum_frame == checksum_calc
        val = VbusReader.septett_deflate(val_sept)
        self.value = 0
        for i, v in enumerate(val):
            self.value |= v << (i * 8)

class VbusTelegram3v0(VbusMessage):
    HEADER_ID = 0x30
    HEADER_LEN = 8
    TELEGRAM_LEN = 9

    def __init__(self, start_time, end_time, msg_buff) -> None:
        super().__init__(start_time, end_time, msg_buff)

class VbusTelegram3v1(VbusMessage):
    HEADER_ID = 0x31
    HEADER_LEN = 0 # FIXME
    TELEGRAM_LEN = 0 # FIXME

    def __init__(self, start_time, end_time, msg_buff) -> None:
        super().__init__(start_time, end_time, msg_buff)

class VbusReader():
    SOF = 0xAA
    BASE_HEADER_LEN = 6

    @staticmethod
    def calc_checksum(data: list) -> int:
        """Calculates the checksum of VBus messages

        Args:
            data (list): Data of which the checksum is calculated

        Returns:
            int: checksum of the provided data
        """
        checksum = 0x7F

        for b in data:
            checksum = (checksum - b) & 0x7F
        
        return checksum
    
    @staticmethod
    def septett_deflate(data: bytearray) -> bytearray:
        """Injects septett bits into the provided array and removes the septett byte

        Args:
            data (bytearray): inflated data including septett byte, limited to 7 payload bytes

        Returns:
            bytearray: deflated data
        """
        assert len(data) <= 8
        result = data[0:-1]
        septett = data[-1]

        for i in range(len(result)):
            if septett & 1:
                result[i] |= 0x80
            septett >>= 1
        return result
    
    @staticmethod
    def septett_inflate(data: bytearray) -> bytearray:
        """Extracts septett bits from the provided array and masks the bits as well as appends the septett byte

        Args:
            data (bytearray): deflated data which the septett byte is calculated from, limited to 7 payload bytes

        Returns:
            bytearray: inflated data
        """
        assert len(data) <= 7
        septett = 0

        for i in range(len(data)):
            if data[i] & 0x80:
                septett |= (1 << i)
            data[i] &= 0x7F
        
        data.append(septett)
        return data

    def __init__(self, on_message=None) -> None:
        self.msg_start = None
        self.msg_protver = None
        self.msg_buff = bytearray()
        self.msg_bytes_to_receive = 0
        self.receiving:bool = False

        self.on_message = on_message

    def msg_received(self, msg):
        if callable(self.on_message):
            try:
                self.on_message(self, msg)
            except:
                import traceback
                traceback.print_exc()

    @staticmethod
    def buff_get_dst_addr(buff: bytearray) -> int:
        return (buff[1] << 0) | (buff[2] << 8)
    
    @staticmethod
    def buff_get_src_addr(buff: bytearray) -> int:
        return (buff[3] << 0) | (buff[4] << 8)

    @staticmethod
    def buff_get_prot_ver(buff: bytearray) -> int:
        return buff[5]

    def _wait_next_message(self: bytearray) -> None:
        self.msg_buff = bytearray()
        self.receiving = False

    def write_bytes(self, data: bytearray):
        for byte in data:
            self.write_byte(byte)

    def write_byte(self, byte: int) -> VbusMessage:
        retval = None
        if not self.msg_start:
            self.msg_start = time.time()

        if byte == self.SOF:
            if len(self.msg_buff) > 0:
                # when the buffer is filled but the message was not finished,
                # automatically treat it as garbage
                retval = VbusMessageGarbage(self.msg_start, time.time(), self.msg_buff)
                #self.msg_received(retval)
            
            logger.debug("Got Sync")
            self.msg_start = time.time()
            self.msg_buff = bytearray()
            self.msg_buff.append(byte)

            self.receiving = True
        elif byte > 0x7F:
            self.msg_buff.append(byte)
            self.receiving = False
            retval = VbusMessageGarbage(self.msg_start, time.time(), self.msg_buff)
            #self.msg_received(retval)
            self.msg_buff = bytearray()

        elif self.receiving == True:
            self.msg_buff.append(byte)
            #logger.debug(f"got byte: 0x{byte:02X}, buffer length: {len(self.msg_buff)}")

            if len(self.msg_buff) == self.BASE_HEADER_LEN:
                logger.debug("Base header received: {0}".format(" ".join(f"{x:02X}" for x in self.msg_buff)))
                dst_addr = self.buff_get_dst_addr(self.msg_buff)
                src_addr = self.buff_get_src_addr(self.msg_buff)
                self.msg_protver = self.buff_get_prot_ver(self.msg_buff)

                logger.debug(f" -> 0x{src_addr:04X} => 0x{dst_addr:04X} Protocol version {self.msg_protver:02X}")
            
            if self.msg_protver == VbusMessage1v0.HEADER_ID:
                if len(self.msg_buff) == VbusMessage1v0.HEADER_LEN:
                    cmd = VbusMessage1v0.buff_get_cmd(self.msg_buff)
                    payload_frames = VbusMessage1v0.buff_get_payload_frames(self.msg_buff)
                    checksum_msg = VbusMessage1v0.buff_get_checksum(self.msg_buff)
                    checksum_calc = self.calc_checksum(self.msg_buff[1:-1])

                    logger.debug(f" -> v1.0 header complete, cmd: 0x{cmd:04X}, {payload_frames} frames, " +
                                f"msg checksum: 0x{checksum_msg:02X}, calc checksum: 0x{checksum_calc:02X}")
                    
                    if checksum_msg != checksum_calc:
                        logger.warning("checksum error")
                        self.receiving = False
                    else:
                        self.msg_bytes_to_receive = VbusMessage1v0.HEADER_LEN + payload_frames * VbusMessage1v0.FRAME_LEN
                elif len(self.msg_buff) == self.msg_bytes_to_receive:
                    logger.debug("All bytes for v1.0 packet received.")
                    retval = VbusMessage1v0(self.msg_start, time.time(), self.msg_buff)
                    #self.msg_received(retval)
                    self._wait_next_message()
            
            elif self.msg_protver == VbusDatagram2v0.HEADER_ID and len(self.msg_buff) == VbusDatagram2v0.DATAGRAM_LEN:
                logger.debug("All bytes for v2.0 datagram received. Processing anyone?")
                retval = VbusDatagram2v0(self.msg_start, time.time(), self.msg_buff)
                #self.msg_received(retval)
                self._wait_next_message()

            
            elif self.msg_protver == VbusTelegram3v0.HEADER_ID:
                if len(self.msg_buff) == self.BASE_HEADER_LEN + VbusTelegram3v0.HEADER_LEN + VbusTelegram3v0.TELEGRAM_LEN:
                    logger.debug("All bytes for v3.0 telegram received. Processing anyone?")
                    retval = VbusTelegram3v0(self.msg_start, time.time(), self.msg_buff)
                    #self.msg_received(retval)
                    self._wait_next_message()

            elif self.msg_protver == VbusTelegram3v1.HEADER_ID:
                if len(self.msg_buff) == self.BASE_HEADER_LEN + VbusTelegram3v1.HEADER_LEN + VbusTelegram3v1.TELEGRAM_LEN: #FIXME
                    logger.debug("All bytes for v3.0 telegram received. Processing anyone?")
                    retval = VbusTelegram3v1(self.msg_start, time.time(), self.msg_buff)
                    #self.msg_received(retval)
                    self._wait_next_message()

        if retval is not None:
            self.msg_received(retval)

        return retval


class VbusSerialReader(VbusReader):
    def __init__(self, serialport, on_message = None) -> None:
        super().__init__(on_message)
        
        self.ser = serialport
        self.ser.timeout = 5
        self.readerrunning = True
        self.thread_serial = threading.Thread(target=self.serialreader_run, args=())
        self.thread_serial.daemon = True
        self.thread_serial.start()

    def serialreader_run(self) -> None:
        """
            receiver thread
        """
        #logger.debug("Reader started")
        print("Reader started")

        while True:
            if not self.readerrunning:
                #logger.debug("Reader stopped")
                print("Reader stopped")
                return
            
            if not self.ser.is_open:
                print("Serial port got closed. Try to re-open it (after a short delay)")
                time.sleep(1)
                try:
                    self.ser.open()
                except:
                    print("Could not re-open serial port.")
                    self.readerrunning = False
                    return

            bytes = []
            try:
                bytes = self.ser.read()
            except:
                pass

            self.write_bytes(bytes)

    def stop(self) -> None:
        """stops the reader"""
        #logger.debug("Reader stop requested")
        self.readerrunning = False
        self.ser.close()


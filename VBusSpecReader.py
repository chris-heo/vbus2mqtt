import logging
from enum import Enum
import math
from typing import Optional, Union

logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.DEBUG)

logger = logging.getLogger(__name__)

class VbusFieldType(Enum):
    Number = 1 # e.g. 133.7
    Reserved = 2 # reserved for later use
    Time = 3 # e.g. 13:37
    WeekTime = 4 # e.g. Wed,13:37
    DateTime = 5 # Oct 23 13:37:54 2016

class _VbusTableRef:
    def __init__(self, base) -> None:
        self.count = base._read_i32()
        self.table_offset = base._read_i32()

class _VbusSpecBlock:
    def __init__(self, parent) -> None:
        self.parent = parent
        self.datecode = parent._read_i32()
        self.text_ref = _VbusTableRef(parent)
        self.localized_text_ref = _VbusTableRef(parent)
        self.unit_ref = _VbusTableRef(parent)
        self.device_template_ref = _VbusTableRef(parent)
        self.packet_template_ref = _VbusTableRef(parent)

class VbusLocalizedText:
    DATA_LEN = (4 * 3)

    def __init__(self, parent) -> None:
        self.parent = parent
        self.indices = {
            "EN" : parent._read_i32(),
            "DE" : parent._read_i32(),
            "FR" : parent._read_i32(),
        } 

    def __getitem__(self, lang) -> str:
        lang = lang.upper()
        if lang in self.indices:
            return self.parent.texts[self.indices[lang]]
        return None

    @property
    def translations(self) -> dict:
        retval = {}
        for lang in self.indices:
            retval[lang] = self.parent.texts[self.indices[lang]]
        return retval
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__module__}.{self.__class__.__qualname__} " + \
            f"en=\"{self['EN']}\" de=\"{self['DE']}\" fr=\"{self['FR']}\">"

class VbusUnit:
    DATA_LEN = (4 * 4)

    def __init__(self, parent) -> None:
        self.parent = parent
        self.id = parent._read_i32()
        self.family_id = parent._read_i32()
        self.code_index = parent._read_i32()
        self.text_index = parent._read_i32()

    @property
    def code_text(self) -> str:
        return self.parent.texts[self.code_index]

    @property
    def text_text(self) -> str:
        return self.parent.texts[self.text_index]
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__module__}.{self.__class__.__qualname__} " + \
            f"id={self.id} family_id={self.family_id} code=\"{self.code_text}\" text=\"{self.text_text}\">"

class VbusDeviceTemplate:
    DATA_LEN = (4 * 2 + 4)

    def __init__(self, parent) -> None:
        self.parent = parent
        self.self_address = parent._read_u16()
        self.self_mask = parent._read_u16()
        self.peer_address = parent._read_u16()
        self.peer_mask = parent._read_u16()
        self.locname_index = parent._read_i32()

    @property
    def name(self) -> VbusLocalizedText:
        return self.parent.text_loc[self.locname_index]
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__module__}.{self.__class__.__qualname__} " + \
            f"self_address=0x{self.self_address:04X} self_mask=0x{self.self_mask:04X} " + \
            f"peer_address=0x{self.peer_address:04X} peer_mask=0x{self.peer_mask:04X} name={self.name}>"

class VbusPacketTemplate:
    DATA_LEN = (6 * 2 + 2 * 4)

    def __init__(self, parent) -> None:
        self.parent = parent
        self.destination_address = parent._read_u16()
        self.destination_mask = parent._read_u16()
        self.source_address = parent._read_u16()
        self.source_mask = parent._read_u16()
        self.command = parent._read_u16()
        self._reserved = parent._read_u16()
        
        self.field_ref = _VbusTableRef(parent)
        self.fields = []

        #logger.debug(f"PacketTemplate dst_addr=0x{self.destination_address:04X} src_addr=0x{self.source_address:04X} cmd={self.command}")
        #logger.debug(f"reading field table for template {self}")
        for i in range(0, self.field_ref.count):
            offset2 = self.field_ref.table_offset + i * VbusPacketField.DATA_LEN
            self.parent.file.seek(offset2)
            self.fields.append(VbusPacketField(self))
    
    @property
    def packet_id(self) -> str:
        return f"00_{self.destination_address:04X}_{self.source_address:04X}_10_{self.command:04X}"
        #        ^^ headerOrChannel                                          ^^ just a fixed number?
        # I have no clue where the magic 00 and 10 are coming from

    @property
    def destination_device(self) -> VbusDeviceTemplate:
        return self.parent.get_device(self.destination_address, self.source_address)

    @property
    def source_device(self) -> VbusDeviceTemplate:
        return self.parent.get_device(self.source_address) # not sure destination address should be added here

    def __repr__(self) -> str:
        return f"<{self.__class__.__module__}.{self.__class__.__qualname__} " + \
            f"dst_address=0x{self.destination_address:04X} dst_mask=0x{self.destination_mask:04X} " + \
            f"src_address=0x{self.source_address:04X} src_mask=0x{self.source_mask:04X} cmd=0x{self.command:04X}>"

    def decode_message(self, data: bytearray) -> tuple["VbusPacketField", Union[int, float]]:
        result = []
        for field in self.fields:
            result.append((field, field.decode_message(data)))
        return result

class VbusPacketField:
    DATA_LEN = (4 * 7)

    def __init__(self, parent) -> None:
        self.parent = parent
        self.base = parent.parent

        self.id_text_index = self.base._read_i32()
        self.name_loc_index = self.base._read_i32()
        self.unit_id = self.base._read_i32()
        self.precision = self.base._read_i32()
        self.type_id = VbusFieldType(self.base._read_i32()) #TODO: create enum
        
        self.part_ref = _VbusTableRef(self.base)

        self.parts = []

        #logger.debug(f"  VbusPacketField: id_text={self.id_text} name={self.name} unit={self.unit} precision={self.precision} type_id={self.type_id}")
        #logger.debug(f"  reading part table for field {self} - {self.part_ref.count} item(s)")
        for i in range(0, self.part_ref.count):
            offset2 = self.part_ref.table_offset + i * VbusPacketFieldPart.DATA_LEN
            self.base.file.seek(offset2)
            self.parts.append(VbusPacketFieldPart(self))

    @property
    def full_id(self) -> str:
        return f"{self.parent.packet_id}_{self.id_text}"

    @property
    def id_text(self) -> str:
        return self.base.texts[self.id_text_index]
    
    @property
    def name(self) -> VbusLocalizedText:
        return self.base.text_loc[self.name_loc_index]
    
    @property
    def unit(self) -> VbusUnit:
        return self.base.get_unit_by_id(self.unit_id)
    
    def decode_message(self, data: bytearray) -> Union[int, float]:
        result = 0
        for part in self.parts:
            result += part.decode_message(data)
        
        if(self.precision != 0):
            result = float(result) * math.pow(10, -self.precision)

        return result

class VbusPacketFieldPart:
    DATA_LEN = (4 + 4 * 1 + 8)

    def __init__(self, parent) -> None:
        self.parent = parent
        self.base = parent.base

        self.offset = self.base._read_i32()
        self.bit_pos = self.base._read_u8()
        self.mask = self.base._read_u8()
        self.is_signed = self.base._read_u8()
        self._reserved = self.base._read_u8()
        self.factor = self.base._read_i64()

        #logger.debug(f"      offset=0x{self.offset:04X} bit_pos={self.bit_pos} mask=0x{self.mask:02X} is_signed={self.is_signed} factor={self.factor}")

    def decode_message(self, data: bytearray) -> int:
        result = data[self.offset] & self.mask
        result = result >> self.bit_pos
        result = int.from_bytes([result], "little", signed=(self.is_signed == 1))
        result = result * self.factor
        return result

class VbusSpec:
    def __init__(self) -> None:
        self.file = None
        self.specblock = None #_VbusSpecBlock()
        self.texts = []
        self.text_loc = []
        self.units = []
        self.device_templates = []

    def load_vsf(self, filename: str) -> None:
        self.file = open(filename, "rb")
        self._read_header()
        self._read_texts()
        self._read_localized_texts()
        self._read_units()
        self._read_device_template()
        self._read_packet_template()

    def _read_u8(self) -> int:
        data = self.file.read(1)
        return int.from_bytes(data, "little", signed=False)

    def _read_u16(self) -> int:
        data = self.file.read(2)
        return int.from_bytes(data, "little", signed=False)
    
    def _read_i32(self) -> int:
        data = self.file.read(4)
        return int.from_bytes(data, "little", signed=True)
            
    def _read_i64(self) -> int:
        data = self.file.read(8)
        return int.from_bytes(data, "little", signed=True)
    
    def _read_utf8(self) -> str:
        buff = bytearray()
        while True:
            tmp = self.file.read(16)
            pos = tmp.find(0)
            if pos > -1:
                tmp = tmp[0:pos]
            buff.extend(tmp)

            if pos != -1:
                return buff.decode("utf-8")

    def _read_header(self) -> None:
        self.checksum_a = self._read_u16()
        self.checksum_b = self._read_u16()
        #logger.debug(f"checksumA: 0x{self.checksum_a:04X}, checksumB: 0x{self.checksum_b:04X}")
        if self.checksum_a != self.checksum_b:
            raise Exception("ChecksumA and ChecksumB don't match.")
        
        self.total_length = self._read_i32()
        #logger.debug(f"total data length: {self.total_length}")

        #TODO: implement file checksum check
        
        self.data_version = self._read_i32()
        #logger.debug(f"data version: {self.data_version}")
        if self.data_version != 1:
            raise Exception("There should be no other data version than 1")
        
        self.spec_offset = self._read_i32()
        #logger.debug(f"spec offset: 0x{self.spec_offset:08X}")

        self.file.seek(self.spec_offset)
        self.specblock = _VbusSpecBlock(self)

    def _read_texts(self) -> None:
        offset = self.specblock.text_ref.table_offset
        #logger.debug(f"*** Textblock @ 0x{offset:08X}")
        self.texts = []
        #logger.debug(f"reading {self.specblock.text_ref.count} text(s)")
        for i in range(0, self.specblock.text_ref.count):
            self.file.seek(offset + i * 4)
            text_addr = self._read_i32()
            self.file.seek(text_addr)
            text = self._read_utf8()
            self.texts.append(text)
            ##logger.debug(f"Text #{i:04g} @ 0x{text_addr:08X}: \"{text}\"")

    def _read_localized_texts(self) -> None:
        offset = self.specblock.localized_text_ref.table_offset
        #logger.debug(f"*** Loc_Textblock @ 0x{offset:08X}")
        self.text_loc = []

        self.file.seek(offset)
        #logger.debug(f"reading {self.specblock.text_ref.count} translation(s)")
        for i in range(0, self.specblock.localized_text_ref.count):
            offset2 = offset + i * VbusLocalizedText.DATA_LEN
            self.file.seek(offset2)
            self.text_loc.append(VbusLocalizedText(self))

    def _read_units(self) -> None:
        offset = self.specblock.unit_ref.table_offset
        #logger.debug(f"*** Units @ 0x{offset:08X}")
        self.units = []

        self.file.seek(offset)
        #logger.debug(f"reading {self.specblock.unit_ref.count} unit(s)")
        for i in range(0, self.specblock.unit_ref.count):
            offset2 = offset + i * VbusUnit.DATA_LEN
            self.file.seek(offset2)
            self.units.append(VbusUnit(self))

    def _read_device_template(self) -> None:
        offset = self.specblock.device_template_ref.table_offset
        #logger.debug(f"*** Device templates @ 0x{offset:08X}")
        self.device_templates = []

        self.file.seek(offset)
        #logger.debug(f"reading {self.specblock.device_template_ref.count} device template(s)")
        for i in range(0, self.specblock.device_template_ref.count):
            offset2 = offset + i * VbusDeviceTemplate.DATA_LEN
            self.file.seek(offset2)
            self.device_templates.append(VbusDeviceTemplate(self))

    def _read_packet_template(self) -> None:
        offset = self.specblock.packet_template_ref.table_offset
        self.packet_templates = []

        self.file.seek(offset)
        #logger.debug(f"reading {self.specblock.packet_template_ref.count} packet template(s)")
        for i in range(0, self.specblock.packet_template_ref.count):
            offset2 = offset + i * VbusPacketTemplate.DATA_LEN
            self.file.seek(offset2)
            self.packet_templates.append(VbusPacketTemplate(self))

    def get_unit_by_id(self, id: int) -> Optional[VbusUnit]:
        for unit in self.units:
            if unit.id == id:
                return unit
        return None
    
    def get_packet(self, source_address: int, destination_address: int, command: int = None) -> Optional[VbusPacketTemplate]:
        for packet in self.packet_templates:
            if packet.source_address == (source_address & packet.source_mask) and \
                packet.destination_address == (destination_address & packet.destination_mask) and \
                (command is None or packet.command == command):
                return packet
        return None
    
    def get_packet_by_id(self, packet_id) -> Optional[VbusPacketTemplate]:
        for packet in self.packet_templates:
            if packet.packet_id == packet_id:
                return packet
        return None
    
    def get_field_by_id(self, field_id) -> Optional[VbusPacketField]:
        packet = self.get_packet_by_id(field_id[0:20])
        short_id = field_id[21:]
        if packet:
            for field in packet.fields:
                if field.id_text == short_id:
                    return field
        else:
            # for the mere unlikelyhood that we got a field id that isn't hierarchical to the packet, 
            # let's search it the slow way...
            for packet in self.packet_templates:
                for field in packet.fields:
                    if field.full_id == field_id:
                        return field
        return None

    def get_device(self, self_address: int, peer_address: int = None) -> Optional[VbusDeviceTemplate]:
        for dev in self.device_templates:
            if dev.self_address == (self_address & dev.self_mask) and \
                (peer_address is None or dev.peer_address == (peer_address & dev.peer_mask)):
                return dev

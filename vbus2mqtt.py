#!/usr/bin/python3

import time
from datetime import datetime
import os
import paho.mqtt.client as mqtt
import json5 as json
import serial
from VBusSpecReader import VbusFieldType, VbusSpec
from VBusReader import VbusSerialReader, VbusMessage1v0, VbusMessageGarbage
from MqttDispatcher import MqttDispatcher

def dt_to_iso8601(timestamp: datetime):
    if timestamp is None:
        return None
    return timestamp.replace(microsecond=0).astimezone().isoformat()

class Vbus2Mqtt():
    def __init__(self, config) -> None:
        self.config = config
        #TODO: check config

        self.stats_startup = time.time()
        self.stats_rxmsg_cnt = 0
        self.stats_rxmsg_last = None
        self.stats_rxerr_cnt = 0
        self.stats_rxerr_last = None
        self.vbus_spec = None

        if self.load_vsf() == False:
            raise Exception("Could not load VSF file and therefore initialize VBus")

        self.init_mqtt()
        self.init_vbus()

        self.dispatcher = MqttDispatcher(self.mqtt_client, config["plugins"], config["transfers"], self.mqtt_topic_prefix)

        self.dispatcher.metafields.update({
            "sw:uptime" : lambda target: round(time.time() - self.stats_startup),
            "comm:rxmsg_cnt" : lambda target: self.stats_rxmsg_cnt,
            "comm:rxmsg_last" : lambda target: dt_to_iso8601(self.stats_rxmsg_last),
            "comm:rxerr_cnt" : lambda target: self.stats_rxerr_cnt,
            "comm:rxerr_last" : lambda target: dt_to_iso8601(self.stats_rxerr_last),
        })

    def init_mqtt(self):
        cfg_mqtt = config["mqtt"]
        self.mqtt_topic_prefix = cfg_mqtt["topic_prefix"] # shortcut, I'm lazy

        self.mqtt_client = mqtt.Client()
        self.mqtt_client.on_connect = self.mqtt_connect

        if "last_will" in cfg_mqtt:
            lw = cfg_mqtt["last_will"]
            self.mqtt_client.will_set(f"{self.mqtt_topic_prefix}{lw['topic']}", payload = lw["offline"], qos = 0, retain = True)

        self.mqtt_client.username_pw_set(cfg_mqtt["user"], cfg_mqtt["pass"])
        self.mqtt_client.connect(cfg_mqtt["host"], cfg_mqtt["port"], 60)
        self.mqtt_client.loop_start()

    def load_vsf(self) -> bool:
        cfg_vbus = self.config["vbus"]
        self.vbus_spec = None
        if os.path.isfile(cfg_vbus["vsf"]):
            try:
                self.vbus_spec = VbusSpec()
                self.vbus_spec.load_vsf(cfg_vbus["vsf"])
            except:
                print("VSF file could not be loaded.")
                return False
        else:
            print("VSF file could not be found.")
            return False
        return True

    def init_vbus(self) -> None:
        cfg_vbus = self.config["vbus"]

        self.vbus_ser = None

        try:
            self.vbus_ser = serial.Serial(cfg_vbus["serialport"], int(cfg_vbus["baudrate"]))
        except:
            print("Serial port could not be opened. Is it used by another application?")
        
        if self.vbus_ser is not None:
            self.vbus_reader = VbusSerialReader(self.vbus_ser, self.vbus_on_message)
        
    def vbus_on_message(self, reader, msg):
        if isinstance(msg, VbusMessageGarbage) or msg.checksum_ok == False:
            self.stats_rxerr_cnt += 1
            self.stats_rxerr_last = datetime.now()
        elif isinstance(msg, VbusMessage1v0):
            self.stats_rxmsg_last = datetime.now()
            self.stats_rxmsg_cnt += 1
            
            decoded = msg.decode(self.vbus_spec)
            data = {}
            for item in decoded:
                fid = item[0].full_id
                value = item[1]

                # round values to not be ridiculous
                if item[0].type_id == VbusFieldType.Number:
                    value = round(item[1], item[0].precision)

                data[fid] = value
            self.dispatcher.update_fields(data, datetime.now())

    def tick(self) -> float:
        return self.dispatcher.tick()

    def mqtt_connect(self, client, userdata, flags, rc):
        cfg_mqtt = self.config["mqtt"]
        print("MQTT connected, config:", cfg_mqtt)
        if "last_will" in cfg_mqtt:
            print("setting last will (online)")
            lw = cfg_mqtt["last_will"]
            client.publish(f"{self.mqtt_topic_prefix}{lw['topic']}", payload = lw["online"], qos = 0, retain = True)


with open('vbus2mqtt.json') as f:
    config = json.load(f)

ctrl = Vbus2Mqtt(config)


while True:
    next = ctrl.tick()
    sleeptime = next - time.time()
    if sleeptime > 0:
        time.sleep(sleeptime)
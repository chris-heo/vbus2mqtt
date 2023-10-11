from typing import Union
import json
import gc
import os
import sys
import time
from datetime import datetime
from JsonHelper import *
import importlib

def dt_to_iso8601(timestamp: datetime):
    if timestamp is None:
        return None
    return timestamp.replace(microsecond=0).astimezone().isoformat()

class MqttDispatcherField:
    def __init__(self, value = None, timestamp: datetime = None) -> None:
        self.value = value
        self.timestamp = timestamp
        self.updated = True
        self.changed = True
        self.transfers = [] # transfers the field is being used in

    def update(self, value, timestamp: datetime = None) -> bool:
        """Updates the field with a newer value

        Args:
            value (Any): New value of the field
            timestamp (datetime, optional): Timestamp of the new value. Defaults to None.

        Returns:
            bool: True, if the value has changed
        """
        self.updated = True
        self.timestamp = timestamp

        if self.value != value:
            self.changed = True
            self.value = value
            return True
        return False

class MqttDispatcherPlugin:
    def __init__(self, dispatcher: "MqttDispatcher", cfg_plugin: dict) -> None:
        self.dispatcher = dispatcher
        self.name = json_get_or_fail(cfg_plugin, "name")

        module_name, module_classname = json_get_or_fail(cfg_plugin, "module").split(":")

        module = importlib.import_module(module_name)
        cls = getattr(module, module_classname)

        plugin_cfg = json_get_or_default(cfg_plugin, "config", None)
        self.plugin_obj = cls(self, plugin_cfg)

    def tick(self):
        return self.plugin_obj.tick()

class MqttDispatcher:
    def __init__(self, mqtt_client, plugin_cfgs = None, transfer_cfgs = None, mqtt_topic_prefix="") -> None:
        self.mqtt_client = mqtt_client
        self.mqtt_topic_prefix = mqtt_topic_prefix
        self.plugins = {}
        self.fields = {}

        self.metafields = {
            "sw:ramuse" : lambda self: sum(sys.getsizeof(i) for i in gc.get_objects()),
            "sw:pid" : lambda that: os.getpid(),
            "time:now": lambda self: dt_to_iso8601(datetime.now()),
        }

        for plugin_cfg in plugin_cfgs:
            plugin_name = json_get_or_fail(plugin_cfg, "name")
            self.plugins[plugin_name] = MqttDispatcherPlugin(self, plugin_cfg)

        self.transfers = []

        if transfer_cfgs is not None:
            for transfer_cfg in transfer_cfgs:
                transfer = Transfer.construct(self, transfer_cfg)
                self.transfers.append(transfer)
                subs = transfer.get_field_subscriptions({}) #WAT?

                for sub in subs:
                    if sub in self.fields:
                        field = self.fields[sub]
                    else:
                        field = MqttDispatcherField()
                        self.fields[sub] = field

                    if transfer not in field.transfers:
                        field.transfers.append(transfer)

    def update_fields(self, val_dict: dict, timestamp: datetime) -> None:
        transfers_updated = []
        transfers_changed = []
        fields_changed = []

        for key in val_dict:
            value = val_dict[key]
            if key not in self.fields:
                continue
            field = self.fields[key]
            changed = False
            if key in self.fields:
                if field.update(value, timestamp) is True:
                    changed = True
            else:
                field = MqttDispatcherField(value, timestamp)

            fields_changed.append(key)

            for transfer in field.transfers:
                if not transfer in transfers_updated:
                    transfers_updated.append(transfer)
                    if changed is True:
                        if not transfer in transfers_changed:
                            transfers_changed.append(transfer)

        for transfer in transfers_updated:
            transfer.updated(fields_changed, timestamp)

        for transfer in transfers_changed:
            transfer.changed(fields_changed, timestamp)


        for key in self.fields:
            # reset updated and changed flags
            self.fields[key].updated = False
            self.fields[key].changed = False

    def get_metafield(self, meta_name, target):
        if meta_name in self.metafields:
            return self.metafields[meta_name](target)
        return f"unknown meta field '{meta_name}'"

    def get_field(self, fieldname):
        if fieldname in self.fields:
            return self.fields[fieldname]
        return None

    def get_field_value(self, fieldname: str, max_age: float = None):
        if fieldname in self.fields:
            field = self.fields[fieldname]
            if max_age is None:
                return field.value
            else:
                age = datetime.now() - field.timestamp
                if age.total_seconds() <= max_age:
                    return field.value
                else: 
                    return None
            
        return None

    def tick(self) -> float:
        next_time = None
        for plugin_name in self.plugins:
            plugin = self.plugins[plugin_name]
            plugin_next = plugin.tick()
            if plugin_next is not None:
                if next_time is None:
                    next_time = plugin_next
                elif plugin_next < next_time:
                    next_time = plugin_next

        for transfer in self.transfers:
            transfer_next = transfer.tick()
            if transfer_next is not None:
                if next_time is None:
                    next_time = transfer_next
                elif transfer_next < next_time:
                    next_time = transfer_next
        return next_time

class TransferTrigger:
    @staticmethod
    def construct(transfer, cfg_trigger) -> "TransferTrigger":
        trig_type = json_get_or_fail(cfg_trigger, "type")
        if trig_type == "update":
            return TransferTriggerUpdate(transfer, cfg_trigger)
        if trig_type == "interval":
            return TransferTriggerInterval(transfer, cfg_trigger)

    def __init__(self, transfer, cfg_trigger) -> None:
        self.transfer = transfer
        # do nothing with cfg_trigger (for now)

class TransferTriggerUpdate(TransferTrigger):
    def __init__(self, transfer, cfg_trigger) -> None:
        super().__init__(transfer, cfg_trigger)

        self.sensor = json_get_or_default(cfg_trigger, "item", None)

    def updated(self, fields, timestamp) -> bool:
        if self.sensor is not None:
            if self.sensor in fields:
                self.transfer.transmit()
                return True
        else:
            self.transfer.transmit()
            return True

        return False

    def changed(self, fields, timestamp) -> bool:
        return False

    def tick(self) -> Union[None, float]:
        return None

class TransferTriggerInterval(TransferTrigger):
    def __init__(self, transfer, cfg_trigger) -> None:
        super().__init__(transfer, cfg_trigger)

        self.interval = json_get_or_fail(cfg_trigger, "interval")
        self.max_age = json_get_or_default(cfg_trigger, "max_age", None)

        self.next_transfer = time.time()

    def updated(self, fields, timestamp) -> bool:
        return False

    def changed(self, fields, timestamp) -> bool:
        return False

    def tick(self) -> Union[None, float]:
        now = time.time()
        #TODO: also consider ticks from plugins
        if now >= self.next_transfer:

            self.transfer.transmit()

            self.next_transfer += self.interval

            # if, for some reason, the next transfer is lagging, reschedule the next transfer
            now = time.time()
            if self.next_transfer <= now:
                self.next_transfer = now + self.interval

        return self.next_transfer

class Transfer:
    @staticmethod
    def construct(dispatcher, config) -> "Transfer":

        type = json_get_or_fail(config, "type")
        cls = None
        if type == "direct":
            cls = TransferDirect
        elif type == "json":
            cls = TransferJson
        else:
            raise Exception("unknown type for transfer configuration")

        return cls(dispatcher, config)

    @classmethod
    def _cfg_get_fields(cls, transfer, parent, cfg_fields):
        retval = []

        for field in cfg_fields:
            item = None
            item = cls._cfg_get_field(transfer, parent, field)

            if item is not None:
                retval.append(item)

        return retval

    @classmethod
    def _cfg_get_field(cls, transfer, parent, field):
        if "group" in field:
            item = TransferGroup(transfer, parent, field)
        elif "item" in field:
            item = TransferValueitem(transfer, parent, field)
        elif "meta" in field:
            item = TransferMetaitem(transfer, parent, field)
        elif "plugin" in field:
            item = TransferPluginitem(transfer, parent, field)

        return item

    def __init__(self, dispatcher, config) -> None:
        self.dispatcher = dispatcher
        self.config = config

        self.metafields = {
            # nothing at all
        }

        self.mqtt_topic = json_get_or_fail(config["mqtt"], "topic", "mqtt")
        self.mqtt_retain = json_get_or_default(config["mqtt"], "retain", False)
        self.mqtt_qos = json_get_or_default(config["mqtt"], "qos", 0)

        self.trigger = TransferTrigger.construct(self, json_get_or_fail(config, "trigger"))

    def get_metafield(self, meta_name, target):
        if meta_name in self.metafields:
            return self.meta_fields[meta_name](target)

        return self.dispatcher.get_metafield(meta_name, target)

    def updated(self, fields, timestamp):
        #print(f"transfer {self.mqtt_topic} got an update")
        return self.trigger.updated(fields, timestamp)

    def changed(self, fields, timestamp):
        #print(f"transfer {self.mqtt_topic} got a change")
        return self.trigger.changed(fields, timestamp)

    def tick(self):
        return self.trigger.tick()

    def transmit(self):
        #print("transmit", self.mqtt_topic, ": ", self.get_content())
        topic = f"{self.dispatcher.mqtt_topic_prefix}{self.mqtt_topic}"
        content = self.get_content()
        #print(content)
        if isinstance(content, dict):
            content = json.dumps(content)
        self.dispatcher.mqtt_client.publish(topic, content, qos = self.mqtt_qos, retain = self.mqtt_retain)

class TransferDirect(Transfer):
    def __init__(self, dispatcher, config) -> None:
        super().__init__(dispatcher, config)

        cfg_field = json_get_or_fail(config, "field")
        self.field = self._cfg_get_field(self, self, cfg_field)

    def get_content(self) -> None:
        return self.field.get_content()

    def get_field_subscriptions(self, retval = {}):
        retval = self.field.get_field_subscriptions(retval)
        return retval

class TransferJson(Transfer):
    def __init__(self, dispatcher, config) -> None:
        super().__init__(dispatcher, config)

        cfg_fields = json_get_or_fail(config, "fields")
        self.fields = self._cfg_get_fields(self, self, cfg_fields)

    def get_content(self) -> None:
        retval = {}
        for field in self.fields:
            retval |= { field.name : field.get_content() }

        return retval

    def get_field_subscriptions(self, retval = {}):
        for field in self.fields:
            retval = field.get_field_subscriptions(retval)
        return retval

class _TransferItem:
    def __init__(self, transfer, parent, config) -> None:
        self.transfer = transfer
        self.parent = parent

class TransferGroup(_TransferItem):
    def __init__(self, transfer, parent, config) -> None:
        super().__init__(transfer, parent, config)

        self.name = json_get_or_fail(config, "group")

        cfg_fields = json_get_or_fail(config, "fields")
        self.fields = TransferJson._cfg_get_fields(transfer, parent, cfg_fields)

    def get_content(self):
        field_contents = {}
        for field in self.fields:
            field_contents |= { field.name : field.get_content() }
        return field_contents

    def get_field_subscriptions(self, retval = {}):
        for field in self.fields:
            retval = field.get_field_subscriptions(retval)
        return retval

class TransferValueitem(_TransferItem):
    def __init__(self, transfer, parent, config) -> None:
        super().__init__(transfer, parent, config)

        self.name = json_get_or_fail(config, "name")
        self.item = json_get_or_fail(config, "item")
        self.max_age = json_get_or_default(config, "max_age")

    def get_content(self):
        return self.transfer.dispatcher.get_field_value(self.item, self.max_age)

    def get_field_subscriptions(self, retval = {}):
        if self.item in retval:
            retval[self.item].append(self)
        else:
            retval[self.item] = [ self ]

        return retval

class TransferMetaitem(_TransferItem):
    def __init__(self, transfer, parent, config) -> None:
        super().__init__(transfer, parent, config)

        self.name = config["name"]
        self.meta_name = config["meta"]

        #if self.meta_name not in self.metafields:
        #    raise Exception(f"meta item '{self.meta_name}' is unknown")

    def get_content(self):
        #return f"meta field '{self.meta_name}' data"
        return self.transfer.get_metafield(self.meta_name, self)

    def get_field_subscriptions(self, retval = {}):
        return retval

class TransferPluginitem(_TransferItem):
    def __init__(self, transfer, parent, config) -> None:
        super().__init__(transfer, parent, config)

        self.name = json_get_or_fail(config, "name")
        self.plugin_name = json_get_or_fail(config, "plugin")

        if self.plugin_name not in transfer.dispatcher.plugins:
            raise Exception(f"plugin '{self.plugin_name}' not found")

        self.plugin = transfer.dispatcher.plugins[self.plugin_name]

        func_name = "plugin_" + json_get_or_fail(config, "function")
        self.plugin_function = getattr(self.plugin.plugin_obj, func_name)

        if not callable(self.plugin_function):
            raise Exception(f"method '{func_name}' of plugin '{self.plugin_name}' is not callable")

    def get_content(self):
        return self.plugin_function()

    def get_field_subscriptions(self, retval = {}):
        for valref in self.plugin.plugin_obj.subscriptions:
            if valref in retval:
                retval[valref].append(self)
            else:
                retval[valref] = [ self ]

        return retval
# vbus2mqtt

> [!WARNING]  
> **This project is still in early alpha stage.**
>
> There is still a lack of many things that make good code - error handling, logging, input sanitation, optimization (around 3% CPU load on a RPi4), you name it.

vbus2mqtt is a bridge for VBus-enabled devices made by Resol (and some branded devices such as Viessmann, Wagner, ...) to MQTT implemented im Python.

The project basically consists of 3 parts:

* VBusReader.py: Extraction of VBus Messages, Datagrams or Telegrams from a bytearray buffer and from a serial interface. Not all message types are supported/tested yet. Also, only reading is currently supported
* VBusSpecReader.py: VBus specification reader for *.vsf files according to its [specification](http://danielwippermann.github.io/resol-vbus/#/md/docs/vbus-specification-file-format-v1) and interpreter for Messages
* MqttDispatcher.py: Aggregator/converter of transfer specification to the actual MQTT communication

## Getting started

1. Download the code here to a directory
2. Get vbus_specification.vsf from the [resul-vbus](https://github.com/danielwippermann/resol-vbus/tree/master/src) repository
3. Install the required pip packages: `pip install -r requirements.txt`
4. Run `vbus2console.py` to explore supported messages/fields (see below)
5. Configure your `vbus2mqtt.json`
6. Run `vbus2mqtt.py` and cross your fingers ;)

# vbus2console.py

This tool can be used to inspect live data from the given serial port.
## Usage

```
usage: vbus2console.py [-h] -p PORT [-b BAUDRATE] [-v VSF] [-l {EN,DE,FR}]
vbus2console.py: error: the following arguments are required: -p/--port
```

The serial port must be provided, baudrate will default to 9600 and the script will try to use vbus_specification.vsf and English descriptions.
If the given file can not be found, only raw values will be shown.

Using a Raspberry Pi with [my hardware](https://hobbyelektronik.org/w/index.php/VBus-Decoder/Adapter_f%C3%BCr_den_Raspberry_Pi_v1.3), the command usually looks as following:

`python3 vbus2console.py -p /dev/serial0`

All read values are printed until the script is terminated.

## Output

```
Reader started
-----------------
  SRC: 0x7321 - Vitosolic 200 [Controller]
  DST: 0x0010 - DFA
  RAW:
    AA 10 00 21 73 10 00 01 12 38 0F 00 2E 01 05 3C
    62 01 38 22 04 3E 38 22 54 01 05 4B 4B 01 3F 02
    01 71 38 22 49 01 05 56 11 01 11 01 00 5B 00 00
    00 00 00 7F 00 00 00 00 00 7F 00 00 00 00 00 7F
    18 01 00 00 00 66 47 00 00 00 00 38 00 00 00 00
    00 7F 00 00 00 00 00 7F 00 00 00 00 00 7F 00 00
    53 00 00 2C 00 00 00 00 00 7F 01 03 14 05 00 62
    02 00 00 00 00 7D
  Checksum ok
  VER: v1.0 message
  CMD: 0x0100
  Fields:
    00_0010_7321_10_0100_000_2_0        Temperature sensor 1    14.30  °C
    00_0010_7321_10_0100_002_2_0        Temperature sensor 2    43.00  °C
    00_0010_7321_10_0100_004_2_0        Temperature sensor 3    35.40  °C
    00_0010_7321_10_0100_006_2_0        Temperature sensor 4    888.80  °C
<snip />
    00_0010_7321_10_0100_044_1_0        Pump speed relay 1      0 %
    00_0010_7321_10_0100_045_1_0        Pump speed relay 2      0 %
<snip />
    00_0010_7321_10_0100_058_2_0        Relay usage mask        83
    00_0010_7321_10_0100_060_2_0        Error mask      0
    00_0010_7321_10_0100_062_2_0        Warning mask    0
    00_0010_7321_10_0100_064_2_0        Controller version      769
    00_0010_7321_10_0100_066_2_0        System time     1300
[...]
```

The field identifiers (e. g. `00_0010_7321_10_0100_000_2_0` for Temperature sensor 1) are used for the vbus2mqtt configuration (see below) and can also be looked up in the the [VBus Specification](https://danielwippermann.github.io/resol-vbus/#/vsf/)

# vbus2mqtt.py

In simple words: VBus in, MQTT out.

The usage (currently) doesn't even need a section. Just run the file, all the configuration is read from hard coded `vbus2mqtt.json`

## Configuration

The configuration is read with a [json5](https://json5.org/) parser, therefore comments, trailing commas etc. are supported for easier testing and documentation.

The file currently consists of 4 sections:

* mqtt: 
* plugins: plugins to do pre-processing of the data provided by VBus
* transfers: mqtt topic content definitions

### Section vbus

Configuration to the VBus interface. This should be pretty much self-explaining:

Example:
```json
"vbus": {
    "serialport": "/dev/serial0",
    "baudrate": 9600,
    "vsf": "vbus_specification.vsf"
}
```

### Section mqtt

Connection information to the server, topic prefix and last will configuration

Example:
```json
"mqtt": {
    "host": "localhost",
    "port": 1883,
    "user": "myuser",
    "pass": "mypass123",
    "topic_prefix": "vbus2mqtt/house/",
    "last_will": {
        "topic": "LWT",
        "online": "Online",
        "offline": "Offline"
    }
}
```

`topic_prefix` is valid for all topics defined in the `transfers` section, leave it empty if you want to use full qualified names in that section. Mind the trailing slash if you want to have a sub-topic for the transfers.

`last_will` should be self-explaining. If you don't know what this is about: When the script starts, the topic `vbus2mqtt/house/LWT` will be published with `Online` as value in the above example. If the connection to the broker gets lost, it will publish `Offline` to the said topic. That's all. Currently, only one last will ist supported.

### Section plugins

Not only raw values can be published, but also processing of is possible.

Example:
```json
"plugins": [
    {
        "name": "powercalc",
        "module": "VBusReaderPlugins:VrpSolarPower",
        "config": {
            "field_tin": "00_0010_7321_10_0100_004_2_0",
            "field_tout": "00_0010_7321_10_0100_010_2_0",
            "field_pump": "00_0010_7321_10_0100_044_1_0",
            "pump_flow": [0, 0, 0, 3.5, 4.5, 5, 6, 6.5, 7, 7.5, 8],
            "medium": "tyfoclor_g-ls"
        }
    }
]
```

The `name` given to the plugin can basically be everything - this is used for reference in the assignment in the field transfers.

`module` contains the python module being loaded as well as the class to be instantiated, separated by a colon. In the example, class `VrpSolarPower` from `VBusReaderPlugins.py` is imported.

The `config` item is passed to the class' object when constructed. This data is completely dependent on the plugin. See below for more info.

### Section transfers

This section is an array of objects that describe the data transferred to the MQTT broker, it contains multiple sub-sections.
```json
"transfers": [
    {
        "mqtt": {
            "topic": "panel_temp",
            "retain": false, // optional
            "qos": 0         // optional
        },
        "trigger": {
            "type": "update"
        },
        "type": "direct",
        "field": {
            "name": null,
            "item": "00_0010_7321_10_0100_000_2_0" // 0x7321 - Vitosolic 200 [Controller] -> 0x0010 - DFA - Temperature sensor 1
        }
    },
    [...]
]
```

The item `topic` in the `mqtt` sub-section should be quite clear - as mentioned above, this value will be concatenated to the topic_prefix. In the given example, the topic would be `vbus2mqtt/house/panel_temp`.

`retain` can be `true` or `false` and will default to `false` if not provided. `qos` can be 0, 1, or 2 and will default to 0 if not provided.


The `trigger` `type` can be either `update` or `interval`.
* With `update`, an update is sent if any of the items associated to the transfer is updated via a VBus message.
* With `interval`, a second item with the key `interval` and a time value in seconds is expected in the sub-section.
* *Planned*: `change` and a combination of `change` and `interval` to reduce traffic. 

Example for an interval:
```json
"trigger": {
    "type": "interval",
    "interval": 5
},
```

This publishes the data of the transfer every 5 seconds, regardless whether there was an update or change of the data.

There are 2 different types of transfers, either direct or json. First only allows the value of one item, latter allows multipe items including nesting.

#### Transfer type direct

When `type` is set to `direct`, the item `field` contains the reference to a single field that is published. See below for the different field types.

Please note that `name` must be provided, yet its content is ignored. Therefore it is recommended to set it to `null`. (I may come up with a better implementation)

Please also note that the key is `field` and not `fields` like for the json transfer type.

See above for an example.

#### Transfer type json

When `type` is set to `json`, the item `fields` is getting a bit more complex.

Best to start with an example:

```json
"type": "json",
"fields": [
    {
        "group": "temperatures",
        "fields": [
            {
                "name": "panel",
                "item": "00_0010_7321_10_0100_000_2_0" // Temperature sensor 1
            },
            {
                "name": "heatx_in",
                "item": "00_0010_7321_10_0100_004_2_0" // Temperature sensor 3
            },
        ]
    },
    {
        "group": "pumps",
        "fields": [
            {
                "name": "pump1",
                "item": "00_0010_7321_10_0100_044_1_0" // Pump speed relay 1
            },
        ]
    }
]
```

With the data from way above, this will publish the following data:

```json
{"temperatures": {"panel": 14.3, "heatx_in": 34.0}, "pumps": {"pump1": 0}}
```

#### Field sources

The examples above only show `item` references which will read fields from VBus messages.

In case the trigger type is set to `interval`, the key value pair `max_age` can be used to set the published data to `null` if the last received value is older than the given time in seconds. E. g.:

```json
{
    "name": "panel",
    "item": "00_0010_7321_10_0100_000_2_0",
    "max_age": 10
}
```

will publish 
```json
{"panel": null}
```

if the last received value for vbus field `00_0010_7321_10_0100_000_2_0` is older than 10 seconds at the time of publishing.

Besides `item`, also the following keys can be used:

* `meta`: Meta information of the software and communications, with the item values
  * `comm:rxerr_cnt` - Count of receive errors from VBus
  * `comm:rxerr_last` - Timestamp of last receive error (ISO8601)
  * `comm:rxmsg_cnt` - Count of received messages from VBus
  * `comm:rxmsg_last` - Timestamp of last received message (ISO8601)
  * `sw:pid` - Process ID of the script
  * `sw:ramuse` - RAM usage in bytes, not including the runtime environment overhead
  * `sw:uptime` - Uptime of the script in seconds
  * `time:now` - Current time (ISO8601), can be used to mark publishing date
* `plugin`: Value from a plugin, see below

the `plugin` item references to the name of a plugin defined in the `plugins` section.
The item `function` contains the method name prefixed with `plugin_` of the plugin that's called to retreive the published value.

Example:
```json
"field": {
    "name": "solar_power",
    "plugin": "powercalc",
    "function": "power"
}
```

This publishes the result when calling the method `plugin_`**`power`** of the object instanciated in the `plugins` section named `powercalc`.

As a mockup:

```python
#VBusReaderPlugins.py
class VrpSolarPower():
    ...
    def plugin_power(self):
        return 1234
```

would publish

```json
{"solar_power": 1234}
```

## Plugin VBusReaderPlugins:VrpSolarPower

This plugin calculates the power received from the collector(s) using the input and output temperature at the heat exchangers "primary" side, the pump power resp. its flow rate and the thermal properties of the medium.

`field_tin`, `field_tout` and `field_pump`, contain the VBus field identifiers where the temperatures resp. pump speed is read from.

As a side note, these references must be put into self.subscriptions to hint the dispatcher to store the values.

`pump_flow` is an array of 11 elemnts that represent the flow rate for the medium in l/min for pump speeds between 0 ... 100%

the item `medium` can contain either a name (for now, only `tyfoclor_g-ls`) or an object with the characteristics of the heat transfer medium, to be precise the parameters for the point-slope form for both thermal capacity (in kJ / (kg * K)) as well as the medium's density (in kg/m³)

* `c_m`: slope of thermal capacity (defaults to 0 if not provided; multiplied with average of `tin` and `tout`)
* `c_t`: y-intercept of thermal capacity
* `rho_m`: slope of density (defaults to 0 if not provided; multiplied with average of `tin` and `tout`)
* `rho_t`: y-intercept of density

# TODO

* Add trigger type `change` and the combination with `interval`, also with threshold for values
* Reconsider the implementation of transfer field names. Maybe change the type of `fields` from array to object which would also make the config a bit more compact but will likely break compatibility with the current config scheme.
* CPU load is a bit high, profiling and code optimization is needed
* Proper packaging of the components
* Proper error handling & logging

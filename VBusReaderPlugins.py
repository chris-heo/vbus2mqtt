from JsonHelper import *

class VrpSolarPower():
    def __init__(self, parent, config) -> None:
        self.parent = parent
        self.config = config

        self.cfg_field_tin = json_get_or_fail(config, "field_tin")
        self.cfg_field_tout = json_get_or_fail(config, "field_tout")
        self.cfg_field_pump = json_get_or_fail(config, "field_pump")
        self.cfg_pump_flow = json_get_or_fail(config, "pump_flow")
        self.cfg_medium = json_get_or_fail(config, "medium")

        # subscribe to field updates
        # currently, this data is not "pushed" to the plugin on an update or change #TODO
        # but the subscriptions are still needed as the dispatcher otherwise will not store the values
        self.subscriptions = [
            self.cfg_field_tin, # heat exchanger input
            self.cfg_field_tout, # heat exchanger output
            self.cfg_field_pump, # primary pump
        ]

        self.medium_c_m = 0
        self.medium_c_t = 0
        self.medium_rho_m = 0
        self.medium_rho_t = 0
        medium_set = False

        # pure 1,2-Propylene glycol (according to Wikipedia)
        # c = 2.5
        # rho = 1040

        # pure Water
        # c = 4.18
        # rho = 998

        # pure Ethylene glycol
        # c = 2.4
        # rho = 1110

        if isinstance(self.cfg_medium, str):
            if self.cfg_medium == "tyfoclor_g-ls": # Tyfocor(R) G-LS (1,2-Propylene glycol)
                self.medium_c_m, self.medium_c_t = (0.004, 3.52)
                self.medium_rho_m, self.medium_rho_t = (-0.86, 1062.2)
                medium_set = True
        elif isinstance(self.cfg_medium, dict):
            self.medium_c_m = json_get_or_default(self.cfg_medium, "c_m", 0)
            self.medium_c_t = json_get_or_fail(self.cfg_medium, "c_t")
            self.medium_rho_m = json_get_or_default(self.cfg_medium, "rho_m", 0)
            self.medium_rho_t = json_get_or_fail(self.cfg_medium, "rho_t")
            medium_set = True

        if medium_set is False:
            raise Exception("No medium specification set")

        if len(self.cfg_pump_flow) != 11:
            raise Exception("Field 'pump_flow' must have 11 elements")

# not supported yet
#    def update(self, data):
#        print("plugin data update")
#        pass
#
#    def change(self, data):
#        print("plugin data change")
#        pass

    def tick(self):
        return None

    def calc_solar_power(self, ti, to, q):
        pump_lut = self.cfg_pump_flow
        flowrate = 0
        if pump_lut[q // 10] != None: 
            flowrate = pump_lut[q // 10]
        else:
            return None

        t_diff = ti - to
        t_avg = (ti + to) / 2

        c = self.medium_c_m * t_avg + self.medium_c_t # kJ/(kg*K)
        rho = self.medium_rho_m * t_avg + self.medium_rho_t # kg/m³; for values in g*cm^-3 multiply by 1000

        return c * rho * flowrate / 60 * t_diff
    
    def plugin_power(self):
        dispatcher = self.parent.dispatcher

        tin = dispatcher.get_field_value(self.cfg_field_tin)
        tout = dispatcher.get_field_value(self.cfg_field_tout)
        pump = dispatcher.get_field_value(self.cfg_field_pump)

        if tin is None or tout is None or pump is None:
            return None
        
        try:
            return self.calc_solar_power(tin, tout, pump)
        except:
            pass

        return None
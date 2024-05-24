import platform
import logging
import sys
import os
import time
import requests
import configparser

if sys.version_info.major == 2:
    import gobject
else:
    from gi.repository import GLib as gobject

sys.path.insert(1, os.path.join(os.path.dirname(__file__), '/opt/victronenergy/dbus-systemcalc-py/ext/velib_python'))
from vedbus import VeDbusService


class DbusShellyUniService:
    def __init__(self, config, section, paths, productname='Shelly Uni', connection='Shelly Uni HTTP JSON service'):
        self._config = config
        self._section = section
        deviceinstance = int(config[section]['Deviceinstance'])
        customname = config[section]['CustomName']
        self._probe_number = int(config[section]['ProbeNumber'])

        # Use a unique path for each instance
        self._dbusservice = VeDbusService("{}.http_{:02d}".format('com.victronenergy.temperature', deviceinstance))
        self._paths = paths

        logging.info("%s /DeviceInstance = %d" % (section, deviceinstance))

        # Create the management objects, as specified in the ccgx dbus-api document
        self._dbusservice.add_path('/Mgmt/ProcessName', __file__)
        self._dbusservice.add_path('/Mgmt/ProcessVersion', 'Unknown version, and running on Python ' + platform.python_version())
        self._dbusservice.add_path('/Mgmt/Connection', connection)

        # Create the mandatory objects
        self._dbusservice.add_path('/DeviceInstance', deviceinstance)
        self._dbusservice.add_path('/ProductId', 0xFFFF)
        self._dbusservice.add_path('/ProductName', productname)
        self._dbusservice.add_path('/CustomName', customname)
        self._dbusservice.add_path('/Connected', 1)
        self._dbusservice.add_path('/FirmwareVersion', self._getShellyFWVersion())
        self._dbusservice.add_path('/HardwareVersion', 0)
        self._dbusservice.add_path('/Serial', self._getShellySerial())
        self._dbusservice.add_path('/UpdateIndex', 0)

        # Add the additional paths
        for path, settings in self._paths.items():
            self._dbusservice.add_path(path, settings['initial'], gettextcallback=settings['textformat'], writeable=True, onchangecallback=self._handlechangedvalue)

        # Last update
        self._lastUpdate = 0

        # Add _update function 'timer'
        gobject.timeout_add(250, self._update) # pause 250ms before the next request

        # Add _signOfLife 'timer' to get feedback in log every 5 minutes
        gobject.timeout_add(self._getSignOfLifeInterval() * 60 * 1000, self._signOfLife)

    def _getShellySerial(self):
        meter_data = self._getShellyData()
        if not meter_data['mac']:
            raise ValueError("Response does not contain 'mac' attribute")
        serial = meter_data['mac']
        return serial

    def _getShellyFWVersion(self):
        meter_data = self._getShellyData()
        if not meter_data['update']['old_version']:
            raise ValueError("Response does not contain 'update/old_version' attribute")
        ver = meter_data['update']['old_version']
        return ver

    def _getSignOfLifeInterval(self):
        value = self._config[self._section]['SignOfLifeLog']
        if not value:
            value = 0
        return int(value)

    def _getShellyStatusUrl(self):
        accessType = self._config[self._section]['AccessType']
        if accessType == 'OnPremise':
            URL = "http://%s:%s@%s/status" % (self._config['ONPREMISE']['Username'], self._config['ONPREMISE']['Password'], self._config[self._section]['Host'])
            URL = URL.replace(":@", "")
        else:
            raise ValueError("AccessType %s is not supported" % (self._config[self._section]['AccessType']))
        return URL

    def _getShellyData(self):
        URL = self._getShellyStatusUrl()
        uni_r = requests.get(url=URL)
        if not uni_r:
            raise ConnectionError("No response from Shelly Uni - %s" % (URL))
        uni_data = uni_r.json()
        if not uni_data:
            raise ValueError("Converting response to JSON failed")
        return uni_data

    def _signOfLife(self):
        logging.info("--- Start: sign of life ---")
        logging.info("Last _update() call: %s" % (self._lastUpdate))
        logging.info("Last '/Temperature': %s" % (self._dbusservice['/Temperature']))
        logging.info("--- End: sign of life ---")
        return True

    def _update(self):
        try:
            meter_data = self._getShellyData()
            probe_number = str(self._probe_number)
            temperature = meter_data['ext_temperature'][probe_number]['tC']
            self._dbusservice['/Temperature'] = temperature
            logging.debug("Temperature: %s" % (self._dbusservice['/Temperature']))

            index = self._dbusservice['/UpdateIndex'] + 1
            if index > 255:
                index = 0
            self._dbusservice['/UpdateIndex'] = index

            self._lastUpdate = time.time()
        except Exception as e:
            logging.critical('Error at %s', '_update', exc_info=e)
        return True

    def _handlechangedvalue(self, path, value):
        logging.debug("someone else updated %s to %s" % (path, value))
        return True


def main():
    logging.basicConfig(format='%(asctime)s,%(msecs)d %(name)s %(levellevel)d %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S',
                        level=logging.INFO,
                        handlers=[
                            logging.FileHandler("%s/current.log" % (os.path.dirname(os.path.realpath(__file__)))),
                            logging.StreamHandler()
                        ])

    try:
        logging.info("Start")

        from dbus.mainloop.glib import DBusGMainLoop
        DBusGMainLoop(set_as_default=True)

        config = configparser.ConfigParser()
        config.read("%s/config.ini" % (os.path.dirname(os.path.realpath(__file__))))

        _c = lambda p, v: (str(round(v, 2)) + '°C')

        # Initialize services for each device
        services = []
        for section in config.sections():
            if section.startswith('DEVICE'):
                service = DbusShellyUniService(
                    config=config,
                    section=section,
                    paths={
                        '/Temperature': {'initial': None, 'textformat': _c},
                        '/TemperatureType': {'initial': 2, 'textformat': str},
                    })
                services.append(service)

        logging.info('Connected to dbus, and switching over to gobject.MainLoop() (= event based)')
        mainloop = gobject.MainLoop()
        mainloop.run()
    except Exception as e:
        logging.critical('Error at %s', 'main', exc_info=e)


if __name__ == "__main__":
    main()

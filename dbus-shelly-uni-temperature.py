#edited by chatgpt.com
import platform
import logging
import sys
import os
import time
import requests
import dbus

if sys.version_info.major == 2:
    import gobject
else:
    from gi.repository import GLib as gobject

sys.path.insert(1, os.path.join(os.path.dirname(__file__), '/opt/victronenergy/dbus-systemcalc-py/ext/velib_python'))
from vedbus import VeDbusService

class SystemBus(dbus.bus.BusConnection):
    def __new__(cls):
        return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SYSTEM)

class SessionBus(dbus.bus.BusConnection):
    def __new__(cls):
        return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SESSION)

def dbusconnection():
    return SessionBus() if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else SystemBus()

class DbusEcowittAPIService:
    def __init__(self, api_url, mac, paths, productname='Ecowitt API', connection='Ecowitt API HTTP JSON service'):
        self._api_url = api_url
        self._mac = mac

        # Use a unique service name and object path for each instance
        service_name = "com.victronenergy.temperature.http_01"
        self._dbusservice = VeDbusService(service_name, dbusconnection())
        self._paths = paths

        logging.info("Service /DeviceInstance = 0")

        # Create the management objects, as specified in the ccgx dbus-api document
        self._dbusservice.add_path('/Mgmt/ProcessName', __file__)
        self._dbusservice.add_path('/Mgmt/ProcessVersion', 'Unknown version, and running on Python ' + platform.python_version())
        self._dbusservice.add_path('/Mgmt/Connection', connection)

        # Create the mandatory objects
        self._dbusservice.add_path('/DeviceInstance', 0)
        self._dbusservice.add_path('/ProductId', 0xFFFF)
        self._dbusservice.add_path('/ProductName', productname)
        self._dbusservice.add_path('/CustomName', 'API Device')
        self._dbusservice.add_path('/Connected', 1)
        self._dbusservice.add_path('/FirmwareVersion', 'N/A')
        self._dbusservice.add_path('/HardwareVersion', 0)
        self._dbusservice.add_path('/Serial', self._mac)
        self._dbusservice.add_path('/UpdateIndex', 0)

        # Add the additional paths
        for path, settings in self._paths.items():
            self._dbusservice.add_path(path, settings['initial'], gettextcallback=settings['textformat'], writeable=True, onchangecallback=self._handlechangedvalue)

        # Last update
        self._lastUpdate = 0

        # Add _update function 'timer'
        gobject.timeout_add(60 * 1000, self._update)  # pause 1 minute before the next request

        # Add _signOfLife 'timer' to get feedback in log every 15 minutes
        gobject.timeout_add(15 * 60 * 1000, self._signOfLife)

    def _getAPIData(self):
        response = requests.get(url=self._api_url)
        if response.status_code != 200:
            raise ConnectionError(f"Failed to fetch data from API: {response.status_code}")
        data = response.json()
        if not data:
            raise ValueError("Converting API response to JSON failed")
        return data

    def _signOfLife(self):
        logging.info("--- Start: sign of life ---")
        logging.info("Last _update() call: %s" % (self._lastUpdate))
        logging.info("Last '/Temperature': %s" % (self._dbusservice['/Temperature']))
        logging.info("--- End: sign of life ---")
        return True

    def _update(self):
        try:
            api_data = self._getAPIData()

            if 'data' not in api_data or 'temperature' not in api_data['data']:
                logging.error("API response does not contain 'data.temperature' attribute")
                return True

            temperature = api_data['data']['temperature']
            self._dbusservice['/Temperature'] = temperature
            logging.debug("Temperature: %s" % self._dbusservice['/Temperature'])

            index = self._dbusservice['/UpdateIndex'] + 1
            if index > 255:
                index = 0
            self._dbusservice['/UpdateIndex'] = index

            self._lastUpdate = time.time()
        except Exception as e:
            logging.critical('Error at %s', '_update', exc_info=e)
        return True

    def _handlechangedvalue(self, path, value):
        logging.debug("Someone else updated %s to %s" % (path, value))
        return True

def main():
    logging.basicConfig(format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
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

        # Define your API details
        APPLICATION_KEY = "YOUR_APPLICATION_KEY"
        API_KEY = "YOUR_API_KEY"
        MAC = "YOUR_MAC_CODE_OF_DEVICE"
        API_URL = f"https://api.ecowitt.net/api/v3/device/real_time?application_key={APPLICATION_KEY}&api_key={API_KEY}&mac={MAC}&call_back=all"

        _c = lambda p, v: (str(round(v, 2)) + '°C')

        # Initialize service
        service = DbusEcowittAPIService(
            api_url=API_URL,
            mac=MAC,
            paths={
                '/Temperature': {'initial': None, 'textformat': _c},
                '/TemperatureType': {'initial': 2, 'textformat': str},
            })

        logging.info('Connected to dbus, and switching over to gobject.MainLoop() (= event based)')
        mainloop = gobject.MainLoop()
        mainloop.run()
    except Exception as e:
        logging.critical('Error at %s', 'main', exc_info=e)

if __name__ == "__main__":
    main()

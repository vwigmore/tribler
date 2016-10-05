import logging
import os
from configobj import ConfigObj
from validate import Validator
from Tribler.Core.Utilities.network_utils import get_random_port
from Tribler.Core.simpledefs import STATEDIR_CONFIG


CONFIGSPEC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.spec')


class TriblerConfig(object):

    def __init__(self):
        config_path = os.path.join(session.get_state_dir(), STATEDIR_CONFIG)
        self.config = ConfigObj(config_path, configspec=CONFIGSPEC_PATH)
        self.selected_ports = {}
        self._logger = logging.getLogger(self.__class__.__name__)

        validator = Validator()
        self.config.validate(validator, copy=True)
        self.config.write()

    def write(self):
        self.config.write()

    def _obtain_port(self, section, option):
        """ Fetch a port setting from the config file and in case it's set to -1 (random), look for a free port and assign it to
                this particular setting.
        """
        settings_port = self.config[section][option]
        path = section + '~' + option
        in_selected_ports = path in self.selected_ports

        if in_selected_ports or settings_port == -1:
            return self._get_random_port(path)
        return settings_port

    def _get_random_port(self, path):
        if path not in self.selected_ports:
            self.selected_ports[path] = get_random_port()
            self._logger.debug(u"Get random port %d for [%s]", self.selected_ports[path], path)
        return self.selected_ports[path]

    # General

    def get_family_filter_enabled(self):
        return self.config['general']['family_filter']

    def set_family_filter_enabled(self, value):
        self.config['general']['family_filter'] = value
        self.config.write()

    def get_state_dir(self):
        return self.config['general']['state_dir']

    def set_state_dir(self, value):
        self.config['general']['state_dir'] = value
        self.config.write()

    # Mainline DHT

    def get_mainline_dht_port(self):
        return self.config['mainline_dht']['port']

    def set_mainline_dht_port(self, value):
        self.config['mainline_dht']['port'] = value
        self.config.write()

    # Torrent checking

    def get_torrent_checking_enabled(self):
        return self.config['torrent_checking']['enabled']

    def set_torrent_checking_enabled(self, value):
        self.config['torrent_checking']['enabled'] = value
        self.config.write()

    # Torrent collecting

    def get_torrent_collecting_enabled(self):
        return self.config['torrent_collecting']['enabled']

    def set_torrent_collecting_enabled(self, value):
        self.config['torrent_collecting']['enabled'] = value
        self.config.write()

    # Libtorrent

    def get_libtorrent_enabled(self):
        return self.config['libtorrent']['enabled']

    def set_libtorrent_enabled(self, value):
        self.config['libtorrent']['enabled'] = value
        self.config.write()

    def get_libtorrent_port(self):
        return self._obtain_port('libtorrent', 'port')

    def set_libtorrent_port(self, port):
        self.config['libtorrent']['port'] = port
        self.config.write()

    # Dispersy

    def get_dispersy_enabled(self):
        return self.config['dispersy']['enabled']

    def set_dispersy_enabled(self, value):
        self.config['dispersy']['enabled'] = value
        self.config.write()

    def get_dispersy_port(self):
        return self.config['dispersy']['port']

    def set_dispersy_port(self, value):
        self.config['dispersy']['port'] = value
        self.config.write()

    # Download states

    def get_download_state(self, infohash):
        if infohash.encode('hex') in self.config["user_download_states"]:
            return self.config["user_download_states"][infohash.encode('hex')]
        return None

    def remove_download_state(self, infohash):
        if infohash.encode('hex') in self.config["user_download_states"]:
            del self.config["user_download_states"][infohash.encode('hex')]
            self.config.write()

    def set_download_state(self, infohash, value):
        self.config["user_download_states"][infohash.encode('hex')] = value
        self.config.write()

    def get_download_states(self):
        return dict((key.decode('hex'), value) for key, value in self.config["user_download_states"].iteritems())

import base64
import json
import urllib
from Tribler.Core.Modules.restapi.channels.base_channels_endpoint import UNKNOWN_CHANNEL_RESPONSE_MSG
from Tribler.Core.TorrentDef import TorrentDef
from Tribler.Core.Utilities.twisted_thread import deferred
from Tribler.Test.Core.Modules.RestApi.Channels.test_channels_endpoint import AbstractTestChannelsEndpoint
from Tribler.Test.Core.base_test import MockObject
from Tribler.Test.test_libtorrent_download import TORRENT_FILE


class TestChannelTorrentsEndpoint(AbstractTestChannelsEndpoint):

    @deferred(timeout=10)
    def test_get_torrents_in_channel_invalid_cid(self):
        """
        Testing whether the API returns error 404 if a non-existent channel is queried for torrents
        """
        expected_json = {"error": UNKNOWN_CHANNEL_RESPONSE_MSG}
        return self.do_request('channels/discovered/abcd/torrents', expected_code=404, expected_json=expected_json)

    @deferred(timeout=10)
    def test_get_torrents_in_channel(self):
        """
        Testing whether the API returns inserted channels when fetching discovered channels
        """
        def verify_torrents(torrents):
            torrents_json = json.loads(torrents)
            self.assertEqual(len(torrents_json['torrents']), 1)
            self.assertEqual(torrents_json['torrents'][0]['infohash'], 'a' * 40)

        self.should_check_equality = False
        channel_id = self.insert_channel_in_db('rand', 42, 'Test channel', 'Test description')

        torrent_list = [[channel_id, 1, 1, ('a' * 40).decode('hex'), 1460000000, "ubuntu-torrent.iso",
                         [['file.txt', 42]], []]]
        self.insert_torrents_into_channel(torrent_list)

        return self.do_request('channels/discovered/%s/torrents' % 'rand'.encode('hex'), expected_code=200)\
            .addCallback(verify_torrents)

    @deferred(timeout=10)
    def test_add_torrent_to_my_channel(self):
        """
        Testing whether adding a torrent file to your channel is working
        """
        my_channel_id = self.create_fake_channel("channel", "")
        torrent_path = TORRENT_FILE

        def verify_method_invocation(channel_id, torrent_def, extra_info={}, forward=True):
            self.assertEqual(my_channel_id, channel_id)
            self.assertEqual(TorrentDef.load(torrent_path), torrent_def)
            self.assertEqual({}, extra_info)
            self.assertEqual(True, forward)

        self.session.add_torrent_def_to_channel = verify_method_invocation

        torrent_file = open(torrent_path, mode='rb')
        torrent_64 = base64.b64encode(torrent_file.read())
        data = {
            "torrent": torrent_64
        }
        expected_json = {"added": True}
        return self.do_request('channels/discovered/%s/torrents' % 'fakedispersyid'.encode('hex'),
                               expected_code=200, expected_json=expected_json, request_type='PUT', post_data=data)

    @deferred(timeout=10)
    def test_add_torrent_to_my_channel_with_description(self):
        my_channel_id = self.create_fake_channel("channel", "")
        torrent_path = TORRENT_FILE

        def verify_method_invocation(channel_id, torrent_def, extra_info={}, forward=True):
            self.assertEqual(my_channel_id, channel_id)
            self.assertEqual(TorrentDef.load(torrent_path), torrent_def)
            self.assertEqual({"description": "video of my cat"}, extra_info)
            self.assertEqual(True, forward)

        self.session.add_torrent_def_to_channel = verify_method_invocation

        torrent_file = open(torrent_path, mode='rb')
        torrent_64 = base64.b64encode(torrent_file.read())
        data = {
            "torrent": torrent_64,
            "description": "video of my cat"
        }
        expected_json = {"added": True}
        return self.do_request('channels/discovered/%s/torrents' % 'fakedispersyid'.encode('hex'),
                               expected_code=200, expected_json=expected_json, request_type='PUT', post_data=data)

    @deferred(timeout=10)
    def test_add_torrent_to_my_channel_404(self):
        self.should_check_equality = False
        return self.do_request('channels/discovered/%s/torrents' % 'fakedispersyid'.encode('hex'),
                               expected_code=404, request_type='PUT')

    @deferred(timeout=10)
    def test_add_torrent_to_my_channel_missing_parameter(self):
        self.create_fake_channel("channel", "")
        expected_json = {"error": "torrent parameter missing"}
        return self.do_request('channels/discovered/%s/torrents' % 'fakedispersyid'.encode('hex'),
                               expected_code=400, expected_json=expected_json, request_type='PUT')

    @deferred(timeout=10)
    def test_add_torrent_to_my_channel_500(self):
        """
        Testing whether the API returns a formatted 500 error if ValueError is raised
        """
        self.create_fake_channel("channel", "")
        torrent_path = TORRENT_FILE

        def fake_error(channel_id, torrent_def, extra_info={}, forward=True):
            raise ValueError("Test error")

        self.session.add_torrent_def_to_channel = fake_error

        def verify_error_message(body):
            error_response = json.loads(body)
            expected_response = {
                u"error": {
                    u"handled": True,
                    u"code": u"ValueError",
                    u"message": u"Test error"
                }
            }
            self.assertDictContainsSubset(expected_response[u"error"], error_response[u"error"])

        torrent_file = open(torrent_path, mode='rb')
        torrent_64 = base64.b64encode(torrent_file.read())
        post_data = {
            "torrent": torrent_64
        }
        self.should_check_equality = False
        return self.do_request('channels/discovered/%s/torrents' % 'fakedispersyid'.encode('hex'),
                               expected_code=500, expected_json=None, request_type='PUT', post_data=post_data)\
            .addCallback(verify_error_message)


class TestModifyChannelTorrentEndpoint(AbstractTestChannelsEndpoint):

    def setUp(self, autoload_discovery=True):
        super(TestModifyChannelTorrentEndpoint, self).setUp(autoload_discovery)
        self.session.lm.ltmgr = MockObject()
        self.session.lm.ltmgr.shutdown = lambda: True

    @deferred(timeout=10)
    def test_add_torrent_from_url_to_my_channel_with_description(self):
        """
        Testing whether adding a torrent from a url to a channel without description works
        """
        my_channel_id = self.create_fake_channel("channel", "")
        torrent_path = TORRENT_FILE

        @staticmethod
        def fake_load_from_url(url):
            return TorrentDef.load(torrent_path)

        TorrentDef.load_from_url = fake_load_from_url

        def verify_method_invocation(channel_id, torrent_def, extra_info={}, forward=True):
            self.assertEqual(my_channel_id, channel_id)
            self.assertEqual(TorrentDef.load(torrent_path), torrent_def)
            self.assertEqual({"description": "test add torrent"}, extra_info)
            self.assertEqual(True, forward)

        self.session.add_torrent_def_to_channel = verify_method_invocation

        torrent_url = 'https://www.tribler.org'
        url = 'channels/discovered/%s/torrents/%s' % ('fakedispersyid'.encode('hex'), urllib.quote_plus(torrent_url))
        return self.do_request(url, expected_code=200, expected_json={"added": torrent_url}, request_type='PUT',
                               post_data={"description": "test add torrent"})

    @deferred(timeout=10)
    def test_add_torrent_from_magnet_to_my_channel_without_description(self):
        """
        Testing whether adding a torrent from magnet link to a channel without description works
        """
        my_channel_id = self.create_fake_channel("channel", "")
        torrent_path = TORRENT_FILE

        def fake_load_from_dht(_, callback):
            meta_info = TorrentDef.load(torrent_path).get_metainfo()
            callback(meta_info)

        self.session.lm.ltmgr.get_metainfo = fake_load_from_dht

        def verify_method_invocation(channel_id, torrent_def, extra_info={}, forward=True):
            self.assertEqual(my_channel_id, channel_id)
            self.assertEqual(TorrentDef.load(torrent_path), torrent_def)
            self.assertEqual({}, extra_info)
            self.assertEqual(True, forward)

        self.session.add_torrent_def_to_channel = verify_method_invocation

        magnet_url = 'magnet:?fake'
        url = 'channels/discovered/%s/torrents/%s' % ('fakedispersyid'.encode('hex'), urllib.quote_plus(magnet_url))
        return self.do_request(url, expected_code=200, expected_json={"added": magnet_url}, request_type='PUT')

    @deferred(timeout=10)
    def test_add_torrent_to_my_channel_404(self):
        """
        Testing whether adding a torrent to a non-existing channel does not work
        """
        self.should_check_equality = False
        return self.do_request('channels/discovered/abcd/torrents/fake_url',
                               expected_code=404, expected_json=None, request_type='PUT')

    @deferred(timeout=10)
    def test_add_torrent_to_my_channel_500(self):
        """
        Testing whether the API returns a formatted 500 error if ValueError is raised
        """
        self.create_fake_channel("channel", "")

        @staticmethod
        def fake_load_from_url(url):
            raise ValueError("Test error")

        TorrentDef.load_from_url = fake_load_from_url

        def verify_error_message(body):
            error_response = json.loads(body)
            expected_response = {
                u"error": {
                    u"handled": True,
                    u"code": u"ValueError",
                    u"message": u"Test error"
                }
            }
            self.assertDictContainsSubset(expected_response[u"error"], error_response[u"error"])

        torrent_url = 'https://www.tribler.org'
        url = 'channels/discovered/%s/torrents/%s' % ('fakedispersyid'.encode('hex'), urllib.quote_plus(torrent_url))
        self.should_check_equality = False
        return self.do_request(url, expected_code=500, expected_json=None, request_type='PUT')\
                   .addCallback(verify_error_message)

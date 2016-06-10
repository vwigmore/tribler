import json

from twisted.web import http

from Tribler.Core.CacheDB.sqlitecachedb import str2bin
from Tribler.Core.Modules.restapi.channels.base_channels_endpoint import BaseChannelsEndpoint
from Tribler.Core.Modules.restapi.util import convert_db_torrent_to_json
from Tribler.Core.simpledefs import ENABLE_FAMILY_FILTER


class ChannelsPlaylistsEndpoint(BaseChannelsEndpoint):
    """
    This class is responsible for handling requests regarding playlists in a channel.
    """
    def __init__(self, session, cid):
        BaseChannelsEndpoint.__init__(self, session)
        self.cid = cid

    def getChild(self, path, request):
        return ChannelsModifyPlaylistsEndpoint(self.session, self.cid, path)

    def render_GET(self, request):
        """
        Returns the playlists in a specific channel.

        Example response:
        {
            "playlists": [{
                "id": 1,
                "name": "My first playlist",
                "description": "Funny movies",
                "torrents": [{
                    "name": "movie_1",
                    "infohash": "e940a7a57294e4c98f62514b32611e38181b6cae"
                }, ... ]
            }, ...]
        }
        """

        channel = self.get_channel_from_db(self.cid)
        if channel is None:
            return ChannelsPlaylistsEndpoint.return_404(request)

        playlists = []
        req_columns = ['Playlists.id', 'Playlists.name', 'Playlists.description']
        req_columns_torrents = ['Torrent.torrent_id', 'infohash', 'Torrent.name', 'length', 'Torrent.category',
                                'num_seeders', 'num_leechers', 'last_tracker_check', 'ChannelTorrents.inserted']
        for playlist in self.channel_db_handler.getPlaylistsFromChannelId(channel[0], req_columns):
            # Fetch torrents in the playlist
            playlist_torrents = self.channel_db_handler.getTorrentsFromPlaylist(playlist[0], req_columns_torrents)

            torrents = []
            for torrent_result in playlist_torrents:
                torrent = convert_db_torrent_to_json(torrent_result)

                if (ENABLE_FAMILY_FILTER and torrent['category'] == 'xxx') or torrent['name'] is None:
                    continue

                torrents.append(torrent)

            playlists.append({"id": playlist[0], "name": playlist[1], "description": playlist[2], "torrents": torrents})

        return json.dumps({"playlists": playlists})

    def render_PUT(self, request):
        """
        Create a new empty playlist with a given name and description.

        Example PUT request:
        {
            "name": "My fancy playlist",
            "description": "This playlist contains some random movies"
        }
        """
        channel_info = self.get_channel_from_db(self.cid)
        if channel_info is None:
            return ChannelsPlaylistsEndpoint.return_404(request)

        parameters = http.parse_qs(request.content.read(), 1)

        if 'name' not in parameters or len(parameters['name']) == 0:
            request.setResponseCode(http.BAD_REQUEST)
            return json.dumps({"error": "name parameter missing"})

        if 'description' not in parameters or len(parameters['description']) == 0:
            request.setResponseCode(http.BAD_REQUEST)
            return json.dumps({"error": "description parameter missing"})

        channel_community = self.get_community_for_channel_id(channel_info[0])
        if channel_community is None:
            return BaseChannelsEndpoint.return_404(request,
                                                   message="the community for the specific channel cannot be found")

        channel_community.create_playlist(parameters['name'][0], parameters['description'][0], [])

        return json.dumps({"created": True})


class ChannelsModifyPlaylistsEndpoint(BaseChannelsEndpoint):
    """
    This class is responsible for requests that are modifying a specific playlist in a channel.
    """

    def __init__(self, session, cid, playlist_id):
        BaseChannelsEndpoint.__init__(self, session)
        self.cid = cid
        self.playlist_id = playlist_id

    def getChild(self, path, request):
        return ChannelsModifyPlaylistTorrentsEndpoint(self.session, self.cid, self.playlist_id, path)

    def render_DELETE(self, request):
        channel_info = self.get_channel_from_db(self.cid)
        if channel_info is None:
            return ChannelsPlaylistsEndpoint.return_404(request)

        playlist = self.channel_db_handler.getPlaylist(self.playlist_id, ['Playlists.dispersy_id'])
        if playlist is None:
            return BaseChannelsEndpoint.return_404(request, message="this playlist cannot be found")

        channel_community = self.get_community_for_channel_id(channel_info[0])
        if channel_community is None:
            return BaseChannelsEndpoint.return_404(request,
                                                   message="the community for the specific channel cannot be found")

        # Remove all torrents from this playlist
        sql = "SELECT dispersy_id FROM PlaylistTorrents WHERE playlist_id = ?"
        playlist_torrents = self.channel_db_handler._db.fetchall(sql, (playlist[0],))
        channel_community.remove_playlist_torrents(playlist[0], [dispersy_id for dispersy_id, in playlist_torrents])

        # Remove the playlist itself
        channel_community.remove_playlists([playlist[0]])

        return json.dumps({"removed": True})

    def render_POST(self, request):
        channel_info = self.get_channel_from_db(self.cid)
        if channel_info is None:
            return ChannelsPlaylistsEndpoint.return_404(request)

        parameters = http.parse_qs(request.content.read(), 1)

        if 'name' not in parameters or len(parameters['name']) == 0:
            request.setResponseCode(http.BAD_REQUEST)
            return json.dumps({"error": "name parameter missing"})

        if 'description' not in parameters or len(parameters['description']) == 0:
            request.setResponseCode(http.BAD_REQUEST)
            return json.dumps({"error": "description parameter missing"})

        playlist = self.channel_db_handler.getPlaylist(self.playlist_id, ['Playlists.id'])
        if playlist is None:
            return BaseChannelsEndpoint.return_404(request, message="this playlist cannot be found")

        channel_community = self.get_community_for_channel_id(channel_info[0])
        if channel_community is None:
            return BaseChannelsEndpoint.return_404(request,
                                                   message="the community for the specific channel cannot be found")

        channel_community.modifyPlaylist(playlist[0], {'name': parameters['name'][0],
                                                       'description': parameters['description'][0]})

        return json.dumps({"modified": True})


class ChannelsModifyPlaylistTorrentsEndpoint(BaseChannelsEndpoint):

    def __init__(self, session, cid, playlist_id, infohash):
        BaseChannelsEndpoint.__init__(self, session)
        self.cid = cid
        self.playlist_id = playlist_id
        self.infohash = infohash.decode('hex')

    def render_PUT(self, request):
        channel_info = self.get_channel_from_db(self.cid)
        if channel_info is None:
            return ChannelsPlaylistsEndpoint.return_404(request)

        playlist = self.channel_db_handler.getPlaylist(self.playlist_id, ['Playlists.dispersy_id'])
        if playlist is None:
            return BaseChannelsEndpoint.return_404(request, message="this playlist cannot be found")

        channel_community = self.get_community_for_channel_id(channel_info[0])
        if channel_community is None:
            return BaseChannelsEndpoint.return_404(request,
                                                   message="the community for the specific channel cannot be found")

        # Check whether this torrent is present in your channel
        torrent_in_channel = False
        for torrent in self.channel_db_handler.getTorrentsFromChannelId(channel_info[0], True, ["infohash"]):
            if torrent[0] == self.infohash:
                torrent_in_channel = True
                break

        if not torrent_in_channel:
            return BaseChannelsEndpoint.return_401(request, message="this torrent is not available in your channel")

        # Check whether this torrent is not already present in this playlist
        for torrent in self.channel_db_handler.getTorrentsFromPlaylist(self.playlist_id, ["infohash"]):
            if torrent[0] == self.infohash:
                request.setResponseCode(http.CONFLICT)
                return json.dumps({"error": "this torrent is already in your playlist"})

        channel_community.create_playlist_torrents(int(self.playlist_id), [self.infohash])

        return json.dumps({"added": True})

    def render_DELETE(self, request):
        channel_info = self.get_channel_from_db(self.cid)
        if channel_info is None:
            return ChannelsPlaylistsEndpoint.return_404(request)

        playlist = self.channel_db_handler.getPlaylist(self.playlist_id, ['Playlists.dispersy_id'])
        if playlist is None:
            return BaseChannelsEndpoint.return_404(request, message="this playlist cannot be found")

        channel_community = self.get_community_for_channel_id(channel_info[0])
        if channel_community is None:
            return BaseChannelsEndpoint.return_404(request,
                                                   message="the community for the specific channel cannot be found")

        # Check whether this torrent is present in this playlist and if so, get the dispersy ID
        torrent_dispersy_id = -1
        for torrent in self.channel_db_handler.getTorrentsFromPlaylist(self.playlist_id, ["infohash", "PlaylistTorrents.dispersy_id"]):
            if torrent[0] == self.infohash:
                torrent_dispersy_id = torrent[1]
                break

        if torrent_dispersy_id == -1:
            request.setResponseCode(http.NOT_FOUND)
            return json.dumps({"error": "this torrent is not in your playlist"})

        channel_community.remove_playlist_torrents(int(self.playlist_id), [torrent_dispersy_id])

        return json.dumps({"removed": True})

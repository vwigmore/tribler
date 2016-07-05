import logging
import mimetypes
import os
from collections import defaultdict
from threading import RLock

from cherrypy.lib.httputil import get_ranges
import time
from twisted.internet import reactor
from twisted.internet.defer import maybeDeferred, Deferred, inlineCallbacks, returnValue
from twisted.web import http, server
from twisted.web.resource import Resource
from Tribler.Core.Libtorrent.LibtorrentDownloadImpl import VODFile

from Tribler.Core.simpledefs import DLMODE_VOD
from Tribler.dispersy.taskmanager import TaskManager


class TwistedVideoServer(TaskManager):

    def __init__(self, session):
        super(TwistedVideoServer, self).__init__()
        self._logger = logging.getLogger(self.__class__.__name__)
        self.session = session
        self.site = None
        self.active_vod_download = None
        self.active_vod_fileindex = -1
        self.vod_info = defaultdict(dict)

    def start(self):
        self.site = reactor.listenTCP(6593, server.Site(resource=VideoServerEndpoint(self)))

    def stop(self):
        return maybeDeferred(self.site.stopListening)

    def get_vod_filename(self, download):
        if download.get_def().is_multifile_torrent():
            return os.path.join(download.get_content_dest(), download.get_selected_files()[0])
        else:
            return download.get_content_dest()

    def get_vod_stream(self, dl_hash, wait=False):
        if 'stream' not in self.vod_info[dl_hash] and self.session.get_download(dl_hash):
            download = self.session.get_download(dl_hash)
            vod_filename = self.get_vod_filename(download)
            while wait and not os.path.exists(vod_filename):
                time.sleep(1)
            self.vod_info[dl_hash]['stream'] = (VODFile(open(vod_filename, 'rb'), download), RLock())

        if self.vod_info[dl_hash].has_key('stream'):
            return self.vod_info[dl_hash]['stream']
        return None, None


class VideoServerEndpoint(Resource):

    def __init__(self, video_server):
        Resource.__init__(self)
        self.video_server = video_server

    def getChild(self, path, request):
        download = self.video_server.session.get_download(path.decode('hex'))
        if not download:
            request.setResponseCode(http.NOT_FOUND)
            return "Download not found"

        return VideoServerDownloadEndpoint(self.video_server, download)


class VideoServerDownloadEndpoint(Resource):

    def __init__(self, video_server, download):
        Resource.__init__(self)
        self.video_server = video_server
        self.download = download

    def getChild(self, path, request):
        return VideoServerDownloadFileEndpoint(self.video_server, self.download, int(path))


class VideoServerDownloadFileEndpoint(Resource):

    isLeaf = True

    def __init__(self, video_server, download, file_index):
        Resource.__init__(self)
        self.video_server = video_server
        self.download = download
        self.buffer_deferred = Deferred()
        self.file_index = file_index
        self.request = None
        self.requested_range = None
        self.firstbyte = 0
        self.num_bytes_to_send = 0

    def wait_for_buffer(self, download):
        self.buffer_deferred.addCallback(self.on_buffer_complete)

        def wait_for_buffer(ds):
            if download.vod_seekpos is None or download != self.video_server.active_vod_download\
                    or ds.get_vod_prebuffering_progress() == 1.0:
                self.buffer_deferred.callback(None)
                return 0, False
            return 1.0, False
        download.set_state_callback(wait_for_buffer)
        return self.buffer_deferred

    def on_buffer_complete(self, _):
        piecelen = self.download.get_def().get_piece_length()
        filename, file_length = self.download.get_def().get_files_as_unicode_with_length()[self.file_index]
        stream, lock = self.video_server.get_vod_stream(self.download.get_def().get_infohash(), wait=True)

        #with lock:
        if stream.closed:
            return

        stream.seek(self.firstbyte)
        nbyteswritten = 0
        while True:
            data = stream.read(0.5 * 1024 * 1024)

            if len(data) == 0:
                break
            elif file_length is not None and nbyteswritten + len(data) > self.num_bytes_to_send:
                endlen = self.num_bytes_to_send - nbyteswritten
                if endlen != 0:
                    self.request.write(data[:endlen])
                    nbyteswritten += endlen
                break
            else:
                self.request.write(data)
                nbyteswritten += len(data)

        if nbyteswritten != self.num_bytes_to_send:
            self._logger.error("sent wrong amount, wanted %s got %s", self.num_bytes_to_send, nbyteswritten)

        if not self.requested_range:
            stream.close()

        self.request.finish()

    def write_headers(self, filename, file_length):
        if self.requested_range is not None:
            self.firstbyte, lastbyte = self.requested_range[0]
            self.num_bytes_to_send = lastbyte - self.firstbyte
            self.request.setResponseCode(http.PARTIAL_CONTENT)
            self.request.setHeader("Content-Range", 'bytes %d-%d/%d' % (self.firstbyte, lastbyte - 1, file_length))
        else:
            self.num_bytes_to_send = file_length
            self.request.setResponseCode(http.OK)

        mimetype = mimetypes.guess_type(filename)[0]
        if mimetype:
            self.request.setHeader("Content-Type", mimetype)
        self.request.setHeader("Accept-Ranges", "bytes")

        if file_length is not None:
            self.request.setHeader('Content-Length', self.num_bytes_to_send)
        else:
            self.request.setHeader('Transfer-Encoding', 'chunked')

        if self.request.getHeader('Connection') and self.request.getHeader('Connection').lower() != 'close':
            self.request.setHeader('Connection', 'Keep-Alive')
            self.request.setHeader('Keep-Alive', 'timeout=300, max=1')

        self.request.write("")

    def render_GET(self, request):
        self.request = request
        filename, file_length = self.download.get_def().get_files_as_unicode_with_length()[self.file_index]
        self.requested_range = get_ranges(request.getHeader('range'), file_length)
        if self.requested_range is not None and len(self.requested_range) != 1:
            request.setResponseCode(http.REQUESTED_RANGE_NOT_SATISFIABLE)
            return "Requested range not satisfiable"

        # Check if the active download/active file index has changed. If so, update the video server variables
        has_changed = self.download != self.video_server.active_vod_download or \
                      self.file_index != self.video_server.active_vod_fileindex
        if has_changed:
            self.video_server.active_vod_download = self.download
            self.video_server.active_vod_fileindex = self.file_index

            # Put the download in VOD (sequential) mode
            if self.download.get_def().is_multifile_torrent():
                self.download.set_selected_files([filename])
            self.download.set_mode(DLMODE_VOD)
            self.download.restart()

        # Write the initial response headers
        self.write_headers(filename, file_length)

        if has_changed:
            self.wait_for_buffer(self.download)
        else:
            self.on_buffer_complete(None)

        return server.NOT_DONE_YET

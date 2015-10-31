import logging
import os
import sys
from random import randint
from twisted.python.threadable import isInIOThread
from traceback import print_exc
from Tribler.Category.Category import Category
from Tribler.Core.DownloadConfig import get_default_dest_dir, get_default_dscfg_filename
from Tribler.Core.Session import Session
from Tribler.Core.simpledefs import (DLSTATUS_DOWNLOADING, DLSTATUS_SEEDING, DLSTATUS_STOPPED,
                                     DLSTATUS_STOPPED_ON_ERROR, DOWNLOAD, NTFY_ACTIVITIES, NTFY_CHANNELCAST,
                                     NTFY_COMMENTS, NTFY_CREATE, NTFY_DELETE, NTFY_DISPERSY, NTFY_FINISHED, NTFY_INSERT,
                                     NTFY_MAGNET_CLOSE, NTFY_MAGNET_GOT_PEERS, NTFY_MAGNET_STARTED, NTFY_MARKINGS,
                                     NTFY_MODERATIONS, NTFY_MODIFICATIONS, NTFY_MODIFIED, NTFY_MYPREFERENCES,
                                     NTFY_PLAYLISTS, NTFY_REACHABLE, NTFY_STARTED, NTFY_STATE, NTFY_TORRENTS,
                                     NTFY_UPDATE, NTFY_VOTECAST, UPLOAD, dlstatus_strings)
from Tribler.Core.version import commit_id, version_id
from Tribler.Core.SessionConfig import SessionStartupConfig
from Tribler.Main.Utility.compat import (convertDefaultDownloadConfig, convertDownloadCheckpoints, convertMainConfig,
                                         convertSessionConfig)
from Tribler.Main.globals import DefaultDownloadStartupConfig
from Tribler.dispersy.util import attach_profiler, call_on_reactor_thread
from Tribler.Main.Utility.utility import Utility
from Tribler.Utilities.Instance2Instance import Instance2InstanceClient, Instance2InstanceServer

from time import time, sleep

ALLOW_MULTIPLE = os.environ.get("TRIBLER_ALLOW_MULTIPLE", "False").lower() == "true"

class TriblerStartupManager(object):

    def __init__(self, params, installdir, autoload_discovery=True,
                 use_torrent_search=True, use_channel_search=True):
        assert not isInIOThread(), "isInIOThread() seems to not be working correctly"
        self._logger = logging.getLogger(self.__class__.__name__)

        self.params = params
        self.installdir = installdir

        self.state_dir = None
        self.error = None
        self.last_update = 0
        self.ready = False
        self.done = False
        self.frame = None

        # DISPERSY will be set when available
        self.dispersy = None
        self.tunnel_community = None

        self.webUI = None
        self.utility = None

        # Stage 1 start
        session = self.InitStage1(installdir, autoload_discovery=autoload_discovery,
                                  use_torrent_search=use_torrent_search, use_channel_search=use_channel_search)

        try:
            self._logger.info('Client Starting Up.')
            self._logger.info("Tribler is using %s as working directory", self.installdir)

            # Stage 2: show the splash window and start the session

            s = self.startAPI(session)

            self.utility = Utility(self.installdir, s.get_state_dir())
            self.utility.set_app(self)
            self.utility.set_session(s)

            self._logger.info('Tribler Version: %s Build: %s', version_id, commit_id)

            version_info = self.utility.read_config('version_info')
            if version_info.get('version_id', None) != version_id:
                # First run of a different version
                version_info['first_run'] = int(time())
                version_info['version_id'] = version_id
                self.utility.write_config('version_info', version_info)

            self._logger.info('Starting session and upgrading database (it may take a while)')
            s.start()
            self.dispersy = s.lm.dispersy

            self._logger.info('Loading userdownloadcoice')

            from Tribler.Main.vwxGUI.UserDownloadChoice import UserDownloadChoice
            UserDownloadChoice.get_singleton().set_utility(self.utility)

            self._logger.info('Initializing Family Filter')
            cat = Category.getInstance(session)

            state = self.utility.read_config('family_filter')
            if state in (1, 0):
                cat.set_family_filter(state == 1)
            else:
                self.utility.write_config('family_filter', 1)
                self.utility.flush_config()

                cat.set_family_filter(True)

            # Create global speed limits
            self._logger.info('Setting up speed limits')

            # Counter to suppress some event from occurring
            self.ratestatecallbackcount = 0

            # So we know if we asked for peer details last cycle
            self.lastwantpeers = []

            maxup = self.utility.read_config('maxuploadrate')
            maxdown = self.utility.read_config('maxdownloadrate')
            # set speed limits using LibtorrentMgr
            s.set_max_upload_speed(maxup)
            s.set_max_download_speed(maxdown)

            # Only allow updates to come in after we defined ratelimiter
            self.prevActiveDownloads = []
            s.set_download_states_callback(self.sesscb_states_callback)

            if not ALLOW_MULTIPLE:
                # Put it here so an error is shown in the startup-error popup
                # Start server for instance2instance communication
                Instance2InstanceServer(self.utility.read_config('i2ilistenport'), self.i2ithread_readlinecallback)

            self._logger.info('GUIUtility register')

            session.lm.threadpool.call_in_thread(0, self.guiservthread_free_space_check)

            self.emercoin_mgr = None
            try:
                from Tribler.Main.Emercoin.EmercoinMgr import EmercoinMgr
                self.emercoin_mgr = EmercoinMgr(self.utility)
            except Exception:
                print_exc()

            self.PostInit2()

            # 08/02/10 Boudewijn: Working from home though console
            # doesn't allow me to press close.  The statement below
            # gracefully closes Tribler after 120 seconds.
            # wx.CallLater(120*1000, wx.GetApp().Exit)

            self.ready = True

        except Exception as e:
            self.onError(e)

    def InitStage1(self, installdir, autoload_discovery=True,
                   use_torrent_search=True, use_channel_search=True):
        """ Stage 1 start: pre-start the session to handle upgrade.
        """

        # Start Tribler Session
        defaultConfig = SessionStartupConfig()
        state_dir = defaultConfig.get_state_dir()
        cfgfilename = Session.get_default_config_filename(state_dir)

        self._logger.debug(u"Session config %s", cfgfilename)
        try:
            self.sconfig = SessionStartupConfig.load(cfgfilename)
        except:
            try:
                self.sconfig = convertSessionConfig(os.path.join(state_dir, 'sessconfig.pickle'), cfgfilename)
                convertMainConfig(state_dir, os.path.join(state_dir, 'abc.conf'),
                                  os.path.join(state_dir, 'tribler.conf'))
            except:
                self.sconfig = SessionStartupConfig()
                self.sconfig.set_state_dir(state_dir)

        self.sconfig.set_install_dir(self.installdir)

        # Arno, 2010-03-31: Hard upgrade to 50000 torrents collected
        self.sconfig.set_torrent_collecting_max_torrents(50000)

        dlcfgfilename = get_default_dscfg_filename(self.sconfig.get_state_dir())
        self._logger.debug("main: Download config %s", dlcfgfilename)
        try:
            defaultDLConfig = DefaultDownloadStartupConfig.load(dlcfgfilename)
        except:
            try:
                defaultDLConfig = convertDefaultDownloadConfig(
                    os.path.join(state_dir, 'dlconfig.pickle'), dlcfgfilename)
            except:
                defaultDLConfig = DefaultDownloadStartupConfig.getInstance()

        if not defaultDLConfig.get_dest_dir():
            defaultDLConfig.set_dest_dir(get_default_dest_dir())
        if not os.path.isdir(defaultDLConfig.get_dest_dir()):
            try:
                os.makedirs(defaultDLConfig.get_dest_dir())
            except:
                # Could not create directory, ask user to select a different location
                dlg = wx.DirDialog(None,
                                   "Could not find download directory, please select a new location to store your downloads",
                                   style=wx.DEFAULT_DIALOG_STYLE)
                dlg.SetPath(get_default_dest_dir())
                if dlg.ShowModal() == wx.ID_OK:
                    new_dest_dir = dlg.GetPath()
                    defaultDLConfig.set_dest_dir(new_dest_dir)
                    defaultDLConfig.save(dlcfgfilename)
                    self.sconfig.save(cfgfilename)
                else:
                    # Quit
                    self.onError = lambda e: self._logger.error(
                        "tribler: quitting due to non-existing destination directory")
                    raise Exception()

        if not use_torrent_search:
            self.sconfig.set_enable_torrent_search(False)
        if not use_channel_search:
            self.sconfig.set_enable_torrent_search(False)

        session = Session(self.sconfig, autoload_discovery=autoload_discovery)

        # check and upgrade
        upgrader = session.prestart()
        if not upgrader.is_done:
            self._logger.error("Tribler upgrade failed.")
        return session

    def _frame_and_ready(self):
        return self.ready and self.frame and self.frame.ready

    def PostInit2(self):
        s = self.utility.session
        s.add_observer(self.sesscb_ntfy_reachable, NTFY_REACHABLE, [NTFY_INSERT])
        s.add_observer(self.sesscb_ntfy_activities, NTFY_ACTIVITIES, [NTFY_INSERT], cache=10)
        s.add_observer(self.sesscb_ntfy_channelupdates,
                       NTFY_CHANNELCAST, [NTFY_INSERT, NTFY_UPDATE, NTFY_CREATE, NTFY_STATE, NTFY_MODIFIED],
                       cache=10)
        s.add_observer(self.sesscb_ntfy_channelupdates, NTFY_VOTECAST, [NTFY_UPDATE], cache=10)
        s.add_observer(self.sesscb_ntfy_myprefupdates, NTFY_MYPREFERENCES, [NTFY_INSERT, NTFY_UPDATE, NTFY_DELETE])
        s.add_observer(self.sesscb_ntfy_torrentupdates, NTFY_TORRENTS, [NTFY_UPDATE, NTFY_INSERT], cache=10)
        s.add_observer(self.sesscb_ntfy_playlistupdates, NTFY_PLAYLISTS, [NTFY_INSERT, NTFY_UPDATE])
        s.add_observer(self.sesscb_ntfy_commentupdates, NTFY_COMMENTS, [NTFY_INSERT, NTFY_DELETE])
        s.add_observer(self.sesscb_ntfy_modificationupdates, NTFY_MODIFICATIONS, [NTFY_INSERT])
        s.add_observer(self.sesscb_ntfy_moderationupdats, NTFY_MODERATIONS, [NTFY_INSERT])
        s.add_observer(self.sesscb_ntfy_markingupdates, NTFY_MARKINGS, [NTFY_INSERT])
        s.add_observer(self.sesscb_ntfy_torrentfinished, NTFY_TORRENTS, [NTFY_FINISHED])
        s.add_observer(self.sesscb_ntfy_magnet,
                       NTFY_TORRENTS, [NTFY_MAGNET_GOT_PEERS, NTFY_MAGNET_STARTED, NTFY_MAGNET_CLOSE])

        # TODO(emilon): Use the LogObserver I already implemented
        # self.dispersy.callback.attach_exception_handler(self.frame.exceptionHandler)

    def startAPI(self, session):
        @call_on_reactor_thread
        def define_communities(*args):
            assert isInIOThread()
            from Tribler.community.channel.community import ChannelCommunity
            from Tribler.community.channel.preview import PreviewChannelCommunity
            from Tribler.community.tunnel.tunnel_community import TunnelSettings
            from Tribler.community.tunnel.hidden_community import HiddenTunnelCommunity
            from Tribler.community.bartercast4.community import BarterCommunity

            # make sure this is only called once
            session.remove_observer(define_communities)

            dispersy = session.get_dispersy_instance()

            self._logger.info("tribler: Preparing communities...")
            now = time()

            default_kwargs = {'tribler_session': session}
            # must be called on the Dispersy thread
            dispersy.define_auto_load(BarterCommunity, session.dispersy_member, load=True)

            # load metadata community
            dispersy.define_auto_load(ChannelCommunity, session.dispersy_member, load=True, kargs=default_kwargs)
            dispersy.define_auto_load(PreviewChannelCommunity, session.dispersy_member, kargs=default_kwargs)

            keypair = dispersy.crypto.generate_key(u"curve25519")
            dispersy_member = dispersy.get_member(private_key=dispersy.crypto.key_to_bin(keypair),)
            settings = TunnelSettings(session.get_install_dir(), tribler_session=session)
            tunnel_kwargs = {'tribler_session': session, 'settings': settings}

            self.tunnel_community = dispersy.define_auto_load(HiddenTunnelCommunity, dispersy_member, load=True,
                                                              kargs=tunnel_kwargs)[0]

            session.set_anon_proxy_settings(2, ("127.0.0.1", session.get_tunnel_community_socks5_listen_ports()))

            diff = time() - now
            self._logger.info("tribler: communities are ready in %.2f seconds", diff)

        session.add_observer(define_communities, NTFY_DISPERSY, [NTFY_STARTED])

        return session

    @staticmethod
    def determine_install_dir():
        # Niels, 2011-03-03: Working dir sometimes set to a browsers working dir
        # only seen on windows

        # apply trick to obtain the executable location
        # see http://www.py2exe.org/index.cgi/WhereAmI
        # Niels, 2012-01-31: py2exe should only apply to windows
        if sys.platform == 'win32':
            def we_are_frozen():
                """Returns whether we are frozen via py2exe.
                This will affect how we find out where we are located."""
                return hasattr(sys, "frozen")

            def module_path():
                """ This will get us the program's directory,
                even if we are frozen using py2exe"""
                if we_are_frozen():
                    return os.path.dirname(unicode(sys.executable, sys.getfilesystemencoding()))

                filedir = os.path.dirname(unicode(__file__, sys.getfilesystemencoding()))
                return os.path.abspath(os.path.join(filedir, '..', '..'))

            return module_path()
        return os.getcwdu()

    def sesscb_ntfy_myprefupdates(self, subject, changeType, objectID, *args):
        if self._frame_and_ready():
            if changeType in [NTFY_INSERT, NTFY_UPDATE]:
                if changeType == NTFY_INSERT:
                    if self.frame.searchlist:
                        manager = self.frame.searchlist.GetManager()
                        manager.downloadStarted(objectID)

                    manager = self.frame.selectedchannellist.GetManager()
                    manager.downloadStarted(objectID)

                manager = self.frame.librarylist.GetManager()
                manager.downloadStarted(objectID)
            elif changeType == NTFY_DELETE:
                self.guiUtility.frame.librarylist.RemoveItem(objectID)

                if self.guiUtility.frame.librarylist.IsShownOnScreen() and \
                   self.guiUtility.frame.librarydetailspanel.torrent and \
                   self.guiUtility.frame.librarydetailspanel.torrent.infohash == objectID:
                    self.guiUtility.frame.librarylist.ResetBottomWindow()
                    self.guiUtility.frame.top_bg.ClearButtonHandlers()

                if self.guiUtility.frame.librarylist.list.IsEmpty():
                    self.guiUtility.frame.librarylist.SetData([])

    def sesscb_states_callback(self, dslist):
        if not self.ready:
            return 5.0, []

        wantpeers = []
        self.ratestatecallbackcount += 1
        try:
            # Print stats on Console
            if self.ratestatecallbackcount % 5 == 0:
                for ds in dslist:
                    safename = repr(ds.get_download().get_def().get_name())
                    self._logger.debug(
                        "%s %s %.1f%% dl %.1f ul %.1f n %d",
                        safename,
                        dlstatus_strings[ds.get_status()],
                        100.0 * ds.get_progress(),
                        ds.get_current_speed(DOWNLOAD),
                        ds.get_current_speed(UPLOAD),
                        ds.get_num_peers())
                    if ds.get_status() == DLSTATUS_STOPPED_ON_ERROR:
                        self._logger.error("main: Error: %s", repr(ds.get_error()))
                        # show error dialog
                        dlg = wx.MessageDialog(self.frame,
                                               "Download stopped on error: %s" % repr(ds.get_error()),
                                               "Download Error",
                                               wx.OK | wx.ICON_ERROR)
                        dlg.ShowModal()
                        dlg.Destroy()

            # Pass DownloadStates to libaryView
            no_collected_list = [ds for ds in dslist]
            try:
                # Arno, 2012-07-17: Retrieving peerlist for the DownloadStates takes CPU
                # so only do it when needed for display.
                # wantpeers.extend(self.guiUtility.library_manager.download_state_callback(no_collected_list))
                pass
            except:
                print_exc()

            # Check to see if a download has finished
            newActiveDownloads = []
            doCheckpoint = False
            for ds in dslist:
                state = ds.get_status()
                download = ds.get_download()
                tdef = download.get_def()
                safename = tdef.get_name_as_unicode()

                if state == DLSTATUS_DOWNLOADING:
                    newActiveDownloads.append(safename)

                elif state == DLSTATUS_SEEDING:

                    if safename in self.prevActiveDownloads:
                        infohash = tdef.get_infohash()

                        self.utility.session.notifier.notify(NTFY_TORRENTS, NTFY_FINISHED, infohash, safename)

                        doCheckpoint = True

                    if download.get_hops() == 0 and download.get_safe_seeding():
                        self._logger.info("Re-add torrent with default nr of hops to prevent naked seeding")
                        self.utility.session.remove_download(download)

                        # copy the old download_config and change the hop count
                        dscfg = download.copy()
                        dscfg.set_hops(self.utility.read_config('default_number_hops'))
                        reactor.callInThread(self.utility.session.start_download, tdef, dscfg)

            self.prevActiveDownloads = newActiveDownloads
            if doCheckpoint:
                self.utility.session.checkpoint()

            # Adjust speeds and call TunnelCommunity.monitor_downloads once every 4 seconds
            adjustspeeds = False
            if self.ratestatecallbackcount % 4 == 0:
                adjustspeeds = True

            if adjustspeeds and self.tunnel_community:
                self.tunnel_community.monitor_downloads(dslist)

        except:
            print_exc()

        self.lastwantpeers = wantpeers
        return 1.0, wantpeers

    def loadSessionCheckpoint(self):
        pstate_dir = self.utility.session.get_downloads_pstate_dir()

        filelist = os.listdir(pstate_dir)
        if any([filename.endswith('.pickle') for filename in filelist]):
            convertDownloadCheckpoints(pstate_dir)

        from Tribler.Main.vwxGUI.UserDownloadChoice import UserDownloadChoice
        user_download_choice = UserDownloadChoice.get_singleton()
        initialdlstatus_dict = {}
        for infohash, state in user_download_choice.get_download_states().iteritems():
            if state == 'stop':
                initialdlstatus_dict[infohash] = DLSTATUS_STOPPED

        self.utility.session.load_checkpoint(initialdlstatus_dict=initialdlstatus_dict)

    def guiservthread_free_space_check(self):
        if not (self and self.frame and self.frame.SRstatusbar):
            return

        free_space = get_free_space(DefaultDownloadStartupConfig.getInstance().get_dest_dir())
        self.frame.SRstatusbar.RefreshFreeSpace(free_space)

        storage_locations = defaultdict(list)
        for download in self.utility.session.get_downloads():
            if download.get_status() == DLSTATUS_DOWNLOADING:
                storage_locations[download.get_dest_dir()].append(download)

        show_message = False
        low_on_space = [
            path for path in storage_locations.keys(
            ) if 0 < get_free_space(
                path) < self.utility.read_config(
                'free_space_threshold')]
        for path in low_on_space:
            for download in storage_locations[path]:
                download.stop()
                show_message = True

        if show_message:
            wx.CallAfter(wx.MessageBox, "Tribler has detected low disk space. Related downloads have been stopped.",
                         "Error")

        self.utility.session.lm.threadpool.call_in_thread(FREE_SPACE_CHECK_INTERVAL, self.guiservthread_free_space_check)

    def guiservthread_checkpoint_timer(self):
        """ Periodically checkpoint Session """
        if self.done:
            return
        try:
            self._logger.info("main: Checkpointing Session")
            self.utility.session.checkpoint()

            self.utility.session.lm.threadpool.call_in_thread(SESSION_CHECKPOINT_INTERVAL, self.guiservthread_checkpoint_timer)
        except:
            print_exc()

    def sesscb_ntfy_activities(self, events):
        if self._frame_and_ready():
            for args in events:
                objectID = args[2]
                args = args[3:]

                self.frame.setActivity(objectID, *args)

    def sesscb_ntfy_reachable(self, subject, changeType, objectID, msg):
        if self._frame_and_ready():
            self.frame.SRstatusbar.onReachable()

    def sesscb_ntfy_channelupdates(self, events):
        if self._frame_and_ready():
            for args in events:
                subject = args[0]
                changeType = args[1]
                objectID = args[2]

                if self.frame.channellist:
                    if len(args) > 3:
                        myvote = args[3]
                    else:
                        myvote = False

                    manager = self.frame.channellist.GetManager()
                    manager.channelUpdated(objectID, subject == NTFY_VOTECAST, myvote=myvote)

                manager = self.frame.selectedchannellist.GetManager()
                manager.channelUpdated(
                    objectID,
                    stateChanged=changeType == NTFY_STATE,
                    modified=changeType == NTFY_MODIFIED)

                if changeType == NTFY_CREATE:
                    if self.frame.channellist:
                        self.frame.channellist.SetMyChannelId(objectID)

                self.frame.managechannel.channelUpdated(
                    objectID,
                    created=changeType == NTFY_CREATE,
                    modified=changeType == NTFY_MODIFIED)

    def sesscb_ntfy_torrentupdates(self, events):
        if self._frame_and_ready():
            infohashes = [args[2] for args in events]

            if self.frame.searchlist:
                manager = self.frame.searchlist.GetManager()
                manager.torrentsUpdated(infohashes)

                manager = self.frame.selectedchannellist.GetManager()
                manager.torrentsUpdated(infohashes)

                manager = self.frame.playlist.GetManager()
                manager.torrentsUpdated(infohashes)

                manager = self.frame.librarylist.GetManager()
                manager.torrentsUpdated(infohashes)

            from Tribler.Main.Utility.GuiDBTuples import CollectedTorrent

            if self.frame.torrentdetailspanel.torrent and self.frame.torrentdetailspanel.torrent.infohash in infohashes:
                # If an updated torrent is being shown in the detailspanel, make sure the information gets refreshed.
                t = self.frame.torrentdetailspanel.torrent
                torrent = t.torrent if isinstance(t, CollectedTorrent) else t
                self.frame.torrentdetailspanel.setTorrent(torrent)

            if self.frame.librarydetailspanel.torrent and self.frame.librarydetailspanel.torrent.infohash in infohashes:
                t = self.frame.librarydetailspanel.torrent
                torrent = t.torrent if isinstance(t, CollectedTorrent) else t
                self.frame.librarydetailspanel.setTorrent(torrent)

    def sesscb_ntfy_torrentfinished(self, subject, changeType, objectID, *args):
        self.guiUtility.Notify(
            "Download Completed", "Torrent '%s' has finished downloading. Now seeding." %
            args[0], icon='seed')

        if self._frame_and_ready():
            infohash = objectID
            torrent = self.guiUtility.torrentsearch_manager.getTorrentByInfohash(infohash)
            self.guiUtility.library_manager.addDownloadState(torrent)

    def sesscb_ntfy_magnet(self, subject, changetype, objectID, *args):
        if changetype == NTFY_MAGNET_STARTED:
            self.guiUtility.library_manager.magnet_started(objectID)
        elif changetype == NTFY_MAGNET_GOT_PEERS:
            self.guiUtility.library_manager.magnet_got_peers(objectID, args[0])
        elif changetype == NTFY_MAGNET_CLOSE:
            self.guiUtility.library_manager.magnet_close(objectID)

    def sesscb_ntfy_playlistupdates(self, subject, changeType, objectID, *args):
        if self._frame_and_ready():
            if changeType == NTFY_INSERT:
                self.frame.managechannel.playlistCreated(objectID)

                manager = self.frame.selectedchannellist.GetManager()
                manager.playlistCreated(objectID)

            else:
                self.frame.managechannel.playlistUpdated(objectID, modified=changeType == NTFY_MODIFIED)

                if len(args) > 0:
                    infohash = args[0]
                else:
                    infohash = False
                manager = self.frame.selectedchannellist.GetManager()
                manager.playlistUpdated(objectID, infohash, modified=changeType == NTFY_MODIFIED)

                manager = self.frame.playlist.GetManager()
                manager.playlistUpdated(objectID, modified=changeType == NTFY_MODIFIED)

    def sesscb_ntfy_commentupdates(self, subject, changeType, objectID, *args):
        if self._frame_and_ready():
            self.frame.selectedchannellist.OnCommentCreated(objectID)
            self.frame.playlist.OnCommentCreated(objectID)

    def sesscb_ntfy_modificationupdates(self, subject, changeType, objectID, *args):
        if self._frame_and_ready():
            self.frame.selectedchannellist.OnModificationCreated(objectID)
            self.frame.playlist.OnModificationCreated(objectID)

    def sesscb_ntfy_moderationupdats(self, subject, changeType, objectID, *args):
        if self._frame_and_ready():
            self.frame.selectedchannellist.OnModerationCreated(objectID)
            self.frame.playlist.OnModerationCreated(objectID)

    def sesscb_ntfy_markingupdates(self, subject, changeType, objectID, *args):
        if self._frame_and_ready():
            self.frame.selectedchannellist.OnMarkingCreated(objectID)
            self.frame.playlist.OnModerationCreated(objectID)

    def onError(self, e):
        print_exc()

    def OnExit(self):
        self._logger.info("main: ONEXIT")
        self.ready = False
        self.done = True

        # write all persistent data to disk
        if self.webUI:
            self.webUI.stop()
            self.webUI.delInstance()

        # Don't checkpoint, interferes with current way of saving Preferences,
        # see Tribler/Main/Dialogs/abcoption.py
        if self.utility:
            # Niels: lets add a max waiting time for this session shutdown.
            session_shutdown_start = time()

            try:
                self._logger.info("ONEXIT cleaning database")
                torrent_db = self.utility.session.open_dbhandler(NTFY_TORRENTS)
                torrent_db._db.clean_db(randint(0, 24) == 0, exiting=True)
            except:
                print_exc()

            self._logger.info("ONEXIT shutdown session")
            self.utility.session.shutdown(hacksessconfcheckpoint=False)

            # Arno, 2012-07-12: Shutdown should be quick
            # Niels, 2013-03-21: However, setting it too low will prevent checkpoints from being written to disk
            waittime = 60
            while not self.utility.session.has_shutdown():
                diff = time() - session_shutdown_start
                if diff > waittime:
                    self._logger.info("main: ONEXIT NOT Waiting for Session to shutdown, took too long")
                    break

                self._logger.info(
                    "ONEXIT Waiting for Session to shutdown, will wait for an additional %d seconds",
                    waittime - diff)
                sleep(3)
            self._logger.info("ONEXIT Session is shutdown")

        self._logger.debug("ONEXIT deleting instances")

        Session.del_instance()
        DefaultDownloadStartupConfig.delInstance()

        return 0

    def db_exception_handler(self, e):
        self._logger.debug("Database Exception handler called %s value %s #", e, e.args)
        try:
            if e.args[1] == "DB object has been closed":
                return  # We caused this non-fatal error, don't show.
            if self.error is not None and self.error.args[1] == e.args[1]:
                return  # don't repeat same error
        except:
            self._logger.error("db_exception_handler error %s %s", e, type(e))
            print_exc()
            # print_stack()

        self.onError(e)

    def getConfigPath(self):
        return self.utility.getConfigPath()

    def i2ithread_readlinecallback(self, ic, cmd):
        """ Called by Instance2Instance thread """

        self._logger.info("main: Another instance called us with cmd %s", cmd)
        ic.close()

        if cmd.startswith('START '):
            param = cmd[len('START '):].strip()
            torrentfilename = None
            if param.startswith('http:'):
                # Retrieve from web
                f = tempfile.NamedTemporaryFile()
                n = urllib2.urlopen(param)
                data = n.read()
                f.write(data)
                f.close()
                n.close()
                torrentfilename = f.name
            else:
                torrentfilename = param

            # Switch to GUI thread
            # New for 5.0: Start in VOD mode
            def start_asked_download():
                if torrentfilename.startswith("magnet:"):
                    self.frame.startDownloadFromMagnet(torrentfilename)
                else:
                    self.frame.startDownload(torrentfilename)
                self.guiUtility.ShowPage('my_files')

            wx.CallAfter(start_asked_download)
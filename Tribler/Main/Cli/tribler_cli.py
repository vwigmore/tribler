import logging
import os
import sys
from random import randint
from traceback import print_exc
from Tribler.Category.Category import Category
from Tribler.Core.osutils import get_free_space
from Tribler.Core.DownloadConfig import get_default_dest_dir, get_default_dscfg_filename
from Tribler.Core.Utilities.twisted_thread import reactor, stop_reactor
from Tribler.Core.simpledefs import (DLSTATUS_DOWNLOADING, DLSTATUS_SEEDING, DLSTATUS_STOPPED,
                                     DLSTATUS_STOPPED_ON_ERROR, DOWNLOAD, NTFY_ACTIVITIES, NTFY_CHANNELCAST,
                                     NTFY_COMMENTS, NTFY_CREATE, NTFY_DELETE, NTFY_DISPERSY, NTFY_FINISHED, NTFY_INSERT,
                                     NTFY_MAGNET_CLOSE, NTFY_MAGNET_GOT_PEERS, NTFY_MAGNET_STARTED, NTFY_MARKINGS,
                                     NTFY_MODERATIONS, NTFY_MODIFICATIONS, NTFY_MODIFIED, NTFY_MYPREFERENCES,
                                     NTFY_PLAYLISTS, NTFY_REACHABLE, NTFY_STARTED, NTFY_STATE, NTFY_TORRENTS,
                                     NTFY_UPDATE, NTFY_VOTECAST, UPLOAD, dlstatus_strings, STATEDIR_GUICONFIG)
from Tribler.Core.Session import Session
from Tribler.Core.SessionConfig import SessionStartupConfig
from Tribler.Core.Utilities.install_dir import determine_install_dir
from Tribler.Main.globals import DefaultDownloadStartupConfig
from Tribler.Main.Utility.compat import (convertDefaultDownloadConfig, convertDownloadCheckpoints, convertMainConfig,
                                         convertSessionConfig)
from Tribler.Main.Utility.utility import Utility, size_format, speed_format
from Tribler.Main.Utility.GuiDBHandler import startWorker, GUIDBProducer
from Tribler.dispersy.util import call_on_reactor_thread

from time import time, sleep

SESSION_CHECKPOINT_INTERVAL = 900.0  # 15 minutes

class TriblerCommandLine:

    def __init__(self):
        self._logger = logging.getLogger(self.__class__.__name__)
        self.install_dir = determine_install_dir()
        self.dslist = []
        self.firewall_reachable = False

    def get_total_connections(self):
        if self.session.lm.dispersy:
            for community in self.session.lm.dispersy.get_communities():
                from Tribler.community.search.community import SearchCommunity

                if isinstance(community, SearchCommunity):
                    return community.get_nr_connections()

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

    def sesscb_ntfy_reachable(self, subject, changeType, objectID, msg):
        self.firewall_reachable = True

    def sesscb_states_callback(self, dslist):
        if not self.ready:
            return 5.0, []

        self.dslist = dslist
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

            # Pass DownloadStates to libaryView
            no_collected_list = [ds for ds in dslist]

            # Check to see if a download has finished
            newActiveDownloads = []
            doCheckpoint = False
            seeding_download_list = []
            for ds in dslist:
                state = ds.get_status()
                download = ds.get_download()
                tdef = download.get_def()
                safename = tdef.get_name_as_unicode()

                if state == DLSTATUS_DOWNLOADING:
                    newActiveDownloads.append(safename)

                elif state == DLSTATUS_SEEDING:
                    seeding_download_list.append({u'infohash': tdef.get_infohash(),
                                                  u'download': download,
                                                  })

                    if safename in self.prevActiveDownloads:
                        infohash = tdef.get_infohash()

                        self.utility.session.notifier.notify(NTFY_TORRENTS, NTFY_FINISHED, infohash, safename)

                        doCheckpoint = True

                    elif download.get_hops() == 0 and download.get_safe_seeding():
                        self._logger.info("Re-add torrent with default nr of hops to prevent naked seeding")
                        self.utility.session.remove_download(download)

                        # copy the old download_config and change the hop count
                        dscfg = download.copy()
                        dscfg.set_hops(self.utility.read_config('default_number_hops'))
                        reactor.callInThread(self.utility.session.start_download, tdef, dscfg)

            self.prevActiveDownloads = newActiveDownloads
            if doCheckpoint:
                self.utility.session.checkpoint()

            if self.utility.read_config(u'seeding_mode') == 'never':
                for data in seeding_download_list:
                    data[u'download'].stop()
                    from Tribler.Main.vwxGUI.UserDownloadChoice import UserDownloadChoice
                    UserDownloadChoice.get_singleton().set_download_state(data[u'infohash'], "stop")

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

    def start_api(self):
        @call_on_reactor_thread
        def define_communities(*args):
            from Tribler.community.channel.community import ChannelCommunity
            from Tribler.community.channel.preview import PreviewChannelCommunity
            from Tribler.community.tunnel.tunnel_community import TunnelSettings
            from Tribler.community.tunnel.hidden_community import HiddenTunnelCommunity

            # make sure this is only called once
            self.session.remove_observer(define_communities)

            dispersy = self.session.get_dispersy_instance()

            self._logger.info("tribler: Preparing communities...")
            now = time()

            default_kwargs = {'tribler_session': self.session}
            # must be called on the Dispersy thread
            if self.session.get_barter_community_enabled():
                from Tribler.community.bartercast4.community import BarterCommunity
                dispersy.define_auto_load(BarterCommunity, self.session.dispersy_member, load=True)

            # load metadata community
            dispersy.define_auto_load(ChannelCommunity, self.session.dispersy_member, load=True, kargs=default_kwargs)
            dispersy.define_auto_load(PreviewChannelCommunity, self.session.dispersy_member, kargs=default_kwargs)

            keypair = dispersy.crypto.generate_key(u"curve25519")
            dispersy_member = dispersy.get_member(private_key=dispersy.crypto.key_to_bin(keypair),)
            settings = TunnelSettings(self.session.get_install_dir(), tribler_session=self.session)
            tunnel_kwargs = {'tribler_session': self.session, 'settings': settings}

            self.tunnel_community = dispersy.define_auto_load(HiddenTunnelCommunity, dispersy_member, load=True,
                                                              kargs=tunnel_kwargs)[0]

            self.session.set_anon_proxy_settings(2, ("127.0.0.1", self.session.get_tunnel_community_socks5_listen_ports()))

            diff = time() - now
            self._logger.info("tribler: communities are ready in %.2f seconds", diff)

        self.session.add_observer(define_communities, NTFY_DISPERSY, [NTFY_STARTED])

    def stage1_start(self):
        """ Stage 1 start: pre-start the session to handle upgrade.
        """

        # Make sure the installation dir is on the PATH
        os.environ['PATH'] += os.pathsep + os.path.abspath(self.install_dir)

        # Start Tribler Session
        defaultConfig = SessionStartupConfig()
        state_dir = defaultConfig.get_state_dir()

        # Switch to the state dir so relative paths can be used (IE, in LevelDB store paths)
        if not os.path.exists(state_dir):
            os.makedirs(state_dir)
        os.chdir(state_dir)

        cfgfilename = Session.get_default_config_filename(state_dir)

        self._logger.debug(u"Session config %s", cfgfilename)
        try:
            self.sconfig = SessionStartupConfig.load(cfgfilename)
        except:
            try:
                self.sconfig = convertSessionConfig(os.path.join(state_dir, 'sessconfig.pickle'), cfgfilename)
                convertMainConfig(state_dir, os.path.join(state_dir, 'abc.conf'),
                                  os.path.join(state_dir, STATEDIR_GUICONFIG))
            except:
                self.sconfig = SessionStartupConfig()
                self.sconfig.set_state_dir(state_dir)

        self.sconfig.set_install_dir(self.install_dir)

        # TODO(emilon): Do we still want to force limit this? With the new
        # torrent store it should be pretty fast even with more that that.

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
                # Quit
                self.onError = lambda e: self._logger.error(
                    "tribler: quitting due to non-existing destination directory")
                raise Exception()

        self.session = Session(self.sconfig, autoload_discovery=True)

        # check and upgrade
        upgrader = self.session.prestart()
        if not upgrader.is_done:
            sleep(0.1)

    def start_tribler(self):
        self.ready = False
        self.stage1_start()
        print "Stage 1 init finished"
        self.start_api()
        print "Started API"

        self.utility = Utility(self.install_dir, self.session.get_state_dir())
        if self.utility.read_config(u'saveas'):
            DefaultDownloadStartupConfig.getInstance().set_dest_dir(self.utility.read_config(u'saveas'))
        self.utility.set_session(self.session)

        self.session.start()
        print "Started session"

        GUIDBProducer.getInstance().utility = self.utility

        from Tribler.Main.vwxGUI.UserDownloadChoice import UserDownloadChoice
        UserDownloadChoice.get_singleton().set_utility(self.utility)

        cat = Category.getInstance(self.session)

        state = self.utility.read_config('family_filter')
        if state in (1, 0):
            cat.set_family_filter(state == 1)
        else:
            self.utility.write_config('family_filter', 1)
            self.utility.flush_config()

            cat.set_family_filter(True)

        # Counter to suppress some event from occurring
        self.ratestatecallbackcount = 0

        # So we know if we asked for peer details last cycle
        self.lastwantpeers = []

        maxup = self.utility.read_config('maxuploadrate')
        maxdown = self.utility.read_config('maxdownloadrate')
        # set speed limits using LibtorrentMgr
        self.session.set_max_upload_speed(maxup)
        self.session.set_max_download_speed(maxdown)

        # Only allow updates to come in after we defined ratelimiter
        self.prevActiveDownloads = []
        self.session.set_download_states_callback(self.sesscb_states_callback)

        # Schedule task for checkpointing Session, to avoid hash checks after
        # crashes.
        startWorker(consumer=None, workerFn=self.guiservthread_checkpoint_timer, delay=SESSION_CHECKPOINT_INTERVAL)
        startWorker(None, self.loadSessionCheckpoint, delay=1.0, workerType="ThreadPool")

        self.session.add_observer(self.sesscb_ntfy_reachable, NTFY_REACHABLE, [NTFY_INSERT])

        self.ready = True

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

    def show_settings(self):
        defaultDLConfig = DefaultDownloadStartupConfig.getInstance()
        print "\n--- GENERAL ---"
        print "Family filter enabled: %s" % Category.getInstance().family_filter_enabled()
        print "Nickname: %s" % self.session.get_nickname()
        print "Download location: %s" % defaultDLConfig.get_dest_dir()
        print "Choose location for every download: %s" % self.utility.read_config('showsaveas')
        if sys.platform != "darwin":
            print "Minimize to tray: %s" % self.utility.read_config('mintray')

        print "\n--- Connection ---"
        print "Current port: %s" % self.utility.session.get_listen_port()
        print "UTP enabled: %s" % self.utility.session.get_libtorrent_utp()
        # TODO finish...

    def show_tribler_status(self):
        free_space = get_free_space(DefaultDownloadStartupConfig.getInstance().get_dest_dir())
        print "Free space: %s" % size_format(free_space, truncate=1)

        # calculate the up/down speeds
        total_down, total_up = 0.0, 0.0
        for ds in self.dslist:
            total_down += ds.get_current_speed(DOWNLOAD)
            total_up += ds.get_current_speed(UPLOAD)

        print "Upload speed: %s" % speed_format(total_up)
        print "Download speed: %s" % speed_format(total_down)
        print "Total downloads: %s" % len(self.dslist)

        print "Firewall reachable: %s" % self.firewall_reachable
        print "Number of connections: %s" % self.get_total_connections()

    def show_downloads(self):
        index = 1
        for dstatus in self.dslist:
            print "1) %s" % dstatus.get_status()

    def close_tribler(self):
        self._logger.info("main: ONEXIT")
        self.ready = False
        self.done = True

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

    def run(self):
        self.start_tribler()
        print "Welcome to Tribler CLI!"
        while True:
            print "1) Print settings"
            print "2) Tribler status info"
            print "3) Add torrent"
            print "4) Show downloads"
            print "5) Exit"
            input = raw_input("Please select option: ")
            if input == "1":
                self.show_settings()
            elif input == "2":
                self.show_tribler_status()
            elif input == "3":
                pass
            elif input == "4":
                self.show_downloads()
            elif input == "5":
                print "Will exit Tribler..."
                break
        self._logger.info("Client shutting down. Sleeping for a few seconds to allow other threads to finish")
        self.close_tribler()

if __name__ == '__main__':
    TriblerCommandLine().run()
    delayed_calls = reactor.getDelayedCalls()
    if delayed_calls:
        print >> sys.stderr, "The reactor was not clean after stopping:"
        for dc in delayed_calls:
            print >> sys.stderr, ">     %s" % dc

    stop_reactor()
import logging.config
import sys
import os
from traceback import print_exc
from Tribler.Utilities.SingleInstanceChecker import SingleInstanceChecker
from Tribler.Core.SessionConfig import SessionStartupConfig
from Tribler.Utilities.Instance2Instance import Instance2InstanceClient, Instance2InstanceServer
from Tribler.Main.Utility.utility import Utility
from Tribler.Main.TriblerStartupManager import TriblerStartupManager
from Tribler.Main.globals import DefaultDownloadStartupConfig
from Tribler.Core.StartTorrentDownloadManager import StartTorrentDownloadManager

ALLOW_MULTIPLE = os.environ.get("TRIBLER_ALLOW_MULTIPLE", "False").lower() == "true"

if sys.platform == 'win32':
    import win32api
    path_env = win32api.GetEnvironmentVariableW(u'PATH')
    path_env = os.path.abspath(u'vlc') + os.pathsep + path_env
    path_env = os.path.abspath(u'.') + os.pathsep + path_env
    win32api.SetEnvironmentVariableW(u'PATH', path_env)

try:
    logging.config.fileConfig("logger.conf")
except Exception as e:
    print >> sys.stderr, "Unable to load logging config from 'logger.conf' file: %s" % repr(e)
logging.basicConfig(format="%(asctime)-15s [%(levelname)s] %(message)s")

logger = logging.getLogger(__name__)

# This import needs to be before any twisted or dispersy import so it can initalize the reactor in a separate thread
# No need to do reactor.run(), it gets started when imported
from Tribler.Core.Utilities.twisted_thread import reactor, stop_reactor

# set wxpython version
import wxversion
try:
    # in the windows and mac distribution, there may be no version available.
    # so select a version only when there is any available.
    if wxversion.getInstalled():
        wxversion.select("2.8-unicode")
except wxversion.VersionError:
    logger.exception("Unable to use wxversion installed wxversions: %s", repr(wxversion.getInstalled()))

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


def show_settings(startupmanager):
    defaultDLConfig = DefaultDownloadStartupConfig.getInstance()
    print "\n--- GENERAL ---"
    print "Nickname: %s" % startupmanager.utility.session.get_nickname()
    print "Download location: %s" % defaultDLConfig.get_dest_dir()
    print "Choose location for every download: %s" % startupmanager.utility.read_config('showsaveas')
    if sys.platform != "darwin":
        print "Minimize to tray: %s" % startupmanager.utility.read_config('mintray')

    print "\n--- Connection ---"
    print "Current port: %s" % startupmanager.utility.session.get_listen_port()
    print "UTP enabled: %s" % startupmanager.utility.session.get_libtorrent_utp()
    # TODO finish...


def add_torrent(startupmanager):
    print "Please select your option (1 = add from path, 2 = add from magnet/url):"
    input = raw_input("Option: ")
    if input == "1":
        filename = raw_input("Path: ")
        start_torrent_mgr = StartTorrentDownloadManager(startupmanager.utility)
        start_torrent_mgr.startDownload(filename)
    elif input == "2":
        filename = raw_input("Link: ")
        start_torrent_mgr = StartTorrentDownloadManager(startupmanager.utility)
        start_torrent_mgr.startDownloadFromArg(filename)


def run(params=None, autoload_discovery=True, use_torrent_search=True, use_channel_search=True):
    if params is None:
        params = [""]

    if len(sys.argv) > 1:
        params = sys.argv[1:]
    try:
        startupmanager = None
        # Create single instance semaphore
        single_instance_checker = SingleInstanceChecker("tribler")

        installdir = determine_install_dir()

        if not ALLOW_MULTIPLE and single_instance_checker.IsAnotherRunning():
            statedir = SessionStartupConfig().get_state_dir()

            # Send  torrent info to abc single instance
            if params[0] != "":
                torrentfilename = params[0]
                i2i_port = Utility(installdir, statedir).read_config('i2ilistenport')
                Instance2InstanceClient(i2i_port, 'START', torrentfilename)

            logger.info("Client shutting down. Detected another instance.")
        else:

            if sys.platform == 'linux2' and os.environ.get("TRIBLER_INITTHREADS", "true").lower() == "true":
                try:
                    import ctypes
                    x11 = ctypes.cdll.LoadLibrary('libX11.so.6')
                    x11.XInitThreads()
                    os.environ["TRIBLER_INITTHREADS"] = "False"
                except OSError as e:
                    logger.debug("Failed to call XInitThreads '%s'", str(e))
                except:
                    logger.exception('Failed to call xInitThreads')

            startupmanager = TriblerStartupManager(params, installdir, autoload_discovery=autoload_discovery,
                         use_torrent_search=use_torrent_search, use_channel_search=use_channel_search)
            utility = startupmanager.utility
            print utility.session.get_listen_port()

        print "Welcome to Tribler CLI!"
        while True:
            print "1) Print settings"
            print "2) Add torrent"
            print "3) Exit"
            input = raw_input("Please select option: ")
            if input == "1":
                show_settings(startupmanager)
            elif input == "2":
                add_torrent(startupmanager)
            elif input == "3":
                print "Will exit Tribler..."
                break
        startupmanager.OnExit()
        logger.info("Client shutting down. Sleeping for a few seconds to allow other threads to finish")

    except:
        print_exc()

if sys.version_info[:2] != (2, 7):
    print >> sys.stderr, "Tribler needs python 2.7.X to run, current version: %s" % sys.version
    exit(1)

if __name__ == '__main__':

    run()
    delayed_calls = reactor.getDelayedCalls()
    if delayed_calls:
        print >> sys.stderr, "The reactor was not clean after stopping:"
        for dc in delayed_calls:
            print >> sys.stderr, ">     %s" % dc

    stop_reactor()

import os
import logging
from traceback import print_exc

from Tribler.Core.TorrentDef import TorrentDef, TorrentDefNoMetainfo
from Tribler.Core.Utilities.utilities import parse_magnetlink
from Tribler.Core.Video.utils import videoextdefaults
from Tribler.Core.Utilities.utilities import parse_magnetlink, fix_torrent
from Tribler.Core.exceptions import DuplicateDownloadException
from Tribler.Main.globals import DefaultDownloadStartupConfig
from urllib import url2pathname


class StartTorrentDownloadManager():

    def __init__(self, utility):
        self._logger = logging.getLogger(self.__class__.__name__)
        self.utility = utility

    def startCMDLineTorrent(self):
        if self.params[0] != "" and not self.params[0].startswith("--"):
            vod = False
            selectedFiles = [self.params[1]] if len(self.params) == 2 else None
            if selectedFiles:
                _, ext = os.path.splitext(selectedFiles[0])
                if ext != '' and ext[0] == '.':
                    ext = ext[1:]
                if ext.lower() in videoextdefaults:
                    vod = True

            self.startDownloadFromArg(self.params[0], cmdline=True, selectedFiles=selectedFiles, vodmode=vod)

    def startDownloadFromArg(self, argument, destdir=None, cmdline=False, selectedFiles = None, vodmode=False):
        if argument.startswith("magnet:"):
            self.startDownloadFromMagnet(argument, destdir=destdir, cmdline=cmdline, selectedFiles=selectedFiles, vodmode=vodmode)
            return True

        if argument.startswith("http"):
            self.startDownloadFromUrl(argument, destdir=destdir, cmdline=cmdline, selectedFiles=selectedFiles, vodmode=vodmode)
            return True

        if argument.startswith("emc:"):
            self.startDownloadFromEMC(argument, destdir=destdir, cmdline=cmdline, selectedFiles=selectedFiles, vodmode=vodmode)
            return True

        if argument.startswith("file:"):
            argument = url2pathname(argument[5:])
            self.startDownload(argument, destdir=destdir, cmdline=cmdline, selectedFiles=selectedFiles, vodmode=vodmode)
            return True

        if cmdline:
            self.startDownload(argument, destdir=destdir, cmdline=cmdline, selectedFiles=selectedFiles, vodmode=vodmode)
            return True

        return False

    def startDownloadFromMagnet(self, url, destdir=None, cmdline=False, selectedFiles=None, vodmode=False, hops=0):
        name, infohash, _ = parse_magnetlink(url)
        if name is None:
            name = ""
        try:
            if infohash is None:
                raise RuntimeError("Missing infohash")
            tdef = TorrentDefNoMetainfo(infohash, name, url=url)
            self.startDownload(tdef=tdef, cmdline=cmdline, destdir=destdir, selectedFiles=selectedFiles,
                               vodmode=vodmode, hops = 0)
        except Exception, e:
            # show an error dialog
            self._logger.error("The magnet link is invalid: %s" % str(e))
        return True

    def startDownloadFromUrl(self, url, destdir=None, cmdline=False, selectedFiles=None, vodmode=False, hops=0):
        try:
            tdef = TorrentDef.load_from_url(url)
            if tdef:
                kwargs = {'tdef': tdef,
                          'cmdline': cmdline,
                          'destdir': destdir,
                          'selectedFiles': selectedFiles,
                          'vodmode': vodmode,
                          'hops': hops}
                self.startDownload(**kwargs)
                return True
        except:
            print_exc()
            self._logger("download from URL failed!")
        return False

    def startDownloadFromEMC(self, url, destdir=None, cmdline=False, selectedFiles=None, vodmode=False, hops=0):
        if self.utility.read_config('use_emc'):
            url = "magnet:"+url[4:] #replace emc: with magnet:
            magnet_link = self.abc.emercoin_mgr.fetch_key(url)

            return self.startDownloadFromMagnet(magnet_link, destdir, cmdline, selectedFiles, vodmode, hops)
        return False

    def startDownload(self, torrentfilename=None, destdir=None, infohash=None, tdef=None, cmdline=False,
                      vodmode=False, hops=0, selectedFiles=None, hidden=False):
        self._logger.debug(u"startDownload: %s %s %s %s %s", torrentfilename, destdir, tdef, vodmode, selectedFiles)

        # TODO(lipu): remove the assertions after it becomes stable
        if infohash is not None:
            assert isinstance(infohash, str), "infohash type: %s" % type(infohash)
            assert len(infohash) == 20, "infohash length is not 20: %s, %s" % (len(infohash), infohash)

        # the priority of the parameters is: (1) tdef, (2) infohash, (3) torrent_file.
        # so if we have tdef, infohash and torrent_file will be ignored, and so on.
        if tdef is None:
            if infohash is not None:
                # try to get the torrent from torrent_store if the infohash is provided
                torrent_data = self.utility.session.get_collected_torrent(infohash)
                if torrent_data is not None:
                    # use this torrent data for downloading
                    tdef = TorrentDef.load_from_memory(torrent_data)

            if tdef is None:
                assert torrentfilename is not None, "torrent file must be provided if tdef and infohash are not given"
                # try to get the torrent from the given torrent file
                torrent_data = fix_torrent(torrentfilename)
                if torrent_data is None:
                    # show error message: could not open torrent file
                    self._logger.error("Could not open torrent file %s" % torrentfilename)
                    return

                tdef = TorrentDef.load_from_memory(torrent_data)

        assert tdef is not None, "tdef MUST not be None after loading torrent"

        try:
            d = self.utility.session.get_download(tdef.get_infohash())
            if d:
                new_trackers = list(set(tdef.get_trackers_as_single_tuple()) - set(
                    d.get_def().get_trackers_as_single_tuple()))
                if not new_trackers:
                    raise DuplicateDownloadException()

                else:
                    # Martijn: we default to loading the trackers here
                    self.utility.session.update_trackers(tdef.get_infohash(), new_trackers)
                return

            defaultDLConfig = DefaultDownloadStartupConfig.getInstance()
            dscfg = defaultDLConfig.copy()

            cancelDownload = False
            useDefault = not self.utility.read_config('showsaveas')
            safe_seeding = self.utility.read_config('default_safeseeding_enabled')
            if not useDefault and not destdir:
                defaultname = tdef.get_name_as_unicode() if tdef.is_multifile_torrent() else None

                dlg = SaveAs(None, tdef, dscfg.get_dest_dir(), defaultname, selectedFiles)
                dlg.CenterOnParent()

                if isinstance(tdef, TorrentDefNoMetainfo):
                    # Correct for the smaller size of the dialog if there is no metainfo
                    center_pos = dlg.GetPosition()
                    center_pos[1] -= 150
                    dlg.SetPosition(center_pos)

                if dlg.ShowModal() == wx.ID_OK:
                    # If the dialog has collected a torrent, use the new tdef
                    tdef = dlg.GetCollected() or tdef

                    # for multifile we enabled correctedFilenames, use split to remove the filename from the path
                    if tdef and tdef.is_multifile_torrent():
                        destdir, _ = os.path.split(dlg.GetPath())
                        selectedFiles = dlg.GetSelectedFiles()
                    else:
                        destdir = dlg.GetPath()

                    # Anonimity over exit nodes or hidden services
                    safe_seeding = dlg.UseSafeSeeding()
                    if dlg.UseTunnels():
                        hops = self.utility.read_config('default_number_hops')

                else:
                    cancelDownload = True
                dlg.Destroy()

            # use default setup
            else:
                if useDefault:
                    if self.utility.read_config('default_anonimity_enabled'):
                        # only load default anonymous level if we use default settings
                        hops = self.utility.read_config('default_number_hops')
                    else:
                        hops = 0

            if hops > 0:
                if not tdef:
                    raise Exception('Currently only torrents can be downloaded in anonymous mode')

            dscfg.set_hops(hops)
            dscfg.set_safe_seeding(safe_seeding)

            if not cancelDownload:
                if destdir is not None:
                    dscfg.set_dest_dir(destdir)

                if selectedFiles and len(selectedFiles) == 1:
                    # we should filter files to see if they are all playable
                    videofiles = selectedFiles

                elif tdef and not selectedFiles:
                    videofiles = tdef.get_files(exts=videoextdefaults)

                else:
                    videofiles = []

                # disable vodmode if no videofiles, unless we still need to collect the torrent
                if vodmode and len(videofiles) == 0 and (not tdef or not isinstance(tdef, TorrentDefNoMetainfo)):
                    vodmode = False

                if vodmode:
                    self._logger.info('MainFrame: startDownload: Starting in VOD mode')
                    result = self.utility.session.start_download(tdef, dscfg)
                    self.guiUtility.library_manager.playTorrent(
                        tdef.get_infohash(), videofiles[0] if len(videofiles) == 1 else None)

                else:
                    if selectedFiles:
                        dscfg.set_selected_files(selectedFiles)

                    self._logger.debug('MainFrame: startDownload: Starting in DL mode')
                    result = self.utility.session.start_download(tdef, dscfg, hidden=hidden)

                if result and not hidden:
                    self.show_saved(tdef)

                return result

        except DuplicateDownloadException as e:
            # If there is something on the cmdline, all other torrents start
            # in STOPPED state. Restart
            if cmdline:
                dlist = self.utility.session.get_downloads()
                for d in dlist:
                    if d.get_def().get_infohash() == tdef.get_infohash():
                        d.restart()
                        break

            self._logger.error("You are already downloading this torrent, seen the Downloads section")

        except Exception as e:
            print_exc()

        return None

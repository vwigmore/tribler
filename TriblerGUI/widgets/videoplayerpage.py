import os
import sys
from PyQt5.QtCore import QTimer

from PyQt5.QtGui import QPixmap, QIcon
from PyQt5.QtWidgets import QWidget
from Tribler import vlc
from TriblerGUI.defs import *
from TriblerGUI.dialogs.dialogcontainer import DialogContainer
from TriblerGUI.utilities import is_video_file, seconds_to_string


class VideoPlayerPage(QWidget):
    """
    This class manages the video player and all controls on the page.
    """

    def __init__(self):
        super(VideoPlayerPage, self).__init__()
        self.video_player_port = None
        self.active_infohash = ""
        self.active_index = -1
        self.is_full_screen = False

    def initialize_player(self):
        self.instance = vlc.Instance()
        self.mediaplayer = self.instance.media_player_new()
        self.window().video_player_position_slider.should_change_video_position.connect(self.on_should_change_video_time)
        self.window().video_player_volume_slider.valueChanged.connect(self.on_volume_change)
        self.window().video_player_volume_slider.setValue(self.mediaplayer.audio_get_volume())
        self.window().video_player_volume_slider.setFixedWidth(0)

        self.window().video_player_play_pause_button.clicked.connect(self.on_play_pause_button_click)
        self.window().video_player_volume_button.clicked.connect(self.on_volume_button_click)
        self.window().video_player_full_screen_button.clicked.connect(self.on_full_screen_button_click)

        # Create play/pause and volume button images
        self.play_icon = QIcon(QPixmap("images/play.png"))
        self.pause_icon = QIcon(QPixmap("images/pause.png"))
        self.menu_icon = QIcon(QPixmap("images/menu_white.png"))
        self.volume_on_icon = QIcon(QPixmap("images/volume_on.png"))
        self.volume_off_icon = QIcon(QPixmap("images/volume_off.png"))
        self.window().video_player_play_pause_button.setIcon(self.play_icon)
        self.window().video_player_volume_button.setIcon(self.volume_on_icon)

        if sys.platform.startswith('linux'):
            self.mediaplayer.set_xwindow(self.window().video_player_widget.winId())
        elif sys.platform == "win32":
            self.mediaplayer.set_hwnd(self.window().video_player_widget.winId())
        elif sys.platform == "darwin":
            self.mediaplayer.set_nsobject(int(self.window().video_player_widget.winId()))

        self.manager = self.mediaplayer.event_manager()
        self.manager.event_attach(vlc.EventType.MediaPlayerBuffering, self.on_vlc_player_buffering)
        self.manager.event_attach(vlc.EventType.MediaPlayerPlaying, self.on_vlc_player_playing)

        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.on_update_timer_tick)
        self.update_timer.start(500)

        self.buffer_dialog = DialogContainer(self.window().video_player_widget)

        self.window().left_menu_playlist.playing_item_change.connect(self.change_playing_index)

    def on_update_timer_tick(self):
        if self.active_infohash == "" or self.active_index == -1:
            self.window().video_player_position_slider.setValue(0)
            self.window().video_player_time_label.setText("0:00 / 0:00")
        else:
            video_time = self.mediaplayer.get_time()
            if video_time == -1:
                video_time = 0

            self.window().video_player_position_slider.setValue(self.mediaplayer.get_position() * 1000)
            self.window().video_player_time_label.setText("%s / 0:00" % seconds_to_string(video_time / 1000))

    def update_with_download_info(self, download):
        if len(download["files"]) > 0 and not self.window().left_menu_playlist.loaded_list:
            self.window().left_menu_playlist.set_files(download["files"])

            # Play the video with the largest file index
            largest_file = None

            for file in download["files"]:
                if is_video_file(file["name"]) and (largest_file is None or file["size"] > largest_file["size"]):
                    largest_file = file

            self.window().left_menu_playlist.set_active_index(largest_file["index"])
            self.change_playing_index(largest_file["index"], largest_file["name"])

    def on_vlc_player_buffering(self, event):
        pass

    def on_vlc_player_playing(self, event):
        pass

    def on_should_change_video_time(self, position):
        self.mediaplayer.set_position(position)

    def on_play_pause_button_click(self):
        print self.mediaplayer.get_state()
        if not self.mediaplayer.is_playing():
            self.window().video_player_play_pause_button.setIcon(self.pause_icon)
            self.mediaplayer.play()
        else:
            self.window().video_player_play_pause_button.setIcon(self.play_icon)
            self.mediaplayer.pause()

    def on_volume_button_click(self):
        if not self.mediaplayer.audio_get_mute():
            self.window().video_player_volume_button.setIcon(self.volume_off_icon)
        else:
            self.window().video_player_volume_button.setIcon(self.volume_on_icon)
        self.mediaplayer.audio_toggle_mute()

    def on_volume_change(self):
        self.mediaplayer.audio_set_volume(self.window().video_player_volume_slider.value())

    def on_full_screen_button_click(self):
        if not self.is_full_screen:
            self.window().top_bar.hide()
            self.window().left_menu.hide()
            self.window().statusBar.hide()
            self.window().showFullScreen()
        else:
            self.window().exit_full_screen()
        self.is_full_screen = not self.is_full_screen

    def set_torrent(self, torrent_info):
        self.active_infohash = torrent_info['infohash']

    def change_playing_index(self, index, filename):
        self.active_index = index
        self.window().video_player_header_label.setText(filename)

        # reset video player controls
        self.mediaplayer.stop()
        self.window().video_player_play_pause_button.setIcon(self.play_icon)
        self.window().video_player_position_slider.setValue(0)

        media_filename = u"http://127.0.0.1:" + unicode(self.video_player_port) + "/" + self.active_infohash + "/" + unicode(index)
        print media_filename
        self.media = self.instance.media_new(media_filename)
        self.mediaplayer.set_media(self.media)
        self.media.parse()

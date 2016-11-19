from PyQt5.QtCore import QPoint
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import QToolButton
from TriblerGUI.widgets.videoplayerinfopopup import VideoPlayerInfoPopup


class VideoPlayerInfoButton(QToolButton):

    def __init__(self, parent):
        super(VideoPlayerInfoButton, self).__init__(parent)
        self.popup = VideoPlayerInfoPopup(self.window())
        self.popup.hide()

    def enterEvent(self, event):
        self.popup.show()
        self.popup.raise_()
        self.popup.move(QPoint(QCursor.pos().x() - self.popup.width(), QCursor.pos().y() - self.popup.height()))
        #self.popup.move(QPoint(self.window().video_player_widget.width() - self.popup.width() - 20, self.window().video_player_widget.height() - self.popup.height()))

    def leaveEvent(self, event):
        self.popup.hide()

# Copyright 2020 by Kurt Rathjen. All Rights Reserved.
#
# This library is free software: you can redistribute it and/or modify it 
# under the terms of the GNU Lesser General Public License as published by 
# the Free Software Foundation, either version 3 of the License, or 
# (at your option) any later version. This library is distributed in the 
# hope that it will be useful, but WITHOUT ANY WARRANTY; without even the 
# implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. 
# See the GNU Lesser General Public License for more details.
# You should have received a copy of the GNU Lesser General Public
# License along with this library. If not, see <http://www.gnu.org/licenses/>.

import uuid
import logging

import maya.cmds
from maya.app.general.mayaMixin import MayaQWidgetDockableMixin

from studiovendor.Qt import QtCore
from studiovendor.Qt import QtWidgets

import studiolibrary
from studiolibrary import librarywindow

import mutils
import mutils.shepmirroring


logger = logging.getLogger(__name__)


_mayaCloseScriptJob = None


class SnapshotMirrorDialog(QtWidgets.QDialog):
    """Simple dialog for performing a live (snapshot) mirror in the scene.

    The user selects rig controls, chooses direction and axis, then clicks
    Mirror to apply the orientation-aware mirror without saving to the library.
    """

    def __init__(self, parent=None):
        super(SnapshotMirrorDialog, self).__init__(parent)
        self.setWindowTitle("Snapshot Mirror")
        self.setMinimumWidth(300)
        self._build()

    def _build(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(8)

        info = QtWidgets.QLabel(
            "Select the source-side controls in the viewport, choose a "
            "direction, then click <b>Mirror</b>."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        dir_group = QtWidgets.QGroupBox("Direction")
        dir_layout = QtWidgets.QHBoxLayout(dir_group)
        self._r2l = QtWidgets.QRadioButton("R \u2192 L")
        self._l2r = QtWidgets.QRadioButton("L \u2192 R")
        self._r2l.setChecked(True)
        dir_layout.addWidget(self._r2l)
        dir_layout.addWidget(self._l2r)
        layout.addWidget(dir_group)

        axis_layout = QtWidgets.QHBoxLayout()
        axis_layout.addWidget(QtWidgets.QLabel("Mirror Axis:"))
        self._axis = QtWidgets.QComboBox()
        self._axis.addItems(["X", "Y", "Z"])
        axis_layout.addWidget(self._axis)
        axis_layout.addStretch()
        layout.addLayout(axis_layout)

        btn_layout = QtWidgets.QHBoxLayout()
        mirror_btn = QtWidgets.QPushButton("Mirror")
        mirror_btn.setDefault(True)
        close_btn = QtWidgets.QPushButton("Close")
        btn_layout.addWidget(mirror_btn)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        mirror_btn.clicked.connect(self._do_mirror)
        close_btn.clicked.connect(self.close)

    def _do_mirror(self):
        direction = "R2L" if self._r2l.isChecked() else "L2R"
        axis = self._axis.currentText()

        applied, skipped = mutils.shepmirroring.snapshot_mirror(
            direction=direction,
            mirror_axis=axis,
        )

        msg = "Mirror applied: {} attributes.".format(applied)
        if skipped:
            msg += " {} controls not found.".format(len(skipped))
        try:
            maya.cmds.inViewMessage(
                assistMessage=msg,
                position="topCenter",
                fade=True,
            )
        except Exception:
            logger.debug(msg)


def enableMayaClosedEvent():
    """
    Create a Maya script job to trigger on the event "quitApplication".

    Enable the Maya closed event to save the library settings on close

    :rtype: None
    """
    global _mayaCloseScriptJob

    if not _mayaCloseScriptJob:
        event = ['quitApplication', mayaClosedEvent]
        try:
            _mayaCloseScriptJob = mutils.ScriptJob(event=event)
            logger.debug("Maya close event enabled")
        except NameError as error:
            logging.exception(error)


def disableMayaClosedEvent():
    """Disable the maya closed event."""
    global _mayaCloseScriptJob

    if _mayaCloseScriptJob:
        _mayaCloseScriptJob.kill()
        _mayaCloseScriptJob = None
        logger.debug("Maya close event disabled")


def mayaClosedEvent():
    """
    Create a Maya script job to trigger on the event "quitApplication".

    :rtype: None
    """
    for libraryWindow in librarywindow.LibraryWindow.instances():
        libraryWindow.saveSettings()


class MayaLibraryWindow(MayaQWidgetDockableMixin, librarywindow.LibraryWindow):

    def destroy(self):
        """
        Overriding this method to avoid multiple script jobs when developing.
        """
        disableMayaClosedEvent()
        librarywindow.LibraryWindow.destroy(self)

    def setObjectName(self, name):
        """
        Overriding to ensure the widget has a unique name for Maya.
        
        :type name: str
        :rtype: None 
        """
        name = '{0}_{1}'.format(name, uuid.uuid4())

        librarywindow.LibraryWindow.setObjectName(self, name)

    def tabWidget(self):
        """
        Return the tab widget for the library widget.

        :rtype: QtWidgets.QTabWidget or None
        """
        if self.isDockable():
            return self.parent().parent().parent()
        else:
            return None

    def workspaceControlName(self):
        """
        Return the workspaceControl name for the widget.
        
        :rtype: str or None
        """
        if self.isDockable() and self.parent():
            return self.parent().objectName()
        else:
            return None

    def isDocked(self):
        """
        Convenience method to return if the widget is docked.
        
        :rtype: bool 
        """
        return not self.isFloating()

    def isFloating(self):
        """
        Return True if the widget is a floating window.
        
        :rtype: bool 
        """
        name = self.workspaceControlName()
        if name:
            try:
                return maya.cmds.workspaceControl(name, q=True, floating=True)
            except AttributeError:
                msg = 'The "maya.cmds.workspaceControl" ' \
                      'command is not supported!'

                logger.warning(msg)

        return True

    def window(self):
        """
        Overriding this method to return itself when docked.
        
        This is used for saving the correct window position and size settings.
        
        :rtype: QWidgets.QWidget
        """
        if self.isDocked():
            return self
        else:
            return librarywindow.LibraryWindow.window(self)

    def show(self, **kwargs):
        """
        Show the library widget as a dockable window.

        Set dockable=False in kwargs if you want to show the widget as a floating window.

        :rtype: None
        """
        dockable = kwargs.get('dockable', True)
        MayaQWidgetDockableMixin.show(self, dockable=dockable)
        self.raise_()
        self.fixBorder()

    def resizeEvent(self, event):
        """
        Override method to remove the border when the window size has changed.
        
        :type event: QtCore.QEvent 
        :rtype: None 
        """
        if event.isAccepted():
            if not self.isLoaded():
                self.fixBorder()

    def floatingChanged(self, isFloating):
        """        
        Override method to remove the grey border when the parent has changed.

        Only supported/triggered in Maya 2018 

        :rtype: None
        """
        self.fixBorder()

    def fixBorder(self):
        """
        Remove the grey border around the tab widget.

        :rtype: None
        """
        if self.tabWidget():
            self.tabWidget().setStyleSheet("border:0px;")

    def showSnapshotMirrorDialog(self):
        """
        Open the Snapshot Mirror dialog as a child of this window.

        Allows the user to mirror the current pose of selected controls
        live in the scene without loading from the library.

        :rtype: None
        """
        dialog = SnapshotMirrorDialog(parent=self)
        dialog.show()

    def createSettingsMenu(self):
        """
        Override to append a Tools section with Snapshot Mirror to the
        standard settings menu.

        :rtype: studioqt.Menu
        """
        menu = librarywindow.LibraryWindow.createSettingsMenu(self)

        menu.addSeparator()
        action = menu.addAction("Snapshot Mirror")
        action.setToolTip(
            "Mirror the current pose of selected controls without loading "
            "from the library (orientation-aware, no mirror table required)."
        )
        action.triggered.connect(self.showSnapshotMirrorDialog)

        return menu


enableMayaClosedEvent()

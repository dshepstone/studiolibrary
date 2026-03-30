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

import copy
import uuid
import logging

import maya.cmds
from maya.app.general.mayaMixin import MayaQWidgetDockableMixin
from studiovendor.Qt import QtCore
from studiovendor.Qt import QtWidgets

import studiolibrary
from studiolibrary import librarywindow
from studiolibrarymaya import conestogatools

import mutils


logger = logging.getLogger(__name__)


_mayaCloseScriptJob = None


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
    DEFAULT_SETTINGS = copy.deepcopy(librarywindow.LibraryWindow.DEFAULT_SETTINGS)
    DEFAULT_SETTINGS["theme"] = {
        "accentColor": "rgb(74, 144, 217)",
        "backgroundColor": "rgb(43, 43, 43)",
    }

    def __init__(self, *args, **kwargs):
        super(MayaLibraryWindow, self).__init__(*args, **kwargs)
        self._toolsMenu = None

        tip = "Conestoga mirror workflow tools."
        icon = studiolibrary.resource.icon("sliders")
        self.addMenuBarAction("Tools", icon, tip, callback=self.showToolsMenu)

    def showToolsMenu(self):
        """Show the Conestoga tools menu."""
        if not self._toolsMenu:
            self._toolsMenu = QtWidgets.QMenu(self)

            action = self._toolsMenu.addAction("Snapshot Mirror (R -> L)")
            action.triggered.connect(lambda: self.runSnapshotMirror(direction="R2L"))

            action = self._toolsMenu.addAction("Snapshot Mirror (L -> R)")
            action.triggered.connect(lambda: self.runSnapshotMirror(direction="L2R"))

            self._toolsMenu.addSeparator()

            action = self._toolsMenu.addAction("Snapshot Mirror (R -> L, XY Plane)")
            action.triggered.connect(lambda: self.runSnapshotMirror(direction="R2L", mirrorPlane="XY"))

            action = self._toolsMenu.addAction("Snapshot Mirror (R -> L, XZ Plane)")
            action.triggered.connect(lambda: self.runSnapshotMirror(direction="R2L", mirrorPlane="XZ"))

        widget = self.menuBarWidget().findToolButton("Tools")
        point = widget.mapToGlobal(QtCore.QPoint(0, widget.height()))
        self._toolsMenu.exec_(point)

    def runSnapshotMirror(self, direction="R2L", mirrorPlane="YZ"):
        """Mirror current selected controls to the opposite side."""
        appliedCount, skipped = conestogatools.snapshot_mirror_selected(
            direction=direction,
            mirror_plane=mirrorPlane,
        )

        if appliedCount:
            message = "Conestoga mirror complete: {0} values applied.".format(appliedCount)
            self.setToastMessage(message)
        else:
            self.setToastMessage("Conestoga mirror finished with no applied values.")

        if skipped:
            logger.info("Conestoga mirror skipped objects/attrs: %s", skipped)

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


enableMayaClosedEvent()

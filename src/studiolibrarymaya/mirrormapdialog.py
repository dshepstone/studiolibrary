import logging

from studiovendor.Qt import QtCore
from studiovendor.Qt import QtWidgets

try:
    import maya.cmds
    import mutils
except ImportError:
    maya = None

logger = logging.getLogger(__name__)


class MirrorMapManagerDialog(QtWidgets.QDialog):

    def __init__(self, parent=None):
        super(MirrorMapManagerDialog, self).__init__(parent)
        self.setWindowTitle("Mirror Map Manager")
        self.resize(560, 420)

        self.manager = mutils.MirrorMapManager()
        self.currentRig = self._detect_rig()

        layout = QtWidgets.QVBoxLayout(self)

        toolbar = QtWidgets.QHBoxLayout()
        self.rigEdit = QtWidgets.QLineEdit(self.currentRig)
        self.searchEdit = QtWidgets.QLineEdit()
        self.searchEdit.setPlaceholderText("Filter controls...")
        toolbar.addWidget(QtWidgets.QLabel("Rig:"))
        toolbar.addWidget(self.rigEdit)
        toolbar.addWidget(self.searchEdit)
        layout.addLayout(toolbar)

        self.controlList = QtWidgets.QListWidget()
        self.pairEdit = QtWidgets.QLineEdit()
        self.excludeCheck = QtWidgets.QCheckBox("Exclude selected control")

        layout.addWidget(QtWidgets.QLabel("Controls in mirror map"))
        layout.addWidget(self.controlList)
        layout.addWidget(QtWidgets.QLabel("Manual partner"))
        layout.addWidget(self.pairEdit)
        layout.addWidget(self.excludeCheck)

        actions = QtWidgets.QGridLayout()
        self.pickControlBtn = QtWidgets.QPushButton("Pick Selected")
        self.assignPairBtn = QtWidgets.QPushButton("Assign Pair")
        self.saveBtn = QtWidgets.QPushButton("Save")
        self.saveAsBtn = QtWidgets.QPushButton("Save As")
        self.importBtn = QtWidgets.QPushButton("Import JSON")
        self.exportBtn = QtWidgets.QPushButton("Export JSON")
        self.newBtn = QtWidgets.QPushButton("Create New")
        self.reloadBtn = QtWidgets.QPushButton("Reload")
        self.deleteBtn = QtWidgets.QPushButton("Delete")

        buttons = [
            self.pickControlBtn, self.assignPairBtn, self.saveBtn,
            self.saveAsBtn, self.importBtn, self.exportBtn,
            self.newBtn, self.reloadBtn, self.deleteBtn,
        ]
        for i, btn in enumerate(buttons):
            actions.addWidget(btn, i // 3, i % 3)
        layout.addLayout(actions)

        self.mirrorMap = None
        self._load_or_create_map(self.currentRig)

        self.searchEdit.textChanged.connect(self._refresh_controls)
        self.controlList.currentTextChanged.connect(self._control_changed)
        self.pickControlBtn.clicked.connect(self._pick_selected)
        self.assignPairBtn.clicked.connect(self._assign_pair)
        self.excludeCheck.toggled.connect(self._toggle_exclude)
        self.saveBtn.clicked.connect(self._save)
        self.saveAsBtn.clicked.connect(self._save_as)
        self.importBtn.clicked.connect(self._import_json)
        self.exportBtn.clicked.connect(self._export_json)
        self.newBtn.clicked.connect(self._new_map)
        self.reloadBtn.clicked.connect(self._reload)
        self.deleteBtn.clicked.connect(self._delete)

    def _detect_rig(self):
        selection = maya.cmds.ls(selection=True, long=True) or []
        return mutils.StudioLibraryMirrorAdapter.detect_rig_id(objects=selection)

    def _load_or_create_map(self, rig_id):
        if self.manager.has_map(rig_id):
            self.mirrorMap = self.manager.load(rig_id)
        else:
            self.mirrorMap = mutils.MirrorMap(rig_id=rig_id)
        self._refresh_controls()

    def _refresh_controls(self):
        self.controlList.clear()
        flt = self.searchEdit.text().strip().lower()
        for key in sorted(self.mirrorMap.controls.keys()):
            if not flt or flt in key.lower():
                self.controlList.addItem(key)

    def _control_changed(self, control):
        self.pairEdit.setText(self.mirrorMap.manual_pairs.get(control, ""))
        self.excludeCheck.blockSignals(True)
        self.excludeCheck.setChecked(control in self.mirrorMap.excluded_controls)
        self.excludeCheck.blockSignals(False)

    def _pick_selected(self):
        selected = maya.cmds.ls(selection=True, long=True) or []
        if not selected:
            return
        leaf = selected[0].split("|")[-1]
        if leaf not in self.mirrorMap.controls:
            self.mirrorMap.controls[leaf] = {"partner": "", "side": "middle", "rules": {}}
            self._refresh_controls()
        items = self.controlList.findItems(leaf, QtCore.Qt.MatchExactly)
        if items:
            self.controlList.setCurrentItem(items[0])

    def _assign_pair(self):
        control = self.controlList.currentItem().text() if self.controlList.currentItem() else ""
        if not control:
            return
        value = self.pairEdit.text().strip()
        if value:
            self.mirrorMap.manual_pairs[control] = value
        elif control in self.mirrorMap.manual_pairs:
            del self.mirrorMap.manual_pairs[control]

    def _toggle_exclude(self, state):
        control = self.controlList.currentItem().text() if self.controlList.currentItem() else ""
        if not control:
            return
        if state:
            self.mirrorMap.excluded_controls.add(control)
        else:
            self.mirrorMap.excluded_controls.discard(control)

    def _save(self):
        self.mirrorMap.rig_id = self.rigEdit.text().strip()
        self.manager.save(self.mirrorMap)

    def _save_as(self):
        rig_id = self.rigEdit.text().strip()
        self.manager.save(self.mirrorMap, rig_id=rig_id)

    def _import_json(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Import Mirror Map", "", "JSON (*.json)")
        if not path:
            return
        self.mirrorMap = self.manager.import_map(path, rig_id=self.rigEdit.text().strip())
        self._refresh_controls()

    def _export_json(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export Mirror Map", "", "JSON (*.json)")
        if not path:
            return
        self.manager.export_map(self.rigEdit.text().strip(), path)

    def _new_map(self):
        self.mirrorMap = mutils.MirrorMap(rig_id=self.rigEdit.text().strip())
        self._refresh_controls()

    def _reload(self):
        self._load_or_create_map(self.rigEdit.text().strip())

    def _delete(self):
        self.manager.delete(self.rigEdit.text().strip())
        self._new_map()


def showMirrorMapManager(parent=None):
    dialog = MirrorMapManagerDialog(parent=parent)
    dialog.show()
    return dialog

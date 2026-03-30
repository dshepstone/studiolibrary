#!/usr/bin/env python3
"""
shepStudioAnimLib.py  —  ShepStudio Anim Library v1.1

A local animation & pose library for Autodesk Maya (2025+).
Export and import poses or full animation clips as lightweight JSON files,
with viewport thumbnails, namespace retargeting, and built-in L↔R mirroring.

Requires:  PySide6 / Maya 2025+

Install:
    1. Place this file in your Maya scripts folder
       (%USERPROFILE%/Documents/maya/scripts)

    2. In the Maya Script Editor (Python tab), run:
         from shepStudioAnimLib import ShepStudioAnimLib
         ShepStudioAnimLib.show()

    3. (Optional) Drag the above two lines onto a shelf button.

MEL one-liner for shelf:
    python("from shepStudioAnimLib import ShepStudioAnimLib; ShepStudioAnimLib.show()");

Author:  David Shepstone
Version: 1.1.0
"""

import base64
import datetime
import json
import os
import re
import shutil
import tempfile
import traceback

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, QSize, Signal
from shiboken6 import wrapInstance

import maya.OpenMayaUI as omui
import maya.cmds as cmds
import maya.mel as mel


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  CONSTANTS                                                               ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

TOOL_NAME      = "ShepStudio Anim Library"
TOOL_VERSION   = "1.1.0"
WORKSPACE_NAME = "shepStudioAnimLibWorkspace"

POSE_EXT = ".sapose"
CLIP_EXT = ".saclip"

FORMAT_POSE    = "shepstudio_pose"
FORMAT_CLIP    = "shepstudio_clip"
FORMAT_VERSION = 1

TOKEN_PAIRS = [
    ("Left", "Right"), ("left", "right"), ("LEFT", "RIGHT"),
    ("Lf", "Rt"), ("lf", "rt"), ("LF", "RT"),
    ("L", "R"), ("l", "r"),
]

# Per-axis negate maps.  Key = mirror axis, value = set of attrs to negate.
#   Translate: the component along the mirror axis is negated.
#   Rotate:    rotations around the OTHER two axes are negated.
MIRROR_NEGATE_MAP = {
    "X": {"translateX", "rotateY", "rotateZ"},   # YZ-plane mirror
    "Y": {"translateY", "rotateX", "rotateZ"},   # XZ-plane mirror
    "Z": {"translateZ", "rotateX", "rotateY"},   # XY-plane mirror
}
MIRROR_NEGATE_ATTRS = MIRROR_NEGATE_MAP["X"]  # Backward compat default

OPT_LIBRARY_ROOT = "shepStudio_libraryRoot"
OPT_THUMB_SIZE   = "shepStudio_thumbSize"

DEFAULT_LIBRARY    = os.path.join(os.path.expanduser("~"), "maya", "shepstudio_library")
DEFAULT_THUMB_SIZE = 150


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  DARK THEME                                                              ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

DARK_STYLESHEET = """
QWidget#shepMainWidget {
    background-color: #2b2b2b; color: #d4d4d4;
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif; font-size: 12px;
}
QLabel { color: #cccccc; }

QMenuBar { background-color: #333; color: #d4d4d4; border-bottom: 1px solid #444; padding: 2px 0; }
QMenuBar::item:selected { background-color: #4a90d9; color: #fff; border-radius: 3px; }
QMenu { background-color: #353535; color: #d4d4d4; border: 1px solid #555; padding: 4px; }
QMenu::item { padding: 6px 28px 6px 22px; }
QMenu::item:selected { background-color: #4a90d9; color: #fff; border-radius: 3px; }
QMenu::item:disabled { color: #666; }
QMenu::separator { height: 1px; background: #555; margin: 4px 8px; }

QGroupBox {
    font-weight: bold; font-size: 11px; color: #ccc;
    border: 1px solid #555; border-radius: 6px;
    margin-top: 10px; padding: 14px 8px 8px 8px;
}
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 2px 10px; left: 8px; }

QPushButton {
    background-color: #404040; color: #d4d4d4; border: 1px solid #555;
    border-radius: 4px; padding: 5px 14px; min-height: 22px; font-size: 11px;
}
QPushButton:hover   { background-color: #505050; border-color: #6a6a6a; }
QPushButton:pressed  { background-color: #353535; }
QPushButton:disabled { background-color: #333; color: #666; border-color: #444; }

QPushButton#capturePoseBtn {
    background-color: #2a6a8a; color: #d0eaff;
    font-size: 13px; font-weight: bold; min-height: 38px;
    border: 1px solid #3a8aba; border-radius: 6px; padding: 8px 20px;
}
QPushButton#capturePoseBtn:hover { background-color: #3a8aba; }

QPushButton#captureClipBtn {
    background-color: #6a5a20; color: #f0e0a0;
    font-size: 13px; font-weight: bold; min-height: 38px;
    border: 1px solid #8a7a30; border-radius: 6px; padding: 8px 20px;
}
QPushButton#captureClipBtn:hover { background-color: #8a7a30; }

QPushButton#importBtn {
    background-color: #3a5a3a; color: #b0dab0;
    font-size: 13px; font-weight: bold; min-height: 34px;
    border: 1px solid #4a7a4a; border-radius: 5px;
}
QPushButton#importBtn:hover { background-color: #4a6a4a; }

QPushButton#deleteBtn {
    background-color: #5a3030; color: #e0a0a0; border: 1px solid #7a4040; min-height: 28px;
}
QPushButton#deleteBtn:hover { background-color: #6a3a3a; }

QComboBox {
    background-color: #383838; color: #d4d4d4; border: 1px solid #555;
    border-radius: 4px; padding: 4px 8px; min-height: 20px;
}
QComboBox:hover { border-color: #4a90d9; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView { background-color: #383838; color: #d4d4d4; selection-background-color: #4a90d9; border: 1px solid #555; }

QLineEdit { background-color: #383838; color: #d4d4d4; border: 1px solid #555; border-radius: 4px; padding: 4px 8px; min-height: 20px; }
QLineEdit:focus { border-color: #4a90d9; }
QSpinBox { background-color: #383838; color: #d4d4d4; border: 1px solid #555; border-radius: 4px; padding: 4px 8px; }

QCheckBox { color: #ccc; spacing: 6px; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #666; border-radius: 3px; background-color: #383838; }
QCheckBox::indicator:checked { background-color: #4a90d9; border-color: #5a9ada; }
QCheckBox::indicator:hover   { border-color: #4a90d9; }

QRadioButton { color: #ccc; spacing: 6px; }
QRadioButton::indicator { width: 14px; height: 14px; }
QRadioButton::indicator:unchecked { border: 1px solid #666; border-radius: 7px; background-color: #383838; }
QRadioButton::indicator:checked   { border: 1px solid #5a9ada; border-radius: 7px; background-color: #4a90d9; }

QTreeView, QListWidget {
    background-color: #2e2e2e; color: #d4d4d4; border: 1px solid #444; border-radius: 4px; outline: none;
}
QTreeView::item:selected, QListWidget::item:selected { background-color: #3a6a9a; color: #fff; }
QTreeView::item:hover, QListWidget::item:hover { background-color: #353535; }
QTreeView::branch { background-color: #2e2e2e; }

QSplitter::handle { background-color: #444; }
QSplitter::handle:horizontal { width: 3px; }
QSplitter::handle:vertical   { height: 3px; }

QScrollArea { border: none; background-color: transparent; }
QScrollBar:vertical   { background: #2e2e2e; width: 10px; }
QScrollBar::handle:vertical { background: #555; min-height: 20px; border-radius: 5px; }
QScrollBar::handle:vertical:hover { background: #666; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #2e2e2e; height: 10px; }
QScrollBar::handle:horizontal { background: #555; min-width: 20px; border-radius: 5px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QToolTip { background-color: #404040; color: #e0e0e0; border: 1px solid #666; border-radius: 4px; padding: 6px 10px; font-size: 11px; }
QStatusBar { background-color: #333; color: #999; font-size: 10px; }
"""


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  SIDE-TOKEN HELPERS                                                      ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

def _bp(tok):
    return r'(?:(?<=_)|(?<=\A)|(?<=[0-9]))' + re.escape(tok) + r'(?:(?=_)|(?=\Z)|(?=[0-9]))'

def swap_side_token(name):
    for lt, rt in TOKEN_PAIRS:
        m = re.search(_bp(rt), name)
        if m:
            return name[:m.start()] + lt + name[m.end():], True
        m = re.search(_bp(lt), name)
        if m:
            return name[:m.start()] + rt + name[m.end():], True
    return name, False


def swap_side_token_directional(name, direction="L2R"):
    """Swap only in the requested direction: L2R or R2L."""
    for lt, rt in TOKEN_PAIRS:
        if direction == "R2L":
            m = re.search(_bp(rt), name)
            if m:
                return name[:m.start()] + lt + name[m.end():], True
        else:
            m = re.search(_bp(lt), name)
            if m:
                return name[:m.start()] + rt + name[m.end():], True
    return name, False

def has_side_token(name):
    for lt, rt in TOKEN_PAIRS:
        if re.search(_bp(lt), name) or re.search(_bp(rt), name):
            return True
    return False


def _detect_side(name):
    """Return 'L', 'R', or None based on the first side token found in *name*."""
    for lt, rt in TOKEN_PAIRS:
        if re.search(_bp(rt), name):
            return "R"
        if re.search(_bp(lt), name):
            return "L"
    return None


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  SNAPSHOT MIRROR  (live scene mirror – like digitMirror)                 ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

def snapshot_mirror(direction="R2L", target_ns="", mirror_axis="X"):
    """Read current pose values from source-side controls and mirror them
    to the corresponding opposite-side controls in the scene.

    Uses orientation-aware negate logic (identical to ``import_pose``):
    rest-pose world matrices are sampled to decide per-attribute whether
    to copy or negate, so rigs with mirrored joint orientations on
    fingers / hands work correctly.

    Returns ``(applied_count, skipped_list)``.
    """
    sel = cmds.ls(sl=True) or []
    if not sel:
        cmds.warning("[ShepStudio] snapshot_mirror: nothing selected.")
        return 0, []

    # Resolve namespace from first selected control when none is given.
    ns = target_ns
    if not ns or ns == "(no namespace)":
        leaf = sel[0].split("|")[-1]
        ns = leaf.rsplit(":", 1)[0] if ":" in leaf else ""

    # ── Phase 1: resolve source / target pairs ──
    pairs = []  # (src_full, tgt_full)
    seen = set()

    for ctrl in sel:
        bare = strip_namespace(ctrl)
        side = _detect_side(bare)
        if not side:
            continue

        swapped_bare = swap_side_token(bare)[0]

        if direction == "R2L":
            src_bare = bare if side == "R" else swapped_bare
            tgt_bare = bare if side == "L" else swapped_bare
        else:
            src_bare = bare if side == "L" else swapped_bare
            tgt_bare = bare if side == "R" else swapped_bare

        pair_key = (src_bare, tgt_bare)
        if pair_key in seen:
            continue
        seen.add(pair_key)

        src_full = add_namespace(src_bare, ns)
        tgt_full = add_namespace(tgt_bare, ns)
        pairs.append((src_full, tgt_full))

    # ── Phase 2: batch orientation sampling ──
    sample_ctrls = set()
    for src_full, tgt_full in pairs:
        if cmds.objExists(src_full):
            sample_ctrls.add(src_full)
        if cmds.objExists(tgt_full):
            sample_ctrls.add(tgt_full)
    axes_data = _sample_rest_axes_batch(list(sample_ctrls))

    print("[ShepStudio] Snapshot mirror: direction={}, axis={}, "
          "{} pairs, ns='{}'".format(direction, mirror_axis, len(pairs), ns))

    # ── Phase 3: apply mirrored values ──
    applied, skipped = 0, []

    for src_full, tgt_full in pairs:
        if not cmds.objExists(src_full):
            skipped.append(src_full)
            continue
        if not cmds.objExists(tgt_full):
            skipped.append(tgt_full)
            continue

        # Build per-control negate set from orientation comparison.
        src_attrs = list_control_attrs(src_full)
        ctrl_negate = _compute_negate_set(
            axes_data.get(src_full), axes_data.get(tgt_full),
            mirror_axis, src_attrs)

        print("[ShepStudio]   {} -> {}  negate={}".format(
            src_full, tgt_full, ctrl_negate or "(none – orientations mirrored)"))

        for attr in src_attrs:
            src_plug = "{}.{}".format(src_full, attr)
            tgt_plug = "{}.{}".format(tgt_full, attr)
            try:
                value = cmds.getAttr(src_plug)
                if not is_writable_plug(tgt_plug):
                    continue
                v = -value if attr in ctrl_negate else value
                cmds.setAttr(tgt_plug, v)
                applied += 1
            except Exception as exc:
                print("[ShepStudio]     WARN: {} – {}".format(tgt_plug, exc))

    print("[ShepStudio] Snapshot mirror done: {} attrs applied, "
          "{} controls skipped".format(applied, len(skipped)))

    return applied, skipped


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  MAYA HELPERS                                                            ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

def maya_main_window():
    return wrapInstance(int(omui.MQtUtil.mainWindow()), QtWidgets.QWidget)

def get_library_root():
    if cmds.optionVar(exists=OPT_LIBRARY_ROOT):
        root = cmds.optionVar(q=OPT_LIBRARY_ROOT)
    else:
        root = DEFAULT_LIBRARY
        cmds.optionVar(sv=(OPT_LIBRARY_ROOT, root))
    if not os.path.isdir(root):
        os.makedirs(root)
    return root

def set_library_root(path):
    cmds.optionVar(sv=(OPT_LIBRARY_ROOT, path))

def strip_namespace(name):
    leaf = name.split("|")[-1]
    return leaf.rsplit(":", 1)[1] if ":" in leaf else leaf

def short_name(name):
    return name.split("|")[-1]

def add_namespace(bare, ns):
    return "{}:{}".format(ns, bare) if ns and ns != "(no namespace)" else bare


def remap_full_path_to_namespace(full_path, target_ns):
    """Remap every DAG segment to target namespace while preserving hierarchy."""
    if not target_ns or target_ns == "(no namespace)":
        return full_path
    parts = [p for p in full_path.split("|") if p]
    remapped = [add_namespace(strip_namespace(p), target_ns) for p in parts]
    return "|".join(remapped)


def control_identity_record(ctrl):
    return {
        "full_path": ctrl,
        "short_name": short_name(ctrl),
        "bare_name": strip_namespace(ctrl),
    }

def detect_scene_namespaces():
    """Detect all non-default namespaces in the scene.

    Uses Maya's namespace list first (most reliable), then falls back
    to scanning nurbsCurve parents for referenced rigs.
    """
    ns_set = set()
    # Method 1: Maya namespace list (catches all referenced rigs)
    try:
        all_ns = cmds.namespaceInfo(":", listOnlyNamespaces=True, recurse=True) or []
        for ns in all_ns:
            if ns not in ("UI", "shared"):
                ns_set.add(ns)
    except Exception:
        pass
    # Method 2: Scan nurbsCurve parents (fallback for older scenes)
    if not ns_set:
        shapes = cmds.ls(type="nurbsCurve", long=True) or []
        for s in shapes:
            for xf in (cmds.listRelatives(s, parent=True, fullPath=True) or []):
                leaf = xf.split("|")[-1]
                if ":" in leaf:
                    ns_set.add(leaf.rsplit(":", 1)[0])
    return sorted(ns_set) or ["(no namespace)"]

def get_rig_controls(roots=None, hierarchy=False):
    if roots:
        if hierarchy:
            cmds.select(roots, hi=True)
            nodes = cmds.ls(sl=True, long=True) or []
            cmds.select(roots)
        else:
            nodes = cmds.ls(roots, long=True) or []
    else:
        nodes = cmds.ls(sl=True, long=True) or []
    ctrls = []
    for n in nodes:
        if cmds.objectType(n) != "transform":
            continue
        has_curve = bool(cmds.listRelatives(n, shapes=True, type="nurbsCurve"))
        has_user_anim = bool((cmds.listAttr(n, userDefined=True, keyable=True) or []) or
                             (cmds.listAttr(n, userDefined=True, channelBox=True) or []))
        if is_helper_control_name(n) and not (has_curve or has_user_anim):
            continue
        if has_curve:
            ctrls.append(n)
        elif cmds.listAttr(n, keyable=True) or []:
            ctrls.append(n)
    # Always try to include manual finger controls as first-class data.
    ctrls = _augment_with_finger_controls(ctrls, roots=roots, hierarchy=hierarchy)
    return ctrls


FINGER_TOKENS = ("thumb", "index", "middle", "ring", "pinky", "finger")
HAND_TOKENS = ("hand", "wrist", "palm")
HAND_DRIVER_ATTR_TOKENS = (
    "curl", "spread", "splay", "fist", "scrunch", "relax", "cup",
    "thumb", "index", "middle", "ring", "pinky", "finger"
)
HELPER_NAME_TOKENS = (
    "grp", "group", "offset", "pivot", "srtbuffer", "buffer",
    "inv", "relax_offset", "sdk", "space", "const", "constraint"
)


def is_finger_control_name(name):
    """Return True when a control name looks finger-related."""
    low = strip_namespace(name).lower()
    return any(tok in low for tok in FINGER_TOKENS)


def is_hand_control_name(name):
    low = strip_namespace(name).lower()
    return any(tok in low for tok in HAND_TOKENS)


def is_helper_control_name(name):
    """Heuristic rejection of helper/buffer nodes."""
    low = strip_namespace(name).lower()
    # split on underscores and camel-ish separators
    parts = re.split(r"[_:|]", low)
    # exact token match (avoid rejecting e.g. 'index')
    if any(tok in parts for tok in HELPER_NAME_TOKENS):
        return True
    # common suffix patterns
    if re.search(r"(?:_|^)(?:grp|offset|pivot|srtbuffer|buffer|inv)$", low):
        return True
    if "relax_offset" in low:
        return True
    return False


def _list_control_set_nodes(namespace_filter=None):
    """Return transform members of likely animation control sets."""
    out = set()
    sets = cmds.ls(type="objectSet") or []
    for s in sets:
        s_low = s.lower()
        if not any(k in s_low for k in ("control", "ctrl", "anim")):
            continue
        members = cmds.sets(s, q=True) or []
        for m in members:
            if not cmds.objExists(m):
                continue
            node = m.split(".")[0]
            if cmds.objectType(node) != "transform":
                parents = cmds.listRelatives(node, parent=True, fullPath=True) or []
                if not parents:
                    continue
                node = parents[0]
            if namespace_filter:
                leaf = node.split("|")[-1]
                node_ns = leaf.rsplit(":", 1)[0] if ":" in leaf else ""
                if node_ns not in namespace_filter:
                    continue
            out.add(node)
    return out


def _namespaces_from_nodes(nodes):
    ns = set()
    for n in nodes or []:
        leaf = n.split("|")[-1]
        if ":" in leaf:
            ns.add(leaf.rsplit(":", 1)[0])
    return ns


def _is_likely_control(node, control_set_nodes=None):
    if cmds.objectType(node) != "transform":
        return False
    if control_set_nodes and node in control_set_nodes:
        return True
    shapes = cmds.listRelatives(node, shapes=True, noIntermediate=True, fullPath=True) or []
    has_ctrl_shape = any(cmds.objectType(s) == "nurbsCurve" for s in shapes)
    if is_helper_control_name(node) and not has_ctrl_shape:
        # Helper-like names can still be valid when the final node is an animator control.
        return False
    if has_ctrl_shape:
        return True
    user_k = cmds.listAttr(node, userDefined=True, keyable=True) or []
    user_cb = cmds.listAttr(node, userDefined=True, channelBox=True) or []
    if user_k or user_cb:
        return True
    return bool(cmds.listAttr(node, keyable=True) or [])


def _augment_with_finger_controls(ctrls, roots=None, hierarchy=False):
    """Add relevant manual finger controls from the same rig namespace/hierarchy."""
    out = list(dict.fromkeys(ctrls or []))
    current_set = set(out)
    ns_filter = _namespaces_from_nodes(out)
    control_set_nodes = _list_control_set_nodes(namespace_filter=ns_filter or None)

    candidates = []
    if hierarchy and roots:
        roots_long = cmds.ls(roots, long=True) or []
        for r in roots_long:
            desc = cmds.listRelatives(r, allDescendents=True, fullPath=True, type="transform") or []
            candidates.extend(desc)
    else:
        candidates = cmds.ls(type="transform", long=True) or []

    added = []
    rejected_helpers = []
    rejected_non_ctrl = []
    for node in candidates:
        if node in current_set:
            continue
        if not is_finger_control_name(node):
            continue
        if is_helper_control_name(node):
            rejected_helpers.append(node)
            continue
        if not _is_likely_control(node, control_set_nodes=control_set_nodes):
            rejected_non_ctrl.append(node)
            continue
        if ns_filter:
            leaf = node.split("|")[-1]
            node_ns = leaf.rsplit(":", 1)[0] if ":" in leaf else ""
            if node_ns not in ns_filter:
                continue
        out.append(node)
        current_set.add(node)
        added.append(node)

    if added:
        print("[ShepStudio] Finger discovery: found {} additional finger controls".format(len(added)))
        for n in added[:20]:
            print("[ShepStudio]   + {}".format(n))
        if len(added) > 20:
            print("[ShepStudio]   ... and {} more".format(len(added) - 20))
    else:
        print("[ShepStudio] Finger discovery: no additional finger controls found")
    if rejected_helpers:
        print("[ShepStudio] Finger discovery: rejected {} helper-like nodes".format(len(rejected_helpers)))
        for n in rejected_helpers[:10]:
            print("[ShepStudio]   helper reject: {}".format(n))
    if rejected_non_ctrl:
        print("[ShepStudio] Finger discovery: rejected {} non-control nodes".format(len(rejected_non_ctrl)))
        for n in rejected_non_ctrl[:10]:
            print("[ShepStudio]   non-control reject: {}".format(n))

    return out


def selection_to_transforms(selection):
    """Normalize mixed Maya selections (components/shapes/transforms) to transforms."""
    out = []
    for item in selection or []:
        if not cmds.objExists(item):
            continue
        node = item.split(".")[0]  # convert component selection to node
        ntype = cmds.objectType(node)
        if ntype == "transform":
            out.append(node)
            continue
        parents = cmds.listRelatives(node, parent=True, fullPath=True) or []
        for p in parents:
            if cmds.objectType(p) == "transform":
                out.append(p)
    # preserve order while removing duplicates
    return list(dict.fromkeys(out))


def list_control_attrs(ctrl):
    """Return keyable + channel-box attrs that can be read/written as scalars."""
    attrs = []
    keyable = cmds.listAttr(ctrl, keyable=True) or []
    channel_box = cmds.listAttr(ctrl, channelBox=True) or []
    for attr in keyable + channel_box:
        if attr in attrs:
            continue
        plug = "{}.{}".format(ctrl, attr)
        try:
            value = cmds.getAttr(plug)
        except Exception:
            continue
        if isinstance(value, (int, float, bool)):
            attrs.append(attr)
    # Finger controls must always preserve manual rotations.
    if is_finger_control_name(ctrl):
        for ra in ("rotateX", "rotateY", "rotateZ"):
            plug = "{}.{}".format(ctrl, ra)
            if ra in attrs:
                continue
            try:
                value = cmds.getAttr(plug)
                if isinstance(value, (int, float)):
                    attrs.append(ra)
            except Exception:
                pass
    # Hand driver attrs (curl/spread/fist/etc.) are often on hand controls.
    if is_hand_control_name(ctrl):
        user_attrs = (cmds.listAttr(ctrl, userDefined=True) or [])
        for attr in user_attrs:
            low = attr.lower()
            if not any(tok in low for tok in HAND_DRIVER_ATTR_TOKENS):
                continue
            if attr in attrs:
                continue
            plug = "{}.{}".format(ctrl, attr)
            try:
                value = cmds.getAttr(plug)
                if isinstance(value, (int, float, bool)):
                    attrs.append(attr)
            except Exception:
                pass
    return attrs


def is_writable_plug(plug):
    """Return True when a plug appears editable by setAttr."""
    try:
        if cmds.getAttr(plug, lock=True):
            return False
    except Exception:
        return False
    try:
        return bool(cmds.getAttr(plug, settable=True))
    except Exception:
        # Fall back to permissive mode and rely on setAttr exception handling.
        return True


def plug_write_state(plug):
    """Return (writable, reason)."""
    if not cmds.objExists(plug):
        return False, "plug_missing"
    try:
        if cmds.getAttr(plug, lock=True):
            return False, "locked"
    except Exception:
        return False, "query_failed"
    try:
        if not bool(cmds.getAttr(plug, settable=True)):
            return False, "not_settable"
    except Exception:
        # Some attrs may still be settable despite query failures.
        pass
    return True, "ok"


def build_rig_snapshot(controls):
    """Create a lightweight schema shared by capture/import tools."""
    snap_controls = {}
    for ctrl in controls or []:
        bare = strip_namespace(ctrl)
        snap_controls[bare] = list_control_attrs(ctrl)
    return {
        "format": "shepstudio_rig_snapshot",
        "version": FORMAT_VERSION,
        "timestamp": datetime.datetime.now().isoformat(),
        "tool_version": TOOL_VERSION,
        "control_count": len(snap_controls),
        "controls": snap_controls,
    }


INFINITY_MAP = {0: "constant", 1: "linear", 2: "constant", 3: "cycle", 4: "cycleRelative", 5: "oscillate"}


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  THUMBNAIL CAPTURE — auto-frames selection                               ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

def capture_thumbnail(width=400, height=400, frame_selection=True, focus_nodes=None):
    tmp = os.path.join(tempfile.gettempdir(), "shepstudio_thumb.png")
    sel_restore = cmds.ls(sl=True, long=True) or []
    try:
        if frame_selection:
            if focus_nodes:
                valid = [n for n in focus_nodes if cmds.objExists(n)]
                if valid:
                    cmds.select(valid, r=True)
            if cmds.ls(sl=True):
                cmds.viewFit(fitFactor=0.8)
                cmds.refresh(force=True)
        result = cmds.playblast(
            frame=[cmds.currentTime(q=True)], format="image", compression="png",
            quality=92, width=width, height=height, showOrnaments=False,
            viewer=False, completeFilename=tmp, percent=100, offScreen=True)
        if result and os.path.isfile(tmp):
            with open(tmp, "rb") as f:
                data = f.read()
            os.remove(tmp)
            return base64.b64encode(data).decode("ascii")
    except Exception:
        traceback.print_exc()
    finally:
        try:
            if sel_restore:
                cmds.select(sel_restore, r=True)
        except Exception:
            pass
    return None


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  CORE — EXPORT                                                          ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

def export_pose(controls, include_static=True, thumbnail_b64=None):
    frame = cmds.currentTime(q=True)
    src_ns = ""
    if controls:
        leaf = controls[0].split("|")[-1]
        if ":" in leaf:
            src_ns = leaf.rsplit(":", 1)[0]

    cd = {}
    controls_v2 = []
    finger_ctrls = []
    finger_saved_attrs = 0
    finger_attr_map = {}
    for ctrl in controls:
        bare = strip_namespace(ctrl)
        is_finger = is_finger_control_name(bare)
        if is_finger:
            finger_ctrls.append(bare)
        vals = {}
        for attr in list_control_attrs(ctrl):
            plug = "{}.{}".format(ctrl, attr)
            try:
                v = cmds.getAttr(plug)
                # Only store scalar numeric values – skip compound parents
                # (translate, rotate, scale return [(x,y,z)]), strings, None,
                # and booleans that setAttr cannot handle without extra args.
                if not isinstance(v, (int, float)):
                    continue
                if include_static or cmds.keyframe(plug, q=True, keyframeCount=True):
                    vals[attr] = v
                    if is_finger and attr in ("rotateX", "rotateY", "rotateZ"):
                        finger_saved_attrs += 1
            except Exception:
                pass
        if vals:
            cd[bare] = vals
            rec = control_identity_record(ctrl)
            rec["attrs"] = vals
            controls_v2.append(rec)
            if is_finger:
                finger_attr_map[bare] = sorted(vals.keys())

    print("[ShepStudio] Pose export: {} controls ({} finger controls)".format(
        len(cd), len(set(finger_ctrls))))
    if finger_ctrls:
        print("[ShepStudio] Pose export: finger rotate attrs saved={}".format(
            finger_saved_attrs))
        for n in sorted(set(finger_ctrls))[:20]:
            print("[ShepStudio]   finger ctrl: {}".format(n))
        if len(set(finger_ctrls)) > 20:
            print("[ShepStudio]   ... and {} more".format(len(set(finger_ctrls)) - 20))
        for ctrl_name, attrs in sorted(finger_attr_map.items())[:20]:
            print("[ShepStudio]   saved attrs {}: {}".format(ctrl_name, ", ".join(attrs)))
    for rec in controls_v2[:10]:
        print("[ShepStudio] Pose identity saved: full='{}' short='{}' bare='{}'".format(
            rec.get("full_path", ""), rec.get("short_name", ""), rec.get("bare_name", "")))

    return {"format": FORMAT_POSE, "version": FORMAT_VERSION,
            "timestamp": datetime.datetime.now().isoformat(),
            "source_file": cmds.file(q=True, sceneName=True) or "untitled",
            "source_namespace": src_ns, "frame": frame,
            "thumbnail": thumbnail_b64, "control_count": len(cd), "controls": cd,
            "controls_v2": controls_v2,
            "rig_snapshot": build_rig_snapshot(controls)}


def export_clip(controls, include_static=True, thumbnail_b64=None):
    src_ns = ""
    if controls:
        leaf = controls[0].split("|")[-1]
        if ":" in leaf:
            src_ns = leaf.rsplit(":", 1)[0]

    fps = mel.eval("currentTimeUnitToFPS")
    cd = {}
    controls_v2 = []
    finger_ctrls = []
    finger_rotate_keys = 0
    finger_rotate_static = 0
    finger_anim_attr_map = {}
    gmin, gmax = 999999, -999999

    for ctrl in controls:
        bare = strip_namespace(ctrl)
        is_finger = is_finger_control_name(bare)
        if is_finger:
            finger_ctrls.append(bare)
        curves = cmds.listConnections(ctrl, type="animCurve") or []
        keyed = set()
        ad = {}

        for crv in curves:
            conns = cmds.listConnections(crv, plugs=True) or []
            if not conns:
                continue
            attr = conns[0].split(".")[-1]
            keyed.add(attr)
            plug = "{}.{}".format(ctrl, attr)
            try:
                cmds.getAttr(plug)
            except Exception:
                continue

            times  = cmds.keyframe(crv, q=True) or []
            vals   = cmds.keyframe(crv, q=True, vc=True) or []
            itts   = cmds.keyTangent(crv, q=True, itt=True) or []
            otts   = cmds.keyTangent(crv, q=True, ott=True) or []
            tlocks = cmds.keyTangent(crv, q=True, lock=True) or []
            wlocks = cmds.keyTangent(crv, q=True, weightLock=True) or []
            bds    = set(cmds.keyframe(crv, q=True, breakdown=True) or [])
            ias    = cmds.keyTangent(crv, q=True, inAngle=True) or []
            oas    = cmds.keyTangent(crv, q=True, outAngle=True) or []
            iws    = cmds.keyTangent(crv, q=True, inWeight=True) or []
            ows    = cmds.keyTangent(crv, q=True, outWeight=True) or []

            weighted = False
            try:
                weighted = bool(cmds.getAttr("{}.weightedTangents".format(crv)))
            except Exception:
                pass
            pre_inf = post_inf = "constant"
            try:
                pre_inf = INFINITY_MAP.get(cmds.getAttr("{}.preInfinity".format(crv)), "constant")
                post_inf = INFINITY_MAP.get(cmds.getAttr("{}.postInfinity".format(crv)), "constant")
            except Exception:
                pass

            keys = []
            for i in range(len(times)):
                keys.append({
                    "time": times[i],
                    "value": vals[i] if i < len(vals) else 0,
                    "in_tan": itts[i] if i < len(itts) else "spline",
                    "out_tan": otts[i] if i < len(otts) else "spline",
                    "tan_lock": int(tlocks[i]) if i < len(tlocks) else 1,
                    "weight_lock": int(wlocks[i]) if i < len(wlocks) else 0,
                    "breakdown": 1 if times[i] in bds else 0,
                    "in_angle": ias[i] if i < len(ias) else 0.0,
                    "in_weight": iws[i] if i < len(iws) else 1.0,
                    "out_angle": oas[i] if i < len(oas) else 0.0,
                    "out_weight": ows[i] if i < len(ows) else 1.0,
                })
            if times:
                gmin = min(gmin, min(times))
                gmax = max(gmax, max(times))
            ad[attr] = {"keys": keys, "weighted": weighted, "pre_infinity": pre_inf, "post_infinity": post_inf}
            if is_finger and attr in ("rotateX", "rotateY", "rotateZ"):
                finger_rotate_keys += len(keys)
            if is_finger:
                finger_anim_attr_map.setdefault(bare, set()).add(attr)

        if include_static:
            statics = {}
            for attr in list_control_attrs(ctrl):
                if attr in keyed:
                    continue
                plug = "{}.{}".format(ctrl, attr)
                if cmds.listConnections(plug, d=False):
                    continue
                try:
                    v = cmds.getAttr(plug)
                    if isinstance(v, (int, float)):
                        statics[attr] = v
                        if is_finger and attr in ("rotateX", "rotateY", "rotateZ"):
                            finger_rotate_static += 1
                except Exception:
                    pass
            if statics:
                ad["__static__"] = statics
                if is_finger:
                    finger_anim_attr_map.setdefault(bare, set()).update(statics.keys())
        if ad:
            cd[bare] = ad
            rec = control_identity_record(ctrl)
            rec["attrs"] = ad
            controls_v2.append(rec)

    if gmin > gmax:
        gmin = gmax = cmds.currentTime(q=True)

    print("[ShepStudio] Clip export: {} controls ({} finger controls)".format(
        len(cd), len(set(finger_ctrls))))
    if finger_ctrls:
        print("[ShepStudio] Clip export: finger rotate keys={}, static attrs={}".format(
            finger_rotate_keys, finger_rotate_static))
        for n in sorted(set(finger_ctrls))[:20]:
            print("[ShepStudio]   finger ctrl: {}".format(n))
        if len(set(finger_ctrls)) > 20:
            print("[ShepStudio]   ... and {} more".format(len(set(finger_ctrls)) - 20))
        for ctrl_name, attrs in sorted(finger_anim_attr_map.items())[:20]:
            print("[ShepStudio]   saved attrs {}: {}".format(ctrl_name, ", ".join(sorted(attrs))))
    for rec in controls_v2[:10]:
        print("[ShepStudio] Clip identity saved: full='{}' short='{}' bare='{}'".format(
            rec.get("full_path", ""), rec.get("short_name", ""), rec.get("bare_name", "")))

    return {"format": FORMAT_CLIP, "version": FORMAT_VERSION,
            "timestamp": datetime.datetime.now().isoformat(),
            "source_file": cmds.file(q=True, sceneName=True) or "untitled",
            "source_namespace": src_ns, "frame_range": [gmin, gmax], "fps": fps,
            "thumbnail": thumbnail_b64, "control_count": len(cd), "controls": cd,
            "controls_v2": controls_v2,
            "rig_snapshot": build_rig_snapshot(controls)}


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  ORIENTATION-AWARE MIRROR  (matches digitMirror logic)                   ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

def _sample_rest_axes_batch(ctrls):
    """Temporarily zero rotations on every ctrl, read each control's
    world matrix to obtain its local-axis directions in world space,
    then restore the original rotations.

    Returns ``{ctrl: {"x": (vx,vy,vz), "y": ..., "z": ...}}``.
    Controls that cannot be sampled are omitted.
    """
    if not ctrls:
        return {}

    existing = [c for c in ctrls if cmds.objExists(c)]
    if not existing:
        return {}

    auto_key = cmds.autoKeyframe(q=True, state=True)
    if auto_key:
        cmds.autoKeyframe(state=False)

    # ── save & zero rotations ──
    saved = {}
    for ctrl in existing:
        saved[ctrl] = {}
        for ax in ("X", "Y", "Z"):
            plug = "{}.rotate{}".format(ctrl, ax)
            try:
                if not is_writable_plug(plug):
                    continue
                saved[ctrl][ax] = cmds.getAttr(plug)
                cmds.setAttr(plug, 0)
            except Exception:
                pass

    # ── read world matrices ──
    results = {}
    for ctrl in existing:
        try:
            wm = cmds.xform(ctrl, matrix=True, worldSpace=True, query=True)
            wm = [round(v, 4) for v in wm]
            results[ctrl] = {
                "x": tuple(wm[0:3]),
                "y": tuple(wm[4:7]),
                "z": tuple(wm[8:11]),
            }
        except Exception:
            pass

    # ── restore rotations ──
    for ctrl in existing:
        for ax, val in saved[ctrl].items():
            try:
                cmds.setAttr("{}.rotate{}".format(ctrl, ax), val)
            except Exception:
                pass
    if auto_key:
        cmds.autoKeyframe(state=True)

    return results


def _dominant_world_axis(vec):
    """Return the world axis label the vector points most along.

    Examples::

        (0.98, 0.01, -0.02)  →  "X"
        (-0.01, -0.99, 0.03) →  "-Y"
    """
    if not vec or all(v == 0 for v in vec):
        return "X"
    total = sum(abs(v) for v in vec)
    if total == 0:
        return "X"
    pct = [abs(v) / total for v in vec]
    idx = pct.index(max(pct))
    label = ("X", "Y", "Z")[idx]
    return ("-" + label) if vec[idx] < 0 else label


def _dominant_axes_dict(axes_dict):
    """Convert ``{"x": (vx,vy,vz), ...}`` to ``{"x": "X", "y": "-Z", ...}``."""
    if not axes_dict:
        return {"x": "X", "y": "Y", "z": "Z"}
    return {
        "x": _dominant_world_axis(axes_dict.get("x", (1, 0, 0))),
        "y": _dominant_world_axis(axes_dict.get("y", (0, 1, 0))),
        "z": _dominant_world_axis(axes_dict.get("z", (0, 0, 1))),
    }


def _infer_attr_rule(attr, src_dom, tgt_dom, mirror_axis):
    """Decide **copy** or **negate** for a single attribute by comparing
    the source and target control's dominant-axis orientations.

    This replicates the **runtime heuristic** from
    ``digetMirrorControl_v2`` (``mirror_pair``, lines 3208-3248)
    exactly, so that controls with *mirrored* joint orientations (the
    common case for finger / hand chains) get the correct per-attribute
    copy/negate decision.

    Returns ``True`` if the value should be **negated**, ``False`` for copy.
    """
    al = attr.lower()

    # ── determine attribute type ──
    if al.startswith("translate"):
        attr_type = "translate"
    elif al.startswith("rotate"):
        attr_type = "rotate"
    else:
        return False  # scale, custom, visibility → always copy

    # ── mirror_attr = local channel most aligned with mirror world axis ──
    def _mirror_local(m_ax, xd, yd, zd):
        for local, world in (("X", xd), ("Y", yd), ("Z", zd)):
            if m_ax == world or ("-" + m_ax) == world:
                return local
        return m_ax

    mirror_attr = _mirror_local(
        mirror_axis, src_dom["x"], src_dom["y"], src_dom["z"])

    same_ori = (src_dom["x"] == tgt_dom["x"] and
                src_dom["y"] == tgt_dom["y"] and
                src_dom["z"] == tgt_dom["z"])

    # ── same orientation → standard symmetric rules ──
    if same_ori:
        if attr_type == "translate":
            # negate the mirror-axis channel, copy others
            return mirror_attr in attr
        if attr_type == "rotate":
            # copy the mirror-axis channel, negate others
            return mirror_attr not in attr

    # ── different orientation (mirrored joint orientations) ──
    # Iterate through each axis pair exactly as the digitMirror runtime
    # does: check x_dom/opp_x_dom first, then y, then z, and use the
    # FIRST matching condition.

    axes_ordered = ("x", "y", "z")
    axis_labels  = {"x": "X", "y": "Y", "z": "Z"}

    def _is_mirror_same(m_ax, dom, opp_dom):
        return ((m_ax == dom and m_ax == opp_dom) or
                ("-" + m_ax == dom and "-" + m_ax == opp_dom))

    def _is_same_not_mirror(m_ax, dom, opp_dom):
        return (dom == opp_dom) and (dom != m_ax) and (dom != "-" + m_ax)

    if attr_type == "translate":
        # Pass 1 – axis pair where both dominants equal the mirror axis
        for ax in axes_ordered:
            if _is_mirror_same(mirror_axis, src_dom[ax], tgt_dom[ax]):
                return True  # negate
        # Pass 2 – first axis pair where dominants are equal (non-mirror)
        for ax in axes_ordered:
            if src_dom[ax] == tgt_dom[ax]:
                lbl = axis_labels[ax]
                # copy when attr channel matches mirror_attr or this pair's label
                return not (mirror_attr in attr or lbl in attr)
        return True  # fallback: negate

    if attr_type == "rotate":
        # First axis pair whose dominants are equal and NOT the mirror axis
        for ax in axes_ordered:
            if _is_same_not_mirror(mirror_axis, src_dom[ax], tgt_dom[ax]):
                lbl = axis_labels[ax]
                # negate when attr channel matches mirror_attr or this pair's label
                return (mirror_attr in attr or lbl in attr)
        return False  # fallback: copy

    return False


def _compute_negate_set(src_axes, tgt_axes, mirror_axis, attrs):
    """Return the subset of *attrs* that should be negated.

    *src_axes* / *tgt_axes* are the raw ``{"x": (vx,vy,vz), ...}``
    dicts from ``_sample_rest_axes_batch``.  If either is ``None`` the
    function falls back to the static ``MIRROR_NEGATE_MAP``.
    """
    fallback = MIRROR_NEGATE_MAP.get(mirror_axis, MIRROR_NEGATE_MAP["X"])
    if src_axes is None or tgt_axes is None:
        return fallback

    src_dom = _dominant_axes_dict(src_axes)
    tgt_dom = _dominant_axes_dict(tgt_axes)

    negate = set()
    for attr in attrs:
        if _infer_attr_rule(attr, src_dom, tgt_dom, mirror_axis):
            negate.add(attr)
    return negate


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  CORE — IMPORT                                                          ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

def _build_selection_context(selected_objects=None, target_ns=""):
    """Build lookup maps constrained to selected rig context."""
    selected = selection_to_transforms(selected_objects or [])
    if not selected:
        return None
    nodes = set()
    for n in selected:
        nodes.add(n)
        for d in (cmds.listRelatives(n, allDescendents=True, fullPath=True, type="transform") or []):
            nodes.add(d)
    # If target namespace is explicit, prefer nodes in that namespace.
    if target_ns and target_ns != "(no namespace)":
        filtered = set()
        for n in nodes:
            leaf = n.split("|")[-1]
            ns = leaf.rsplit(":", 1)[0] if ":" in leaf else ""
            if ns == target_ns:
                filtered.add(n)
        if filtered:
            nodes = filtered

    ctx = {"full": {}, "short": {}, "bare": {}}
    for n in nodes:
        ctx["full"][n] = n
        s = short_name(n)
        b = strip_namespace(n)
        ctx["short"].setdefault(s, []).append(n)
        ctx["bare"].setdefault(b, []).append(n)
    return ctx


def _resolve_from_context(saved_control_record, target_ns="", context=None):
    """Attempt resolution inside selected context first."""
    if not context:
        return None, "context", "no_context", []
    full_path = saved_control_record.get("full_path", "") or ""
    short = saved_control_record.get("short_name", "") or ""
    bare = saved_control_record.get("bare_name", "") or strip_namespace(short or full_path)

    if full_path in context["full"]:
        return full_path, "context_full_path", "ok", [full_path]
    if full_path and target_ns and target_ns != "(no namespace)":
        remapped = remap_full_path_to_namespace(full_path, target_ns)
        if remapped in context["full"]:
            return remapped, "context_full_path_ns_remap", "ok", [remapped]

    short_candidates = []
    if short:
        short_candidates.append(short)
        if target_ns and target_ns != "(no namespace)":
            short_candidates.append(add_namespace(strip_namespace(short), target_ns))
    for cand in short_candidates:
        found = context["short"].get(cand, [])
        if len(found) == 1:
            return found[0], "context_short_name", "ok", found
        if len(found) > 1:
            return None, "context_short_name", "ambiguous", found

    bare_candidates = []
    if target_ns and target_ns != "(no namespace)":
        bare_candidates.append(add_namespace(bare, target_ns))
    bare_candidates.append(bare)
    for cand in bare_candidates:
        found = context["bare"].get(strip_namespace(cand), [])
        if len(found) == 1:
            return found[0], "context_bare_name", "ok", found
        if len(found) > 1:
            return None, "context_bare_name", "ambiguous", found
    return None, "context", "not_found", []


def resolve_saved_control(saved_control_record, target_ns="", selection_context=None):
    """Resolve a saved control record to a scene node safely.

    Priority:
      1) exact full path
      2) remapped full path (namespace remap)
      3) exact short name (or remapped short)
      4) unique leaf-name fallback (namespaced bare, then bare)
    """
    full_path = saved_control_record.get("full_path", "") or ""
    short = saved_control_record.get("short_name", "") or ""
    bare = saved_control_record.get("bare_name", "") or strip_namespace(short or full_path)

    # Selection-aware matching first (StudioLibrary-style target context).
    ctx_node, ctx_match, ctx_status, ctx_candidates = _resolve_from_context(
        saved_control_record, target_ns=target_ns, context=selection_context)
    if ctx_status == "ok":
        return ctx_node, ctx_match, ctx_status, ctx_candidates
    if ctx_status == "ambiguous":
        return None, ctx_match, ctx_status, ctx_candidates

    # 1) exact full path
    if full_path and cmds.objExists(full_path):
        return full_path, "full_path", "ok", []

    # 2) namespace-remapped full path
    if full_path and target_ns and target_ns != "(no namespace)":
        remapped = remap_full_path_to_namespace(full_path, target_ns)
        if cmds.objExists(remapped):
            return remapped, "full_path_ns_remap", "ok", []

    # 3) exact/remapped short name
    short_candidates = []
    if short:
        short_candidates.append(short)
        if target_ns and target_ns != "(no namespace)":
            short_candidates.append(add_namespace(strip_namespace(short), target_ns))
    for cand in short_candidates:
        found = cmds.ls(cand, long=True) or []
        if len(found) == 1:
            return found[0], "short_name", "ok", found
        if len(found) > 1:
            return None, "short_name", "ambiguous", found

    # 4) unique bare-name fallback
    leaf_candidates = []
    if target_ns and target_ns != "(no namespace)":
        leaf_candidates.append(add_namespace(bare, target_ns))
    leaf_candidates.append(bare)
    for cand in leaf_candidates:
        found = cmds.ls(cand, long=True) or []
        if len(found) == 1:
            return found[0], "bare_name", "ok", found
        if len(found) > 1:
            return None, "bare_name", "ambiguous", found

    return None, "none", "not_found", []


def pose_control_records_from_data(data):
    """Return normalized pose records across old/new file formats."""
    if isinstance(data.get("controls_v2"), list):
        return data.get("controls_v2")

    records = []
    for bare, attrs in (data.get("controls", {}) or {}).items():
        records.append({
            "full_path": "",
            "short_name": bare,
            "bare_name": bare,
            "attrs": attrs,
        })
    return records


def clip_control_records_from_data(data):
    """Return normalized clip records across old/new file formats."""
    if isinstance(data.get("controls_v2"), list):
        return data.get("controls_v2")

    records = []
    for bare, anim_data in (data.get("controls", {}) or {}).items():
        records.append({
            "full_path": "",
            "short_name": bare,
            "bare_name": bare,
            "attrs": anim_data,
        })
    return records


def _resolve_mirror_ctrl(bare, mirror, mirror_direction, target_ns):
    """Return (target_bare, was_swapped) for a single control during import.

    *was_swapped* is True only when the side token was actually replaced,
    which is the signal that attribute values should be negated.  Controls
    without a recognised side token, or whose swapped name does not exist
    in the scene, are returned unchanged with ``was_swapped=False`` so their
    values are applied as-is (no negation).
    """
    if not mirror:
        return bare, False

    tb, did_swap = swap_side_token_directional(bare, mirror_direction)
    if not did_swap:
        # No side token found – apply control as-is, no negation.
        return bare, False

    # Safety: if the swapped control does not exist but the original does,
    # fall back to the original name (un-swapped, no negation).
    test_swapped = add_namespace(tb, target_ns)
    test_original = add_namespace(bare, target_ns)
    if (not cmds.objExists(test_swapped)) and cmds.objExists(test_original):
        print("[ShepStudio]   '{}' -> '{}' NOT FOUND, falling back to original".format(bare, tb))
        return bare, False

    return tb, True


def import_pose(data, target_ns="", mirror=False, mirror_direction="L2R",
                mirror_axis="X", selected_objects=None):
    """Apply a saved pose to the scene.

    When *mirror* is True the tool:

    1. Swaps side tokens in control names (``L2R`` or ``R2L``).
    2. Samples rest-pose world-matrix orientations for both the source
       and target control to decide **per attribute** whether to negate
       or copy the value.  This matches the ``digetMirrorControl``
       heuristic so that rigs with mirrored joint orientations (common
       on finger / hand chains) get their rotations copied instead of
       incorrectly negated.
    3. Falls back to the static ``MIRROR_NEGATE_MAP`` only when the
       orientation cannot be sampled.
    """
    records = pose_control_records_from_data(data)
    selection_context = _build_selection_context(selected_objects, target_ns=target_ns)
    controls = {r.get("bare_name", ""): (r.get("attrs", {}) or {}) for r in records}
    applied, skipped = 0, []
    finger_expected = [r.get("bare_name", "") for r in records if is_finger_control_name(r.get("bare_name", ""))]
    finger_restored = 0
    missing_expected_fingers = []
    restored_finger_controls = set()
    restored_finger_attr_map = {}
    control_debug_reports = []
    skipped_reasons = {
        "node_not_found": 0, "ambiguous_node_match": 0,
        "plug_missing": 0, "locked": 0, "not_settable": 0,
        "query_failed": 0, "setattr_failed": 0
    }

    # ── Phase 1: resolve control names ──
    resolved = []  # mirror: (bare, target_bare, was_swapped, attrs), non-mirror: (record, node, match_type, status, candidates)
    if mirror:
        for bare, attrs in controls.items():
            tb, was_swapped = _resolve_mirror_ctrl(
                bare, mirror, mirror_direction, target_ns)
            resolved.append((bare, tb, was_swapped, attrs))
    else:
        for rec in records:
            node, match_type, status, candidates = resolve_saved_control(
                rec, target_ns, selection_context=selection_context)
            resolved.append((rec, node, match_type, status, candidates))

    # ── Phase 2: orientation sampling (outside undo) ──
    # Collect every control that needs axis sampling.
    negate_map = {}  # target_full -> set_of_attrs_to_negate
    if mirror:
        sample_ctrls = set()
        for bare, tb, was_swapped, attrs in resolved:
            if was_swapped:
                sample_ctrls.add(add_namespace(bare, target_ns))  # source
                sample_ctrls.add(add_namespace(tb, target_ns))    # target
        axes_data = _sample_rest_axes_batch(list(sample_ctrls))

        print("[ShepStudio] Mirror pose import: direction={}, axis={}, "
              "{} controls in file, namespace='{}'".format(
                  mirror_direction, mirror_axis, len(controls), target_ns))

        for bare, tb, was_swapped, attrs in resolved:
            tgt_full = add_namespace(tb, target_ns)
            if was_swapped:
                src_full = add_namespace(bare, target_ns)
                negate_map[tgt_full] = _compute_negate_set(
                    axes_data.get(src_full), axes_data.get(tgt_full),
                    mirror_axis, list(attrs.keys()))

                print("[ShepStudio]   {} -> {}  negate={}".format(
                    bare, tb, negate_map[tgt_full] or "(none – orientations mirrored)"))
            else:
                negate_map[tgt_full] = set()

    # ── Phase 3: apply values ──
    print("[ShepStudio] Pose import: {} controls in file, target namespace='{}', "
          "mirror={}".format(len(controls), target_ns, mirror))

    # Show first few resolved names so the user can verify the mapping
    if mirror:
        for i, (bare, tb, _ws, _a) in enumerate(resolved):
            if i >= 3:
                print("[ShepStudio]   ... and {} more".format(len(resolved) - 3))
                break
            fn = add_namespace(tb, target_ns)
            exists = cmds.objExists(fn)
            print("[ShepStudio]   '{}' -> '{}' {}".format(
                bare, fn, "(found)" if exists else "(NOT FOUND)"))
    else:
        for i, (rec, node, match_type, status, candidates) in enumerate(resolved):
            if i >= 6:
                print("[ShepStudio]   ... and {} more".format(len(resolved) - 6))
                break
            ident = rec.get("full_path") or rec.get("short_name") or rec.get("bare_name")
            print("[ShepStudio]   '{}' -> '{}' [{}:{}]".format(
                ident, node or "(none)", match_type, status))
            if status == "ambiguous":
                print("[ShepStudio]      ambiguous candidates: {}".format(", ".join(candidates[:6])))

    iterable = []
    if mirror:
        for bare, tb, was_swapped, attrs in resolved:
            iterable.append((bare, add_namespace(tb, target_ns), was_swapped, attrs, "mirror", "", "", bare))
    else:
        for rec, node, match_type, status, _cands in resolved:
            bare = rec.get("bare_name", "")
            attrs = rec.get("attrs", {}) or {}
            if status == "ambiguous":
                skipped_reasons["ambiguous_node_match"] += 1
                skipped.append(bare)
                continue
            if not node:
                skipped_reasons["node_not_found"] += 1
                skipped.append(bare)
                continue
            iterable.append((
                bare, node, False, attrs, match_type,
                rec.get("full_path", ""), rec.get("short_name", ""), rec.get("bare_name", bare)
            ))

    for bare, fn, was_swapped, attrs, _match_type, saved_full, saved_short, saved_bare in iterable:
        control_report = {
            "saved_full": saved_full,
            "saved_short": saved_short,
            "saved_bare": saved_bare,
            "resolved": fn,
            "strategy": _match_type,
            "attrs_found": sorted(attrs.keys()),
            "attrs_applied": [],
            "attrs_skipped": {},
        }
        if not cmds.objExists(fn):
            skipped.append(fn)
            skipped_reasons["node_not_found"] += 1
            control_report["attrs_skipped"]["<control>"] = "node_not_found"
            control_debug_reports.append(control_report)
            if is_finger_control_name(bare):
                missing_expected_fingers.append(fn)
            continue

        ctrl_negate = negate_map.get(fn, set()) if mirror else set()

        ctrl_applied = 0
        for attr, value in attrs.items():
            # Skip non-numeric values (strings, None, booleans, compound
            # parent arrays like [(x,y,z)]) – these can't be set with a
            # simple cmds.setAttr(plug, value) call.
            if not isinstance(value, (int, float)):
                continue

            plug = "{}.{}".format(fn, attr)
            try:
                writable, reason = plug_write_state(plug)
                if not writable:
                    # For valid finger controls, attempt direct setAttr once before skipping.
                    if is_finger_control_name(bare) and reason in ("not_settable", "query_failed"):
                        try:
                            negate = was_swapped and attr in ctrl_negate
                            v = -value if negate else value
                            cmds.setAttr(plug, v)
                            applied += 1
                            finger_restored += 1
                            restored_finger_controls.add(strip_namespace(fn))
                            restored_finger_attr_map.setdefault(strip_namespace(fn), set()).add(attr)
                            print("[ShepStudio]     forced setAttr succeeded on non-settable finger plug: {}".format(plug))
                            control_report["attrs_applied"].append(attr)
                            continue
                        except Exception as exc:
                            print("[ShepStudio]     forced setAttr failed on {}: {}".format(plug, exc))
                            skipped_reasons["setattr_failed"] += 1
                            control_report["attrs_skipped"][attr] = "setattr_failed"
                    skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1
                    control_report["attrs_skipped"][attr] = reason
                    continue
                negate = was_swapped and attr in ctrl_negate
                v = -value if negate else value
                cmds.setAttr(plug, v)
                applied += 1
                ctrl_applied += 1
                control_report["attrs_applied"].append(attr)
                if is_finger_control_name(bare) and attr in ("rotateX", "rotateY", "rotateZ"):
                    finger_restored += 1
                    restored_finger_controls.add(strip_namespace(fn))
                    restored_finger_attr_map.setdefault(strip_namespace(fn), set()).add(attr)
            except Exception as exc:
                skipped_reasons["setattr_failed"] += 1
                control_report["attrs_skipped"][attr] = "setattr_failed"
                print("[ShepStudio]     WARN: {} – {}".format(plug, exc))
        control_debug_reports.append(control_report)

    if skipped:
        print("[ShepStudio] {} controls not found in scene (first 10):".format(
            len(skipped)))
        for s in skipped[:10]:
            print("[ShepStudio]   - {}".format(s))

    print("[ShepStudio] Import done: {} attrs applied, "
          "{} controls skipped".format(applied, len(skipped)))
    print("[ShepStudio] Pose import fingers: expected={}, restored rotate attrs={}".format(
        len(finger_expected), finger_restored))
    if missing_expected_fingers:
        print("[ShepStudio] Missing expected finger controls (first 20):")
        for n in missing_expected_fingers[:20]:
            print("[ShepStudio]   - {}".format(n))
        if len(missing_expected_fingers) > 20:
            print("[ShepStudio]   ... and {} more".format(len(missing_expected_fingers) - 20))
    print("[ShepStudio] Pose import skip reasons: {}".format(skipped_reasons))
    for ctrl_name, attrs in sorted(restored_finger_attr_map.items())[:20]:
        print("[ShepStudio] Pose finger restored {}: {}".format(ctrl_name, ", ".join(sorted(attrs))))
    for rep in control_debug_reports:
        if not (is_finger_control_name(rep["saved_bare"]) or is_hand_control_name(rep["saved_bare"])):
            continue
        print("[ShepStudio] IMPORT REPORT control='{}' full='{}' short='{}' -> '{}' [{}]".format(
            rep["saved_bare"], rep["saved_full"], rep["saved_short"], rep["resolved"], rep["strategy"]))
        print("[ShepStudio]   attrs in file: {}".format(", ".join(rep["attrs_found"][:25])))
        print("[ShepStudio]   attrs applied: {}".format(", ".join(rep["attrs_applied"][:25]) or "(none)"))
        if rep["attrs_skipped"]:
            for a, r in sorted(rep["attrs_skipped"].items())[:25]:
                print("[ShepStudio]   skip {} -> {}".format(a, r))
    debug_compare_finger_pose_coverage(data, target_ns, restored_controls=restored_finger_controls)

    return applied, skipped


def import_clip(data, target_ns="", mirror=False, frame_offset=0.0,
                replace_keys=True, include_static=True,
                mirror_direction="L2R", mirror_axis="X", selected_objects=None):
    """Apply a saved animation clip to the scene (with optional mirror).

    Uses orientation-aware negate logic identical to ``import_pose``.
    """
    records = clip_control_records_from_data(data)
    selection_context = _build_selection_context(selected_objects, target_ns=target_ns)
    controls = {r.get("bare_name", ""): (r.get("attrs", {}) or {}) for r in records}
    applied, skipped = 0, []
    finger_expected = [r.get("bare_name", "") for r in records if is_finger_control_name(r.get("bare_name", ""))]
    finger_restored_keys = 0
    finger_restored_static = 0
    missing_expected_fingers = []
    restored_finger_controls = set()
    restored_finger_attr_map = {}
    skipped_reasons = {
        "node_not_found": 0, "ambiguous_node_match": 0,
        "plug_missing": 0, "locked": 0, "not_settable": 0,
        "query_failed": 0, "setattr_failed": 0
    }

    # ── Phase 1: resolve control names ──
    resolved = []
    if mirror:
        for bare, ad in controls.items():
            tb, was_swapped = _resolve_mirror_ctrl(
                bare, mirror, mirror_direction, target_ns)
            resolved.append((bare, tb, was_swapped, ad))
    else:
        for rec in records:
            node, match_type, status, candidates = resolve_saved_control(
                rec, target_ns, selection_context=selection_context)
            resolved.append((rec, node, match_type, status, candidates))

    # ── Phase 2: orientation sampling ──
    negate_map = {}
    if mirror:
        sample_ctrls = set()
        for bare, tb, was_swapped, ad in resolved:
            if was_swapped:
                sample_ctrls.add(add_namespace(bare, target_ns))
                sample_ctrls.add(add_namespace(tb, target_ns))
        axes_data = _sample_rest_axes_batch(list(sample_ctrls))

        print("[ShepStudio] Mirror clip import: direction={}, axis={}, "
              "{} controls".format(mirror_direction, mirror_axis, len(controls)))

        for bare, tb, was_swapped, ad in resolved:
            tgt_full = add_namespace(tb, target_ns)
            if was_swapped:
                src_full = add_namespace(bare, target_ns)
                all_attrs = set()
                for attr, anim in ad.items():
                    if attr == "__static__":
                        all_attrs.update(anim.keys())
                    else:
                        all_attrs.add(attr)
                negate_map[tgt_full] = _compute_negate_set(
                    axes_data.get(src_full), axes_data.get(tgt_full),
                    mirror_axis, list(all_attrs))
            else:
                negate_map[tgt_full] = set()

    # ── Phase 3: apply values ──
    iterable = []
    if mirror:
        for bare, tb, was_swapped, ad in resolved:
            iterable.append((bare, add_namespace(tb, target_ns), was_swapped, ad, "", "", bare, "mirror"))
    else:
        for rec, node, match_type, status, candidates in resolved:
            bare = rec.get("bare_name", "")
            ad = rec.get("attrs", {}) or {}
            if status == "ambiguous":
                skipped_reasons["ambiguous_node_match"] += 1
                skipped.append(bare)
                print("[ShepStudio] Ambiguous clip control '{}': {}".format(
                    bare, ", ".join(candidates[:6])))
                continue
            if not node:
                skipped_reasons["node_not_found"] += 1
                skipped.append(bare)
                continue
            iterable.append((
                bare, node, False, ad,
                rec.get("full_path", ""), rec.get("short_name", ""), rec.get("bare_name", bare), match_type
            ))

    for bare, fn, was_swapped, ad, saved_full, saved_short, saved_bare, match_type in iterable:
        control_report = {
            "saved_full": saved_full,
            "saved_short": saved_short,
            "saved_bare": saved_bare,
            "resolved": fn,
            "strategy": match_type,
            "attrs_found": sorted(ad.keys()),
            "attrs_applied": [],
            "attrs_skipped": {},
        }
        if not cmds.objExists(fn):
            skipped.append(fn)
            skipped_reasons["node_not_found"] += 1
            control_report["attrs_skipped"]["<control>"] = "node_not_found"
            control_debug_reports.append(control_report)
            if is_finger_control_name(bare):
                missing_expected_fingers.append(fn)
            continue

        ctrl_negate = negate_map.get(fn, set()) if mirror else set()

        for attr, anim in ad.items():
            if attr == "__static__" and include_static:
                for sa, sv in anim.items():
                    if not isinstance(sv, (int, float)):
                        continue
                    plug = "{}.{}".format(fn, sa)
                    try:
                        writable, reason = plug_write_state(plug)
                        if not writable:
                            if is_finger_control_name(bare) and reason in ("not_settable", "query_failed"):
                                try:
                                    neg = was_swapped and sa in ctrl_negate
                                    cmds.setAttr(plug, -sv if neg else sv)
                                    finger_restored_static += 1
                                    restored_finger_controls.add(strip_namespace(fn))
                                    restored_finger_attr_map.setdefault(strip_namespace(fn), set()).add(sa)
                                    control_report["attrs_applied"].append(sa)
                                    print("[ShepStudio]     forced setAttr succeeded on finger static plug: {}".format(plug))
                                    continue
                                except Exception as exc:
                                    print("[ShepStudio]     forced setAttr failed on {}: {}".format(plug, exc))
                                    skipped_reasons["setattr_failed"] += 1
                                    control_report["attrs_skipped"][sa] = "setattr_failed"
                            skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1
                            control_report["attrs_skipped"][sa] = reason
                            continue
                        neg = was_swapped and sa in ctrl_negate
                        cmds.setAttr(plug, -sv if neg else sv)
                        control_report["attrs_applied"].append(sa)
                        if is_finger_control_name(bare) and sa in ("rotateX", "rotateY", "rotateZ"):
                            finger_restored_static += 1
                            restored_finger_controls.add(strip_namespace(fn))
                            restored_finger_attr_map.setdefault(strip_namespace(fn), set()).add(sa)
                    except Exception:
                        skipped_reasons["setattr_failed"] += 1
                        control_report["attrs_skipped"][sa] = "setattr_failed"
                        pass
                continue

            plug = "{}.{}".format(fn, attr)
            try:
                writable, reason = plug_write_state(plug)
                if not writable:
                    skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1
                    control_report["attrs_skipped"][attr] = reason
                    continue
                cmds.getAttr(plug)
            except Exception:
                skipped_reasons["query_failed"] += 1
                continue

            keys = anim.get("keys", [])
            if not keys:
                continue
            if replace_keys:
                try:
                    cmds.cutKey(plug, clear=True)
                except Exception:
                    pass

            neg = was_swapped and attr in ctrl_negate
            weighted = anim.get("weighted", False)
            for k in keys:
                t = k["time"] + frame_offset
                v = -k["value"] if neg else k["value"]
                try:
                    cmds.setKeyframe(plug, time=t, value=v,
                                     breakdown=k.get("breakdown", 0))
                    if is_finger_control_name(bare) and attr in ("rotateX", "rotateY", "rotateZ"):
                        finger_restored_keys += 1
                        restored_finger_controls.add(strip_namespace(fn))
                        restored_finger_attr_map.setdefault(strip_namespace(fn), set()).add(attr)
                except Exception:
                    skipped_reasons["setattr_failed"] += 1
                    control_report["attrs_skipped"][attr] = "setattr_failed"
                    continue
                try:
                    cmds.keyTangent(plug, e=True, time=(t, t),
                                    lock=k.get("tan_lock", 1))
                except Exception:
                    pass
                if weighted:
                    try:
                        cmds.keyTangent(plug, e=True, weightedTangents=True)
                        cmds.keyTangent(plug, e=True, time=(t, t),
                                        weightLock=k.get("weight_lock", 0))
                    except Exception:
                        pass
                try:
                    kw = dict(edit=True, absolute=True, time=(t, t),
                              itt=k.get("in_tan", "spline"),
                              ott=k.get("out_tan", "spline"))
                    if k.get("in_tan") == "fixed":
                        kw["inAngle"] = k.get("in_angle", 0)
                        kw["inWeight"] = k.get("in_weight", 1)
                    if k.get("out_tan") == "fixed":
                        kw["outAngle"] = k.get("out_angle", 0)
                        kw["outWeight"] = k.get("out_weight", 1)
                    cmds.keyTangent(plug, **kw)
                except Exception:
                    pass
            try:
                cmds.setInfinity(
                    plug,
                    preInfinite=anim.get("pre_infinity", "constant"),
                    postInfinite=anim.get("post_infinity", "constant"),
                )
            except Exception:
                pass
            applied += 1
            control_report["attrs_applied"].append(attr)
        control_debug_reports.append(control_report)

    print("[ShepStudio] Clip import fingers: expected={}, restored rotate keys={}, restored static={}".format(
        len(finger_expected), finger_restored_keys, finger_restored_static))
    if missing_expected_fingers:
        print("[ShepStudio] Missing expected finger controls (first 20):")
        for n in missing_expected_fingers[:20]:
            print("[ShepStudio]   - {}".format(n))
        if len(missing_expected_fingers) > 20:
            print("[ShepStudio]   ... and {} more".format(len(missing_expected_fingers) - 20))
    print("[ShepStudio] Clip import skip reasons: {}".format(skipped_reasons))
    for ctrl_name, attrs in sorted(restored_finger_attr_map.items())[:20]:
        print("[ShepStudio] Clip finger restored {}: {}".format(ctrl_name, ", ".join(sorted(attrs))))
    for rep in control_debug_reports:
        if not (is_finger_control_name(rep["saved_bare"]) or is_hand_control_name(rep["saved_bare"])):
            continue
        print("[ShepStudio] CLIP REPORT control='{}' full='{}' short='{}' -> '{}' [{}]".format(
            rep["saved_bare"], rep["saved_full"], rep["saved_short"], rep["resolved"], rep["strategy"]))
        print("[ShepStudio]   attrs in file: {}".format(", ".join(rep["attrs_found"][:25])))
        print("[ShepStudio]   attrs applied: {}".format(", ".join(rep["attrs_applied"][:25]) or "(none)"))
        if rep["attrs_skipped"]:
            for a, r in sorted(rep["attrs_skipped"].items())[:25]:
                print("[ShepStudio]   skip {} -> {}".format(a, r))
    debug_compare_finger_pose_coverage(data, target_ns, restored_controls=restored_finger_controls)

    return applied, skipped


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  FILE I/O                                                                ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

def save_to_file(data, filepath):
    d = os.path.dirname(filepath)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)

def load_from_file(filepath):
    with open(filepath, "r") as f:
        return json.load(f)


def debug_compare_finger_pose_coverage(data, target_ns="", restored_controls=None):
    """Print side-by-side coverage for scene vs file vs restored finger controls."""
    saved = set(k for k in (data.get("controls", {}) or {}).keys() if is_finger_control_name(k))
    scene = set()
    ns_filter = {target_ns} if target_ns and target_ns != "(no namespace)" else None
    for node in cmds.ls(type="transform", long=True) or []:
        if ns_filter:
            leaf = node.split("|")[-1]
            node_ns = leaf.rsplit(":", 1)[0] if ":" in leaf else ""
            if node_ns not in ns_filter:
                continue
        if is_helper_control_name(node):
            continue
        if is_finger_control_name(node) and _is_likely_control(node):
            scene.add(strip_namespace(node))
    restored = set(restored_controls or [])
    print("[ShepStudio] Finger coverage compare:")
    print("[ShepStudio]   Scene expected: {}".format(len(scene)))
    print("[ShepStudio]   Saved in file: {}".format(len(saved)))
    print("[ShepStudio]   Restored now:   {}".format(len(restored)))
    missing_in_file = sorted(scene - saved)
    missing_on_restore = sorted(saved - restored)
    if missing_in_file:
        print("[ShepStudio]   Missing in file (first 20): {}".format(", ".join(missing_in_file[:20])))
    if missing_on_restore:
        print("[ShepStudio]   Saved but not restored (first 20): {}".format(", ".join(missing_on_restore[:20])))


def debug_compare_shep_vs_studio_pose(shep_pose_path, studio_pose_json_path):
    """Compare finger control identities between ShepStudio and StudioLibrary poses."""
    try:
        shep = load_from_file(shep_pose_path)
    except Exception as exc:
        print("[ShepStudio] compare failed loading Shep pose: {}".format(exc))
        return
    try:
        studio = load_from_file(studio_pose_json_path)
    except Exception as exc:
        print("[ShepStudio] compare failed loading Studio pose: {}".format(exc))
        return

    shep_records = pose_control_records_from_data(shep)
    shep_fingers = set(
        (r.get("full_path") or r.get("short_name") or r.get("bare_name", ""))
        for r in shep_records if is_finger_control_name(r.get("bare_name", ""))
    )

    # Studio pose schema varies; support common map/list patterns.
    studio_controls = studio.get("controls", {}) if isinstance(studio, dict) else {}
    studio_keys = set()
    if isinstance(studio_controls, dict):
        studio_keys = set(studio_controls.keys())
    elif isinstance(studio_controls, list):
        for c in studio_controls:
            if isinstance(c, dict):
                studio_keys.add(c.get("name") or c.get("full_path") or c.get("path") or "")
            elif isinstance(c, str):
                studio_keys.add(c)
    studio_fingers = set(k for k in studio_keys if is_finger_control_name(k))

    print("[ShepStudio] Pose compare: Shep finger ctrls={}, Studio finger ctrls={}".format(
        len(shep_fingers), len(studio_fingers)))
    only_shep = sorted(shep_fingers - studio_fingers)
    only_studio = sorted(studio_fingers - shep_fingers)
    if only_shep:
        print("[ShepStudio]   Only in Shep (first 20): {}".format(", ".join(only_shep[:20])))
    if only_studio:
        print("[ShepStudio]   Only in Studio (first 20): {}".format(", ".join(only_studio[:20])))


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  THUMBNAIL CARD                                                          ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class ThumbnailCard(QtWidgets.QFrame):
    clicked = Signal(str)
    double_clicked = Signal(str)

    def __init__(self, filepath, thumb_size=DEFAULT_THUMB_SIZE, parent=None):
        super().__init__(parent)
        self.filepath = filepath
        self.ts = thumb_size
        self.setFixedSize(thumb_size + 16, thumb_size + 44)
        self.setCursor(Qt.PointingHandCursor)
        self._build()

    def _build(self):
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4,4,4,4)
        lay.setSpacing(2)
        self.thumb = QtWidgets.QLabel()
        self.thumb.setFixedSize(self.ts, self.ts)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setStyleSheet("background-color:#1e1e1e; border-radius:4px; border:1px solid #444;")
        lay.addWidget(self.thumb)
        self.name_lbl = QtWidgets.QLabel()
        self.name_lbl.setAlignment(Qt.AlignCenter)
        self.name_lbl.setStyleSheet("font-size:10px; color:#bbb;")
        self.name_lbl.setFixedWidth(self.ts+8)
        lay.addWidget(self.name_lbl)
        self.type_lbl = QtWidgets.QLabel()
        self.type_lbl.setAlignment(Qt.AlignCenter)
        self.type_lbl.setFixedWidth(self.ts+8)
        lay.addWidget(self.type_lbl)

        name = os.path.splitext(os.path.basename(self.filepath))[0]
        ext = os.path.splitext(self.filepath)[1].lower()
        self.name_lbl.setText(name)
        if ext == POSE_EXT:
            self.type_lbl.setText("POSE")
            self.type_lbl.setStyleSheet("font-size:9px; font-weight:bold; color:#7ab8e0;")
        else:
            self.type_lbl.setText("ANIMATION")
            self.type_lbl.setStyleSheet("font-size:9px; font-weight:bold; color:#e0c87a;")

        try:
            with open(self.filepath, "r") as f:
                data = json.load(f)
            tb = data.get("thumbnail")
            if tb:
                pix = QtGui.QPixmap()
                pix.loadFromData(base64.b64decode(tb))
                self.thumb.setPixmap(pix.scaled(self.ts-4, self.ts-4, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.thumb.setText("No\nPreview")
                self.thumb.setStyleSheet(self.thumb.styleSheet() + "color:#555; font-size:11px;")
        except Exception:
            self.thumb.setText("Error")

    def set_selected(self, sel):
        b = "border:2px solid #4a90d9;" if sel else "border:2px solid transparent;"
        bg = "background-color:#33506a;" if sel else "background-color:transparent;"
        self.setStyleSheet("ThumbnailCard{{{bg}{b}border-radius:6px;}}ThumbnailCard:hover{{background-color:#353545;}}".format(bg=bg, b=b))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton: self.clicked.emit(self.filepath)
        super().mousePressEvent(e)
    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton: self.double_clicked.emit(self.filepath)
        super().mouseDoubleClickEvent(e)


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  FLOW LAYOUT                                                             ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class FlowLayout(QtWidgets.QLayout):
    def __init__(self, parent=None, margin=8, spacing=8):
        super().__init__(parent)
        self._items, self._m, self._s = [], margin, spacing
    def addItem(self, item):  self._items.append(item)
    def count(self):          return len(self._items)
    def itemAt(self, i):      return self._items[i] if 0<=i<len(self._items) else None
    def takeAt(self, i):      return self._items.pop(i) if 0<=i<len(self._items) else None
    def hasHeightForWidth(self): return True
    def heightForWidth(self, w): return self._lay(QtCore.QRect(0,0,w,0), True)
    def setGeometry(self, r): super().setGeometry(r); self._lay(r)
    def sizeHint(self): return self.minimumSize()
    def minimumSize(self):
        s = QtCore.QSize()
        for it in self._items: s = s.expandedTo(it.minimumSize())
        return s + QtCore.QSize(2*self._m, 2*self._m)
    def _lay(self, rect, test=False):
        x, y, lh = rect.x()+self._m, rect.y()+self._m, 0
        for it in self._items:
            w, h = it.sizeHint().width(), it.sizeHint().height()
            if x+w+self._s > rect.right() and lh > 0:
                x = rect.x()+self._m; y += lh+self._s; lh = 0
            if not test: it.setGeometry(QtCore.QRect(QtCore.QPoint(x,y), it.sizeHint()))
            x += w+self._s; lh = max(lh, h)
        return y+lh-rect.y()+self._m


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  CAPTURE DIALOG                                                          ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class CaptureDialog(QtWidgets.QDialog):
    """Modal dialog for capturing a pose or animation clip."""

    def __init__(self, mode="pose", parent=None, focus_nodes=None):
        super().__init__(parent)
        self.mode = mode
        self.focus_nodes = focus_nodes or []
        self.result_name = None
        self.result_hierarchy = False
        self.result_static = True
        self.thumb_b64 = None
        self._thumb_auto_frame = True
        self.setWindowTitle("Capture Pose" if mode == "pose" else "Capture Animation")
        self.setMinimumWidth(440)
        self.setStyleSheet(DARK_STYLESHEET.replace("#shepMainWidget", "CaptureDialog"))
        self._build()

    def _build(self):
        lay = QtWidgets.QVBoxLayout(self)
        lay.setSpacing(10)

        # Step-by-step instructions
        if self.mode == "pose":
            desc = (
                "<b>Step 1:</b>  You've selected your rig controls  ✓<br>"
                "<b>Step 2:</b>  Enter a name below<br>"
                "<b>Step 3:</b>  Choose scope & options<br>"
                "<b>Step 4:</b>  Click <b>Save Pose</b>"
            )
        else:
            desc = (
                "<b>Step 1:</b>  You've selected your rig controls  ✓<br>"
                "<b>Step 2:</b>  Enter a name below<br>"
                "<b>Step 3:</b>  Choose scope & options<br>"
                "<b>Step 4:</b>  Click <b>Save Animation</b>"
            )
        header = QtWidgets.QLabel(desc)
        header.setWordWrap(True)
        header.setStyleSheet("color:#aaa; font-size:11px; padding:6px; background-color:#333; border-radius:4px;")
        lay.addWidget(header)

        # Name
        nr = QtWidgets.QHBoxLayout()
        nl = QtWidgets.QLabel("Name:")
        nl.setStyleSheet("font-weight:bold;")
        nr.addWidget(nl)
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setPlaceholderText("e.g.  Idle_Pose_v01")
        self.name_edit.setToolTip("Enter a descriptive name.  Avoid special characters: / \\ : * ? \" < > |")
        nr.addWidget(self.name_edit)
        lay.addLayout(nr)

        # Scope
        sr = QtWidgets.QHBoxLayout()
        sl = QtWidgets.QLabel("Scope:")
        sl.setStyleSheet("font-weight:bold;")
        sr.addWidget(sl)
        self.scope_sel = QtWidgets.QRadioButton("Selected Controls Only")
        self.scope_sel.setChecked(True)
        self.scope_sel.setToolTip("Only export data for the controls currently selected in the viewport.")
        self.scope_hier = QtWidgets.QRadioButton("Full Hierarchy")
        self.scope_hier.setToolTip("Walk down the hierarchy from your selection and capture every rig control found.")
        sr.addWidget(self.scope_sel)
        sr.addWidget(self.scope_hier)
        sr.addStretch()
        lay.addLayout(sr)

        self.static_cb = QtWidgets.QCheckBox("Include static (un-keyed) attributes")
        self.static_cb.setChecked(True)
        self.static_cb.setToolTip("Also store attribute values that have no keyframes — catches hand-posed values.")
        lay.addWidget(self.static_cb)

        # Thumbnail
        tg = QtWidgets.QGroupBox("Thumbnail Preview")
        tl = QtWidgets.QHBoxLayout(tg)
        self.thumb_preview = QtWidgets.QLabel("Capturing…")
        self.thumb_preview.setFixedSize(160, 160)
        self.thumb_preview.setAlignment(Qt.AlignCenter)
        self.thumb_preview.setStyleSheet("background-color:#1e1e1e; border-radius:6px; border:1px solid #444; color:#666; font-size:11px;")
        tl.addWidget(self.thumb_preview)
        info = QtWidgets.QLabel(
            "The camera auto-frames your selected\n"
            "controls and captures a viewport\n"
            "screenshot for the library card.\n\n"
            "This happens automatically when\n"
            "this dialog opens.\n\n"
            "If framing is not ideal, move the camera\n"
            "in the viewport and recapture."
        )
        info.setStyleSheet("color:#777; font-size:10px;")
        tl.addWidget(info)
        tl.addStretch()
        lay.addWidget(tg)

        thumb_btns = QtWidgets.QHBoxLayout()
        thumb_btns.addStretch()
        self.recap_auto_btn = QtWidgets.QPushButton("Recapture (Auto-Frame)")
        self.recap_auto_btn.setToolTip("Auto-frame selected controls and recapture thumbnail.")
        self.recap_auto_btn.clicked.connect(self._recapture_auto)
        thumb_btns.addWidget(self.recap_auto_btn)
        self.recap_manual_btn = QtWidgets.QPushButton("Recapture (Current View)")
        self.recap_manual_btn.setToolTip("Use your current viewport camera position and recapture thumbnail.")
        self.recap_manual_btn.clicked.connect(self._recapture_manual)
        thumb_btns.addWidget(self.recap_manual_btn)
        lay.addLayout(thumb_btns)

        # Buttons
        br = QtWidgets.QHBoxLayout()
        br.addStretch()
        self.save_btn = QtWidgets.QPushButton("💾  Save Pose" if self.mode == "pose" else "💾  Save Animation")
        self.save_btn.setMinimumHeight(34)
        self.save_btn.setMinimumWidth(160)
        self.save_btn.setStyleSheet(
            "QPushButton{background-color:#3a7abd; color:#fff; font-weight:bold; font-size:12px;"
            "border:1px solid #4a90d9; border-radius:5px; padding:6px 16px;}"
            "QPushButton:hover{background-color:#4a90d9;}")
        self.save_btn.clicked.connect(self._accept)
        br.addWidget(self.save_btn)
        cancel = QtWidgets.QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        br.addWidget(cancel)
        lay.addLayout(br)

    def do_capture(self):
        QtWidgets.QApplication.processEvents()
        self.thumb_b64 = capture_thumbnail(400, 400, self._thumb_auto_frame, self.focus_nodes)
        if self.thumb_b64:
            pix = QtGui.QPixmap()
            pix.loadFromData(base64.b64decode(self.thumb_b64))
            self.thumb_preview.setPixmap(pix.scaled(156,156, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.thumb_preview.setText("")
        else:
            self.thumb_preview.setText("Capture failed\n(check viewport)")

    def _recapture_auto(self):
        self._thumb_auto_frame = True
        self.do_capture()

    def _recapture_manual(self):
        popup = QtWidgets.QDialog(self)
        popup.setWindowTitle("Viewport Thumbnail Capture")
        popup.setMinimumWidth(420)
        popup.setWindowFlag(Qt.Tool, True)
        lay = QtWidgets.QVBoxLayout(popup)
        lay.addWidget(QtWidgets.QLabel(
            "Manually frame the pose in the Maya viewport,\n"
            "then click <b>Capture Current View</b> below."
        ))
        btns = QtWidgets.QHBoxLayout()
        btns.addStretch()
        cap_btn = QtWidgets.QPushButton("Capture Current View")
        cancel_btn = QtWidgets.QPushButton("Cancel")
        btns.addWidget(cap_btn)
        btns.addWidget(cancel_btn)
        lay.addLayout(btns)

        def _capture_now():
            self._thumb_auto_frame = False
            self.do_capture()
            popup.accept()

        cap_btn.clicked.connect(_capture_now)
        cancel_btn.clicked.connect(popup.reject)
        popup.exec()

    def _accept(self):
        name = self.name_edit.text().strip()
        if not name:
            QtWidgets.QMessageBox.warning(self, "Name Required", "Please enter a name for this library item.")
            return
        for c in r'/\:*?"<>|':
            name = name.replace(c, "_")
        self.result_name = name
        self.result_hierarchy = self.scope_hier.isChecked()
        self.result_static = self.static_cb.isChecked()
        self.accept()


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  SETTINGS DIALOG                                                         ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ShepStudio Settings")
        self.setMinimumWidth(480)
        self.setStyleSheet(DARK_STYLESHEET.replace("#shepMainWidget", "SettingsDialog"))
        lay = QtWidgets.QVBoxLayout(self)
        lay.setSpacing(12)

        g = QtWidgets.QGroupBox("Library Location")
        gl = QtWidgets.QVBoxLayout(g)
        gl.addWidget(QtWidgets.QLabel("Root folder where poses & clips are stored.\nCreate sub-folders per character or project."))
        rl = QtWidgets.QHBoxLayout()
        self.root_edit = QtWidgets.QLineEdit(get_library_root())
        bb = QtWidgets.QPushButton("Browse…")
        bb.clicked.connect(self._browse)
        rl.addWidget(self.root_edit); rl.addWidget(bb)
        gl.addLayout(rl)
        lay.addWidget(g)

        g2 = QtWidgets.QGroupBox("Display")
        g2l = QtWidgets.QHBoxLayout(g2)
        g2l.addWidget(QtWidgets.QLabel("Thumbnail card size:"))
        self.ts = QtWidgets.QSpinBox()
        self.ts.setRange(80,300)
        self.ts.setValue(cmds.optionVar(q=OPT_THUMB_SIZE) if cmds.optionVar(exists=OPT_THUMB_SIZE) else DEFAULT_THUMB_SIZE)
        g2l.addWidget(self.ts); g2l.addStretch()
        lay.addWidget(g2)

        br = QtWidgets.QHBoxLayout()
        br.addStretch()
        sb = QtWidgets.QPushButton("Save"); sb.clicked.connect(self._save)
        cb = QtWidgets.QPushButton("Cancel"); cb.clicked.connect(self.reject)
        br.addWidget(sb); br.addWidget(cb)
        lay.addLayout(br)

    def _browse(self):
        p = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose Library Folder", self.root_edit.text())
        if p: self.root_edit.setText(p)
    def _save(self):
        r = self.root_edit.text().strip()
        if r:
            set_library_root(r)
            if not os.path.isdir(r): os.makedirs(r)
        cmds.optionVar(iv=(OPT_THUMB_SIZE, self.ts.value()))
        self.accept()


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  NAMESPACE REMAP DIALOG                                                  ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class NamespaceRemapDialog(QtWidgets.QDialog):
    """Pop-out window for mapping a saved file's namespace to the scene."""

    def __init__(self, parent=None, source_ns="", scene_namespaces=None,
                 current_scene_ns="", current_remap=""):
        super().__init__(parent)
        self.setWindowTitle("Namespace Remap")
        self.setMinimumWidth(520)
        self.setStyleSheet(
            "QDialog { background-color: #2b2b2b; color: #d4d4d4; }"
            "QLabel  { color: #cccccc; }"
            "QGroupBox { font-weight: bold; border: 1px solid #555; "
            "            border-radius: 4px; margin-top: 8px; padding-top: 14px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; "
            "                   padding: 0 4px; color: #aaa; }"
            "QPushButton { background-color: #3a3a3a; border: 1px solid #555; "
            "              border-radius: 3px; padding: 5px 14px; color: #d4d4d4; }"
            "QPushButton:hover { background-color: #4a4a4a; }"
            "QPushButton#applyBtn { background-color: #2a6a2a; border-color: #3a8a3a; }"
            "QPushButton#applyBtn:hover { background-color: #3a7a3a; }"
            "QComboBox { background-color: #1e1e1e; border: 1px solid #555; "
            "            border-radius: 3px; padding: 3px 6px; color: #d4d4d4; }"
            "QLineEdit { background-color: #1e1e1e; border: 1px solid #555; "
            "            border-radius: 3px; padding: 3px 6px; color: #d4d4d4; }"
        )

        self._result_ns = current_scene_ns
        self._result_remap = current_remap

        root = QtWidgets.QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 16)

        # ── Title ──
        title = QtWidgets.QLabel("Namespace Remap")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #7ab8e0;")
        root.addWidget(title)

        # ── Mapping table ──
        tbl = QtWidgets.QGroupBox("Remap Mapping")
        tl = QtWidgets.QVBoxLayout(tbl); tl.setSpacing(8)

        # Header
        hdr = QtWidgets.QHBoxLayout()
        for label_text in ("File Namespace", "Scene Namespace", "Remap To"):
            lbl = QtWidgets.QLabel(label_text)
            lbl.setStyleSheet("font-weight:bold; font-size:12px; color:#999;")
            hdr.addWidget(lbl, stretch=1)
        tl.addLayout(hdr)

        # Row: source → scene → remap
        row = QtWidgets.QHBoxLayout()

        self.src_label = QtWidgets.QLabel(source_ns if source_ns else "(no namespace)")
        self.src_label.setStyleSheet(
            "background:#1a1a1a; border:1px solid #444; border-radius:3px; "
            "padding:5px 8px; color:#e0c87a; font-weight:bold; font-size:12px;"
        )
        self.src_label.setMinimumHeight(28)
        row.addWidget(self.src_label, stretch=1)

        self.scene_combo = QtWidgets.QComboBox()
        self.scene_combo.setMinimumHeight(28)
        if scene_namespaces:
            self.scene_combo.addItems(scene_namespaces)
        if current_scene_ns:
            idx = self.scene_combo.findText(current_scene_ns)
            if idx >= 0:
                self.scene_combo.setCurrentIndex(idx)
        row.addWidget(self.scene_combo, stretch=1)

        self.remap_edit = QtWidgets.QLineEdit()
        self.remap_edit.setPlaceholderText("(optional override)")
        self.remap_edit.setMinimumHeight(28)
        if current_remap:
            self.remap_edit.setText(current_remap)
        row.addWidget(self.remap_edit, stretch=1)

        tl.addLayout(row)

        # Refresh button
        ref_row = QtWidgets.QHBoxLayout()
        ref_row.addStretch()
        ref_btn = QtWidgets.QPushButton("↻  Refresh Namespaces")
        ref_btn.clicked.connect(self._refresh)
        ref_row.addWidget(ref_btn)
        tl.addLayout(ref_row)

        root.addWidget(tbl)

        # ── Help text ──
        help_box = QtWidgets.QGroupBox("How To Use")
        hl = QtWidgets.QVBoxLayout(help_box)
        help_label = QtWidgets.QLabel(
            "<p style='line-height:1.5;'>"
            "<b>File Namespace</b> shows the namespace that was used when the "
            "pose or animation was originally captured.<br>"
            "Example: <span style='color:#e0c87a;'>ProRigs_Chris_v01_10_L</span></p>"
            "<p style='line-height:1.5;'>"
            "<b>Scene Namespace</b> is the namespace of the rig currently in "
            "your Maya scene that you want to apply the data to. Select it "
            "from the dropdown.<br>"
            "Example: <span style='color:#7ab8e0;'>ProRigs_Chris_v01_10</span></p>"
            "<p style='line-height:1.5;'>"
            "<b>Remap To</b> is an optional override. If the namespace you "
            "need is not in the Scene Namespace dropdown, type it here. "
            "This field takes priority over the dropdown when filled in.</p>"
            "<hr style='border-color:#444;'>"
            "<p style='line-height:1.5; color:#aaa;'>"
            "<b>How it works:</b>  Saved controls are stored without "
            "namespaces (e.g. <code>ac_lf_handFK</code>). On import, the "
            "Scene Namespace (or Remap To value) is prepended:<br>"
            "<code style='color:#888;'>ac_lf_handFK</code> &rarr; "
            "<code style='color:#7ab8e0;'>ProRigs_Chris_v01_10</code>"
            "<code style='color:#888;'>:ac_lf_handFK</code></p>"
            "<p style='line-height:1.5; color:#aaa;'>"
            "If no controls are found after import, check the Script Editor "
            "for diagnostic messages showing which control names were "
            "attempted and whether they were found in the scene.</p>"
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet("font-size: 11px; color: #bbb;")
        hl.addWidget(help_label)
        root.addWidget(help_box)

        # ── Buttons ──
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()

        apply_btn = QtWidgets.QPushButton("Apply")
        apply_btn.setObjectName("applyBtn")
        apply_btn.setFixedWidth(100)
        apply_btn.clicked.connect(self._apply)
        btn_row.addWidget(apply_btn)

        close_btn = QtWidgets.QPushButton("Close")
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)

        root.addLayout(btn_row)

    def _refresh(self):
        ns = detect_scene_namespaces()
        prev = self.scene_combo.currentText()
        self.scene_combo.clear()
        self.scene_combo.addItems(ns)
        idx = self.scene_combo.findText(prev)
        if idx >= 0:
            self.scene_combo.setCurrentIndex(idx)

    def _apply(self):
        self._result_ns = self.scene_combo.currentText()
        self._result_remap = self.remap_edit.text().strip()
        self.accept()

    @property
    def target_namespace(self):
        """Return the resolved target namespace."""
        if self._result_remap:
            return self._result_remap
        return self._result_ns


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  MAIN WINDOW                                                             ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class ShepStudioAnimLib(QtWidgets.QWidget):
    _instance = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("shepMainWidget")
        self.setStyleSheet(DARK_STYLESHEET)
        self.setMinimumSize(320, 260)
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Expanding)
        self._folder = get_library_root()
        self._sel_file = None
        self._sel_card = None
        self._data = None
        self._build_ui()
        self._refresh_tree()
        self._refresh_grid()
        self._refresh_ns()

    @classmethod
    def show(cls):
        if cmds.workspaceControl(WORKSPACE_NAME, exists=True):
            cmds.deleteUI(WORKSPACE_NAME)
        cls._instance = cls(parent=maya_main_window())
        cmds.workspaceControl(WORKSPACE_NAME, label=TOOL_NAME,
            widthProperty="free", initialWidth=960, initialHeight=680, retain=False)
        wp = wrapInstance(int(omui.MQtUtil.findControl(WORKSPACE_NAME)), QtWidgets.QWidget)
        wp.setMinimumSize(320, 260)
        wp.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Expanding)
        wl = wp.layout()
        if not wl:
            wl = QtWidgets.QVBoxLayout(wp)
            wl.setContentsMargins(0,0,0,0)
        wl.addWidget(cls._instance)

    # ── UI ──

    def _build_ui(self):
        ml = QtWidgets.QVBoxLayout(self)
        ml.setContentsMargins(0,0,0,0)
        ml.setSpacing(0)

        self.menu_bar = QtWidgets.QMenuBar()
        self._build_menu()
        ml.addWidget(self.menu_bar)

        sp = QtWidgets.QSplitter(Qt.Horizontal)
        folders = self._build_folders()
        grid = self._build_grid()
        detail = self._build_detail()
        for pane in (folders, grid, detail):
            pane.setMinimumWidth(0)
            pane.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Expanding)
        sp.addWidget(folders)
        sp.addWidget(grid)
        sp.addWidget(detail)
        sp.setChildrenCollapsible(True)
        sp.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Expanding)
        sp.setSizes([185, 440, 310])
        ml.addWidget(sp, stretch=1)

        self.status = QtWidgets.QStatusBar()
        self.status.showMessage("Ready  —  Select controls in the viewport, then click  Capture Pose  or  Capture Animation")
        ml.addWidget(self.status)

    def _build_menu(self):
        fm = self.menu_bar.addMenu("File")
        fm.addAction("Capture Pose from Selection…", self._cap_pose)
        fm.addAction("Capture Animation from Selection…", self._cap_clip)
        fm.addSeparator()
        fm.addAction("Refresh Library", self._refresh_all)
        fm.addAction("Open Library Folder…", self._open_lib)
        fm.addSeparator()
        fm.addAction("Settings…", self._settings)
        hm = self.menu_bar.addMenu("Help")
        hm.addAction("How to Use", self._help)
        hm.addAction("About", self._about)

    # ── Folders ──

    def _build_folders(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(4,4,0,4)
        lay.setSpacing(4)
        hl = QtWidgets.QHBoxLayout()
        t = QtWidgets.QLabel("Folders")
        t.setStyleSheet("font-weight:bold; font-size:12px; color:#fff;")
        hl.addWidget(t); hl.addStretch()
        ab = QtWidgets.QPushButton("+"); ab.setFixedSize(24,24)
        ab.setToolTip("Create a new sub-folder")
        ab.clicked.connect(lambda: self._new_folder(self._folder))
        hl.addWidget(ab)
        lay.addLayout(hl)

        self.tree = QtWidgets.QTreeView()
        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._folder_ctx)
        self.tree.setToolTip("Your library folders.\nRight-click for options.\nClick a folder to browse its contents.")
        self.fsm = QtWidgets.QFileSystemModel()
        self.fsm.setRootPath(get_library_root())
        self.fsm.setFilter(QtCore.QDir.AllDirs | QtCore.QDir.NoDotAndDotDot)
        self.tree.setModel(self.fsm)
        self.tree.setRootIndex(self.fsm.index(get_library_root()))
        for c in range(1, self.fsm.columnCount()): self.tree.hideColumn(c)
        self.tree.clicked.connect(self._on_folder)
        lay.addWidget(self.tree)
        return w

    # ── Grid ──

    def _build_grid(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(4,4,4,4)
        lay.setSpacing(6)

        tr = QtWidgets.QHBoxLayout()
        self.grid_title = QtWidgets.QLabel("Library")
        self.grid_title.setStyleSheet("font-weight:bold; font-size:12px; color:#fff;")
        tr.addWidget(self.grid_title); tr.addStretch()
        lay.addLayout(tr)

        # Capture buttons
        cb = QtWidgets.QHBoxLayout()
        cb.setSpacing(8)
        self.cap_pose_btn = QtWidgets.QPushButton("📋  Capture Pose")
        self.cap_pose_btn.setObjectName("capturePoseBtn")
        self.cap_pose_btn.setToolTip(
            "CAPTURE POSE\n\n"
            "1. Select rig controls in the viewport\n"
            "2. Click this button\n"
            "3. Enter a name and click Save\n\n"
            "Stores every keyable attribute value\nat the current frame.")
        self.cap_pose_btn.clicked.connect(self._cap_pose)
        cb.addWidget(self.cap_pose_btn)
        self.cap_clip_btn = QtWidgets.QPushButton("🎬  Capture Animation")
        self.cap_clip_btn.setObjectName("captureClipBtn")
        self.cap_clip_btn.setToolTip(
            "CAPTURE ANIMATION\n\n"
            "1. Select rig controls in the viewport\n"
            "2. Click this button\n"
            "3. Enter a name and click Save\n\n"
            "Stores all keyframes with full tangent\nfidelity, breakdowns, and infinity modes.")
        self.cap_clip_btn.clicked.connect(self._cap_clip)
        cb.addWidget(self.cap_clip_btn)
        lay.addLayout(cb)

        # Empty hint
        self.hint = QtWidgets.QLabel(
            "No items in this folder yet.\n\n"
            "HOW TO SAVE:\n"
            "  1.  Select rig controls in the viewport\n"
            "  2.  Click  Capture Pose  or  Capture Animation  above\n"
            "  3.  Or right-click anywhere here for more options\n\n"
            "HOW TO LOAD:\n"
            "  1.  Click a saved item to see its details\n"
            "  2.  Set the Scene Namespace in the Namespace Remap section\n"
            "  3.  Click  Apply Pose  or  Import Animation")
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#666; font-size:11px; padding:30px; background-color:#252525; border-radius:8px; border:1px dashed #444;")

        self.grid_scroll = QtWidgets.QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.grid_scroll.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid_scroll.customContextMenuRequested.connect(self._grid_ctx)
        self.gw = QtWidgets.QWidget()
        self.gw.setContextMenuPolicy(Qt.CustomContextMenu)
        self.gw.customContextMenuRequested.connect(self._grid_ctx)
        self.gl = FlowLayout(self.gw)
        self.grid_scroll.setWidget(self.gw)

        self.stack = QtWidgets.QStackedWidget()
        self.stack.addWidget(self.hint)        # 0
        self.stack.addWidget(self.grid_scroll) # 1
        lay.addWidget(self.stack, stretch=1)
        return w

    # ── Detail ──

    def _build_detail(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(4,4,4,4)
        lay.setSpacing(6)

        detail_scroll = QtWidgets.QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        detail_body = QtWidgets.QWidget()
        body_lay = QtWidgets.QVBoxLayout(detail_body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(6)

        self.preview = QtWidgets.QLabel("Select an item\nfrom the library grid")
        self.preview.setFixedHeight(190)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("background-color:#1e1e1e; border-radius:6px; border:1px solid #444; color:#555; font-size:12px;")
        body_lay.addWidget(self.preview)

        ig = QtWidgets.QGroupBox("Info")
        il = QtWidgets.QFormLayout(ig)
        il.setSpacing(4)
        il.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
        il.setLabelAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.i_name = QtWidgets.QLabel("—")
        self.i_type = QtWidgets.QLabel("—")
        self.i_ctrls = QtWidgets.QLabel("—")
        self.i_frames = QtWidgets.QLabel("—")
        self.i_date = QtWidgets.QLabel("—")
        self.i_ns = QtWidgets.QLabel("—")
        for label in (self.i_name, self.i_type, self.i_ctrls, self.i_frames, self.i_date, self.i_ns):
            label.setWordWrap(True)
        il.addRow("Name:", self.i_name)
        il.addRow("Type:", self.i_type)
        il.addRow("Controls:", self.i_ctrls)
        il.addRow("Frames:", self.i_frames)
        il.addRow("Created:", self.i_date)
        il.addRow("Source NS:", self.i_ns)
        body_lay.addWidget(ig)

        # ── Namespace Remap (compact – opens pop-out dialog) ──
        rg = QtWidgets.QGroupBox("Namespace Remap")
        rl = QtWidgets.QVBoxLayout(rg); rl.setSpacing(4)

        # Summary label showing current mapping
        self.remap_summary = QtWidgets.QLabel("No file selected")
        self.remap_summary.setWordWrap(True)
        self.remap_summary.setStyleSheet(
            "background:#1e1e1e; border:1px solid #444; border-radius:3px; "
            "padding:6px 8px; color:#aaa; font-size:11px;"
        )
        rl.addWidget(self.remap_summary)

        remap_btn = QtWidgets.QPushButton("Namespace Remap...")
        remap_btn.setToolTip(
            "Open the Namespace Remap window to map the saved\n"
            "file's namespace to your scene namespace."
        )
        remap_btn.clicked.connect(self._open_remap_dialog)
        rl.addWidget(remap_btn)

        remap_help = QtWidgets.QLabel(
            "<small>Set the scene namespace that matches your rig.<br>"
            "Click the button above to open the remap window,<br>"
            "or the pose will use the namespace shown below.</small>"
        )
        remap_help.setWordWrap(True)
        remap_help.setStyleSheet("color: #777; font-size: 10px;")
        rl.addWidget(remap_help)

        body_lay.addWidget(rg)

        # Hidden combo used as data store (populated by _refresh_ns)
        self.ns_combo = QtWidgets.QComboBox()
        self.ns_combo.setVisible(False)

        # Internal state for remap
        self._remap_source_ns = ""
        self._remap_target_ns = ""
        self._remap_custom = ""

        # ── Import Options ──
        og = QtWidgets.QGroupBox("Import Options")
        og.setToolTip("Configure how the saved data will be applied to your scene.")
        ol = QtWidgets.QVBoxLayout(og); ol.setSpacing(6)

        ofr = QtWidgets.QHBoxLayout()
        ofl = QtWidgets.QLabel("Frame Offset:")
        ofl.setToolTip("Shift all imported keyframes by this many frames.\nExample: offset 10 means frame 1 data lands on frame 11.")
        ofr.addWidget(ofl)
        self.offset_spin = QtWidgets.QSpinBox()
        self.offset_spin.setRange(-100000,100000)
        ofr.addWidget(self.offset_spin); ofr.addStretch()
        ol.addLayout(ofr)

        self.replace_cb = QtWidgets.QCheckBox("Replace existing keys")
        self.replace_cb.setChecked(True)
        self.replace_cb.setToolTip("Delete existing keyframes before importing.\nUncheck to merge/layer on top.")
        ol.addWidget(self.replace_cb)
        self.static_cb = QtWidgets.QCheckBox("Include static (un-keyed) attrs")
        self.static_cb.setChecked(True)
        self.static_cb.setToolTip("Also apply saved attribute values that had no keyframes.")
        ol.addWidget(self.static_cb)
        body_lay.addWidget(og)

        mg = QtWidgets.QGroupBox("Mirror")
        mg.setToolTip(
            "Mirror a pose from one side of the rig to the other.\n\n"
            "Works with control names that contain a recognised side\n"
            "token separated by underscores:\n"
            "  Lf_ / Rt_,  L_ / R_,  Left_ / Right_  (any case)\n\n"
            "Example:  Rt_Hand_Ctrl  ↔  Lf_Hand_Ctrl"
        )
        ml2 = QtWidgets.QVBoxLayout(mg); ml2.setSpacing(6)

        # ── Enable mirror on library import ──
        self.mirror_cb = QtWidgets.QCheckBox("Enable mirror on library import")
        self.mirror_cb.setToolTip(
            "Check this ON before clicking Apply to mirror a saved pose.\n\n"
            "HOW TO USE:\n"
            "  1. Click a saved pose in the library grid\n"
            "     (e.g. a pose captured from the RIGHT hand)\n"
            "  2. Set the correct Scene Namespace in the remap section above\n"
            "  3. Check this box ON\n"
            "  4. Choose the direction below (e.g. R → L)\n"
            "  5. Click Apply\n\n"
            "The tool reads every control in the saved file, swaps\n"
            "the side token in the name, and applies the values to\n"
            "the opposite-side control.  Only controls whose names\n"
            "were actually swapped get their mirror-axis attributes\n"
            "negated (translateX, rotateY, rotateZ for X-axis)."
        )
        ml2.addWidget(self.mirror_cb)

        # ── Direction ──
        dir_label = QtWidgets.QLabel("Direction:")
        dir_label.setToolTip(
            "Which side is the SOURCE of the pose data?\n\n"
            "  L → R :  saved pose has LEFT-side controls,\n"
            "           apply mirrored values to RIGHT side\n\n"
            "  R → L :  saved pose has RIGHT-side controls,\n"
            "           apply mirrored values to LEFT side"
        )
        ml2.addWidget(dir_label)
        dr = QtWidgets.QHBoxLayout()
        self.l2r = QtWidgets.QRadioButton("L → R"); self.l2r.setChecked(True)
        self.l2r.setToolTip(
            "Source = Left side.  Swaps Lf→Rt, L→R, Left→Right\n"
            "in saved control names and applies to the Right side."
        )
        self.r2l = QtWidgets.QRadioButton("R → L")
        self.r2l.setToolTip(
            "Source = Right side.  Swaps Rt→Lf, R→L, Right→Left\n"
            "in saved control names and applies to the Left side."
        )
        dr.addWidget(self.l2r); dr.addWidget(self.r2l); dr.addStretch()
        ml2.addLayout(dr)

        # ── Mirror axis ──
        ax_row = QtWidgets.QHBoxLayout()
        ax_label = QtWidgets.QLabel("Mirror Axis:")
        ax_label.setToolTip(
            "The world axis that separates left from right.\n\n"
            "  X  (most common for bipedal rigs)\n"
            "     negates:  translateX, rotateY, rotateZ\n\n"
            "  Y  negates:  translateY, rotateX, rotateZ\n\n"
            "  Z  negates:  translateZ, rotateX, rotateY\n\n"
            "Translation along the mirror axis is negated.\n"
            "Rotation AROUND the mirror axis is preserved;\n"
            "rotations around the other two axes are negated."
        )
        ax_row.addWidget(ax_label)
        self.mirror_axis_combo = QtWidgets.QComboBox()
        self.mirror_axis_combo.addItems(["X", "Y", "Z"])
        self.mirror_axis_combo.setCurrentText("X")
        self.mirror_axis_combo.setToolTip(
            "X = standard bipedal left/right mirror (YZ plane).\n"
            "Choose Y or Z only if your rig is oriented differently."
        )
        self.mirror_axis_combo.setFixedWidth(50)
        ax_row.addWidget(self.mirror_axis_combo)
        ax_row.addStretch()
        ml2.addLayout(ax_row)

        # ── Separator ──
        sep = QtWidgets.QFrame(); sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setFrameShadow(QtWidgets.QFrame.Sunken)
        ml2.addWidget(sep)

        # ── Snapshot mirror ──
        snap_label = QtWidgets.QLabel("Live Scene Mirror (Snapshot)")
        snap_label.setStyleSheet("font-weight: bold;")
        snap_label.setToolTip(
            "Mirror the CURRENT scene pose — no saved library item needed.\n\n"
            "This works like the digitMirror tool: it reads attribute\n"
            "values directly from scene controls on one side and writes\n"
            "mirrored values to the opposite side."
        )
        ml2.addWidget(snap_label)

        self.snap_mirror_btn = QtWidgets.QPushButton("Mirror Pose (Snapshot)")
        self.snap_mirror_btn.setObjectName("snapMirrorBtn")
        self.snap_mirror_btn.setToolTip(
            "HOW TO USE:\n"
            "  1. Pose one side of your rig (e.g. the RIGHT hand)\n"
            "  2. Select the controls you posed, OR select controls\n"
            "     on the TARGET side (e.g. select LEFT hand controls)\n"
            "  3. Choose the direction above (e.g. R → L)\n"
            "  4. Click this button\n\n"
            "The tool finds each selected control's opposite-side\n"
            "partner, reads values from the SOURCE side, and writes\n"
            "mirrored values to the TARGET side.\n\n"
            "Supports both workflows:\n"
            "  • Select RIGHT controls  +  R → L  =  mirror to LEFT\n"
            "  • Select LEFT controls   +  R → L  =  reads from RIGHT,\n"
            "    writes mirrored values onto your selected LEFT controls\n\n"
            "Naming requirement:\n"
            "  Controls must contain a side token separated by\n"
            "  underscores: Lf_, Rt_, L_, R_, Left_, Right_"
        )
        self.snap_mirror_btn.clicked.connect(self._do_snapshot_mirror)
        ml2.addWidget(self.snap_mirror_btn)

        # ── Help note ──
        help_note = QtWidgets.QLabel(
            "<small>"
            "<b>Supported naming:</b>  Lf_ / Rt_,  L_ / R_,  "
            "Left_ / Right_  (any case).<br>"
            "<b>Tip:</b>  Check the Script Editor for detailed "
            "mirror diagnostics."
            "</small>"
        )
        help_note.setWordWrap(True)
        help_note.setStyleSheet("color: #888;")
        ml2.addWidget(help_note)
        body_lay.addWidget(mg)

        bl = QtWidgets.QHBoxLayout()
        self.imp_btn = QtWidgets.QPushButton("Apply")
        self.imp_btn.setObjectName("importBtn")
        self.imp_btn.setToolTip("Apply the selected library item to the target rig")
        self.imp_btn.clicked.connect(self._do_import)
        bl.addWidget(self.imp_btn)
        self.del_btn = QtWidgets.QPushButton("Delete")
        self.del_btn.setObjectName("deleteBtn")
        self.del_btn.setToolTip("Permanently delete the selected library item")
        self.del_btn.clicked.connect(self._del_item)
        bl.addWidget(self.del_btn)
        body_lay.addLayout(bl)
        body_lay.addStretch()

        detail_scroll.setWidget(detail_body)
        lay.addWidget(detail_scroll, stretch=1)
        return w

    # ── Context menus ──

    def _folder_ctx(self, pos):
        m = QtWidgets.QMenu(self)
        idx = self.tree.indexAt(pos)
        fp = self.fsm.filePath(idx) if idx.isValid() else self._folder
        m.addAction("New Folder…", lambda: self._new_folder(fp))
        if idx.isValid():
            m.addSeparator()
            m.addAction("Rename Folder…", lambda: self._rename_folder(fp))
            m.addAction("Delete Folder", lambda: self._del_folder(fp))
        m.addSeparator()
        m.addAction("Open in File Explorer", lambda: self._open_explorer(fp))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def _grid_ctx(self, pos):
        m = QtWidgets.QMenu(self)
        sec = m.addAction("— Capture from Selection —"); sec.setEnabled(False)
        m.addAction("📋  Capture Pose…", self._cap_pose)
        m.addAction("🎬  Capture Animation…", self._cap_clip)
        if self._sel_file and self._data:
            m.addSeparator()
            sec2 = m.addAction("— Selected Item —"); sec2.setEnabled(False)
            is_pose = self._data.get("format") == FORMAT_POSE
            m.addAction("✅  Apply Pose" if is_pose else "✅  Import Animation", self._do_import)
            m.addAction("✏️  Rename…", self._rename_item)
            m.addAction("🗑️  Delete", self._del_item)
        m.addSeparator()
        m.addAction("🔄  Refresh", self._refresh_all)
        m.exec(self.grid_scroll.viewport().mapToGlobal(pos))

    # ── Refresh ──

    def _refresh_all(self):
        self._refresh_tree(); self._refresh_grid(); self._refresh_ns()
        self.status.showMessage("Library refreshed")

    def _refresh_tree(self):
        r = get_library_root()
        self.fsm.setRootPath(r)
        self.tree.setRootIndex(self.fsm.index(r))

    def _refresh_grid(self):
        while self.gl.count():
            it = self.gl.takeAt(0)
            if it and it.widget(): it.widget().deleteLater()
        if not os.path.isdir(self._folder):
            self._sel_file = None
            self._sel_card = None
            self._data = None
            self._clear_detail()
            self.stack.setCurrentIndex(0); return
        self.grid_title.setText(os.path.basename(self._folder) or "Library")
        files = sorted(os.path.join(self._folder, f) for f in os.listdir(self._folder) if os.path.splitext(f)[1].lower() in (POSE_EXT, CLIP_EXT))
        if not files:
            self._sel_file = None
            self._sel_card = None
            self._data = None
            self._clear_detail()
            self.stack.setCurrentIndex(0); return
        self.stack.setCurrentIndex(1)
        ts = cmds.optionVar(q=OPT_THUMB_SIZE) if cmds.optionVar(exists=OPT_THUMB_SIZE) else DEFAULT_THUMB_SIZE
        selected_exists = self._sel_file in files if self._sel_file else False
        for fp in files:
            c = ThumbnailCard(fp, ts)
            c.clicked.connect(self._on_card)
            c.double_clicked.connect(self._on_dbl_card)
            c.set_selected(fp == self._sel_file)
            self.gl.addWidget(c)
        if not selected_exists:
            self._sel_file = None
            self._sel_card = None
            self._data = None
            self._clear_detail()
        self.gw.updateGeometry()
        self.gw.adjustSize()
        self.status.showMessage("{} item{} in '{}'".format(len(files), "s" if len(files)!=1 else "", os.path.basename(self._folder)))

    def _refresh_ns(self):
        ns = detect_scene_namespaces()
        self.ns_combo.clear()
        self.ns_combo.addItems(ns)

    # ── Folder actions ──

    def _on_folder(self, idx):
        p = self.fsm.filePath(idx)
        if os.path.isdir(p):
            self._folder = p; self._sel_file = None; self._data = None
            self._refresh_grid(); self._clear_detail()

    def _new_folder(self, parent):
        n, ok = QtWidgets.QInputDialog.getText(self, "New Folder", "Folder name:")
        if ok and n.strip():
            p = os.path.join(parent, n.strip())
            if not os.path.isdir(p): os.makedirs(p)
            self._refresh_tree()
            self._folder = p
            self.tree.setCurrentIndex(self.fsm.index(p))
            self._sel_file = None
            self._data = None
            self._refresh_grid()
            self._clear_detail()

    def _rename_folder(self, fp):
        old = os.path.basename(fp)
        n, ok = QtWidgets.QInputDialog.getText(self, "Rename Folder", "New name:", text=old)
        if ok and n.strip() and n.strip() != old:
            np = os.path.join(os.path.dirname(fp), n.strip())
            try:
                os.rename(fp, np)
                if self._folder == fp: self._folder = np
                self._refresh_tree(); self._refresh_grid()
            except Exception as e:
                cmds.warning("Rename failed: {}".format(e))

    def _del_folder(self, fp):
        if QtWidgets.QMessageBox.Yes == QtWidgets.QMessageBox.question(self, "Delete Folder?",
                "Delete '{}' and ALL contents?\nCannot be undone.".format(os.path.basename(fp))):
            try:
                shutil.rmtree(fp)
                if self._folder == fp: self._folder = get_library_root()
                self._refresh_tree(); self._refresh_grid()
            except Exception as e:
                cmds.warning("Delete failed: {}".format(e))

    def _open_explorer(self, p):
        if os.name == "nt": os.startfile(p)
        else:
            import subprocess; subprocess.Popen(["xdg-open", p])

    # ── Card selection ──

    def _on_card(self, fp):
        self._sel_file = fp
        for i in range(self.gl.count()):
            it = self.gl.itemAt(i)
            if it and it.widget():
                c = it.widget()
                c.set_selected(c.filepath == fp)
                if c.filepath == fp: self._sel_card = c
        self._load_detail(fp)

    def _select_card_by_path(self, fp):
        """Select a card in the grid and keep it visible."""
        if not fp:
            return
        for i in range(self.gl.count()):
            it = self.gl.itemAt(i)
            if not it or not it.widget():
                continue
            c = it.widget()
            if c.filepath == fp:
                self._on_card(fp)
                self.grid_scroll.ensureWidgetVisible(c, 24, 24)
                return

    def _on_dbl_card(self, fp):
        self._on_card(fp); self._do_import()

    # ── Detail ──

    def _clear_detail(self):
        self.preview.setPixmap(QtGui.QPixmap())
        self.preview.setText("Select an item\nfrom the library grid")
        for l in (self.i_name, self.i_type, self.i_ctrls, self.i_frames, self.i_date, self.i_ns):
            l.setText("—")
        self._remap_source_ns = ""
        self._remap_target_ns = ""
        self._remap_custom = ""
        self.remap_summary.setText("No file selected")
        self._data = None

    def _load_detail(self, fp):
        try:
            d = load_from_file(fp); self._data = d
        except Exception as e:
            self.status.showMessage("Error: {}".format(e)); return
        name = os.path.splitext(os.path.basename(fp))[0]
        ip = d.get("format") == FORMAT_POSE
        self.i_name.setText(name)
        self.i_type.setText("Pose" if ip else "Animation Clip")
        self.i_type.setStyleSheet("color:#7ab8e0; font-weight:bold;" if ip else "color:#e0c87a; font-weight:bold;")
        self.i_ctrls.setText(str(d.get("control_count","?")))
        src_ns = d.get("source_namespace", "") or ""
        self.i_ns.setText(src_ns or "(none)")
        # Auto-populate namespace remap state
        self._remap_source_ns = src_ns
        # Try to auto-select matching scene namespace in dropdown
        if src_ns:
            idx = self.ns_combo.findText(src_ns)
            if idx >= 0:
                self.ns_combo.setCurrentIndex(idx)
                self._remap_target_ns = src_ns
        self._remap_custom = ""
        self._update_remap_summary()
        if ip:
            self.i_frames.setText("Frame {}".format(d.get("frame","?")))
            self.imp_btn.setText("✅  Apply Pose")
        else:
            fr = d.get("frame_range",[0,0])
            self.imp_btn.setText("✅  Import Animation")
            self.i_frames.setText("{} – {}  ({} frames)".format(fr[0],fr[1],int(fr[1]-fr[0]+1)))
        ts = d.get("timestamp","")
        if ts:
            try:
                self.i_date.setText(datetime.datetime.fromisoformat(ts).strftime("%Y-%m-%d  %H:%M"))
            except Exception:
                self.i_date.setText(ts[:19])
        tb = d.get("thumbnail")
        if tb:
            pix = QtGui.QPixmap(); pix.loadFromData(base64.b64decode(tb))
            self.preview.setPixmap(pix.scaled(self.preview.width()-4, self.preview.height()-4, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.preview.setText("")
        else:
            self.preview.setPixmap(QtGui.QPixmap()); self.preview.setText("No Preview")

    # ── Capture ──

    def _cap_pose(self): self._do_capture("pose")
    def _cap_clip(self): self._do_capture("clip")

    def _do_capture(self, mode):
        raw_sel = cmds.ls(sl=True, long=True) or []
        sel = selection_to_transforms(raw_sel)
        if not sel:
            QtWidgets.QMessageBox.warning(self, "Nothing Selected",
                "Please select rig controls (or their curve shapes/components) in the viewport first.\n\n"
                "• For a partial save, select only the controls you need\n"
                "• For a full rig, select any control and choose\n"
                "  'Full Hierarchy' in the next dialog")
            return
        dlg = CaptureDialog(mode, self, focus_nodes=sel)
        dlg.show(); dlg.do_capture()
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        ctrls = get_rig_controls(sel, dlg.result_hierarchy)
        if not ctrls:
            ctrls = [n for n in sel if cmds.objectType(n) == "transform"]
        if not ctrls:
            cmds.warning("No rig controls found."); return
        finger_ctrls = [c for c in ctrls if is_finger_control_name(c)]
        print("[ShepStudio] Capture selection: {} controls total, {} finger controls".format(
            len(ctrls), len(finger_ctrls)))
        for c in sorted(set(strip_namespace(x) for x in finger_ctrls))[:20]:
            print("[ShepStudio]   capture finger: {}".format(c))
        if len(finger_ctrls) > 20:
            print("[ShepStudio]   ... and {} more".format(len(finger_ctrls) - 20))

        self.status.showMessage("Saving {} for {} controls…".format("pose" if mode=="pose" else "animation", len(ctrls)))
        QtWidgets.QApplication.processEvents()
        if mode == "pose":
            data = export_pose(ctrls, dlg.result_static, dlg.thumb_b64)
            ext = POSE_EXT
        else:
            data = export_clip(ctrls, dlg.result_static, dlg.thumb_b64)
            ext = CLIP_EXT
        fp = os.path.join(self._folder, dlg.result_name + ext)
        if os.path.exists(fp):
            if QtWidgets.QMessageBox.Yes != QtWidgets.QMessageBox.question(self, "Overwrite?",
                    "'{}' exists.  Overwrite?".format(dlg.result_name + ext)):
                return
        save_to_file(data, fp)
        self._sel_file = fp
        self._refresh_tree()
        self._refresh_grid()
        self._select_card_by_path(fp)
        if not self._data:
            self._load_detail(fp)
        QtWidgets.QApplication.processEvents()
        self.status.showMessage("Saved '{}' — {} controls".format(dlg.result_name, data.get("control_count",0)))

    # ── Namespace Remap ──

    def _update_remap_summary(self):
        """Update the compact summary label in the Namespace Remap section."""
        src = self._remap_source_ns or "(no namespace)"
        tgt = self._remap_custom or self._remap_target_ns or self.ns_combo.currentText()
        if not tgt or tgt == "(no namespace)":
            tgt = "(no namespace)"
        self.remap_summary.setText(
            "<b>File:</b>  <span style='color:#e0c87a;'>{}</span>"
            "&nbsp;&nbsp;&rarr;&nbsp;&nbsp;"
            "<b>Scene:</b>  <span style='color:#7ab8e0;'>{}</span>".format(src, tgt)
        )

    def _open_remap_dialog(self):
        """Open the Namespace Remap pop-out dialog."""
        ns_list = [self.ns_combo.itemText(i) for i in range(self.ns_combo.count())]
        dlg = NamespaceRemapDialog(
            parent=self,
            source_ns=self._remap_source_ns,
            scene_namespaces=ns_list,
            current_scene_ns=self._remap_target_ns or self.ns_combo.currentText(),
            current_remap=self._remap_custom,
        )
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._remap_target_ns = dlg.scene_combo.currentText()
            self._remap_custom = dlg.remap_edit.text().strip()
            # Sync hidden combo
            idx = self.ns_combo.findText(self._remap_target_ns)
            if idx >= 0:
                self.ns_combo.setCurrentIndex(idx)
            # Also refresh our internal combo with any newly detected namespaces
            new_ns_list = [dlg.scene_combo.itemText(i)
                           for i in range(dlg.scene_combo.count())]
            if new_ns_list != ns_list:
                self.ns_combo.clear()
                self.ns_combo.addItems(new_ns_list)
                idx = self.ns_combo.findText(self._remap_target_ns)
                if idx >= 0:
                    self.ns_combo.setCurrentIndex(idx)
            self._update_remap_summary()

    # ── Import ──

    def _get_target_namespace(self):
        """Return the target namespace from the Namespace Remap state.

        Priority:  Remap To (custom)  >  Scene Namespace (dropdown).
        """
        if self._remap_custom:
            return self._remap_custom
        if self._remap_target_ns:
            return self._remap_target_ns
        return self.ns_combo.currentText()

    def _do_import(self):
        if not self._data:
            QtWidgets.QMessageBox.information(
                self, "No Item Selected",
                "Click a saved pose or animation in the library grid first."
            )
            return
        tns = self._get_target_namespace()
        mir = self.mirror_cb.isChecked()
        mir_dir = "R2L" if self.r2l.isChecked() else "L2R"
        mir_axis = self.mirror_axis_combo.currentText()
        ip = self._data.get("format") == FORMAT_POSE
        selected_objects = cmds.ls(sl=True, long=True) or []

        src_ns = self._data.get("source_namespace", "") or ""
        print("[ShepStudio] ── Import ──")
        print("[ShepStudio]   File namespace:  '{}'".format(src_ns))
        print("[ShepStudio]   Target namespace: '{}'".format(tns))

        self.status.showMessage("Importing…")
        QtWidgets.QApplication.processEvents()
        cmds.undoInfo(openChunk=True)
        try:
            if ip:
                a, s = import_pose(
                    self._data, tns, mir, mir_dir, mir_axis,
                    selected_objects=selected_objects)
                noun = "attribute values"
            else:
                a, s = import_clip(
                    self._data, tns, mir, self.offset_spin.value(),
                    self.replace_cb.isChecked(), self.static_cb.isChecked(),
                    mir_dir, mir_axis, selected_objects=selected_objects,
                )
                noun = "anim curves"
        finally:
            cmds.undoInfo(closeChunk=True)
        msg = "Applied {} {}".format(a, noun)
        if s:
            msg += "  ({} controls not found)".format(len(s))
            print("[ShepStudio] Skipped:")
            for x in s[:30]:
                print("  ", x)
        if a == 0 and s:
            msg += "  — check namespace remap!"
        self.status.showMessage(msg)

    # ── Snapshot Mirror ──

    def _do_snapshot_mirror(self):
        """Live mirror: read current pose from one side and apply to the other."""
        sel = cmds.ls(sl=True) or []
        if not sel:
            QtWidgets.QMessageBox.information(
                self, "No Selection",
                "Select one or more rig controls in the viewport,\n"
                "then click Mirror Pose.\n\n"
                "Controls must contain a side token separated by\n"
                "underscores (e.g. Lf_Hand_Ctrl, Rt_Index_1_Ctrl)."
            )
            return
        tns = self._get_target_namespace()
        mir_dir = "R2L" if self.r2l.isChecked() else "L2R"
        mir_axis = self.mirror_axis_combo.currentText()
        self.status.showMessage("Mirroring pose…")
        QtWidgets.QApplication.processEvents()
        cmds.undoInfo(openChunk=True)
        try:
            a, s = snapshot_mirror(mir_dir, tns, mir_axis)
        finally:
            cmds.undoInfo(closeChunk=True)
        msg = "Mirrored {} attribute values".format(a)
        if s:
            msg += "  ({} controls not found)".format(len(s))
            print("[ShepStudio] Skipped:")
            for x in s[:30]:
                print("  ", x)
        if a == 0 and not s:
            msg = "No side-tokens found in selection — nothing to mirror"
        self.status.showMessage(msg)

    # ── Delete / Rename item ──

    def _del_item(self):
        if not self._sel_file: return
        n = os.path.basename(self._sel_file)
        if QtWidgets.QMessageBox.Yes == QtWidgets.QMessageBox.question(self, "Delete?", "Delete '{}'?\nCannot be undone.".format(n)):
            try: os.remove(self._sel_file)
            except Exception as e: cmds.warning(str(e)); return
            self._sel_file = None; self._data = None; self._clear_detail(); self._refresh_grid()
            self.status.showMessage("Deleted '{}'".format(n))

    def _rename_item(self):
        if not self._sel_file: return
        old = os.path.splitext(os.path.basename(self._sel_file))[0]
        ext = os.path.splitext(self._sel_file)[1]
        n, ok = QtWidgets.QInputDialog.getText(self, "Rename", "New name:", text=old)
        if ok and n.strip() and n.strip() != old:
            np = os.path.join(os.path.dirname(self._sel_file), n.strip() + ext)
            try:
                os.rename(self._sel_file, np)
                self._sel_file = np; self._refresh_grid(); self._load_detail(np)
            except Exception as e:
                cmds.warning(str(e))

    # ── Settings / Help ──

    def _settings(self):
        if SettingsDialog(self).exec() == QtWidgets.QDialog.Accepted:
            self._refresh_all()

    def _open_lib(self): self._open_explorer(get_library_root())

    def _help(self):
        QtWidgets.QMessageBox.information(self, "How to Use — ShepStudio Anim Library",
            "<h3>Saving Poses & Animation</h3>"
            "<ol><li>Select the rig controls you want to save in the viewport</li>"
            "<li>Click <b>Capture Pose</b> or <b>Capture Animation</b> (or right-click the grid)</li>"
            "<li>The camera auto-frames your selection for a thumbnail screenshot</li>"
            "<li>Enter a name, choose scope, and click <b>Save</b></li></ol>"
            "<h3>Loading</h3>"
            "<ol><li>Click a saved item in the library grid</li>"
            "<li>Set the <b>Scene Namespace</b> in the Namespace Remap section</li>"
            "<li>Adjust Frame Offset or other options as needed</li>"
            "<li>Click <b>Apply Pose</b> or <b>Import Animation</b></li></ol>"
            "<h3>Mirroring</h3>"
            "<p>Check <b>Enable Mirror</b> and choose L→R or R→L. The tool swaps side tokens "
            "(lf↔rt, L↔R, Left↔Right) in control names and negates translateX, rotateY, rotateZ.</p>"
            "<h3>Tips</h3>"
            "<ul><li>Right-click the grid or folder tree for context menus</li>"
            "<li>Double-click a library item to apply it instantly</li>"
            "<li>Use <b>Full Hierarchy</b> scope to capture an entire rig from one selection</li>"
            "<li>Namespace retargeting lets you apply one character's data to another</li></ul>")

    def _about(self):
        QtWidgets.QMessageBox.information(self, "About",
            "<b>{}</b> v{}<br><br>"
            "A local animation & pose library for Maya.<br>"
            "Export / import poses and animation clips with<br>"
            "viewport thumbnails, namespace retargeting,<br>"
            "and built-in L↔R mirroring.<br><br>"
            "<i>Author: David Shepstone</i>".format(TOOL_NAME, TOOL_VERSION))

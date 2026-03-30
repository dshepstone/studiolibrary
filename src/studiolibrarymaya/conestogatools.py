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

import re

import maya.cmds


TOKEN_PAIRS = [
    ("Left", "Right"), ("left", "right"), ("LEFT", "RIGHT"),
    ("Lf", "Rt"), ("lf", "rt"), ("LF", "RT"),
    ("L", "R"), ("l", "r"),
]

MIRROR_NEGATE_MAP = {
    "YZ": {"translateX", "rotateY", "rotateZ"},
    "XZ": {"translateY", "rotateX", "rotateZ"},
    "XY": {"translateZ", "rotateX", "rotateY"},
}

TRANSFORM_ATTRS = [
    "translateX", "translateY", "translateZ",
    "rotateX", "rotateY", "rotateZ",
]


def _boundary_pattern(token):
    return r"(?:(?<=_)|(?<=\A)|(?<=[0-9])){0}(?:(?=_)|(?=\Z)|(?=[0-9]))".format(re.escape(token))


def swap_side_token_directional(name, direction="L2R"):
    """
    Swap a side token in the requested direction.

    :type name: str
    :type direction: str
    :rtype: tuple[str, bool]
    """
    for left, right in TOKEN_PAIRS:
        if direction == "R2L":
            match = re.search(_boundary_pattern(right), name)
            if match:
                return name[:match.start()] + left + name[match.end():], True
        else:
            match = re.search(_boundary_pattern(left), name)
            if match:
                return name[:match.start()] + right + name[match.end():], True
    return name, False


def snapshot_mirror_selected(direction="R2L", mirror_plane="YZ"):
    """
    Mirror values from selected controls to opposite-side controls.

    :type direction: str
    :type mirror_plane: str
    :rtype: tuple[int, list[str]]
    """
    selection = maya.cmds.ls(selection=True) or []
    if not selection:
        maya.cmds.warning("[Conestoga] No objects selected for snapshot mirror.")
        return 0, []

    negate_attrs = MIRROR_NEGATE_MAP.get(mirror_plane, MIRROR_NEGATE_MAP["YZ"])
    applied_count = 0
    skipped = []

    for source in selection:
        source_short = source.split("|")[-1]
        namespace = ""
        bare_name = source_short

        if ":" in source_short:
            namespace = source_short.rsplit(":", 1)[0] + ":"
            bare_name = source_short.rsplit(":", 1)[1]

        target_bare, swapped = swap_side_token_directional(bare_name, direction=direction)
        if not swapped:
            skipped.append(source)
            continue

        target = namespace + target_bare
        if not maya.cmds.objExists(target):
            skipped.append(target)
            continue

        for attr in TRANSFORM_ATTRS:
            src_attr = "{0}.{1}".format(source, attr)
            dst_attr = "{0}.{1}".format(target, attr)

            if not maya.cmds.objExists(src_attr) or not maya.cmds.objExists(dst_attr):
                continue

            if not maya.cmds.getAttr(dst_attr, settable=True):
                continue

            value = maya.cmds.getAttr(src_attr)
            if isinstance(value, (list, tuple)):
                value = value[0]

            if attr in negate_attrs:
                value = -value

            try:
                maya.cmds.setAttr(dst_attr, value)
                applied_count += 1
            except RuntimeError:
                skipped.append(dst_attr)

    return applied_count, skipped

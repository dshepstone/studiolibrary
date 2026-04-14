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

import os
import logging

from studiolibrarymaya import baseitem

try:
    import mutils
    import mutils.gui
    import mutils.shepmirroring
    import maya.cmds
except ImportError as error:
    print(error)


logger = logging.getLogger(__name__)


def save(path, *args, **kwargs):
    """Convenience function for saving an AnimItem."""
    AnimItem(path).safeSave(*args, **kwargs)


def load(path, *args, **kwargs):
    """Convenience function for loading an AnimItem."""
    AnimItem(path).load(*args, **kwargs)


class AnimItem(baseitem.BaseItem):

    NAME = "Animation"
    EXTENSION = ".anim"
    ICON_PATH = os.path.join(os.path.dirname(__file__), "icons", "animation.png")
    TRANSFER_CLASS = mutils.Animation

    def imageSequencePath(self):
        """
        Return the image sequence location for playing the animation preview.

        :rtype: str
        """
        return self.path() + "/sequence"

    def loadSchema(self):
        """
        Get schema used to load the animation item.

        :rtype: list[dict]
        """
        schema = super(AnimItem, self).loadSchema()

        anim = mutils.Animation.fromPath(self.path())

        startFrame = anim.startFrame() or 0
        endFrame = anim.endFrame() or 0

        value = "{0} - {1}".format(startFrame, endFrame)
        schema.insert(3, {"name": "Range", "value": value})

        schema.extend([
            {
                "name": "optionsGroup",
                "title": "Options",
                "type": "group",
                "order": 2,
            },
            {
                "name": "connect",
                "type": "bool",
                "inline": True,
                "default": False,
                "persistent": True,
                "label": {"name": ""}
            },
            {
                "name": "currentTime",
                "type": "bool",
                "inline": True,
                "default": True,
                "persistent": True,
                "label": {"name": ""}
            },
            {
                "name": "frameOffset",
                "title": "Frame Offset",
                "type": "int",
                "default": 0,
                "persistent": True,
            },
            {
                "name": "sourceTime",
                "title": "source",
                "type": "range",
                "default": [startFrame, endFrame],
            },
            {
                "name": "option",
                "type": "enum",
                "default": "replace all",
                "items": ["replace", "replace all", "insert", "merge"],
                "persistent": True,
            },
            {
                "name": "mirrorGroup",
                "title": "Mirror",
                "type": "group",
                "order": 3,
            },
            {
                "name": "mirrorEnabled",
                "title": "Mirror",
                "type": "bool",
                "inline": True,
                "default": False,
                "persistent": True,
            },
            {
                "name": "mirrorDirection",
                "title": "Direction",
                "type": "radio",
                "value": "L2R",
                "items": ["L2R", "R2L"],
                "default": "L2R",
                "persistent": True,
                "persistentKey": "AnimItem",
            },
            {
                "name": "mirrorAxis",
                "title": "Mirror Axis",
                "type": "enum",
                "default": "X",
                "items": ["X", "Y", "Z"],
                "persistent": True,
                "persistentKey": "AnimItem",
            },
        ])

        return schema

    def loadValidator(self, **values):
        """
        Show/hide mirror direction and axis based on mirrorEnabled.

        :type values: dict
        :rtype: list[dict]
        """
        mirror_on = values.get("mirrorEnabled", False)

        fields = [
            {
                "name": "mirrorDirection",
                "visible": mirror_on,
            },
            {
                "name": "mirrorAxis",
                "visible": mirror_on,
            },
        ]

        fields.extend(super(AnimItem, self).loadValidator(**values))
        return fields

    def load(self, **kwargs):
        """
        Load the animation for the given objects and options.

        Supports an optional *frameOffset* (int) that shifts the pasted
        animation relative to the current time, and orientation-aware
        mirroring via *mirrorEnabled*, *mirrorDirection*, and *mirrorAxis*.

        :type kwargs: dict
        """
        frame_offset = kwargs.get("frameOffset", 0) or 0
        mirror_enabled = kwargs.get("mirrorEnabled", False)
        mirror_direction = kwargs.get("mirrorDirection", "L2R")
        mirror_axis = kwargs.get("mirrorAxis", "X")
        namespaces = kwargs.get("namespaces")
        objects = kwargs.get("objects")

        # Determine the effective startFrame, shifting by frameOffset.
        start_frame = kwargs.get("startFrame")
        if frame_offset and kwargs.get("currentTime", True):
            try:
                current = maya.cmds.currentTime(query=True)
                start_frame = int(current) + int(frame_offset)
            except Exception:
                pass

        anim = mutils.Animation.fromPath(self.path())
        anim.load(
            objects=objects,
            namespaces=namespaces,
            attrs=kwargs.get("attrs"),
            startFrame=start_frame,
            sourceTime=kwargs.get("sourceTime"),
            option=kwargs.get("option"),
            connect=kwargs.get("connect"),
            mirrorTable=kwargs.get("mirrorTable"),
            currentTime=kwargs.get("currentTime"),
        )

        # If orientation-aware mirror is enabled, apply a snapshot mirror
        # on top of the freshly-pasted animation using the selected objects.
        if mirror_enabled:
            target_ns = namespaces[0] if namespaces else ""
            if not target_ns and objects:
                # Infer namespace from first object.
                leaf = objects[0].split("|")[-1]
                target_ns = leaf.rsplit(":", 1)[0] if ":" in leaf else ""

            mutils.shepmirroring.snapshot_mirror(
                direction=mirror_direction,
                target_ns=target_ns,
                mirror_axis=mirror_axis,
            )

    def saveSchema(self):
        """
        Get the schema for saving an animation item.

        :rtype: list[dict]
        """
        start, end = (1, 100)

        try:
            start, end = mutils.currentFrameRange()
        except NameError as error:
            logger.exception(error)

        return [
            {
                "name": "folder",
                "type": "path",
                "layout": "vertical",
                "visible": False,
            },
            {
                "name": "name",
                "type": "string",
                "layout": "vertical"
            },
            {
                "name": "fileType",
                "type": "enum",
                "layout": "vertical",
                "default": "mayaAscii",
                "items": ["mayaAscii", "mayaBinary"],
                "persistent": True
            },
            {
                "name": "frameRange",
                "type": "range",
                "layout": "vertical",
                "default": [start, end],
                "actions": [
                    {
                        "name": "From Timeline",
                        "callback": mutils.playbackFrameRange
                    },
                    {
                        "name": "From Selected Timeline",
                        "callback": mutils.selectedFrameRange
                    },
                    {
                        "name": "From Selected Objects",
                        "callback": mutils.selectedObjectsFrameRange
                    },
                ]
            },
            {
                "name": "byFrame",
                "type": "int",
                "default": 1,
                "layout": "vertical",
                "persistent": True
            },
            {
                "name": "comment",
                "type": "text",
                "layout": "vertical"
            },
            {
                "name": "bakeConnected",
                "type": "bool",
                "default": False,
                "persistent": True,
                "inline": True,
                "label": {"visible": False}
            },
            {
                "name": "objects",
                "type": "objects",
                "label": {
                    "visible": False
                }
            },
        ]

    def saveValidator(self, **kwargs):
        """
        The save validator is called when an input field has changed.

        :type kwargs: dict
        :rtype: list[dict]
        """
        fields = super(AnimItem, self).saveValidator(**kwargs)

        # Validate the by frame field
        if kwargs.get("byFrame") == '' or kwargs.get("byFrame", 1) < 1:
            fields.extend([
                {
                    "name": "byFrame",
                    "error": "The by frame value cannot be less than 1!"
                }
            ])

        # Validate the frame range field
        start, end = kwargs.get("frameRange", (0, 1))
        if start >= end:
            fields.extend([
                {
                    "name": "frameRange",
                    "error":  "The start frame cannot be greater "
                              "than or equal to the end frame!"
                }
            ])

        # Validate the current selection field
        objects = kwargs.get("objects")
        if objects and mutils.getDurationFromNodes(objects, time=[start, end]) <= 0:
            fields.extend([
                {
                    "name": "objects",
                    "error": "No animation was found on the selected object/s!"
                             "Please create a pose instead!",
                }
            ])

        return fields

    def save(self, objects, sequencePath="", **kwargs):
        """
        Save the animation from the given objects to the item path.
        
        :type objects: list[str]
        :type sequencePath: str
        :type kwargs: dict
        """
        super(AnimItem, self).save(**kwargs)

        # Save the animation to the given path location on disc
        mutils.saveAnim(
            objects,
            self.path(),
            time=kwargs.get("frameRange"),
            fileType=kwargs.get("fileType"),
            iconPath=kwargs.get("thumbnail"),
            metadata={"description": kwargs.get("comment", "")},
            sequencePath=sequencePath,
            bakeConnected=kwargs.get("bakeConnected")
        )

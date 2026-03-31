# Copyright 2026
"""Rig-specific mirror map support for Studio Library pose mirroring."""

import copy
import json
import logging
import os
import re

try:
    import maya.cmds
except ImportError:  # pragma: no cover
    maya = None

logger = logging.getLogger(__name__)

MIRROR_MAP_VERSION = 1
NUMERIC_ATTR_TYPES = {
    "bool", "byte", "short", "long", "float", "double",
    "doubleAngle", "doubleLinear", "time", "enum",
}
DEFAULT_RULES_BY_AXIS = {
    "x": {"translateX": "negate", "rotateY": "negate", "rotateZ": "negate"},
    "y": {"translateY": "negate", "rotateX": "negate", "rotateZ": "negate"},
    "z": {"translateZ": "negate", "rotateX": "negate", "rotateY": "negate"},
}


def _leaf_name(name):
    return (name or "").split("|")[-1]


def _strip_namespace(name):
    return _leaf_name(name).split(":")[-1]


def _namespace(name):
    leaf = _leaf_name(name)
    return leaf.rsplit(":", 1)[0] if ":" in leaf else ""


def _token_pattern(token):
    escaped = re.escape(token)
    return re.compile(r"(?:(?<=^)|(?<=_)|(?<=:))" + escaped + r"(?:(?=$)|(?=_)|(?=:))")


def _safe_swap_token(name, from_token, to_token):
    if not from_token:
        return None
    pattern = _token_pattern(from_token)
    if not pattern.search(name):
        return None
    return pattern.sub(to_token, name, count=1)


def _possible_keys(name):
    leaf = _leaf_name(name)
    no_ns = _strip_namespace(leaf)
    return [name, leaf, no_ns]


class MirrorMap(object):

    def __init__(self, rig_id, left_token="lf", right_token="rt", mirror_axis="x"):
        self.rig_id = rig_id
        self.left_token = left_token
        self.right_token = right_token
        self.mirror_axis = mirror_axis.lower()
        self.controls = {}
        self.manual_pairs = {}
        self.excluded_controls = set()
        self.default_rules = copy.deepcopy(DEFAULT_RULES_BY_AXIS.get(self.mirror_axis, {}))

    def to_dict(self):
        return {
            "schema": "studiolibrary.mirror_map",
            "version": MIRROR_MAP_VERSION,
            "rig_id": self.rig_id,
            "left_token": self.left_token,
            "right_token": self.right_token,
            "mirror_axis": self.mirror_axis,
            "default_rules": self.default_rules,
            "controls": self.controls,
            "manual_pairs": self.manual_pairs,
            "excluded_controls": sorted(self.excluded_controls),
        }

    @classmethod
    def from_dict(cls, data):
        mirror_map = cls(
            rig_id=data.get("rig_id", "unknown_rig"),
            left_token=data.get("left_token", "lf"),
            right_token=data.get("right_token", "rt"),
            mirror_axis=data.get("mirror_axis", "x"),
        )
        mirror_map.controls = data.get("controls", {}) or {}
        mirror_map.manual_pairs = data.get("manual_pairs", {}) or {}
        mirror_map.excluded_controls = set(data.get("excluded_controls", []) or [])
        mirror_map.default_rules.update(data.get("default_rules", {}) or {})
        return mirror_map

    def find_control_entry(self, name):
        for key in _possible_keys(name):
            if key in self.controls:
                return self.controls[key]
        return {}

    def find_manual_pair(self, name):
        for key in _possible_keys(name):
            if key in self.manual_pairs:
                return self.manual_pairs[key]
        return None

    def is_excluded(self, name):
        for key in _possible_keys(name):
            if key in self.excluded_controls:
                return True
        return False


class MirrorMapManager(object):

    def __init__(self, root_path=None):
        root_path = root_path or os.environ.get("STUDIOLIBRARY_MIRROR_MAP_PATH")
        self.root_path = root_path or os.path.expanduser("~/.studiolibrary/mirror_maps")
        if not os.path.exists(self.root_path):
            os.makedirs(self.root_path)

    def _path(self, rig_id):
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", rig_id)
        return os.path.join(self.root_path, "{0}.json".format(safe))

    def has_map(self, rig_id):
        return os.path.exists(self._path(rig_id))

    def list_maps(self):
        return sorted([x[:-5] for x in os.listdir(self.root_path) if x.endswith(".json")])

    def load(self, rig_id):
        path = self._path(rig_id)
        with open(path, "r") as stream:
            return MirrorMap.from_dict(json.load(stream))

    def save(self, mirror_map, rig_id=None):
        rig_id = rig_id or mirror_map.rig_id
        path = self._path(rig_id)
        with open(path, "w") as stream:
            json.dump(mirror_map.to_dict(), stream, indent=4, sort_keys=True)
        return path

    def delete(self, rig_id):
        path = self._path(rig_id)
        if os.path.exists(path):
            os.remove(path)

    def export_map(self, rig_id, path):
        mirror_map = self.load(rig_id)
        with open(path, "w") as stream:
            json.dump(mirror_map.to_dict(), stream, indent=4, sort_keys=True)

    def import_map(self, path, rig_id=None):
        with open(path, "r") as stream:
            mirror_map = MirrorMap.from_dict(json.load(stream))
        if rig_id:
            mirror_map.rig_id = rig_id
        self.save(mirror_map)
        return mirror_map

    def convert_diget_snapshot(self, path, rig_id=None):
        with open(path, "r") as stream:
            data = json.load(stream)

        rig = rig_id or data.get("rig_id") or data.get("prefix") or data.get("namespace") or "unknown_rig"
        mirror_map = MirrorMap(
            rig_id=rig,
            left_token=data.get("left_token", "lf"),
            right_token=data.get("right_token", "rt"),
            mirror_axis=str(data.get("mirror_axis", "x")).lower(),
        )
        mirror_map.manual_pairs = data.get("manual_pairs", {}) or {}
        mirror_map.excluded_controls = set(data.get("excluded_controls", []) or [])

        controls = data.get("controls", {}) or data.get("snapshot", {}) or {}
        for key, value in controls.items():
            if isinstance(value, dict):
                mirror_map.controls[key] = {
                    "partner": value.get("partner") or value.get("mirror") or value.get("other_side"),
                    "side": value.get("side", "middle"),
                    "full_path": value.get("full_path"),
                    "rules": value.get("rules") or value.get("attribute_rules") or {},
                }

        self.save(mirror_map)
        return mirror_map


class DagLookup(object):

    def __init__(self):
        self.by_leaf = {}
        self.by_stripped = {}
        self.transforms = []

    @classmethod
    def from_scene(cls):
        lookup = cls()
        candidates = maya.cmds.ls(type="transform", long=True) or []
        for long_name in candidates:
            shapes = maya.cmds.listRelatives(long_name, shapes=True, fullPath=True) or []
            if not any(maya.cmds.nodeType(shape) == "nurbsCurve" for shape in shapes):
                continue
            lookup.transforms.append(long_name)
            leaf = _leaf_name(long_name)
            lookup.by_leaf.setdefault(leaf, []).append(long_name)
            lookup.by_stripped.setdefault(_strip_namespace(leaf), []).append(long_name)
        return lookup

    def resolve(self, name, preferred_namespace=""):
        if maya.cmds.objExists(name):
            return name

        leaf = _leaf_name(name)
        stripped = _strip_namespace(name)
        candidates = list(self.by_leaf.get(leaf, []))
        if not candidates:
            candidates = list(self.by_stripped.get(stripped, []))

        if preferred_namespace and len(candidates) > 1:
            matches = [c for c in candidates if _namespace(c) == preferred_namespace]
            if len(matches) == 1:
                return matches[0]
            if matches:
                candidates = matches

        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            logger.warning("DAG ambiguity for %s: %s", name, candidates)
        return None


class PartnerResolver(object):

    def __init__(self, mirror_map):
        self.map = mirror_map

    def resolve_partner_name(self, name):
        manual = self.map.find_manual_pair(name)
        if manual:
            logger.debug("manual pair used: %s -> %s", name, manual)
            return manual

        entry = self.map.find_control_entry(name)
        stored = entry.get("partner") if entry else None
        if stored:
            logger.debug("stored partner used: %s -> %s", name, stored)
            return stored

        leaf = _leaf_name(name)
        swapped = _safe_swap_token(leaf, self.map.left_token, self.map.right_token)
        if not swapped:
            swapped = _safe_swap_token(leaf, self.map.right_token, self.map.left_token)

        if swapped:
            logger.debug("auto token swap used: %s -> %s", name, swapped)
            return swapped

        logger.debug("no partner found for %s", name)
        return None


class StudioLibraryMirrorAdapter(object):

    def __init__(self, mirror_map, dag_lookup=None):
        self.mirror_map = mirror_map
        self.dag_lookup = dag_lookup or DagLookup.from_scene()
        self.partner_resolver = PartnerResolver(mirror_map)
        self.stats = {"success": 0, "skipped": 0, "errors": 0}

    @staticmethod
    def detect_rig_id(objects=None, pose_objects=None):
        candidates = list(objects or []) + list(pose_objects or [])
        for name in candidates:
            leaf = _leaf_name(name)
            if ":" in leaf:
                return leaf.split(":", 1)[0]
        for name in candidates:
            return _strip_namespace(name).split("_", 1)[0]
        return "default_rig"

    def resolve_destination(self, destination_name):
        if self.mirror_map.is_excluded(destination_name):
            self.stats["skipped"] += 1
            logger.debug("control skipped due to exclusion: %s", destination_name)
            return None

        partner = self.partner_resolver.resolve_partner_name(destination_name)
        if not partner:
            self.stats["skipped"] += 1
            return None

        preferred_ns = _namespace(_leaf_name(destination_name))
        resolved = self.dag_lookup.resolve(partner, preferred_namespace=preferred_ns)
        if not resolved:
            self.stats["skipped"] += 1
            logger.debug("cannot resolve partner DAG path for %s -> %s", destination_name, partner)
            return None
        return resolved

    def _rule_for_attr(self, destination_name, attr):
        entry = self.mirror_map.find_control_entry(destination_name)
        rules = (entry or {}).get("rules", {})
        if attr in rules:
            return rules[attr]
        return self.mirror_map.default_rules.get(attr, "copy")

    def should_skip_attr(self, destination_name, attr, attr_type):
        if attr_type not in NUMERIC_ATTR_TYPES:
            logger.debug("attr skipped due to non-numeric type: %s.%s (%s)", destination_name, attr, attr_type)
            return True
        plug = "{0}.{1}".format(destination_name, attr)
        if not maya.cmds.objExists(plug):
            return True
        if maya.cmds.getAttr(plug, lock=True):
            return True
        return not maya.cmds.getAttr(plug, settable=True)

    def mirrored_value(self, destination_name, attr, value):
        rule = self._rule_for_attr(destination_name, attr)
        if rule == "ignore":
            return None
        if rule == "negate":
            try:
                return -value
            except TypeError:
                logger.debug("cannot negate non-numeric value for %s.%s", destination_name, attr)
                return None
        return value

    def log_summary(self):
        logger.info(
            "mirror apply success=%s skipped=%s errors=%s",
            self.stats["success"],
            self.stats["skipped"],
            self.stats["errors"],
        )

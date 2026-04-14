# Orientation-Aware Mirror Utilities for Studio Library
#
# Adapted from shepStudioAnimLib.py by David Shepstone.
# Provides orientation-aware L<->R mirroring that works without a mirror table
# by sampling rest-pose world matrices to decide per-attribute copy vs. negate.
# Also includes snapshot mirror (live scene mirror), finger/hand control
# detection, and enhanced namespace utilities.

import re
import logging

try:
    import maya.cmds as cmds
except ImportError:
    cmds = None

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Side-token helpers
# ---------------------------------------------------------------------------

def _bp(tok):
    """Build a word-boundary-aware regex pattern for the given side token."""
    return r'(?:(?<=_)|(?<=\A)|(?<=[0-9]))' + re.escape(tok) + r'(?:(?=_)|(?=\Z)|(?=[0-9]))'


def swap_side_token(name):
    """Swap any recognised side token in *name* (bidirectional).

    Returns ``(new_name, was_swapped)``.
    """
    for lt, rt in TOKEN_PAIRS:
        m = re.search(_bp(rt), name)
        if m:
            return name[:m.start()] + lt + name[m.end():], True
        m = re.search(_bp(lt), name)
        if m:
            return name[:m.start()] + rt + name[m.end():], True
    return name, False


def swap_side_token_directional(name, direction="L2R"):
    """Swap only in the requested direction: ``'L2R'`` or ``'R2L'``."""
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
    """Return True when *name* contains a recognised side token."""
    for lt, rt in TOKEN_PAIRS:
        if re.search(_bp(lt), name) or re.search(_bp(rt), name):
            return True
    return False


def _detect_side(name):
    """Return ``'L'``, ``'R'``, or ``None`` based on the first token found."""
    for lt, rt in TOKEN_PAIRS:
        if re.search(_bp(rt), name):
            return "R"
        if re.search(_bp(lt), name):
            return "L"
    return None


# ---------------------------------------------------------------------------
# Namespace utilities
# ---------------------------------------------------------------------------

def strip_namespace(name):
    """Return the bare node name with namespace removed."""
    leaf = name.split("|")[-1]
    return leaf.rsplit(":", 1)[1] if ":" in leaf else leaf


def short_name(name):
    """Return the leaf DAG name (no namespace stripped)."""
    return name.split("|")[-1]


def add_namespace(bare, ns):
    """Prepend *ns* to *bare* if a namespace is given."""
    if ns and ns != "(no namespace)":
        return "{}:{}".format(ns, bare)
    return bare


def remap_full_path_to_namespace(full_path, target_ns):
    """Remap every DAG segment of *full_path* to *target_ns*."""
    if not target_ns or target_ns == "(no namespace)":
        return full_path
    parts = [p for p in full_path.split("|") if p]
    remapped = [add_namespace(strip_namespace(p), target_ns) for p in parts]
    return "|".join(remapped)


def detect_scene_namespaces():
    """Return all non-default namespaces in the current Maya scene.

    Uses ``cmds.namespaceInfo`` first, falls back to scanning nurbsCurve
    parents for older scenes.  Returns ``["(no namespace)"]`` when none
    are found.
    """
    ns_set = set()
    try:
        all_ns = cmds.namespaceInfo(":", listOnlyNamespaces=True, recurse=True) or []
        for ns in all_ns:
            if ns not in ("UI", "shared"):
                ns_set.add(ns)
    except Exception:
        pass

    if not ns_set:
        shapes = cmds.ls(type="nurbsCurve", long=True) or []
        for s in shapes:
            for xf in (cmds.listRelatives(s, parent=True, fullPath=True) or []):
                leaf = xf.split("|")[-1]
                if ":" in leaf:
                    ns_set.add(leaf.rsplit(":", 1)[0])

    return sorted(ns_set) or ["(no namespace)"]


# ---------------------------------------------------------------------------
# Control name heuristics
# ---------------------------------------------------------------------------

def is_finger_control_name(name):
    """Return True when the bare control name looks finger-related."""
    low = strip_namespace(name).lower()
    return any(tok in low for tok in FINGER_TOKENS)


def is_hand_control_name(name):
    """Return True when the bare control name looks hand/wrist-related."""
    low = strip_namespace(name).lower()
    return any(tok in low for tok in HAND_TOKENS)


def is_helper_control_name(name):
    """Heuristic rejection of helper/buffer nodes."""
    low = strip_namespace(name).lower()
    parts = re.split(r"[_:|]", low)
    if any(tok in parts for tok in HELPER_NAME_TOKENS):
        return True
    if re.search(r"(?:_|^)(?:grp|offset|pivot|srtbuffer|buffer|inv)$", low):
        return True
    if "relax_offset" in low:
        return True
    return False


# ---------------------------------------------------------------------------
# Attribute helpers
# ---------------------------------------------------------------------------

def list_control_attrs(ctrl):
    """Return keyable + channel-box attrs readable as scalar numbers.

    Finger controls always include rotateX/Y/Z.
    Hand controls include curl/spread/fist/etc. user attributes.
    """
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

    if is_finger_control_name(ctrl):
        for ra in ("rotateX", "rotateY", "rotateZ"):
            if ra in attrs:
                continue
            plug = "{}.{}".format(ctrl, ra)
            try:
                value = cmds.getAttr(plug)
                if isinstance(value, (int, float)):
                    attrs.append(ra)
            except Exception:
                pass

    if is_hand_control_name(ctrl):
        user_attrs = cmds.listAttr(ctrl, userDefined=True) or []
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
    """Return True when *plug* appears editable by ``setAttr``."""
    try:
        if cmds.getAttr(plug, lock=True):
            return False
    except Exception:
        return False
    try:
        return bool(cmds.getAttr(plug, settable=True))
    except Exception:
        return True


def plug_write_state(plug):
    """Return ``(writable, reason)`` for a given Maya plug string."""
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
        pass
    return True, "ok"


# ---------------------------------------------------------------------------
# Finger/control discovery
# ---------------------------------------------------------------------------

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


def _is_likely_control(node, control_set_nodes=None):
    if cmds.objectType(node) != "transform":
        return False
    if control_set_nodes and node in control_set_nodes:
        return True
    shapes = cmds.listRelatives(node, shapes=True, noIntermediate=True, fullPath=True) or []
    has_ctrl_shape = any(cmds.objectType(s) == "nurbsCurve" for s in shapes)
    if is_helper_control_name(node) and not has_ctrl_shape:
        return False
    if has_ctrl_shape:
        return True
    user_k = cmds.listAttr(node, userDefined=True, keyable=True) or []
    user_cb = cmds.listAttr(node, userDefined=True, channelBox=True) or []
    if user_k or user_cb:
        return True
    return bool(cmds.listAttr(node, keyable=True) or [])


def _namespaces_from_nodes(nodes):
    ns = set()
    for n in nodes or []:
        leaf = n.split("|")[-1]
        if ":" in leaf:
            ns.add(leaf.rsplit(":", 1)[0])
    return ns


def _augment_with_finger_controls(ctrls, roots=None, hierarchy=False):
    """Add finger controls from the rig that were not already in *ctrls*."""
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
    for node in candidates:
        if node in current_set:
            continue
        if not is_finger_control_name(node):
            continue
        if is_helper_control_name(node):
            continue
        if not _is_likely_control(node, control_set_nodes=control_set_nodes):
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
        logger.debug("[ShepMirror] Finger discovery: %d additional controls", len(added))

    return out


def get_rig_controls(roots=None, hierarchy=False):
    """Return the rig controls from *roots* (or current selection).

    Includes finger controls discovered via ``_augment_with_finger_controls``.
    """
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
        has_user_anim = bool(
            (cmds.listAttr(n, userDefined=True, keyable=True) or []) or
            (cmds.listAttr(n, userDefined=True, channelBox=True) or [])
        )
        if is_helper_control_name(n) and not (has_curve or has_user_anim):
            continue
        if has_curve:
            ctrls.append(n)
        elif cmds.listAttr(n, keyable=True) or []:
            ctrls.append(n)

    return _augment_with_finger_controls(ctrls, roots=roots, hierarchy=hierarchy)


# ---------------------------------------------------------------------------
# Orientation sampling
# ---------------------------------------------------------------------------

def _sample_rest_axes_batch(ctrls):
    """Zero rotations, read world matrices, restore — batch version.

    Returns ``{ctrl: {"x": (vx,vy,vz), "y": ..., "z": ...}}``.
    """
    if not ctrls:
        return {}

    existing = [c for c in ctrls if cmds.objExists(c)]
    if not existing:
        return {}

    auto_key = cmds.autoKeyframe(q=True, state=True)
    if auto_key:
        cmds.autoKeyframe(state=False)

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
    """Return the world axis label the vector points most along."""
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
    """Return True if *attr* should be negated during orientation-aware mirror."""
    al = attr.lower()

    if al.startswith("translate"):
        attr_type = "translate"
    elif al.startswith("rotate"):
        attr_type = "rotate"
    else:
        return False

    def _mirror_local(m_ax, xd, yd, zd):
        for local, world in (("X", xd), ("Y", yd), ("Z", zd)):
            if m_ax == world or ("-" + m_ax) == world:
                return local
        return m_ax

    mirror_attr = _mirror_local(mirror_axis, src_dom["x"], src_dom["y"], src_dom["z"])

    same_ori = (src_dom["x"] == tgt_dom["x"] and
                src_dom["y"] == tgt_dom["y"] and
                src_dom["z"] == tgt_dom["z"])

    if same_ori:
        if attr_type == "translate":
            return mirror_attr in attr
        if attr_type == "rotate":
            return mirror_attr not in attr

    axes_ordered = ("x", "y", "z")
    axis_labels = {"x": "X", "y": "Y", "z": "Z"}

    def _is_mirror_same(m_ax, dom, opp_dom):
        return ((m_ax == dom and m_ax == opp_dom) or
                ("-" + m_ax == dom and "-" + m_ax == opp_dom))

    def _is_same_not_mirror(m_ax, dom, opp_dom):
        return (dom == opp_dom) and (dom != m_ax) and (dom != "-" + m_ax)

    if attr_type == "translate":
        for ax in axes_ordered:
            if _is_mirror_same(mirror_axis, src_dom[ax], tgt_dom[ax]):
                return True
        for ax in axes_ordered:
            if src_dom[ax] == tgt_dom[ax]:
                lbl = axis_labels[ax]
                return not (mirror_attr in attr or lbl in attr)
        return True

    if attr_type == "rotate":
        for ax in axes_ordered:
            if _is_same_not_mirror(mirror_axis, src_dom[ax], tgt_dom[ax]):
                lbl = axis_labels[ax]
                return (mirror_attr in attr or lbl in attr)
        return False

    return False


def _compute_negate_set(src_axes, tgt_axes, mirror_axis, attrs):
    """Return the subset of *attrs* that should be negated.

    Falls back to the static ``MIRROR_NEGATE_MAP`` when orientation
    data is unavailable.
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


# ---------------------------------------------------------------------------
# Studio Library pose mirror (reads SL's pose.json format)
# ---------------------------------------------------------------------------

def studio_import_pose_with_mirror(
        pose_path,
        namespaces=None,
        objects=None,
        mirror_direction="L2R",
        mirror_axis="X",
):
    """Apply an orientation-aware mirror of a Studio Library pose file.

    Reads ``pose.json`` (Studio Library format), swaps side tokens in
    control names, samples rest-pose world-matrix orientations, and
    applies each attribute with copy or negate as appropriate.

    :type pose_path: str
    :type namespaces: list[str] or None
    :type objects: list[str] or None
    :type mirror_direction: str  — ``'L2R'`` or ``'R2L'``
    :type mirror_axis: str       — ``'X'``, ``'Y'``, or ``'Z'``
    :rtype: int  (number of attributes applied)
    """
    import json

    try:
        with open(pose_path, "r") as fh:
            data = json.load(fh)
    except Exception as exc:
        logger.error("[ShepMirror] Cannot read pose file %s: %s", pose_path, exc)
        return 0

    # Studio Library pose format: data["objects"][ctrl_name]["attrs"][attr]["value"]
    pose_objects = data.get("objects", {})
    if not pose_objects:
        logger.warning("[ShepMirror] No objects found in pose file: %s", pose_path)
        return 0

    target_ns = ""
    if namespaces:
        target_ns = namespaces[0]

    # Build (src_bare, tgt_bare, attrs_dict, was_swapped) tuples.
    resolved_pairs = []
    for ctrl_name in pose_objects:
        bare = strip_namespace(ctrl_name)
        tb, was_swapped = swap_side_token_directional(bare, mirror_direction)
        attrs = {}
        for attr, attr_data in pose_objects[ctrl_name].get("attrs", {}).items():
            val = attr_data.get("value")
            if isinstance(val, (int, float)):
                attrs[attr] = val
        resolved_pairs.append((bare, tb, attrs, was_swapped))

    # Batch orientation sampling for controls that have a mirrored counterpart.
    sample_ctrls = set()
    for src_bare, tgt_bare, attrs, was_swapped in resolved_pairs:
        if was_swapped:
            src_full = add_namespace(src_bare, target_ns)
            tgt_full = add_namespace(tgt_bare, target_ns)
            if cmds.objExists(src_full):
                sample_ctrls.add(src_full)
            if cmds.objExists(tgt_full):
                sample_ctrls.add(tgt_full)

    axes_data = _sample_rest_axes_batch(list(sample_ctrls))

    logger.debug(
        "[ShepMirror] studio_import_pose_with_mirror: direction=%s axis=%s "
        "%d controls target_ns='%s'",
        mirror_direction, mirror_axis, len(resolved_pairs), target_ns
    )

    # Apply attributes.
    cmds.undoInfo(openChunk=True)
    applied = 0
    try:
        for src_bare, tgt_bare, attrs, was_swapped in resolved_pairs:
            tgt_full = add_namespace(tgt_bare, target_ns)

            if not cmds.objExists(tgt_full):
                # Fallback: try without namespace.
                if cmds.objExists(tgt_bare):
                    tgt_full = tgt_bare
                else:
                    logger.debug("[ShepMirror]   Not found: %s", tgt_full)
                    continue

            negate_set = set()
            if was_swapped:
                src_full = add_namespace(src_bare, target_ns)
                negate_set = _compute_negate_set(
                    axes_data.get(src_full), axes_data.get(tgt_full),
                    mirror_axis, list(attrs.keys())
                )
                logger.debug(
                    "[ShepMirror]   %s -> %s  negate=%s",
                    src_bare, tgt_bare, negate_set or "(none)"
                )

            for attr, value in attrs.items():
                plug = "{}.{}".format(tgt_full, attr)
                writable, reason = plug_write_state(plug)
                if not writable:
                    continue
                try:
                    v = -value if (was_swapped and attr in negate_set) else value
                    cmds.setAttr(plug, v)
                    applied += 1
                except Exception as exc:
                    logger.debug("[ShepMirror]   WARN: %s – %s", plug, exc)
    finally:
        cmds.undoInfo(closeChunk=True)

    logger.debug("[ShepMirror] Done: %d attrs applied", applied)
    return applied


# ---------------------------------------------------------------------------
# Snapshot mirror — live scene mirror without a saved file
# ---------------------------------------------------------------------------

def snapshot_mirror(direction="R2L", target_ns="", mirror_axis="X"):
    """Read the current pose from source-side controls and mirror to the
    opposite-side controls in the scene.

    Uses orientation-aware negate logic so rigs with mirrored joint
    orientations (fingers, hands) are handled correctly.

    :type direction: str    — ``'R2L'`` or ``'L2R'``
    :type target_ns: str    — namespace to operate in (empty = no namespace)
    :type mirror_axis: str  — ``'X'``, ``'Y'``, or ``'Z'``
    :rtype: tuple(int, list)  — ``(attrs_applied, skipped_controls)``
    """
    sel = cmds.ls(sl=True) or []
    if not sel:
        cmds.warning("[ShepMirror] snapshot_mirror: nothing selected.")
        return 0, []

    ns = target_ns
    if not ns or ns == "(no namespace)":
        leaf = sel[0].split("|")[-1]
        ns = leaf.rsplit(":", 1)[0] if ":" in leaf else ""

    pairs = []
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

    sample_ctrls = set()
    for src_full, tgt_full in pairs:
        if cmds.objExists(src_full):
            sample_ctrls.add(src_full)
        if cmds.objExists(tgt_full):
            sample_ctrls.add(tgt_full)
    axes_data = _sample_rest_axes_batch(list(sample_ctrls))

    logger.debug(
        "[ShepMirror] Snapshot mirror: direction=%s axis=%s %d pairs ns='%s'",
        direction, mirror_axis, len(pairs), ns
    )

    cmds.undoInfo(openChunk=True)
    applied, skipped = 0, []
    try:
        for src_full, tgt_full in pairs:
            if not cmds.objExists(src_full):
                skipped.append(src_full)
                continue
            if not cmds.objExists(tgt_full):
                skipped.append(tgt_full)
                continue

            src_attrs = list_control_attrs(src_full)
            ctrl_negate = _compute_negate_set(
                axes_data.get(src_full), axes_data.get(tgt_full),
                mirror_axis, src_attrs
            )

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
                    logger.debug("[ShepMirror]   WARN: %s – %s", tgt_plug, exc)
    finally:
        cmds.undoInfo(closeChunk=True)

    logger.debug(
        "[ShepMirror] Snapshot mirror done: %d attrs applied, %d controls skipped",
        applied, len(skipped)
    )
    return applied, skipped

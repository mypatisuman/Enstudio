"""
instrument_packages.py - deterministic instrument + accessory topology templates.

WHY THIS EXISTS
---------------
One pressure loop in the four-way topology is eight to thirteen nodes and as
many connections:

    Acc -> Acc    pipe tap -> root valve -> siphon -> manifold
    Acc -> Inst   manifold -> transmitter
    Inst -> Inst  transmitter -> controller
    Inst -> Acc   controller -> positioner -> actuator -> control valve

Asking the LLM to emit all of that inside one JSON graph produced different
wiring on every run, and the deterministic fallbacks in the greenfield and
brownfield agents each hand-rolled the same chain in a long if/elif ladder --
two copies that had already drifted apart (greenfield emitted AFR, standards
and model_family; brownfield did not).

The model now chooses WHAT to add -- package, anchor, subsystem, loop number --
and this module builds HOW, identically every time and identically on both the
LLM path and the fallback path.

A template is a list of members and a list of connections. Members name a role
("root", "transmitter", ...), an ISA prefix, a node kind and a description.
Connections reference roles, plus the special role "@anchor" for the existing
node the package taps. Members marked inline (control valves, flow elements)
belong in a process line and are placed with break_line rather than hung off
the anchor.

Node kinds use EnGenie's renderer vocabulary (see generate_pid_svg); every tag
is additionally normalised through isa_classifier.classify_node_kind on write.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: An explicit ISA tag such as PT-101, PCV-2041 or HV-101A. The separator is
#: required: without it, model numbers like EJA110E or DVC6200 read as tags.
TAG_RE = re.compile(r"^([A-Z]{1,5})[-_](\d{2,6})([A-Z]?)$")

#: Measured-variable letter <-> package name.
VARIABLE_OF = {"P": "pressure", "T": "temperature", "F": "flow", "L": "level"}
LETTER_OF = {v: k for k, v in VARIABLE_OF.items()}


@dataclass(frozen=True)
class Member:
    role: str
    prefix: str
    kind: str
    description: str
    suffix: str = ""          # e.g. "A" for the first root valve
    inline: bool = False      # goes into a process line, not onto the anchor
    control_only: bool = False


@dataclass(frozen=True)
class Package:
    name: str
    measured: str
    members: tuple[Member, ...]
    connections: tuple[tuple[str, str, str], ...]   # (from_role, to_role, kind)
    control_connections: tuple[tuple[str, str, str], ...] = field(default_factory=tuple)


def _control(letter: str, valve_desc: str) -> tuple[tuple[Member, ...], tuple]:
    """The shared final-control-element tail: controller, air supply,
    positioner, actuator, control valve."""
    members = (
        Member("controller", letter + "IC", "controller",
               valve_desc + " indicating controller (DCS)", control_only=True),
        Member("air_regulator", "AFR", "regulator",
               "Instrument air filter regulator", control_only=True),
        Member("positioner", "POS", "positioner",
               "Electro-pneumatic smart valve positioner", control_only=True),
        Member("actuator", "ACT", "actuator",
               "Spring-diaphragm pneumatic actuator", control_only=True),
        Member("control_valve", letter + "CV", "valve",
               valve_desc + " control valve body", inline=True, control_only=True),
    )
    connections = (
        ("transmitter", "controller", "signal"),
        ("controller", "positioner", "signal"),
        ("air_regulator", "positioner", "pneumatic"),
        ("positioner", "actuator", "pneumatic"),
        ("actuator", "control_valve", "pneumatic"),
    )
    return members, connections


_P_CTRL, _P_CONN = _control("P", "Pressure")
_T_CTRL, _T_CONN = _control("T", "Temperature")
_F_CTRL, _F_CONN = _control("F", "Flow")
_L_CTRL, _L_CONN = _control("L", "Level")

#: The control tail on its own, keyed by measured-variable letter -- used to
#: add control to a measurement loop that already exists in the plant.
CONTROL_TAILS: dict[str, tuple[tuple[Member, ...], tuple]] = {
    "P": (_P_CTRL, _P_CONN), "T": (_T_CTRL, _T_CONN),
    "F": (_F_CTRL, _F_CONN), "L": (_L_CTRL, _L_CONN),
}


PACKAGES: dict[str, Package] = {
    "pressure": Package(
        name="pressure", measured="Pressure",
        members=(
            Member("root", "HV", "valve", "Impulse root isolation valve", suffix="A"),
            Member("siphon", "SYP", "siphon", "Pigtail condensation siphon"),
            Member("manifold", "MNF", "manifold", "3-valve coplanar manifold"),
            Member("transmitter", "PT", "transmitter", "Pressure transmitter"),
            *_P_CTRL,
        ),
        connections=(
            ("@anchor", "root", "impulse"),
            ("root", "siphon", "impulse"),
            ("siphon", "manifold", "impulse"),
            ("manifold", "transmitter", "impulse"),
        ),
        control_connections=_P_CONN,
    ),
    "temperature": Package(
        name="temperature", measured="Temperature",
        members=(
            Member("thermowell", "TW", "thermowell", "Flanged thermowell insertion sheath"),
            Member("element", "TE", "transmitter", "RTD temperature element"),
            Member("transmitter", "TT", "transmitter", "Temperature transmitter"),
            *_T_CTRL,
        ),
        connections=(
            ("@anchor", "thermowell", "impulse"),
            ("thermowell", "element", "impulse"),
            ("element", "transmitter", "signal"),
        ),
        control_connections=_T_CONN,
    ),
    "flow": Package(
        name="flow", measured="Flow",
        members=(
            Member("element", "FE", "transmitter", "Orifice plate flow element", inline=True),
            Member("root_high", "HV", "valve", "High-pressure impulse root valve", suffix="A"),
            Member("root_low", "HV", "valve", "Low-pressure impulse root valve", suffix="B"),
            Member("manifold", "MNF", "manifold", "5-valve coplanar manifold"),
            Member("transmitter", "FT", "transmitter",
                   "Differential-pressure flow transmitter"),
            *_F_CTRL,
        ),
        connections=(
            ("@anchor", "element", "impulse"),
            ("element", "root_high", "impulse"),
            ("element", "root_low", "impulse"),
            ("root_high", "manifold", "impulse"),
            ("root_low", "manifold", "impulse"),
            ("manifold", "transmitter", "impulse"),
        ),
        control_connections=_F_CONN,
    ),
    "level": Package(
        name="level", measured="Level",
        members=(
            Member("root_top", "HV", "valve", "Upper tap root isolation valve", suffix="A"),
            Member("root_bottom", "HV", "valve", "Lower tap root isolation valve", suffix="B"),
            Member("manifold", "MNF", "manifold", "3-valve coplanar manifold"),
            Member("transmitter", "LT", "transmitter", "Level transmitter"),
            *_L_CTRL,
        ),
        connections=(
            ("@anchor", "root_top", "impulse"),
            ("@anchor", "root_bottom", "impulse"),
            ("root_top", "manifold", "impulse"),
            ("root_bottom", "manifold", "impulse"),
            ("manifold", "transmitter", "impulse"),
        ),
        control_connections=_L_CONN,
    ),
}


#: Instrument category wording -> package name. Used by the deterministic
#: fallback builders to turn an extracted BOM line into a package choice.
_CATEGORY_HINTS: tuple[tuple[str, str], ...] = (
    ("pressure", "pressure"),
    ("temp", "temperature"),
    ("thermo", "temperature"),
    ("rtd", "temperature"),
    ("flow", "flow"),
    ("coriolis", "flow"),
    ("magnetic", "flow"),
    ("orifice", "flow"),
    ("level", "level"),
    ("radar", "level"),
)


def names() -> list[str]:
    return sorted(PACKAGES)


def members_for(package: str, with_control: bool) -> list[Member]:
    pkg = PACKAGES[package]
    return [m for m in pkg.members if with_control or not m.control_only]


def connections_for(package: str, with_control: bool) -> list[tuple[str, str, str]]:
    pkg = PACKAGES[package]
    return list(pkg.connections) + (list(pkg.control_connections) if with_control else [])


def package_for_category(category: str = "", product_name: str = "") -> str | None:
    """The package an extracted instrument category implies, or None when the
    category is not a measurement the templates cover (a standalone valve, a
    relief device, an analyser)."""
    text = (category + " " + product_name).lower()
    for hint, package in _CATEGORY_HINTS:
        if hint in text:
            return package
    return None


def wants_control(category: str = "", product_name: str = "") -> bool:
    """Whether the extracted line implies a final control element, i.e. the
    package should carry its controller/positioner/actuator/valve tail."""
    text = (category + " " + product_name).lower()
    return any(w in text for w in ("control valve", "control loop", "controller",
                                   "throttl", "modulat", "fcv", "pcv", "tcv", "lcv"))


def explicit_tag(inst: dict) -> str | None:
    """An ISA tag the engineer or BOM already assigned to this line, if any.
    A stated tag is data, not a suggestion: it is used as given."""
    for key in ("tag", "tag_number", "product_name"):
        value = str(inst.get(key) or "").strip().upper()
        if TAG_RE.match(value):
            return value
    return None


def package_for_tag(tag: str) -> str | None:
    m = TAG_RE.match(tag or "")
    return VARIABLE_OF.get(m.group(1)[0]) if m else None


def role_for_tag(package: str, tag: str) -> str | None:
    """Which package role an explicit tag fills: PT-101 is the pressure
    package's transmitter, PCV-102 its control valve. None when the tag does
    not belong to this package's measured variable."""
    m = TAG_RE.match(tag or "")
    letter = LETTER_OF.get(package)
    if not m or not letter:
        return None
    prefix = m.group(1)
    if not prefix.startswith(letter):
        return None
    if prefix.endswith("CV") or prefix == letter + "V":
        return "control_valve"
    if prefix.endswith("IC"):
        return "controller"
    if prefix.endswith("T") and len(prefix) <= 3:
        return "transmitter"
    return None


def plan_packages(instruments: list[dict] | None) -> tuple[list[dict], list[dict]]:
    """Turn an extracted instrument list into a build plan.

    Returns (plans, unmapped). Each plan is
    {"package", "with_control", "sources", "role_tags"}; each unmapped item is
    {"category", "product_name", "tag"} for a single node the caller adds.

    Lines that measure the same variable collapse into ONE package rather than
    one package each: a flow meter and a flow control valve are a single flow
    loop with a final control element, not two flow loops. That merge is why
    the plan is computed before anything is built.

    Explicit tags are honoured. A line whose tag is PT-101 binds the pressure
    package's transmitter role to PT-101, so the loop is numbered 101 rather
    than minted fresh; PCV-102 binds the control valve role.

    A line that implies control but names no measured variable (a bare "Control
    Valve") attaches its control tail to the package its tag belongs to, else
    the first package. It never causes a transmitter to be invented: with no
    matching package it stays unmapped and is added as a single valve.
    """
    plans: list[dict] = []
    by_package: dict[str, dict[str, Any]] = {}
    unmapped: list[dict] = []
    floating: list[dict] = []

    for inst in instruments or []:
        category = str(inst.get("category") or "")
        product = str(inst.get("product_name") or "")
        tag = explicit_tag(inst)
        package = package_for_category(category, product)
        control = wants_control(category, product)
        if package is None and tag and not control:
            package = package_for_tag(tag) if role_for_tag(
                package_for_tag(tag) or "", tag) == "transmitter" else None
        if package is None:
            if control:
                floating.append({"tag": tag, "source": inst})
            else:
                unmapped.append({"category": category, "product_name": product,
                                 "tag": tag})
            continue
        entry: dict[str, Any] | None = by_package.get(package)
        if entry is None:
            entry = {"package": package, "with_control": control,
                     "sources": [], "role_tags": {}}
            by_package[package] = entry
            plans.append(entry)
        entry["with_control"] = bool(entry["with_control"]) or control
        entry["sources"].append(inst)
        role = role_for_tag(package, tag) if tag else None
        if role:
            entry["role_tags"].setdefault(role, tag)

    for item in floating:
        tag = item["tag"]
        target = None
        if tag:
            target = by_package.get(package_for_tag(tag) or "")
        elif plans:
            target = plans[0]
        if target is None:
            src = item["source"]
            unmapped.append({"category": str(src.get("category") or "Control Valve"),
                             "product_name": str(src.get("product_name") or ""),
                             "tag": tag})
            continue
        target["with_control"] = True
        target["sources"].append(item["source"])
        if tag and role_for_tag(target["package"], tag) == "control_valve":
            target["role_tags"].setdefault("control_valve", tag)
    return plans, unmapped

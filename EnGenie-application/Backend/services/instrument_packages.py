"""
services/instrument_packages.py — deterministic instrument + accessory packages.

WHY THIS EXISTS
---------------
A retrofit of one pressure loop is eight to thirteen nodes and as many
connections, wired in a fixed four-way topology:

    Acc -> Acc   pipe tap -> root valve -> siphon -> manifold
    Acc -> Inst  manifold -> transmitter
    Inst -> Inst transmitter -> controller
    Inst -> Acc  controller -> positioner -> actuator -> control valve

Asking the LLM to enumerate all of that tool call by tool call burned the step
budget, produced inconsistent wiring between runs, and re-added accessories on a
retry. The model now chooses WHAT to add -- package, anchor, subsystem, loop
number -- and this module builds HOW, the same way every time.

A template is a list of members and a list of connections. Members name a role
(`root`, `transmitter`, ...), an ISA prefix, a node kind and a description.
Connections reference roles, plus the special role `@anchor` for the existing
tie-in node. `inline` members (control valves, flow elements) are placed into an
existing process line with break_line rather than hung off the anchor.
"""

from __future__ import annotations

from dataclasses import dataclass, field


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
        Member("controller", f"{letter}IC", "controller", f"{valve_desc} controller (DCS)", control_only=True),
        Member("air_regulator", "AFR", "regulator", "Instrument air filter regulator", control_only=True),
        Member("positioner", "POS", "positioner", "Smart valve positioner", control_only=True),
        Member("actuator", "ACT", "actuator", "Diaphragm actuator", control_only=True),
        Member("control_valve", f"{letter}CV", "control_valve", f"{valve_desc} control valve",
               inline=True, control_only=True),
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

PACKAGES: dict[str, Package] = {
    "pressure": Package(
        name="pressure", measured="Pressure",
        members=(
            Member("root", "HV", "hand_valve", "Root isolation valve", suffix="A"),
            Member("siphon", "SYP", "siphon", "Pigtail siphon"),
            Member("manifold", "MNF", "manifold", "3-valve manifold"),
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
            Member("thermowell", "TW", "thermowell", "Thermowell"),
            Member("element", "TE", "element", "RTD temperature element"),
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
            Member("element", "FE", "element", "Flow element (orifice)"),
            Member("root_high", "HV", "hand_valve", "High-pressure root valve", suffix="A"),
            Member("root_low", "HV", "hand_valve", "Low-pressure root valve", suffix="B"),
            Member("manifold", "MNF", "manifold", "3-valve manifold"),
            Member("transmitter", "FT", "transmitter", "Flow transmitter"),
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
            Member("root_top", "HV", "hand_valve", "Upper tap root valve", suffix="A"),
            Member("root_bottom", "HV", "hand_valve", "Lower tap root valve", suffix="B"),
            Member("manifold", "MNF", "manifold", "3-valve manifold"),
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


def names() -> list[str]:
    return sorted(PACKAGES)


def members_for(package: str, with_control: bool) -> list[Member]:
    pkg = PACKAGES[package]
    return [m for m in pkg.members if with_control or not m.control_only]


def connections_for(package: str, with_control: bool) -> list[tuple[str, str, str]]:
    pkg = PACKAGES[package]
    return list(pkg.connections) + (list(pkg.control_connections) if with_control else [])

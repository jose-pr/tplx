"""`DataEncoder`: how data is presented to Liquid, Handlebars, Mustache, the
shell engine and the program-backed engines, and how a subclass changes it."""

import json
import logging
from argparse import Namespace
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import PurePosixPath

import pytest

from tplx import DataEncoder, DataView, Loader, ShellTemplate


class Mac:
    """A value type: it writes itself as text, so it is not a structure."""

    __slots__ = ("octets",)

    def __init__(self, text):
        self.octets = text

    def __str__(self):
        return self.octets


class Owner:
    def __init__(self):
        self.name = "owner"
        self._back = self  # a back-reference that would recurse forever


@dataclass
class Point:
    x: int
    y: int


ENCODER = DataEncoder()


# -- what is a structure -----------------------------------------------------


def test_objects_become_lazy_views_and_values_pass_through():
    view = ENCODER.view({"o": Namespace(a=1), "ip": ip_address("10.0.0.1")})
    assert isinstance(view["o"], DataView) and view["o"]["a"] == 1
    assert view["ip"] == ip_address("10.0.0.1")


def test_an_object_with_its_own_str_is_a_value_not_a_structure():
    assert ENCODER.view({"mac": Mac("aa:bb")})["mac"].octets == "aa:bb"
    assert ENCODER.json({"mac": Mac("aa:bb")}) == {"mac": "aa:bb"}
    assert ENCODER.flatten({"mac": Mac("aa:bb")}) == {"MAC": "aa:bb"}


def test_a_path_and_a_dataclass():
    assert ENCODER.view({"p": PurePosixPath("/srv")})["p"] == PurePosixPath("/srv")
    assert ENCODER.json({"pt": Point(1, 2)}) == {"pt": {"x": 1, "y": 2}}


def test_a_view_hides_dunders_but_not_single_underscores():
    view = ENCODER.wrap(Namespace(_id="x", name="n"))
    assert set(view) == {"_id", "name"} and view.name == "n"


# -- json --------------------------------------------------------------------


def test_json_drops_private_names_unless_exposed_and_survives_cycles():
    document = ENCODER.json({"o": Owner(), "_hidden": 1})
    json.dumps(document)
    assert document == {"o": {"name": "owner"}}
    exposed = DataEncoder(expose=["_id"]).json({"o": Namespace(_id="t1")})
    assert exposed == {"o": {"_id": "t1"}}


def test_json_writes_other_values_as_text_and_stops_at_max_depth():
    assert ENCODER.json({"ip": ip_address("10.0.0.1"), "n": [1, "a"]}) == {
        "ip": "10.0.0.1",
        "n": [1, "a"],
    }
    deep = DataEncoder(max_depth=1).json({"a": {"b": {"c": 1}}})
    assert deep == {"a": "{'b': {'c': 1}}"}


# -- flatten -----------------------------------------------------------------


def test_flatten_joins_upper_cases_and_numbers_list_items():
    assert ENCODER.flatten(
        {"a": {"b": 1}, "l": ["x", Namespace(c=None)], "t": True}
    ) == {
        "A_B": "1",
        "L_0": "x",
        "L_1_C": "",
        "T": "true",
    }


def test_flatten_keeps_only_exposed_private_names():
    data = {"image": Namespace(_id="debian", _cache=object())}
    assert ENCODER.flatten(data) == {}
    assert DataEncoder(expose=["_id"]).flatten(data) == {"IMAGE__ID": "debian"}


def test_flatten_warns_when_two_paths_meet(caplog):
    with caplog.at_level(logging.WARNING, logger="tplx"):
        assert ENCODER.flatten({"target": {"ip": "a"}, "target_ip": "b"}) == {
            "TARGET_IP": "b"
        }
    assert "TARGET_IP" in caplog.text


def test_flatten_survives_a_cycle():
    assert ENCODER.flatten({"o": Owner()}) == {"O_NAME": "owner"}


# -- subclasses ---------------------------------------------------------------


class PointAsText(DataEncoder):
    """Writes a `Point` as `x,y` everywhere instead of as a structure."""

    def default(self, value):
        if isinstance(value, Point):
            return f"{value.x},{value.y}"
        return super().default(value)


class DottedLower(DataEncoder):
    def key(self, path):
        return ".".join(path)

    def text(self, value):
        if isinstance(value, bool):
            return "yes" if value else "no"
        return super().text(value)


def test_default_decides_how_a_type_is_encoded(tree):
    encoder = PointAsText()
    assert encoder.json({"pt": Point(1, 2)}) == {"pt": "1,2"}
    assert encoder.flatten({"pt": Point(1, 2)}) == {"PT": "1,2"}
    pytest.importorskip("liquid")
    tree.write("p.liquid", "{{ pt }}")
    assert (
        Loader([tree.root], encoder=encoder).render("p.liquid", pt=Point(1, 2)) == "1,2"
    )


def test_key_and_text_decide_how_data_is_flattened():
    flat = DottedLower().flatten({"target": {"hostname": "h", "pxe": False}})
    assert flat == {"target.hostname": "h", "target.pxe": "no"}


def test_the_shell_engine_uses_the_loaders_encoder(tree):
    loader = Loader([tree.root], encoder=DottedLower())
    # The shell engine's names are identifiers, so dotted keys are out of its
    # reach; the boolean text still comes from the encoder.
    tree.write("t.shtpl", "%{FLAG}")
    assert loader.render("t.shtpl", flag=True) == "yes"
    assert ShellTemplate("%{FLAG}").render(flag=True) == "true"


# -- edges ----------------------------------------------------------------------


class Node:
    def __init__(self, name):
        self.name = name
        self.peer = None


def test_keys_that_are_not_text_are_kept_and_named_by_their_text():
    data = {"vlans": {10: "mgmt", 20: "data"}}
    assert ENCODER.json(data) == {"vlans": {"10": "mgmt", "20": "data"}}
    assert ENCODER.flatten(data) == {"VLANS_10": "mgmt", "VLANS_20": "data"}


def test_flatten_writes_the_text_of_a_structure_at_max_depth_as_json_does():
    shallow = DataEncoder(max_depth=1)
    assert shallow.json({"a": {"b": 1}}) == {"a": "{'b': 1}"}
    assert shallow.flatten({"a": {"b": 1}}) == {"A": "{'b': 1}"}
    assert shallow.flatten({"a": 1}) == {"A": "1"}


def test_a_cycle_through_objects_is_cut_at_the_back_reference():
    a, b = Node("a"), Node("b")
    a.peer, b.peer = b, a
    assert ENCODER.json({"n": a}) == {"n": {"name": "a", "peer": {"name": "b"}}}
    assert ENCODER.flatten({"n": a}) == {"N_NAME": "a", "N_PEER_NAME": "b"}


def test_json_drops_a_reference_back_to_a_mapping_on_the_path():
    loop = {"name": "x"}
    loop["self"] = loop
    assert ENCODER.json({"c": loop}) == {"c": {"name": "x"}}


def test_a_view_refuses_dunder_names_by_item_as_by_attribute():
    view = ENCODER.wrap(Node("n"))
    with pytest.raises(KeyError):
        view["__class__"]
    assert dict(ENCODER.wrap({"__k__": 1})) == {"__k__": 1}  # a mapping's own key


def test_json_writes_a_non_finite_number_as_text():
    document = ENCODER.json({"a": float("nan"), "b": float("inf")})
    assert document == {"a": "nan", "b": "inf"}
    json.dumps(document, allow_nan=False)

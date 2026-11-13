# -*- coding: utf-8 -*-
"""Shared loader for baked construction step JSON data."""
import json
import os
from types import SimpleNamespace

from ._handlers import HANDLERS

STEPS_DIR = os.path.dirname(os.path.abspath(__file__))


def load_step(name, handlers=HANDLERS):
    path = os.path.join(STEPS_DIR, name + ".json")
    with open(path, "r", encoding="utf-8") as handle:
        params = json.load(handle)
    feature_type = params["RECORD"]["type"]
    return SimpleNamespace(
        STEP_NUMBER=params["STEP_NUMBER"],
        ORIGINAL_FEATURE_INDEX=params["ORIGINAL_FEATURE_INDEX"],
        SUPPORTED=feature_type in handlers,
        RECORD=params["RECORD"],
        DEFINITION=params["DEFINITION"],
        DEPENDENCIES=tuple(params["DEPENDENCIES"]),
        GEOMETRY=params["GEOMETRY"],
        build=handlers.get(feature_type),
    )

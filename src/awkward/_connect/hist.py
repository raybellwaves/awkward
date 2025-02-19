# BSD 3-Clause License; see https://github.com/scikit-hep/awkward-1.0/blob/main/LICENSE
"""
Provide native support for Awkward Arrays in Hist via `Hist.fill_flattened`.
"""
from __future__ import annotations

import numpy as np

import awkward as ak
from awkward._backends import NumpyBackend
from awkward._typing import Any, Sequence

numpy = NumpyBackend.instance()


def unpack(array: ak.Array) -> dict[str, ak.Array] | None:
    if not ak.fields(array):
        return None
    else:
        return {k: x for k, x in zip(ak.fields(array), ak.unzip(array))}


def broadcast_and_flatten(args: Sequence[Any]) -> tuple[np.ndarray]:
    try:
        arrays = [ak.Array(x, backend=numpy) for x in args]
    except TypeError:
        return NotImplementedError

    if any(x.fields for x in arrays):
        raise ak._errors.wrap_error(
            ValueError("cannot broadcast-and-flatten array with structure (fields)")
        )
    return tuple(
        ak.to_numpy(ak.flatten(x, axis=None)) for x in ak.broadcast_arrays(*arrays)
    )

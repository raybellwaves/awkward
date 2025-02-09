# BSD 3-Clause License; see https://github.com/scikit-hep/awkward-1.0/blob/main/LICENSE

import pytest

import awkward as ak

jax = pytest.importorskip("jax")
ak.jax.register_and_check()

left = ak.Array([1, 2, 3], backend="jax")
right = ak.Array([100, 200, 300.0], backend="cpu")
typetracer = ak.Array([44, 55, 66], backend="typetracer")


def test_concatenate():
    with pytest.raises(
        ValueError, match="cannot operate on arrays with incompatible array libraries"
    ):
        ak.concatenate((left, right))

    result = ak.concatenate((left, typetracer))
    assert ak.backend(result) == "typetracer"


def test_broadcast_arrays():
    with pytest.raises(
        ValueError, match="cannot operate on arrays with incompatible array libraries"
    ):
        ak.broadcast_arrays(left, right)

    result = ak.broadcast_arrays(left, typetracer)
    assert all(ak.backend(x) == "typetracer" for x in result)


def test_broadcast_fields():
    with pytest.raises(
        ValueError, match="cannot operate on arrays with incompatible array libraries"
    ):
        ak.broadcast_fields(left, right)

    result = ak.broadcast_fields(left, typetracer)
    assert all(ak.backend(x) == "typetracer" for x in result)


def test_cartesian():
    with pytest.raises(
        ValueError, match="cannot operate on arrays with incompatible array libraries"
    ):
        ak.cartesian((left, right), axis=0)

    result = ak.cartesian((left, typetracer), axis=0)
    assert ak.backend(result) == "typetracer"


def test_to_rdataframe():
    pytest.importorskip("ROOT")
    array = ak.Array([100, 200, 300.0], backend="typetracer")
    with pytest.raises(
        TypeError,
        match="Converting a TypeTracer nplike to an nplike with `known_data=True`",
    ):
        ak.to_rdataframe({"array": array})


def test_transform():
    def apply(layouts, backend, **kwargs):
        if not all(x.is_numpy for x in layouts):
            return
        return tuple(x.copy(data=backend.nplike.asarray(x) * 2) for x in layouts)

    with pytest.raises(
        ValueError, match="cannot operate on arrays with incompatible array libraries"
    ):
        ak.transform(apply, left, right)

    result = ak.transform(apply, left, typetracer)
    assert all(ak.backend(x) == "typetracer" for x in result)

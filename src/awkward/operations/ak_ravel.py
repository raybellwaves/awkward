# BSD 3-Clause License; see https://github.com/scikit-hep/awkward-1.0/blob/main/LICENSE
__all__ = ("ravel",)
import awkward as ak
from awkward._connect.numpy import unsupported
from awkward._layout import wrap_layout
from awkward._nplikes.numpylike import NumpyMetadata

np = NumpyMetadata.instance()


def ravel(array, *, highlevel=True, behavior=None):
    """
    Args:
        array: Array-like data (anything #ak.to_layout recognizes).
        highlevel (bool): If True, return an #ak.Array; otherwise, return
            a low-level #ak.contents.Content subclass.
        behavior (None or dict): Custom #ak.behavior for the output array, if
            high-level.

    Returns an array with all level of nesting removed by erasing the
    boundaries between consecutive lists.

    This is the equivalent of NumPy's `np.ravel` for Awkward Arrays.

    Consider the following:

        >>> array = ak.Array([[[1.1, 2.2, 3.3],
        ...                    [],
        ...                    [4.4, 5.5],
        ...                    [6.6]],
        ...                   [],
        ...                   [[7.7],
        ...                    [8.8, 9.9]
        ...                   ]])

    Ravelling the array produces a flat array

        >>> ak.ravel(array).show()
        [1.1,
         2.2,
         3.3,
         4.4,
         5.5,
         6.6,
         7.7,
         8.8,
         9.9]

    Missing values are not eliminated by flattening. See #ak.flatten with
    `axis=None` for an equivalent function that eliminates the option type.
    """
    with ak._errors.OperationErrorContext(
        "ak.ravel",
        {"array": array, "highlevel": highlevel, "behavior": behavior},
    ):
        return _impl(array, highlevel, behavior)


def _impl(array, highlevel, behavior):
    layout = ak.operations.to_layout(array, allow_record=False, allow_other=False)

    out = ak._do.remove_structure(layout, function_name="ak.ravel", drop_nones=False)
    assert isinstance(out, tuple) and all(
        isinstance(x, ak.contents.Content) for x in out
    )

    result = ak._do.mergemany(out)

    return wrap_layout(result, behavior, highlevel, like=array)


@ak._connect.numpy.implements("ravel")
def _nep_18_impl(a, order=unsupported):
    return ravel(a)

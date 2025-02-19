# BSD 3-Clause License; see https://github.com/scikit-hep/awkward-1.0/blob/main/LICENSE
__all__ = ("ones_like",)

import awkward as ak
from awkward._connect.numpy import unsupported
from awkward._nplikes.numpylike import NumpyMetadata

np = NumpyMetadata.instance()


def ones_like(
    array, *, dtype=None, including_unknown=False, highlevel=True, behavior=None
):
    """
    Args:
        array: Array-like data (anything #ak.to_layout recognizes).
        dtype (None or NumPy dtype): Overrides the data type of the result.
        including_unknown (bool): If True, the `unknown` type is considered
            a value type and is converted to a zero-length array of the
            specified dtype; if False, `unknown` will remain `unknown`.
        highlevel (bool, default is True): If True, return an #ak.Array;
            otherwise, return a low-level #ak.contents.Content subclass.
        behavior (None or dict): Custom #ak.behavior for the output array, if
            high-level.

    This is the equivalent of NumPy's `np.ones_like` for Awkward Arrays.

    See #ak.full_like for details, and see also #ak.zeros_like.

    (There is no equivalent of NumPy's `np.empty_like` because Awkward Arrays
    are immutable.)
    """
    with ak._errors.OperationErrorContext(
        "ak.ones_like",
        {
            "array": array,
            "dtype": dtype,
            "including_unknown": including_unknown,
            "highlevel": highlevel,
            "behavior": behavior,
        },
    ):
        return _impl(array, highlevel, behavior, dtype, including_unknown)


def _impl(array, highlevel, behavior, dtype, including_unknown):
    return ak.operations.ak_full_like._impl(
        array, 1, highlevel, behavior, dtype, including_unknown
    )


@ak._connect.numpy.implements("ones_like")
def _nep_18_impl(
    a, dtype=None, order=unsupported, subok=unsupported, shape=unsupported
):
    return ones_like(a, dtype=dtype)

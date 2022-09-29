# BSD 3-Clause License; see https://github.com/scikit-hep/awkward-1.0/blob/main/LICENSE

import awkward as ak

np = ak.nplikes.NumpyMetadata.instance()


def packed(array, highlevel=True, behavior=None):
    """
    Args:
        array: Array whose internal structure will be packed.
        highlevel (bool): If True, return an #ak.Array; otherwise, return
            a low-level #ak.contents.Content subclass.
        behavior (None or dict): Custom #ak.behavior for the output array, if
            high-level.

    Returns an array with the same type and values as the input, but with packed inner structures:

    - #ak.contents.NumpyArray becomes C-contiguous (if it isn't already)
    - #ak.contents.RegularArray trims unreachable content
    - #ak.contents.ListArray becomes #ak.contents.ListOffsetArray, making all list data contiguous
    - #ak.contents.ListOffsetArray starts at `offsets[0] == 0`, trimming unreachable content
    - #ak.contents.RecordArray trims unreachable contents
    - #ak.contents.IndexedArray gets projected
    - #ak.contents.IndexedOptionArray remains an #ak.contents.IndexedOptionArray (with simplified `index`) if it contains records, becomes #ak.contents.ByteMaskedArray otherwise
    - #ak.contents.ByteMaskedArray becomes an #ak.contents.IndexedOptionArray if it contains records, stays a #ak.contents.ByteMaskedArray otherwise
    - #ak.contents.BitMaskedArray becomes an #ak.contents.IndexedOptionArray if it contains records, stays a #ak.contents.BitMaskedArray otherwise
    - #ak.contents.UnionArray gets projected contents
    - #ak.record.Record becomes a record over a single-item #ak.contents.RecordArray

    Example:

        >>> a = ak.Array([[1, 2, 3], [], [4, 5], [6], [7, 8, 9, 10]])
        >>> b = a[::-1]
        >>> b
        <Array [[7, 8, 9, 10], [6, ... [], [1, 2, 3]] type='5 * var * int64'>
        >>> b.layout
        <ListArray64>
            <starts><Index64 i="[6 5 3 3 0]" offset="0" length="5" at="0x55e091c2b1f0"/></starts>
            <stops><Index64 i="[10 6 5 3 3]" offset="0" length="5" at="0x55e091a6ce80"/></stops>
            <content><NumpyArray format="l" shape="10" data="1 2 3 4 5 6 7 8 9 10" at="0x55e091c47260"/></content>
        </ListArray64>
        >>> c = ak.packed(b)
        >>> c
        <Array [[7, 8, 9, 10], [6, ... [], [1, 2, 3]] type='5 * var * int64'>
        >>> c.layout
        <ListOffsetArray64>
            <offsets><Index64 i="[0 4 5 7 7 10]" offset="0" length="6" at="0x55e091b077a0"/></offsets>
            <content><NumpyArray format="l" shape="10" data="7 8 9 10 6 4 5 1 2 3" at="0x55e091d04d30"/></content>
        </ListOffsetArray64>

    Performing these operations will minimize the output size of data sent to
    #ak.to_buffers (though conversions through Arrow, #ak.to_arrow and
    #ak.to_parquet, do not need this because packing is part of that conversion).

    See also #ak.to_buffers.
    """
    with ak._errors.OperationErrorContext(
        "ak.packed",
        dict(array=array, highlevel=highlevel, behavior=behavior),
    ):
        return _impl(array, highlevel, behavior)


def _impl(array, highlevel, behavior):
    layout = ak.operations.to_layout(array, allow_record=True, allow_other=False)
    out = layout.packed()
    return ak._util.wrap(out, behavior, highlevel)

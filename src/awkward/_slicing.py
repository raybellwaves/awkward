# BSD 3-Clause License; see https://github.com/scikit-hep/awkward-1.0/blob/main/LICENSE

from __future__ import annotations

import awkward as ak
from awkward._backends import Backend
from awkward._errors import wrap_error
from awkward._nplikes import nplike_of, to_nplike
from awkward._nplikes.jax import Jax
from awkward._nplikes.numpylike import NumpyMetadata, ShapeItem
from awkward._nplikes.typetracer import is_unknown_scalar
from awkward.typing import TYPE_CHECKING, Sequence, SupportsIndex, TypeAlias

if TYPE_CHECKING:
    from awkward._nplikes.numpylike import ArrayLike  # noqa: F401
    from awkward.contents.content import Content

np = NumpyMetadata.instance()


SliceItem: TypeAlias = "int | slice | str | None | Ellipsis | ArrayLike | Content"


def regularise_slice(
    slice: slice, length: ShapeItem, *, backend: Backend
) -> tuple[SupportsIndex, SupportsIndex, SupportsIndex]:
    """
    Args:
        slice: slice object
        length: length of layout
        backend: backend of layout

    Return a tuple of (start, stop, step) indices into a layout, suitable for
    `_getitem_range` (if step == 1). Normalise lengths to fit length of array,
    and for arrays with unknown lengths, these offsets become none.
    """
    index_nplike = backend.index_nplike
    start = slice.start
    stop = slice.stop
    step = slice.step

    length_scalar = index_nplike.shape_item_as_index(length)
    # Unknown lengths mean that the slice index is unknown
    if length is None:
        return length_scalar, length_scalar, step

    # Normalise `None` values
    if start is None:
        start = 0
    if stop is None:
        stop = length_scalar
    if step is None:
        step = 1

    # Normalise negative integers
    if not is_unknown_scalar(start) and start < 0:
        start = start + length_scalar
    if not is_unknown_scalar(stop) and stop < 0:
        stop = stop + length_scalar

    # Clamp values into length bounds
    if not is_unknown_scalar(start):
        if is_unknown_scalar(length_scalar):
            start = length_scalar
        else:
            start = min(max(start, 0), length_scalar)
    if not is_unknown_scalar(stop):
        if is_unknown_scalar(length_scalar):
            stop = length_scalar
        else:
            stop = min(max(stop, 0), length_scalar)

    return start, stop, step


def headtail(
    oldtail: tuple[SliceItem, ...]
) -> tuple[SliceItem | tuple, tuple[SliceItem, ...]]:
    if len(oldtail) == 0:
        return (), ()
    else:
        return oldtail[0], oldtail[1:]


def prepare_advanced_indexing(items):
    """Broadcast index objects to satisfy NumPy indexing rules

    Args:
        items: iterable of index items.

    Returns a tuple of broadcasted index items.

    Raises a ValueError if an invalid-style index is used, and a TypeError if an invalid
    index item type is given.
    """
    # First identify which items need to be broadcast
    broadcastable_index = []
    broadcastable = []
    n_awkward_contents = 0
    for item in items:
        if isinstance(item, ak.contents.Content):
            n_awkward_contents += 1
        if (
            isinstance(
                item,
                (
                    slice,
                    list,  # of strings
                    ak.contents.ListOffsetArray,
                    ak.contents.IndexedOptionArray,
                    str,
                ),
            )
            or item is np.newaxis
            or item is Ellipsis
        ):
            broadcastable_index.append(None)
        else:
            # this includes integers (which broadcast to arrays)
            broadcastable_index.append(len(broadcastable))
            broadcastable.append(item)

    # Now ensure that we don't have mixed Awkward-NumPy style indexing
    if n_awkward_contents > 1 or (n_awkward_contents == 1 and len(broadcastable) != 0):
        raise wrap_error(
            ValueError(
                "cannot mix Awkward slicing (using an array with missing or variable-length lists in the slice) with "
                "NumPy advanced slicing (using more than one broadcastable array or integer in the slice), "
                "though you can perform multiple slices "
            )
        )

    # Then broadcast the index items
    nplike = nplike_of(*broadcastable)
    broadcasted = nplike.broadcast_arrays(*broadcastable)

    # And re-assemble the index with the broadcasted items
    prepared = []
    for i_broadcast, item in zip(broadcastable_index, items):
        # Non-broadcasted item
        if i_broadcast is None:
            prepared.append(item)
            continue

        x = broadcasted[i_broadcast]
        if len(x.shape) == 0:
            prepared.append(int(x))
        elif np.issubdtype(x.dtype, np.int64):
            prepared.append(ak.index.Index64(nplike.reshape(x, (-1,))))
            prepared[-1].metadata["shape"] = x.shape
        elif np.issubdtype(x.dtype, np.integer):
            prepared.append(
                ak.index.Index64(
                    nplike.reshape(nplike.astype(x, dtype=np.int64), (-1,))
                )
            )
            prepared[-1].metadata["shape"] = x.shape
        elif np.issubdtype(x.dtype, np.bool_):
            if len(x.shape) == 1:
                current = ak.index.Index64(nplike.nonzero(x)[0])
                prepared.append(current)
                prepared[-1].metadata["shape"] = current.data.shape
            else:
                for w in nplike.nonzero(x):
                    prepared.append(ak.index.Index64(w))
        else:
            raise wrap_error(
                TypeError(
                    "array slice must be an array of integers or booleans, not\n\n    {}".format(
                        repr(x).replace("\n", "\n    ")
                    )
                )
            )

    # Finally, ensure that we don't have an unsupported mode of NumPy indexing
    # We do this here, rather than above the broadcast, because unlike the
    # Awkward-NumPy case, we don't want to treat integer indices as "advanced"
    # indices, i.e. `0, :, 0` should not trigger this case, but `0, :, [0]` should
    # (it is broadcast to `[0], :, [0]`)
    # We'll perform this validation using a simple finite-state machine
    it = iter(prepared)
    # Find an array
    for item in it:
        if isinstance(item, ak.index.Index):
            break
    # Then find a separator
    for item in it:
        if (item is np.newaxis) or (item is Ellipsis) or isinstance(item, slice):
            break
    # Now error if we find another array
    for item in it:
        if isinstance(item, ak.index.Index):
            raise wrap_error(
                ValueError(
                    "NumPy advanced indexing with array indices separated by None "
                    "(np.newaxis), Ellipsis, or slice are not permitted with Awkward Arrays"
                )
            )
    return tuple(prepared)


def normalise_item(item, backend: Backend) -> SliceItem:
    """
    Args:
        item: content to normalise
        backend: backend of the result

    Normalise each slice item into a fixed set of possible types, such as slices
    integers, strings, np.newaxis, Ellipsis, bare integer arrays, or ragged arrays
    of integers.
    """
    # Basic indices
    if ak._util.is_integer(item):
        return int(item)

    elif isinstance(item, slice):
        return item

    elif isinstance(item, str):
        return item

    elif item is np.newaxis:
        return item

    elif item is Ellipsis:
        return item

    elif isinstance(item, ak.highlevel.Array):
        return normalise_item(item.layout, backend)

    # Advanced / Ragged / Masked index items
    elif isinstance(item, ak.contents.EmptyArray):
        return normalise_item(item.to_NumpyArray(np.int64), backend)

    elif isinstance(item, ak.contents.NumpyArray):
        return to_nplike(item.data, backend.index_nplike)

    elif isinstance(item, ak.contents.RegularArray):
        # Pure NumPy arrays (without masks) follow NumPy advanced indexing
        # If we can produce such a content, return the underlying NumPy array
        # Otherwise, we probably have options or are not purelist_regular, etc.
        # As such, we then follow Awkward indexing. This logic should follow
        # the generic `isinstance(item, ak.contents.Content)` case below
        as_numpy = item.maybe_to_NumpyArray()

        if as_numpy is None:
            out = _normalise_item_bool_to_int(_normalise_item_nested(item), backend)
            assert out.backend is backend
            assert not isinstance(out, ak.contents.NumpyArray)
            return out
        else:
            return to_nplike(
                as_numpy.data, backend.index_nplike, from_nplike=as_numpy.backend.nplike
            )

    # Ragged indexing should be performed with integer contents
    elif isinstance(item, ak.contents.Content):
        out = _normalise_item_bool_to_int(_normalise_item_nested(item), backend)
        assert out.backend is backend
        if isinstance(out, ak.contents.NumpyArray):
            return out.data
        else:
            return out

    # Fallback for sized objects
    elif ak._util.is_sized_iterable(item):
        # Do we have an array
        nplike = ak._nplikes.nplike_of(item, default=None)
        # We can end up with non-array objects associated with an nplike
        if nplike is not None and nplike.is_own_array(item):
            # Is it a scalar, not array?
            if len(item.shape) == 0:
                raise wrap_error(
                    NotImplementedError("scalar objects in slice normalisation")
                )
            else:
                layout = ak.operations.ak_to_layout._impl(
                    item, allow_record=False, allow_other=True, regulararray=False
                )
                return normalise_item(layout, backend)

        # Empty index array
        elif len(item) == 0:
            return backend.index_nplike.empty(0, dtype=np.int64)

        # List of strings
        elif all(isinstance(x, str) for x in item):
            return list(item)

        # Other iterable
        else:
            layout = ak.operations.ak_to_layout._impl(
                item, allow_record=False, allow_other=True, regulararray=False
            )
            return normalise_item(layout, backend)

    else:
        raise wrap_error(
            TypeError(
                "only integers, slices (`:`), ellipsis (`...`), np.newaxis (`None`), "
                "integer/boolean arrays (possibly with variable-length nested "
                "lists or missing values), field name (str) or names (non-tuple "
                "iterable of str) are valid indices for slicing, not\n\n    "
                + repr(item).replace("\n", "\n    ")
            )
        )


def normalise_items(where: Sequence, backend: Backend) -> list:
    where_backend = ak._backends.backend_of(*where, default=backend)
    common_backend = ak._backends.common_backend([backend, where_backend])
    # First prepare items for broadcasting into like-types
    return [normalise_item(x, backend=common_backend) for x in where]


def _normalise_item_RegularArray_to_ListOffsetArray64(item: Content) -> Content:
    if isinstance(item, ak.contents.RegularArray):
        next = item.to_ListOffsetArray64()
        return ak.contents.ListOffsetArray(
            next.offsets,
            _normalise_item_RegularArray_to_ListOffsetArray64(next.content),
            parameters=item.parameters,
        )

    elif isinstance(item, ak.contents.NumpyArray) and item.purelist_depth == 1:
        return item

    else:
        raise wrap_error(AssertionError(type(item)))


def _normalise_item_nested(item: Content) -> Content:
    if isinstance(item, ak.contents.EmptyArray):
        # policy: unknown -> int
        return _normalise_item_nested(item.to_NumpyArray(np.int64))

    elif isinstance(item, ak.contents.NumpyArray) and issubclass(
        item.dtype.type, (bool, np.bool_, np.integer)
    ):
        if issubclass(item.dtype.type, (bool, np.bool_, np.int64)):
            next = item
        else:
            next = ak.contents.NumpyArray(
                item.backend.nplike.astype(item.data, np.int64),
                parameters=item.parameters,
                backend=item.backend,
            )
        # Any NumpyArray at this point is part of a non-Numpy indexing
        # slice item. Therefore, we want to invoke ragged indexing by
        # converting N-dimensional layouts to ListOffsetArray, and converting the
        # dtype to int if not a supported index type
        return _normalise_item_RegularArray_to_ListOffsetArray64(next.to_RegularArray())

    elif isinstance(
        item,
        ak.contents.ListOffsetArray,
    ) and issubclass(item.offsets.dtype.type, np.int64):
        return ak.contents.ListOffsetArray(
            item.offsets,
            _normalise_item_nested(item.content),
            parameters=item.parameters,
        )

    elif isinstance(
        item,
        (
            ak.contents.ListOffsetArray,
            ak.contents.ListArray,
            ak.contents.RegularArray,
        ),
    ):
        next = item.to_ListOffsetArray64(False)
        return _normalise_item_nested(next)

    elif isinstance(
        item,
        (
            ak.contents.IndexedArray,
            ak.contents.IndexedOptionArray,
            ak.contents.ByteMaskedArray,
            ak.contents.BitMaskedArray,
            ak.contents.UnmaskedArray,
        ),
    ) and isinstance(
        item.content,
        (
            ak.contents.IndexedArray,
            ak.contents.IndexedOptionArray,
            ak.contents.ByteMaskedArray,
            ak.contents.BitMaskedArray,
            ak.contents.UnmaskedArray,
        ),
    ):
        return _normalise_item_nested(item)

    elif isinstance(
        item,
        ak.contents.IndexedArray,
    ):
        next = item.project()
        return _normalise_item_nested(next)

    elif isinstance(
        item,
        ak.contents.IndexedOptionArray,
    ):
        nextindex = item.backend.index_nplike.astype(
            item.index.data, dtype=np.int64
        )  # this ALWAYS copies
        nonnull = nextindex >= 0

        projected = item.content._carry(ak.index.Index64(nextindex[nonnull]), False)

        # content has been projected; index must agree
        nextindex[nonnull] = item.backend.index_nplike.arange(
            projected.length, dtype=np.int64
        )

        return ak.contents.IndexedOptionArray(
            ak.index.Index64(nextindex),
            _normalise_item_nested(projected),
            parameters=item.parameters,
        )

    elif isinstance(
        item,
        (
            ak.contents.ByteMaskedArray,
            ak.contents.BitMaskedArray,
            ak.contents.UnmaskedArray,
        ),
    ):
        is_valid = item.mask_as_bool(valid_when=True)
        positions_where_valid = item.backend.index_nplike.nonzero(is_valid)[0]

        nextcontent = _normalise_item_nested(
            item.content._carry(ak.index.Index64(positions_where_valid), False)
        )

        nextindex = item.backend.index_nplike.full(
            is_valid.shape[0], -1, dtype=np.int64
        )
        nextindex[positions_where_valid] = item.backend.index_nplike.arange(
            positions_where_valid.shape[0], dtype=np.int64
        )

        return ak.contents.IndexedOptionArray(
            ak.index.Index64(nextindex, nplike=item.backend.index_nplike),
            nextcontent,
            parameters=item.parameters,
        )

    elif isinstance(item, ak.contents.UnionArray):
        raise wrap_error(
            TypeError(
                "irreducible unions (different types at the same level in an array) can't be used as slices"
            )
        )

    elif isinstance(item, ak.contents.RecordArray):
        raise wrap_error(TypeError("record arrays can't be used as slices"))

    else:
        raise wrap_error(
            TypeError(
                "only integers, slices (`:`), ellipsis (`...`), np.newaxis (`None`), "
                "integer/boolean arrays (possibly with variable-length nested "
                "lists or missing values), field name (str) or names (non-tuple "
                "iterable of str) are valid indices for slicing, not\n\n    "
                + repr(item).replace("\n", "\n    ")
            )
        )


def _normalise_item_bool_to_int(item: Content, backend: Backend) -> Content:
    """
    Args:
        item: content to normalise
        backend: backend of the result

    Normalise boolean mask advanced indices into integer advanced indices.
    """
    from awkward.contents.indexedoptionarray import IndexedOptionArray
    from awkward.contents.listoffsetarray import ListOffsetArray
    from awkward.contents.numpyarray import NumpyArray

    item_backend = item.backend

    # actually convert leaf-node booleans to integers
    if (
        isinstance(item, ListOffsetArray)
        and isinstance(item.content, NumpyArray)
        and np.issubdtype(item.content.dtype, np.bool_)
    ):
        if item_backend.nplike.known_data or item_backend.nplike.known_shape:
            item = item.to_ListOffsetArray64(True)
            localindex = ak._do.local_index(item, axis=1)
            nextcontent = localindex.content.data[item.content.data]

            cumsum = item_backend.index_nplike.empty(
                item.content.data.shape[0] + 1, dtype=np.int64
            )
            cumsum[0] = 0
            cumsum[1:] = item_backend.index_nplike.asarray(
                item_backend.nplike.cumsum(item.content.data)
            )
            nextoffsets = cumsum[item.offsets]

        else:
            item._touch_data(recursive=False)
            nextoffsets = item.offsets
            nextcontent = item_backend.nplike.empty(None, dtype=np.int64)

        return ListOffsetArray(
            ak.index.Index64(nextoffsets),
            NumpyArray(nextcontent, backend=item_backend),
        ).to_backend(backend)

    elif (
        isinstance(item, ListOffsetArray)
        and isinstance(item.content, IndexedOptionArray)
        and isinstance(item.content.content, NumpyArray)
        and np.issubdtype(item.content.content.dtype, np.bool_)
    ):
        if item_backend.nplike.known_data or item_backend.nplike.known_shape:
            if isinstance(item_backend.nplike, Jax):
                raise wrap_error("This slice is not supported for JAX differentiation.")
            # missing values as any integer other than -1 are extremely rare
            isnegative = item.content.index.data < 0
            if item_backend.index_nplike.any(item.content.index.data < -1):
                safeindex = item.content.index.data.copy()
                safeindex[isnegative] = -1
            else:
                safeindex = item.content.index.data

            # expanded is a new buffer (can be modified in-place)
            if item.content.content.data.shape[0] > 0:
                expanded = item.content.content.data[safeindex]
            else:
                expanded = item.content.content.backend.nplike.ones(
                    safeindex.shape[0], dtype=np.bool_
                )

            localindex = ak._do.local_index(item, axis=1)

            # nextcontent does not include missing values
            expanded[isnegative] = False
            nextcontent = localindex.content.data[expanded]

            # list offsets do include missing values
            expanded[isnegative] = True
            cumsum = item_backend.nplike.empty(expanded.shape[0] + 1, dtype=np.int64)
            cumsum[0] = 0
            cumsum[1:] = item_backend.nplike.cumsum(expanded)
            nextoffsets = cumsum[item.offsets]

            # outindex fits into the lists; non-missing are sequential
            outindex = item_backend.index_nplike.full(
                nextoffsets[-1], -1, dtype=np.int64
            )
            outindex[~isnegative[expanded]] = item_backend.index_nplike.arange(
                nextcontent.shape[0], dtype=np.int64
            )

        else:
            item._touch_data(recursive=False)
            nextoffsets = item.offsets
            outindex = item.content.index
            nextcontent = item_backend.nplike.empty(None, dtype=np.int64)

        return ListOffsetArray(
            ak.index.Index64(nextoffsets, nplike=item_backend.index_nplike),
            IndexedOptionArray(
                ak.index.Index(outindex, nplike=item_backend.index_nplike),
                NumpyArray(nextcontent, backend=item_backend),
            ),
        ).to_backend(backend)

    elif isinstance(item, ListOffsetArray):
        return ListOffsetArray(
            item.offsets, _normalise_item_bool_to_int(item.content, backend)
        ).to_backend(backend)

    elif isinstance(item, IndexedOptionArray):
        if isinstance(item.content, ListOffsetArray):
            return IndexedOptionArray(
                item.index, _normalise_item_bool_to_int(item.content, backend)
            ).to_backend(backend)

        if isinstance(item.content, NumpyArray) and issubclass(
            item.content.dtype.type, (bool, np.bool_)
        ):
            if item_backend.nplike.known_data or item_backend.nplike.known_shape:
                if isinstance(item_backend.nplike, Jax):
                    raise wrap_error(
                        TypeError(
                            "This slice is not supported for JAX differentiation."
                        )
                    )

                # missing values as any integer other than -1 are extremely rare
                isnegative = item.index.data < 0
                if item_backend.index_nplike.any(item.index.data < -1):
                    safeindex = item.index.data.copy()
                    safeindex[isnegative] = -1
                else:
                    safeindex = item.index.data

                # expanded is a new buffer (can be modified in-place)
                if item.content.data.shape[0] > 0:
                    expanded = item.content.data[safeindex]
                else:
                    expanded = item.content.backend.nplike.ones(
                        safeindex.shape[0], dtype=np.bool_
                    )

                # nextcontent does not include missing values
                expanded[isnegative] = False
                nextcontent = item_backend.nplike.nonzero(expanded)[0]

                # outindex does include missing values
                expanded[isnegative] = True
                lenoutindex = item_backend.nplike.count_nonzero(expanded)

                # non-missing are sequential
                non_negative = item_backend.nplike.logical_not(isnegative[expanded])
                outindex = item_backend.index_nplike.full(
                    lenoutindex, -1, dtype=np.int64
                )
                outindex[
                    to_nplike(non_negative, item_backend.index_nplike)
                ] = item_backend.index_nplike.arange(
                    nextcontent.shape[0], dtype=np.int64
                )

            else:
                item._touch_data(recursive=False)
                outindex = item.index
                nextcontent = item_backend.nplike.empty(None, dtype=np.int64)

            return IndexedOptionArray(
                ak.index.Index(outindex, nplike=item_backend.index_nplike),
                NumpyArray(nextcontent, backend=item_backend),
            ).to_backend(backend)

        else:
            return IndexedOptionArray(
                item.index, _normalise_item_bool_to_int(item.content, backend)
            ).to_backend(backend)

    elif isinstance(item, NumpyArray):
        assert item.data.shape == (item.length,)
        return item

    else:
        raise wrap_error(AssertionError(type(item)))


def getitem_next_array_wrap(
    outcontent: Content, shape: tuple[int], outer_length: int = 0
) -> Content:
    for i in range(len(shape))[::-1]:
        length = shape[i - 1] if i > 0 else outer_length
        size = shape[i]
        if size is None:
            size = 1
        outcontent = ak.contents.RegularArray(outcontent, size, length, parameters=None)
    return outcontent

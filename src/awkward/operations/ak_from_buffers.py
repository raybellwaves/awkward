# BSD 3-Clause License; see https://github.com/scikit-hep/awkward-1.0/blob/main/LICENSE
from __future__ import annotations

__all__ = ("from_buffers",)

import math

import awkward as ak
from awkward._layout import wrap_layout
from awkward._nplikes.numpy import Numpy
from awkward._nplikes.numpylike import NumpyMetadata
from awkward._regularize import is_integer

np = NumpyMetadata.instance()
numpy = Numpy.instance()


def from_buffers(
    form,
    length,
    container,
    buffer_key="{form_key}-{attribute}",
    *,
    backend="cpu",
    byteorder="<",
    highlevel=True,
    behavior=None,
):
    """
    Args:
        form (#ak.forms.Form or str/dict equivalent): The form of the Awkward
            Array to reconstitute from named buffers.
        length (int): Length of the array. (The output of this function is always
            single-partition.)
        container (Mapping, such as dict): The str \u2192 Python buffers that
            represent the decomposed Awkward Array. This `container` is only
            assumed to have a `__getitem__` method that accepts strings as keys.
        buffer_key (str or callable): Python format string containing
            `"{form_key}"` and/or `"{attribute}"` or a function that takes these
            as keyword arguments and returns a string to use as a key for a buffer
            in the `container`.
        backend (str): Library to use to generate values that are
            put into the new array. The default, cpu, makes NumPy
            arrays, which are in main memory (e.g. not GPU). If all the values in
            `container` have the same `backend` as this, they won't be copied.
        byteorder (`"<"`, `">"`): Endianness of buffers read from `container`.
            If the byteorder does not match the current system byteorder, the
            arrays will be copied.
        highlevel (bool): If True, return an #ak.Array; otherwise, return
            a low-level #ak.contents.Content subclass.
        behavior (None or dict): Custom #ak.behavior for the output array, if
            high-level.

    Reconstitutes an Awkward Array from a Form, length, and a collection of memory
    buffers, so that data can be losslessly read from file formats and storage
    devices that only map names to binary blobs (such as a filesystem directory).

    The first three arguments of this function are the return values of
    #ak.to_buffers, so a full round-trip is

        >>> reconstituted = ak.from_buffers(*ak.to_buffers(original))

    The `container` argument lets you specify your own Mapping, which might be
    an interface to some storage format or device (e.g. h5py). It's okay if
    the `container` dropped NumPy's `dtype` and `shape` information, leaving
    raw bytes, since `dtype` and `shape` can be reconstituted from the
    #ak.forms.NumpyForm.
    If the values of `container` are recognised as arrays by the given backend,
    a view over their existing data will be used, where possible.

    The `buffer_key` should be the same as the one used in #ak.to_buffers.

    See #ak.to_buffers for examples.
    """
    with ak._errors.OperationErrorContext(
        "ak.from_buffers",
        {
            "form": form,
            "length": length,
            "container": container,
            "buffer_key": buffer_key,
            "backend": backend,
            "byteorder": byteorder,
            "highlevel": highlevel,
            "behavior": behavior,
        },
    ):
        return _impl(
            form,
            length,
            container,
            buffer_key,
            backend,
            byteorder,
            highlevel,
            behavior,
            False,
        )


def _impl(
    form,
    length,
    container,
    buffer_key,
    backend,
    byteorder,
    highlevel,
    behavior,
    simplify,
):
    backend = ak._backends.regularize_backend(backend)

    if isinstance(form, str):
        if ak.types.numpytype.is_primitive(form):
            form = ak.forms.NumpyForm(form)
        else:
            form = ak.forms.from_json(form)
    elif isinstance(form, dict):
        form = ak.forms.from_dict(form)

    if not (is_integer(length) and length >= 0):
        raise ak._errors.wrap_error(
            TypeError("'length' argument must be a non-negative integer")
        )

    if not isinstance(form, ak.forms.Form):
        raise ak._errors.wrap_error(
            TypeError(
                "'form' argument must be a Form or its Python dict/JSON string representation"
            )
        )

    if isinstance(buffer_key, str):

        def getkey(form, attribute):
            return buffer_key.format(form_key=form.form_key, attribute=attribute)

    elif callable(buffer_key):

        def getkey(form, attribute):
            return buffer_key(form_key=form.form_key, attribute=attribute, form=form)

    else:
        raise ak._errors.wrap_error(
            TypeError(
                f"buffer_key must be a string or a callable, not {type(buffer_key)}"
            )
        )

    out = reconstitute(form, length, container, getkey, backend, byteorder, simplify)
    return wrap_layout(out, behavior, highlevel)


_index_to_dtype = {
    "i8": np.dtype("<i1"),
    "u8": np.dtype("<u1"),
    "i32": np.dtype("<i4"),
    "u32": np.dtype("<u4"),
    "i64": np.dtype("<i8"),
}


def _from_buffer(nplike, buffer, dtype, count, byteorder):
    if nplike.is_own_array(buffer):
        array = nplike.reshape(buffer.view(dtype), shape=(-1,), copy=False)

        # Require 1D
        if array.size < count:
            raise ak._errors.wrap_error(
                TypeError(
                    f"size of array ({array.size}) is less than size of form ({count})"
                )
            )

        return array[:count]
    else:
        array = nplike.frombuffer(buffer, dtype=dtype, count=count)
        if byteorder != ak._util.native_byteorder:
            return array.byteswap(inplace=False)
        else:
            return array


def reconstitute(form, length, container, getkey, backend, byteorder, simplify):
    if isinstance(form, ak.forms.EmptyForm):
        if length != 0:
            raise ak._errors.wrap_error(
                ValueError(f"EmptyForm node, but the expected length is {length}")
            )
        return ak.contents.EmptyArray()

    elif isinstance(form, ak.forms.NumpyForm):
        dtype = ak.types.numpytype.primitive_to_dtype(form.primitive)
        raw_array = container[getkey(form, "data")]
        real_length = length
        for x in form.inner_shape:
            real_length *= x
        data = _from_buffer(
            backend.nplike,
            raw_array,
            dtype=dtype,
            count=real_length,
            byteorder=byteorder,
        )
        if form.inner_shape != ():
            if len(data) == 0:
                data = backend.nplike.reshape(data, (length, *form.inner_shape))
            else:
                data = backend.nplike.reshape(data, (-1, *form.inner_shape))
        return ak.contents.NumpyArray(data, parameters=form.parameters, backend=backend)

    elif isinstance(form, ak.forms.UnmaskedForm):
        content = reconstitute(
            form.content, length, container, getkey, backend, byteorder, simplify
        )
        if simplify:
            make = ak.contents.UnmaskedArray.simplified
        else:
            make = ak.contents.UnmaskedArray
        return make(content, parameters=form.parameters)

    elif isinstance(form, ak.forms.BitMaskedForm):
        raw_array = container[getkey(form, "mask")]
        excess_length = int(math.ceil(length / 8.0))
        mask = _from_buffer(
            backend.index_nplike,
            raw_array,
            dtype=_index_to_dtype[form.mask],
            count=excess_length,
            byteorder=byteorder,
        )
        content = reconstitute(
            form.content, length, container, getkey, backend, byteorder, simplify
        )
        if simplify:
            make = ak.contents.BitMaskedArray.simplified
        else:
            make = ak.contents.BitMaskedArray
        return make(
            ak.index.Index(mask),
            content,
            form.valid_when,
            length,
            form.lsb_order,
            parameters=form.parameters,
        )

    elif isinstance(form, ak.forms.ByteMaskedForm):
        raw_array = container[getkey(form, "mask")]
        mask = _from_buffer(
            backend.index_nplike,
            raw_array,
            dtype=_index_to_dtype[form.mask],
            count=length,
            byteorder=byteorder,
        )
        content = reconstitute(
            form.content, length, container, getkey, backend, byteorder, simplify
        )
        if simplify:
            make = ak.contents.ByteMaskedArray.simplified
        else:
            make = ak.contents.ByteMaskedArray
        return make(
            ak.index.Index(mask),
            content,
            form.valid_when,
            parameters=form.parameters,
        )

    elif isinstance(form, ak.forms.IndexedOptionForm):
        raw_array = container[getkey(form, "index")]
        index = _from_buffer(
            backend.index_nplike,
            raw_array,
            dtype=_index_to_dtype[form.index],
            count=length,
            byteorder=byteorder,
        )
        next_length = (
            0 if len(index) == 0 else max(0, backend.index_nplike.max(index) + 1)
        )
        content = reconstitute(
            form.content, next_length, container, getkey, backend, byteorder, simplify
        )
        if simplify:
            make = ak.contents.IndexedOptionArray.simplified
        else:
            make = ak.contents.IndexedOptionArray
        return make(
            ak.index.Index(index),
            content,
            parameters=form.parameters,
        )

    elif isinstance(form, ak.forms.IndexedForm):
        raw_array = container[getkey(form, "index")]
        index = _from_buffer(
            backend.index_nplike,
            raw_array,
            dtype=_index_to_dtype[form.index],
            count=length,
            byteorder=byteorder,
        )
        next_length = (
            0
            if len(index) == 0
            else backend.index_nplike.index_as_shape_item(
                backend.index_nplike.max(index) + 1
            )
        )
        content = reconstitute(
            form.content, next_length, container, getkey, backend, byteorder, simplify
        )
        if simplify:
            make = ak.contents.IndexedArray.simplified
        else:
            make = ak.contents.IndexedArray
        return make(
            ak.index.Index(index),
            content,
            parameters=form.parameters,
        )

    elif isinstance(form, ak.forms.ListForm):
        raw_array1 = container[getkey(form, "starts")]
        raw_array2 = container[getkey(form, "stops")]
        starts = _from_buffer(
            backend.index_nplike,
            raw_array1,
            dtype=_index_to_dtype[form.starts],
            count=length,
            byteorder=byteorder,
        )
        stops = _from_buffer(
            backend.index_nplike,
            raw_array2,
            dtype=_index_to_dtype[form.stops],
            count=length,
            byteorder=byteorder,
        )
        reduced_stops = stops[starts != stops]
        next_length = 0 if len(starts) == 0 else backend.index_nplike.max(reduced_stops)
        content = reconstitute(
            form.content, next_length, container, getkey, backend, byteorder, simplify
        )
        return ak.contents.ListArray(
            ak.index.Index(starts),
            ak.index.Index(stops),
            content,
            parameters=form.parameters,
        )

    elif isinstance(form, ak.forms.ListOffsetForm):
        raw_array = container[getkey(form, "offsets")]
        offsets = _from_buffer(
            backend.index_nplike,
            raw_array,
            dtype=_index_to_dtype[form.offsets],
            count=length + 1,
            byteorder=byteorder,
        )
        next_length = 0 if len(offsets) == 1 else offsets[-1]
        content = reconstitute(
            form.content, next_length, container, getkey, backend, byteorder, simplify
        )
        return ak.contents.ListOffsetArray(
            ak.index.Index(offsets),
            content,
            parameters=form.parameters,
        )

    elif isinstance(form, ak.forms.RegularForm):
        next_length = length * form.size
        content = reconstitute(
            form.content, next_length, container, getkey, backend, byteorder, simplify
        )
        return ak.contents.RegularArray(
            content,
            form.size,
            length,
            parameters=form.parameters,
        )

    elif isinstance(form, ak.forms.RecordForm):
        contents = [
            reconstitute(
                content, length, container, getkey, backend, byteorder, simplify
            )
            for content in form.contents
        ]
        return ak.contents.RecordArray(
            contents,
            None if form.is_tuple else form.fields,
            length,
            parameters=form.parameters,
        )

    elif isinstance(form, ak.forms.UnionForm):
        raw_array1 = container[getkey(form, "tags")]
        raw_array2 = container[getkey(form, "index")]
        tags = _from_buffer(
            backend.index_nplike,
            raw_array1,
            dtype=_index_to_dtype[form.tags],
            count=length,
            byteorder=byteorder,
        )
        index = _from_buffer(
            backend.index_nplike,
            raw_array2,
            dtype=_index_to_dtype[form.index],
            count=length,
            byteorder=byteorder,
        )
        lengths = []
        for tag in range(len(form.contents)):
            selected_index = index[tags == tag]
            if len(selected_index) == 0:
                lengths.append(0)
            else:
                lengths.append(backend.index_nplike.max(selected_index) + 1)
        contents = [
            reconstitute(
                content, lengths[i], container, getkey, backend, byteorder, simplify
            )
            for i, content in enumerate(form.contents)
        ]
        if simplify:
            make = ak.contents.UnionArray.simplified
        else:
            make = ak.contents.UnionArray
        return make(
            ak.index.Index(tags),
            ak.index.Index(index),
            contents,
            parameters=form.parameters,
        )

    else:
        raise ak._errors.wrap_error(
            AssertionError("unexpected form node type: " + str(type(form)))
        )

# BSD 3-Clause License; see https://github.com/scikit-hep/awkward-1.0/blob/main/LICENSE
from __future__ import annotations

import copy
import json
from collections.abc import Iterable

import awkward as ak
from awkward._behavior import find_record_reducer
from awkward._layout import maybe_posaxis
from awkward._nplikes.numpy import Numpy
from awkward._nplikes.numpylike import IndexType, NumpyMetadata
from awkward._nplikes.shape import unknown_length
from awkward._parameters import (
    parameters_intersect,
    type_parameters_equal,
)
from awkward._regularize import is_integer
from awkward._slicing import NO_HEAD
from awkward._typing import TYPE_CHECKING, Final, Self, SupportsIndex, final
from awkward._util import unset
from awkward.contents.content import Content
from awkward.forms.recordform import RecordForm
from awkward.index import Index
from awkward.record import Record

if TYPE_CHECKING:
    from awkward._slicing import SliceItem

np = NumpyMetadata.instance()
numpy = Numpy.instance()


@final
class RecordArray(Content):
    """
    RecordArray represents an array of tuples or records, all with the
    same type. Its `contents` is an ordered list of arrays.

    * If `fields` is None, the data are tuples, indexed only by their order.
    * Otherwise, `fields` is an ordered list of names with the same length as
      the `contents`, associating a field name to every content.

    The length of the RecordArray, if not given, is the length of its shortest
    content; all are aligned element-by-element. If a RecordArray has zero contents,
    it may still represent a non-empty array. In that case, its length is specified
    by a `length` parameter.

    RecordArrays correspond to Apache Arrow's
    [struct type](https://arrow.apache.org/docs/format/Columnar.html#struct-layout).

    To illustrate how the constructor arguments are interpreted, the following is a
    simplified implementation of `__init__`, `__len__`, and `__getitem__`:

        class RecordArray(Content):
            def __init__(self, contents, fields, length):
                assert isinstance(contents, list)
                assert isinstance(length, int)
                for x in contents:
                    assert isinstance(x, Content)
                    assert len(x) >= length
                assert fields is None or isinstance(fields, list)
                if isinstance(fields, list):
                    assert len(fields) == len(contents)
                    for x in fields:
                        assert isinstance(x, str)
                self.contents = contents
                self.fields = fields
                self.length = length

            def __len__(self):
                return self.length

            def __getitem__(self, where):
                if isinstance(where, int):
                    if where < 0:
                        where += len(self)
                    assert 0 <= where < len(self)
                    record = [x[where] for x in self.contents]
                    if self.fields is None:
                        return tuple(record)
                    else:
                        return dict(zip(self.fields, record))

                elif isinstance(where, slice) and where.step is None:
                    if len(self.contents) == 0:
                        start = min(max(where.start, 0), self.length)
                        stop = min(max(where.stop, 0), self.length)
                        if stop < start:
                            stop = start
                        return RecordArray([], self.fields, stop - start)
                    else:
                        return RecordArray(
                            [x[where] for x in self.contents],
                            self.fields,
                            where.stop - where.start,
                        )

                elif isinstance(where, str):
                    if self.fields is None:
                        try:
                            i = int(where)
                        except ValueError:
                            pass
                        else:
                            if i < len(self.contents):
                                return self.contents[i][0 : len(self)]
                    else:
                        try:
                            i = self.fields.index(where)
                        except ValueError:
                            pass
                        else:
                            return self.contents[i][0 : len(self)]
                    raise ValueError("field " + repr(where) + " not found")

                else:
                    raise AssertionError(where)
    """

    is_record = True

    @property
    def is_leaf(self):
        return len(self._contents) == 0

    def __init__(
        self,
        contents: Iterable[Content],
        fields: Iterable[str] | None,
        length: int | type[unknown_length] | None = None,
        *,
        parameters=None,
        backend=None,
    ):
        if not (length is None or length is unknown_length):
            length = int(length)  # TODO: this should not happen!
        if not isinstance(contents, Iterable):
            raise ak._errors.wrap_error(
                TypeError(
                    "{} 'contents' must be iterable, not {}".format(
                        type(self).__name__, repr(contents)
                    )
                )
            )
        if not isinstance(contents, list):
            contents = list(contents)

        for content in contents:
            if not isinstance(content, Content):
                raise ak._errors.wrap_error(
                    TypeError(
                        "{} all 'contents' must be Content subclasses, not {}".format(
                            type(self).__name__, repr(content)
                        )
                    )
                )
            if backend is None:
                backend = content.backend
            elif backend is not content.backend:
                raise ak._errors.wrap_error(
                    TypeError(
                        "{} 'contents' must use the same array library (backend): {} vs {}".format(
                            type(self).__name__,
                            type(backend).__name__,
                            type(content.backend).__name__,
                        )
                    )
                )

        # If no content backend was found, then choose our own
        if backend is None:
            backend = ak._backends.NumpyBackend.instance()

        if length is None:
            if len(contents) == 0:
                raise ak._errors.wrap_error(
                    TypeError(
                        "{} if len(contents) == 0, a 'length' must be specified".format(
                            type(self).__name__
                        )
                    )
                )

            if backend.nplike.known_data:
                for content in contents:
                    assert content.length is not unknown_length
                    # First time we're setting length, and content.length is not unknown_length
                    if length is None:
                        length = content.length
                    # length is not unknown_length, content.length is not unknown_length
                    else:
                        length = min(length, content.length)
            else:
                for content in contents:
                    # First time we're setting length, and content.length is not unknown_length
                    if length is None:
                        length = content.length
                        # Any unknown_length means all unknown_length
                        if length is unknown_length:
                            break
                    # `length` is set, can't be unknown_length
                    elif content.length is unknown_length:
                        length = unknown_length
                        break
                    # `length` is set, can't be unknown_length
                    else:
                        length = min(length, content.length)
        elif length is not unknown_length:
            for content in contents:
                if content.length is not unknown_length and content.length < length:
                    raise ak._errors.wrap_error(
                        ValueError(
                            "{} len(content) ({}) must be >= length ({}) for all 'contents'".format(
                                type(self).__name__, content.length, length
                            )
                        )
                    )

            if not (is_integer(length) and length >= 0):
                raise ak._errors.wrap_error(
                    TypeError(
                        "{} 'length' must be a non-negative integer or None, not {}".format(
                            type(self).__name__, repr(length)
                        )
                    )
                )

        if isinstance(fields, Iterable):
            if not isinstance(fields, list):
                fields = list(fields)
            if not all(isinstance(x, str) for x in fields):
                raise ak._errors.wrap_error(
                    TypeError(
                        "{} 'fields' must all be strings, not {}".format(
                            type(self).__name__, repr(fields)
                        )
                    )
                )
            if not len(contents) == len(fields):
                raise ak._errors.wrap_error(
                    ValueError(
                        "{} len(contents) ({}) must be equal to len(fields) ({})".format(
                            type(self).__name__, len(contents), len(fields)
                        )
                    )
                )
        elif fields is not None:
            raise ak._errors.wrap_error(
                TypeError(
                    "{} 'fields' must be an iterable or None, not {}".format(
                        type(self).__name__, repr(fields)
                    )
                )
            )

        self._contents = contents
        self._fields = fields
        self._length = length
        self._init(parameters, backend)

    @property
    def contents(self):
        return self._contents

    @property
    def fields(self):
        if self._fields is None:
            return [str(i) for i in range(len(self._contents))]
        else:
            return self._fields

    form_cls: Final = RecordForm

    def copy(
        self,
        contents=unset,
        fields=unset,
        length=unset,
        *,
        parameters=unset,
        backend=unset,
    ):
        return RecordArray(
            self._contents if contents is unset else contents,
            self._fields if fields is unset else fields,
            self._length if length is unset else length,
            parameters=self._parameters if parameters is unset else parameters,
            backend=self._backend if backend is unset else backend,
        )

    def __copy__(self):
        return self.copy()

    def __deepcopy__(self, memo):
        return self.copy(
            contents=[copy.deepcopy(x, memo) for x in self._contents],
            fields=copy.deepcopy(self._fields, memo),
            parameters=copy.deepcopy(self._parameters, memo),
        )

    @classmethod
    def simplified(
        cls,
        contents,
        fields,
        length=None,
        *,
        parameters=None,
        backend=None,
    ):
        return cls(contents, fields, length, parameters=parameters, backend=backend)

    @property
    def is_tuple(self):
        return self._fields is None

    def to_tuple(self) -> Self:
        return RecordArray(
            self._contents, None, self._length, parameters=None, backend=self._backend
        )

    def _form_with_key(self, getkey):
        form_key = getkey(self)
        return self.form_cls(
            [x._form_with_key(getkey) for x in self._contents],
            self._fields,
            parameters=self._parameters,
            form_key=form_key,
        )

    def _to_buffers(self, form, getkey, container, backend, byteorder):
        assert isinstance(form, self.form_cls)
        if self._fields is None:
            for i, content in enumerate(self._contents):
                content._to_buffers(
                    form.content(i), getkey, container, backend, byteorder
                )
        else:
            for field, content in zip(self._fields, self._contents):
                content._to_buffers(
                    form.content(field), getkey, container, backend, byteorder
                )

    def _to_typetracer(self, forget_length: bool) -> Self:
        backend = ak._backends.TypeTracerBackend.instance()
        contents = [x._to_typetracer(forget_length) for x in self._contents]
        return RecordArray(
            contents,
            self._fields,
            unknown_length if forget_length else self._length,
            parameters=self._parameters,
            backend=backend,
        )

    def _touch_data(self, recursive):
        if recursive:
            for x in self._contents:
                x._touch_data(recursive)

    def _touch_shape(self, recursive):
        if recursive:
            for x in self._contents:
                x._touch_shape(recursive)

    @property
    def length(self):
        return self._length

    def __repr__(self):
        return self._repr("", "", "")

    def _repr(self, indent, pre, post):
        out = [indent, pre, "<RecordArray is_tuple="]
        out.append(repr(json.dumps(self.is_tuple)))
        out.append(" len=")
        out.append(repr(str(self.length)))
        out.append(">")
        out.extend(self._repr_extra(indent + "    "))
        out.append("\n")

        if self._fields is None:
            for i, x in enumerate(self._contents):
                out.append(f"{indent}    <content index={repr(str(i))}>\n")
                out.append(x._repr(indent + "        ", "", "\n"))
                out.append(indent + "    </content>\n")
        else:
            for i, x in enumerate(self._contents):
                out.append(
                    "{}    <content index={} field={}>\n".format(
                        indent, repr(str(i)), repr(self._fields[i])
                    )
                )
                out.append(x._repr(indent + "        ", "", "\n"))
                out.append(indent + "    </content>\n")

        out.append(indent + "</RecordArray>")
        out.append(post)
        return "".join(out)

    def index_to_field(self, index: SupportsIndex) -> str:
        return self.form_cls.index_to_field(self, index)

    def field_to_index(self, field: str) -> SupportsIndex:
        return self.form_cls.field_to_index(self, field)

    def has_field(self, field: str | SupportsIndex) -> bool:
        return self.form_cls.has_field(self, field)

    def content(self, index_or_field: str | SupportsIndex) -> Content:
        out = self.form_cls.content(self, index_or_field)
        if (
            self._length is unknown_length
            or out.length is unknown_length
            or out.length == self._length
        ):
            return out
        else:
            return out[: self._length]

    def maybe_content(self, index_or_field) -> Content:
        if self.has_field(index_or_field):
            return self.content(index_or_field)
        else:
            return ak.contents.IndexedOptionArray(
                ak.index.Index64(
                    self._backend.index_nplike.full(self.length, -1, dtype=np.int64)
                ),
                ak.contents.EmptyArray(),
            )

    def _getitem_nothing(self) -> Content:
        return self._getitem_range(0, 0)

    def _getitem_at(self, where: IndexType):
        if self._backend.nplike.known_data and where < 0:
            where += self.length

        if not (self._length is unknown_length or (0 <= where < self._length)):
            raise ak._errors.index_error(self, where)
        return Record(self, where)

    def _getitem_range(self, start: SupportsIndex, stop: IndexType) -> Content:
        if not self._backend.nplike.known_data:
            self._touch_shape(recursive=False)
            return self

        if self._length is unknown_length:
            return self

        start, stop, _, length = self._backend.index_nplike.derive_slice_for_length(
            slice(start, stop), self._length
        )

        if len(self._contents) == 0:
            return RecordArray(
                [],
                self._fields,
                length,
                parameters=self._parameters,
                backend=self._backend,
            )
        else:
            return RecordArray(
                [x._getitem_range(start, stop) for x in self._contents],
                self._fields,
                length,
                parameters=self._parameters,
                backend=self._backend,
            )

    def _getitem_field(
        self, where: str | SupportsIndex, only_fields: tuple[str, ...] = ()
    ) -> Content:
        if len(only_fields) == 0:
            return self.content(where)

        else:
            nexthead, nexttail = ak._slicing.head_tail(only_fields)
            if isinstance(nexthead, str):
                return self.content(where)._getitem_field(nexthead, nexttail)
            else:
                return self.content(where)._getitem_fields(nexthead, nexttail)

    def _getitem_fields(
        self, where: list[str | SupportsIndex], only_fields: tuple[str, ...] = ()
    ) -> Content:
        indexes = [self.field_to_index(field) for field in where]
        if self._fields is None:
            fields = None
        else:
            fields = [self._fields[i] for i in indexes]

        if len(only_fields) == 0:
            contents = [self.content(i) for i in indexes]
        else:
            nexthead, nexttail = ak._slicing.head_tail(only_fields)
            if isinstance(nexthead, str):
                contents = [
                    self.content(i)._getitem_field(nexthead, nexttail) for i in indexes
                ]
            else:
                contents = [
                    self.content(i)._getitem_fields(nexthead, nexttail) for i in indexes
                ]
        return RecordArray(
            contents, fields, self._length, parameters=None, backend=self._backend
        )

    def _carry(self, carry: Index, allow_lazy: bool) -> Content:
        assert isinstance(carry, ak.index.Index)

        if allow_lazy:
            where = carry.data

            if allow_lazy != "copied":
                where = where.copy()

            negative = where < 0
            if self._backend.index_nplike.known_data:
                if self._backend.index_nplike.any(negative):
                    where[negative] += self._length

                if self._backend.index_nplike.any(where >= self._length):
                    raise ak._errors.index_error(self, where)

            nextindex = ak.index.Index64(where, nplike=self._backend.index_nplike)
            return ak.contents.IndexedArray(nextindex, self, parameters=None)

        else:
            contents = [
                self.content(i)._carry(carry, allow_lazy)
                for i in range(len(self._contents))
            ]

            # if issubclass(carry.dtype.type, np.integer):
            #     length = carry.length
            # else:
            #     length = self.length
            assert issubclass(carry.dtype.type, np.integer)
            length = carry.length

            return RecordArray(
                contents,
                self._fields,
                length,
                parameters=self._parameters,
                backend=self._backend,
            )

    def _getitem_next_jagged(self, slicestarts, slicestops, slicecontent, tail):
        contents = []
        for i in range(len(self._contents)):
            contents.append(
                self.content(i)._getitem_next_jagged(
                    slicestarts, slicestops, slicecontent, tail
                )
            )
        return RecordArray(
            contents, self._fields, self._length, parameters=None, backend=self._backend
        )

    def _getitem_next(
        self,
        head: SliceItem | tuple,
        tail: tuple[SliceItem, ...],
        advanced: Index | None,
    ) -> Content:
        if head is NO_HEAD:
            return self

        elif isinstance(head, str):
            return self._getitem_next_field(head, tail, advanced)

        elif isinstance(head, list):
            return self._getitem_next_fields(head, tail, advanced)

        elif isinstance(head, ak.contents.IndexedOptionArray):
            return self._getitem_next_missing(head, tail, advanced)

        else:
            nexthead, nexttail = ak._slicing.head_tail(tail)

            contents = []
            for i in range(len(self._contents)):
                contents.append(self.content(i)._getitem_next(head, (), advanced))

            parameters = None
            if (
                isinstance(
                    head,
                    (
                        slice,
                        ak.contents.ListOffsetArray,
                        ak.contents.IndexedOptionArray,
                    ),
                )
                or head is Ellipsis
                or advanced is None
            ):
                parameters = self._parameters
            next = RecordArray(
                contents,
                self._fields,
                parameters=parameters,
                backend=self._backend,
            )
            return next._getitem_next(nexthead, nexttail, advanced)

    def _offsets_and_flattened(self, axis, depth):
        posaxis = maybe_posaxis(self, axis, depth)
        if posaxis is not None and posaxis + 1 == depth:
            raise ak._errors.wrap_error(np.AxisError("axis=0 not allowed for flatten"))

        elif posaxis is not None and posaxis + 1 == depth + 1:
            raise ak._errors.wrap_error(
                ValueError(
                    "arrays of records cannot be flattened (but their contents can be; try a different 'axis')"
                )
            )

        else:
            contents = []
            for content in self._contents:
                trimmed = content._getitem_range(0, self.length)
                offsets, flattened = trimmed._offsets_and_flattened(axis, depth)
                if self._backend.nplike.known_data and offsets.length != 0:
                    raise ak._errors.wrap_error(
                        AssertionError(
                            "RecordArray content with axis > depth + 1 returned a non-empty offsets from offsets_and_flattened"
                        )
                    )
                contents.append(flattened)
            offsets = ak.index.Index64.zeros(
                1,
                nplike=self._backend.index_nplike,
                dtype=np.int64,
            )
            return (
                offsets,
                RecordArray(
                    contents,
                    self._fields,
                    self._length,
                    parameters=None,
                    backend=self._backend,
                ),
            )

    def _mergeable_next(self, other, mergebool):
        # Is the other content is an identity, or a union?
        if other.is_identity_like or other.is_union:
            return True
        # Check against option contents
        elif other.is_option or other.is_indexed:
            return self._mergeable_next(other.content, mergebool)
        # Otherwise, do the parameters match? If not, we can't merge.
        elif not type_parameters_equal(self._parameters, other._parameters):
            return False
        elif isinstance(other, RecordArray):
            if self.is_tuple and other.is_tuple:
                if len(self._contents) == len(other._contents):
                    for self_cont, other_cont in zip(self._contents, other._contents):
                        if not self_cont._mergeable_next(other_cont, mergebool):
                            return False

                    return True

            elif not self.is_tuple and not other.is_tuple:
                if set(self._fields) != set(other._fields):
                    return False

                for i, field in enumerate(self._fields):
                    x = self._contents[i]
                    y = other._contents[other.field_to_index(field)]
                    if not x._mergeable_next(y, mergebool):
                        return False
                return True

            else:
                return False

        else:
            return False

    def _mergemany(self, others):
        if len(others) == 0:
            return self

        head, tail = self._merging_strategy(others)

        parameters = self._parameters
        headless = head[1:]

        for_each_field = []
        for field in self.contents:
            trimmed = field[0 : self.length]
            for_each_field.append([trimmed])

        if self.is_tuple:
            for array in headless:
                if isinstance(array, ak.contents.EmptyArray):
                    continue

                parameters = parameters_intersect(parameters, array._parameters)

                if isinstance(array, ak.contents.RecordArray):
                    if self.is_tuple:
                        if len(self.contents) == len(array.contents):
                            for i in range(len(self.contents)):
                                field = array[self.index_to_field(i)]
                                for_each_field[i].append(field[0 : array.length])
                        else:
                            raise ak._errors.wrap_error(
                                ValueError(
                                    "cannot merge tuples with different numbers of fields"
                                )
                            )
                    else:
                        raise ak._errors.wrap_error(
                            ValueError("cannot merge tuple with non-tuple record")
                        )
                else:
                    raise ak._errors.wrap_error(
                        AssertionError(
                            "cannot merge "
                            + type(self).__name__
                            + " with "
                            + type(array).__name__
                        )
                    )

        else:
            these_fields = self._fields.copy()
            these_fields.sort()

            for array in headless:
                parameters = parameters_intersect(parameters, array._parameters)

                if isinstance(array, ak.contents.RecordArray):
                    if not array.is_tuple:
                        those_fields = array._fields.copy()
                        those_fields.sort()

                        if these_fields == those_fields:
                            for i in range(len(self.contents)):
                                field = array[self.index_to_field(i)]

                                trimmed = field[0 : array.length]
                                for_each_field[i].append(trimmed)
                        else:
                            raise ak._errors.wrap_error(
                                AssertionError(
                                    "cannot merge records with different sets of field names"
                                )
                            )
                    else:
                        raise ak._errors.wrap_error(
                            AssertionError("cannot merge non-tuple record with tuple")
                        )

                elif isinstance(array, ak.contents.EmptyArray):
                    pass
                else:
                    raise ak._errors.wrap_error(
                        AssertionError(
                            "cannot merge "
                            + type(self).__name__
                            + " with "
                            + type(array).__name__
                        )
                    )

        nextcontents = []
        minlength = ak._util.unset
        for forfield in for_each_field:
            merged = forfield[0]._mergemany(forfield[1:])

            nextcontents.append(merged)

            if minlength is ak._util.unset or (
                not (merged.length is unknown_length or minlength is unknown_length)
                and merged.length < minlength
            ):
                minlength = merged.length

        if minlength is unknown_length:
            minlength = self.length
            for x in others:
                minlength += x.length

        next = RecordArray(
            nextcontents,
            self._fields,
            minlength,
            parameters=parameters,
            backend=self._backend,
        )

        if len(tail) == 0:
            return next

        reversed = tail[0]._reverse_merge(next)
        if len(tail) == 1:
            return reversed
        else:
            return reversed._mergemany(tail[1:])

    def _fill_none(self, value: Content) -> Content:
        contents = []
        for content in self._contents:
            contents.append(content._fill_none(value))
        return RecordArray(
            contents,
            self._fields,
            self._length,
            parameters=self._parameters,
            backend=self._backend,
        )

    def _local_index(self, axis, depth):
        posaxis = maybe_posaxis(self, axis, depth)
        if posaxis is not None and posaxis + 1 == depth:
            return self._local_index_axis0()
        else:
            contents = []
            for content in self._contents:
                contents.append(content._local_index(axis, depth))
            return RecordArray(
                contents,
                self._fields,
                self.length,
                parameters=self._parameters,
                backend=self._backend,
            )

    def _numbers_to_type(self, name, including_unknown):
        contents = []
        for x in self._contents:
            contents.append(x._numbers_to_type(name, including_unknown))
        return ak.contents.RecordArray(
            contents,
            self._fields,
            self._length,
            parameters=self._parameters,
            backend=self._backend,
        )

    def _is_unique(self, negaxis, starts, parents, outlength):
        for content in self._contents:
            if not content._is_unique(negaxis, starts, parents, outlength):
                return False
        return True

    def _unique(self, negaxis, starts, parents, outlength):
        raise ak._errors.wrap_error(NotImplementedError)

    def _argsort_next(
        self, negaxis, starts, shifts, parents, outlength, ascending, stable
    ):
        raise ak._errors.wrap_error(NotImplementedError)

    def _sort_next(self, negaxis, starts, parents, outlength, ascending, stable):
        if self._fields is None or len(self._fields) == 0:
            return ak.contents.NumpyArray(
                self._backend.nplike.instance().empty(0, dtype=np.int64),
                parameters=None,
                backend=self._backend,
            )

        contents = []
        for content in self._contents:
            contents.append(
                content._sort_next(
                    negaxis, starts, parents, outlength, ascending, stable
                )
            )
        return RecordArray(
            contents,
            self._fields,
            self._length,
            parameters=self._parameters,
            backend=self._backend,
        )

    def _combinations(self, n, replacement, recordlookup, parameters, axis, depth):
        posaxis = maybe_posaxis(self, axis, depth)
        if posaxis is not None and posaxis + 1 == depth:
            return self._combinations_axis0(n, replacement, recordlookup, parameters)
        else:
            contents = []
            for content in self._contents:
                contents.append(
                    content._combinations(
                        n, replacement, recordlookup, parameters, axis, depth
                    )
                )
            return ak.contents.RecordArray(
                contents,
                recordlookup,
                self.length,
                parameters=self._parameters,
                backend=self._backend,
            )

    def _reduce_next(
        self,
        reducer,
        negaxis,
        starts,
        shifts,
        parents,
        outlength,
        mask,
        keepdims,
        behavior,
    ):
        reducer_recordclass = find_record_reducer(reducer, self, behavior)
        if reducer_recordclass is None:
            raise ak._errors.wrap_error(
                TypeError(
                    "no ak.{} overloads for custom types: {}".format(
                        reducer.name, ", ".join(self._fields)
                    )
                )
            )
        else:
            raise ak._errors.wrap_error(
                NotImplementedError(
                    "overloading reducers for RecordArrays has not been implemented yet"
                )
            )

    def _validity_error(self, path):
        for i, cont in enumerate(self.contents):
            if cont.length < self.length:
                return f"at {path} ({type(self)!r}): len(field({i})) < len(recordarray)"
        for i, cont in enumerate(self.contents):
            sub = cont._validity_error(f"{path}.field({i})")
            if sub != "":
                return sub
        return ""

    def _nbytes_part(self):
        result = 0
        for content in self.contents:
            result = result + content._nbytes_part()
        return result

    def _pad_none(self, target, axis, depth, clip):
        posaxis = maybe_posaxis(self, axis, depth)
        if posaxis is not None and posaxis + 1 == depth:
            return self._pad_none_axis0(target, clip)
        else:
            contents = []
            for content in self._contents:
                contents.append(content._pad_none(target, axis, depth, clip))
            if len(contents) == 0:
                return ak.contents.RecordArray(
                    contents,
                    self._fields,
                    self._length,
                    parameters=self._parameters,
                    backend=self._backend,
                )
            else:
                return ak.contents.RecordArray(
                    contents,
                    self._fields,
                    self._length,
                    parameters=self._parameters,
                    backend=self._backend,
                )

    def _to_arrow(self, pyarrow, mask_node, validbytes, length, options):
        values = [
            (x if x.length == length else x[:length])._to_arrow(
                pyarrow, mask_node, validbytes, length, options
            )
            for x in self._contents
        ]

        types = pyarrow.struct(
            [
                pyarrow.field(self.index_to_field(i), values[i].type).with_nullable(
                    x.is_option
                )
                for i, x in enumerate(self._contents)
            ]
        )

        return pyarrow.Array.from_buffers(
            ak._connect.pyarrow.to_awkwardarrow_type(
                types,
                options["extensionarray"],
                options["record_is_scalar"],
                mask_node,
                self,
            ),
            length,
            [ak._connect.pyarrow.to_validbits(validbytes)],
            children=values,
        )

    def _to_backend_array(self, allow_missing, backend):
        if self.fields is None:
            return backend.nplike.empty(self.length, dtype=[])
        contents = [x._to_backend_array(allow_missing, backend) for x in self._contents]
        if any(len(x.shape) != 1 for x in contents):
            raise ak._errors.wrap_error(
                ValueError(f"cannot convert {self} into np.ndarray")
            )
        out = backend.nplike.empty(
            self.length,
            dtype=[(str(n), x.dtype) for n, x in zip(self.fields, contents)],
        )
        mask = None
        for n, x in zip(self.fields, contents):
            if allow_missing and isinstance(x, self._backend.nplike.ma.MaskedArray):
                if mask is None:
                    mask = backend.index_nplike.ma.zeros(
                        self.length, [(n, np.bool_) for n in self.fields]
                    )
                if x.mask is not None:
                    mask[n] |= x.mask
            out[n] = x

        if mask is not None:
            out = backend.nplike.ma.MaskedArray(out, mask)

        return out

    def _remove_structure(self, backend, options):
        if options["flatten_records"]:
            out = []
            for content in self._contents:
                out.extend(content[: self._length]._remove_structure(backend, options))
            return out
        else:
            in_function = ""
            if options["function_name"] is not None:
                in_function = " in " + options["function_name"]
            raise ak._errors.wrap_error(
                TypeError(
                    (
                        "encountered a record whilst removing array structure{}, "
                        "but this operation does not support erasing records. "
                        "Try first calling `ak.ravel` or `ak.flatten(..., axis=None)."
                    ).format(in_function)
                )
            )

    def _recursively_apply(
        self, action, behavior, depth, depth_context, lateral_context, options
    ):
        if self._backend.nplike.known_data:
            contents = [x[: self._length] for x in self._contents]
        else:
            self._touch_data(recursive=False)
            contents = self._contents

        if options["return_array"]:

            def continuation():
                if not options["allow_records"]:
                    raise ak._errors.wrap_error(
                        ValueError(
                            f"cannot broadcast records in {options['function_name']}"
                        )
                    )
                return RecordArray(
                    [
                        content._recursively_apply(
                            action,
                            behavior,
                            depth,
                            copy.copy(depth_context),
                            lateral_context,
                            options,
                        )
                        for content in contents
                    ],
                    self._fields,
                    self._length,
                    parameters=self._parameters if options["keep_parameters"] else None,
                    backend=self._backend,
                )

        else:

            def continuation():
                for content in contents:
                    content._recursively_apply(
                        action,
                        behavior,
                        depth,
                        copy.copy(depth_context),
                        lateral_context,
                        options,
                    )

        result = action(
            self,
            depth=depth,
            depth_context=depth_context,
            lateral_context=lateral_context,
            continuation=continuation,
            behavior=behavior,
            backend=self._backend,
            options=options,
        )

        if isinstance(result, Content):
            return result
        elif result is None:
            return continuation()
        else:
            raise ak._errors.wrap_error(AssertionError(result))

    def to_packed(self) -> Self:
        return RecordArray(
            [
                x.to_packed()
                if x.length == self._length
                else x[: self._length].to_packed()
                for x in self._contents
            ],
            self._fields,
            self._length,
            parameters=self._parameters,
            backend=self._backend,
        )

    def _to_list(self, behavior, json_conversions):
        if not self._backend.nplike.known_data:
            raise ak._errors.wrap_error(
                TypeError("cannot convert typetracer arrays to Python lists")
            )

        out = self._to_list_custom(behavior, json_conversions)
        if out is not None:
            return out

        if self.is_tuple and json_conversions is None:
            contents = [x._to_list(behavior, json_conversions) for x in self._contents]
            out = [None] * self._length
            for i in range(self._length):
                out[i] = tuple(x[i] for x in contents)
            return out

        else:
            fields = self._fields
            if fields is None:
                fields = [str(i) for i in range(len(self._contents))]
            contents = [x._to_list(behavior, json_conversions) for x in self._contents]
            out = [None] * self._length
            for i in range(self._length):
                out[i] = dict(zip(fields, [x[i] for x in contents]))
            return out

    def _to_backend(self, backend: ak._backends.Backend) -> Self:
        contents = [content.to_backend(backend) for content in self._contents]
        return RecordArray(
            contents,
            self._fields,
            length=self._length,
            parameters=self._parameters,
            backend=backend,
        )

    def _is_equal_to(self, other, index_dtype, numpyarray):
        return (
            self.fields == other.fields
            and len(self.contents) == len(other.contents)
            and all(
                self.contents[i].is_equal_to(other.contents[i], index_dtype, numpyarray)
                for i in range(len(self.contents))
            )
        )

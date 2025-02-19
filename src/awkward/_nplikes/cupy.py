# BSD 3-Clause License; see https://github.com/scikit-hep/awkward-1.0/blob/main/LICENSE
from __future__ import annotations

import numpy

import awkward as ak
from awkward._nplikes.array_module import ArrayModuleNumpyLike
from awkward._nplikes.numpylike import ArrayLike
from awkward._typing import Final


class Cupy(ArrayModuleNumpyLike):
    is_eager: Final = False

    def __init__(self):
        import awkward._connect.cuda  # noqa: F401

        self._module = ak._connect.cuda.import_cupy("Awkward Arrays with CUDA")

    @property
    def ma(self):
        raise ak._errors.wrap_error(
            ValueError(
                "CUDA arrays cannot have missing values until CuPy implements "
                "numpy.ma.MaskedArray"
            )
        )

    @property
    def char(self):
        raise ak._errors.wrap_error(
            ValueError(
                "CUDA arrays cannot do string manipulations until CuPy implements "
                "numpy.char"
            )
        )

    @property
    def ndarray(self):
        return self._module.ndarray

    def frombuffer(
        self, buffer, *, dtype: numpy.dtype | None = None, count: int = -1
    ) -> ArrayLike:
        np_array = numpy.frombuffer(buffer, dtype=dtype, count=count)
        return self._module.asarray(np_array)

    def array_equal(self, x1: ArrayLike, x2: ArrayLike, *, equal_nan: bool = False):
        if x1.shape != x2.shape:
            return False
        else:
            return self._module.all(x1 - x2 == 0)

    def repeat(
        self, x: ArrayLike, repeats: ArrayLike | int, *, axis: int | None = None
    ):
        if axis is not None:
            raise ak._errors.wrap_error(
                NotImplementedError(f"repeat for CuPy with axis={axis!r}")
            )
        # https://github.com/cupy/cupy/issues/3849
        if isinstance(repeats, self._module.ndarray):
            all_stops = self._module.cumsum(repeats)
            parents = self._module.zeros(all_stops[-1].item(), dtype=int)
            stops, stop_counts = self._module.unique(all_stops[:-1], return_counts=True)
            parents[stops] = stop_counts
            self._module.cumsum(parents, out=parents)
            return x[parents]
        else:
            return self._module.repeat(x, repeats=repeats)

    # For all reducers: https://github.com/cupy/cupy/issues/3819

    def all(
        self,
        x: ArrayLike,
        *,
        axis: int | tuple[int, ...] | None = None,
        keepdims: bool = False,
        maybe_out: ArrayLike | None = None,
    ) -> ArrayLike:
        out = self._module.all(x, axis=axis, out=maybe_out)
        if axis is None and isinstance(out, self._module.ndarray):
            return out.item()
        else:
            return out

    def any(
        self,
        x: ArrayLike,
        *,
        axis: int | tuple[int, ...] | None = None,
        keepdims: bool = False,
        maybe_out: ArrayLike | None = None,
    ) -> ArrayLike:
        out = self._module.any(x, axis=axis, out=maybe_out)
        if axis is None and isinstance(out, self._module.ndarray):
            return out.item()
        else:
            return out

    def count_nonzero(
        self,
        x: ArrayLike,
        *,
        axis: int | tuple[int, ...] | None = None,
        keepdims: bool = False,
    ) -> ArrayLike:
        out = self._module.count_nonzero(x, axis=axis)
        if axis is None and isinstance(out, self._module.ndarray):
            return out.item()
        else:
            return out

    def min(
        self,
        x: ArrayLike,
        *,
        axis: int | tuple[int, ...] | None = None,
        keepdims: bool = False,
        maybe_out: ArrayLike | None = None,
    ) -> ArrayLike:
        out = self._module.min(x, axis=axis, out=maybe_out)
        if axis is None and isinstance(out, self._module.ndarray):
            return out.item()
        else:
            return out

    def max(
        self,
        x: ArrayLike,
        *,
        axis: int | tuple[int, ...] | None = None,
        keepdims: bool = False,
        maybe_out: ArrayLike | None = None,
    ) -> ArrayLike:
        out = self._module.max(x, axis=axis, out=maybe_out)
        if axis is None and isinstance(out, self._module.ndarray):
            return out.item()
        else:
            return out

    def array_str(
        self, array, max_line_width=None, precision=None, suppress_small=None
    ):
        return self._module.array_str(array, max_line_width, precision, suppress_small)

    @classmethod
    def is_own_array(cls, obj) -> bool:
        """
        Args:
            obj: object to test

        Return `True` if the given object is a cupy buffer, otherwise `False`.

        """
        module, _, suffix = type(obj).__module__.partition(".")
        return module == "cupy"

    def is_c_contiguous(self, x: ArrayLike) -> bool:
        return x.flags["C_CONTIGUOUS"]

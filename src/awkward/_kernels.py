# BSD 3-Clause License; see https://github.com/scikit-hep/awkward-1.0/blob/main/LICENSE
from __future__ import annotations

import ctypes
from abc import abstractmethod
from typing import Any, Callable

import awkward as ak
from awkward._nplikes.jax import Jax
from awkward._nplikes.numpy import Numpy
from awkward._nplikes.numpylike import NumpyMetadata
from awkward._typing import Protocol, TypeAlias

KernelKeyType: TypeAlias = tuple  # Tuple[str, Unpack[Tuple[metadata.dtype, ...]]]


metadata = NumpyMetadata.instance()


class KernelError(Protocol):
    filename: str | None  # pylint: disable=E0602
    str: str | None
    pass_through: bool
    attempt: int
    id: int


class Kernel(Protocol):
    @property
    @abstractmethod
    def key(self) -> KernelKeyType:
        ...

    @abstractmethod
    def __call__(self, *args) -> KernelError | None:
        raise ak._errors.wrap_error(NotImplementedError)


class BaseKernel(Kernel):
    _impl: Callable[..., Any]
    _key: KernelKeyType

    def __init__(self, impl: Callable[..., Any], key: KernelKeyType):
        self._impl = impl
        self._key = key

    @property
    def key(self) -> KernelKeyType:
        return self._key

    def __repr__(self):
        return "<{} {}{}>".format(
            type(self).__name__,
            self.key[0],
            "".join(", " + str(metadata.dtype(x)) for x in self.key[1:]),
        )


class CTypesFunc(Protocol):
    argtypes: tuple[Any, ...]

    def __call__(self, *args) -> Any:
        ...


class NumpyKernel(BaseKernel):
    @classmethod
    def _cast(cls, x, t):
        if issubclass(t, ctypes._Pointer):
            # Do we have a NumPy-owned array?
            if Numpy.is_own_array(x):
                if x.ndim > 0:
                    return ctypes.cast(x.ctypes.data, t)
                else:
                    return x
            # Or, do we have a ctypes type
            elif hasattr(x, "_b_base_"):
                return ctypes.cast(x, t)
            else:
                raise ak._errors.wrap_error(
                    AssertionError("CuPy buffers shouldn't be passed to Numpy Kernels.")
                )
        else:
            return x

    def __call__(self, *args) -> None:
        assert len(args) == len(self._impl.argtypes)

        return self._impl(
            *(self._cast(x, t) for x, t in zip(args, self._impl.argtypes))
        )


class JaxKernel(NumpyKernel):
    def __call__(self, *args) -> None:
        assert len(args) == len(self._impl.argtypes)

        if not any(Jax.is_tracer(arg) for arg in args):
            return super().__call__(*args)


class CupyKernel(BaseKernel):
    def max_length(self, args):
        import awkward._connect.cuda as ak_cuda

        cupy = ak_cuda.import_cupy("Awkward Arrays with CUDA")
        max_length = metadata.iinfo(metadata.int64).min
        # TODO should kernels strip nplike wrapper? Probably
        for array in args:
            if isinstance(array, cupy.ndarray):
                max_length = max(max_length, len(array))
        return max_length

    def calc_grid(self, length):
        if length > 1024:
            return -(length // -1024), 1, 1
        return 1, 1, 1

    def calc_blocks(self, length):
        if length > 1024:
            return 1024, 1, 1
        return length, 1, 1

    def __call__(self, *args) -> None:
        import awkward._connect.cuda as ak_cuda

        cupy = ak_cuda.import_cupy("Awkward Arrays with CUDA")
        maxlength = self.max_length(args)
        grid, blocks = self.calc_grid(maxlength), self.calc_blocks(maxlength)
        cupy_stream_ptr = cupy.cuda.get_current_stream().ptr

        if cupy_stream_ptr not in ak_cuda.cuda_streamptr_to_contexts:
            ak_cuda.cuda_streamptr_to_contexts[cupy_stream_ptr] = (
                cupy.array(ak_cuda.NO_ERROR),
                [],
            )

        assert len(args) == len(self._impl.dir)
        # The first arg is the invocation index which raises itself by 8 in the kernel if there was no error before.
        # The second arg is the error_code.
        args = (
            *args,
            len(ak_cuda.cuda_streamptr_to_contexts[cupy_stream_ptr][1]),
            ak_cuda.cuda_streamptr_to_contexts[cupy_stream_ptr][0],
        )
        ak_cuda.cuda_streamptr_to_contexts[cupy_stream_ptr][1].append(
            ak_cuda.Invocation(
                name=self.key[0],
                error_context=ak._errors.ErrorContext.primary(),
            )
        )

        self._impl(grid, blocks, args)


class TypeTracerKernelError(KernelError):
    def __init__(self):
        self.str = None
        self.filename = None
        self.pass_through = False
        self.attempt = ak._util.kSliceNone
        self.id = ak._util.kSliceNone


class TypeTracerKernel:
    def __init__(self, index):
        self._name_and_types = index

    def __call__(self, *args) -> TypeTracerKernelError:
        return TypeTracerKernelError()

    def __repr__(self):
        return "<{} {}{}>".format(
            type(self).__name__,
            self._name_and_types[0],
            "".join(", " + str(metadata.dtype(x)) for x in self._name_and_types[1:]),
        )

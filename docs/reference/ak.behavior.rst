ak.behavior
-----------

.. py:data:: ak.behavior

* `Motivation <#motivation>`__
* `Parameters and behaviors <#parameters-and-behaviors>`__
* `Adding behavior to records <#adding-behavior-to-records>`__
* `Overriding NumPy ufuncs and binary operators <#overriding-numpy-ufuncs-and-binary-operators>`__
* `Mixin decorators <#mixin-decorators>`__
* `Adding behavior to arrays <#adding-behavior-to-arrays>`__
* `Custom type names <#custom-type-names>`__
* `Custom broadcasting <#custom-broadcasting>`__
* `Overriding behavior in Numba <#overriding-behavior-in-numba>`__
* `Complete example <#complete-example>`__

Motivation
==========

A data structure is defined both in terms of the information it encodes and
in how it can be used. For example, a hash-table is not just a buffer, it's
also the "get" and "set" operations that make the buffer usable as a key-value
store. Awkward Arrays have a suite of operations for transforming tree
structures into new tree structures, but an application of these structures to
a data analysis problem should be able to interpret them as objects in the
analysis domain, such as latitude-longitude coordinates in geographical
studies or Lorentz vectors in particle physics.

Object-oriented programming unites data with its operations. This is a
conceptual improvement for data analysts because functions like "distance
between this latitude-longitude point and another on a spherical globe" can
be bound to the objects that represent latitude-longitude points. It
matches the way that data analysts usually think about their data.

However, if these methods are saved in the data, or are written in a way
that will only work for one version of the data structures, then it becomes
difficult to work with large datasets. Old data that do not "fit" the new
methods would have to be converted, or the analysis would have to be broken
into different cases for each data generation. This problem is known as
schema evolution, and there are many solutions to it.

The approach taken by the Awkward Array library is to encode very little
interpretation into the data themselves and apply an interpretation as
late as possible. Thus, a latitude-longitude record might be stamped with
the name ``"latlon"``, but the operations on it are added immediately before
the user wants them. These operations can be written in such a way that
they only require the ``"latlon"`` to have ``lat`` and ``lon`` fields, so
different versions of the data can have additional fields or even be
embedded in different structures.

Parameters and behaviors
========================

In Awkward Array, metadata are embedded in data using an array node's
**parameters**, and parameter-dependent operations can be defined using
**behavior**. A global mapping from parameters to behavior is in a dict called
:data:`.behavior`:

.. code-block:: python

    >>> import awkward as ak
    >>> ak.behavior

but behavior dicts can also be loaded into :class:`ak.Array`,
:class:`ak.Record`, and :class:`ak.ArrayBuilder` objects as a
constructor argument. See
:attr:`ak.Array.behavior`.

The general flow is

* **parameters** link data objects to names;
* **behavior** links names to code.

In large datasets, parameters may be hard to change (permanently, at least:
on-the-fly parameter changes are easier), but behavior is easy to change
(it is always assigned on-the-fly).

In the following example, we create two nested arrays of records with fields
``"x"`` and ``"y"`` and the records are named ``"point"``.

.. code-block:: python

    one = ak.Array([[{"x": 1, "y": 1.1}, {"x": 2, "y": 2.2}, {"x": 3, "y": 3.3}],
                    [],
                    [{"x": 4, "y": 4.4}, {"x": 5, "y": 5.5}],
                    [{"x": 6, "y": 6.6}],
                    [{"x": 7, "y": 7.7}, {"x": 8, "y": 8.8}, {"x": 9, "y": 9.9}]],
                   with_name="point")
    two = ak.Array([[{"x": 0.9, "y": 1}, {"x": 2, "y": 2.2}, {"x": 2.9, "y": 3}],
                    [],
                    [{"x": 3.9, "y": 4}, {"x": 5, "y": 5.5}],
                    [{"x": 5.9, "y": 6}],
                    [{"x": 6.9, "y": 7}, {"x": 8, "y": 8.8}, {"x": 8.9, "y": 9}]],
                   with_name="point")

The name appears in the way the type is presented as a string (a departure from
`Datashape notation <https://datashape.readthedocs.io/>`__):

.. code-block:: python

    >>> ak.type(one)
    5 * var * point["x": int64, "y": float64]

and it may be accessed as the ``"__record__"`` property, through the
:attr:`ak.Array.layout`:

.. code-block:: python

    >>> one.layout
    <ListOffsetArray64>
        <offsets><Index64 i="[0 3 3 5 6 9]" offset="0" length="6"/></offsets>
        <content><RecordArray>
            <parameters>
                <param key="__record__">"point"</param>
            </parameters>
            <field index="0" key="x">
                <NumpyArray format="l" shape="9" data="1 2 3 4 5 6 7 8 9"/>
            </field>
            <field index="1" key="y">
                <NumpyArray format="d" shape="9" data="1.1 2.2 3.3 4.4 5.5 6.6 7.7 8.8 9.9"/>
            </field>
        </RecordArray></content>
    </ListOffsetArray64>
    >>> one.layout.content.parameters
    {'__record__': 'point'}

We have to dig into the layout's content because the ``"__record__"`` parameter
is set on the :class:`ak.contents.RecordArray`, which is buried inside of a
:class:`ak.contents.ListOffsetArray`.

Alternatively, we can navigate to a single :class:`ak.Record` first:

.. code-block:: python

    >>> one[0, 0]
    <Record {x: 1, y: 1.1} type='point["x": int64, "y": float64]'>
    >>> one[0, 0].layout.parameters
    {'__record__': 'point'}

Adding behavior to records
==========================

Suppose we want the points in the above example to be able to calculate
distances to other points. We can do this by creating a subclass of
:class:`ak.Record` that has the new methods and associating it with
the ``"__record__"`` name.

.. code-block:: python

    class Point(ak.Record):
        def distance(self, other):
            return np.sqrt((self.x - other.x)**2 + (self.y - other.y)**2)

    ak.behavior["point"] = Point

Now ``one[0, 0]`` is instantiated as a ``Point``, rather than a :class:`ak.Record`,

.. code-block:: python

    >>> one[0, 0]
    <Point {x: 1, y: 1.1} type='point["x": int64, "y": float64]'>

and it has the ``distance`` method.

.. code-block:: python

    >>> for xs, ys in zip(one, two):
    ...     for x, y in zip(xs, ys):
    ...         print(x.distance(y))
    0.14142135623730953
    0.0
    0.31622776601683783
    0.4123105625617664
    0.0
    0.6082762530298216
    0.7071067811865477
    0.0
    0.905538513813742

Looping over data in Python is inconvenient and slow; we want to compute
quantities like this with array-at-a-time methods, but ``distance`` is
bound to a :class:`ak.Record`, not an :class:`ak.Array` of records.

.. code-block:: python

    >>> one.distance(two)
    AttributeError: no field named 'distance'

To add ``distance`` as a method on arrays of points, create a subclass of
:class:`ak.Array` and attach that as ``ak.behavior[".", "point"]`` for
"array of points."

.. code-block:: python

    class PointArray(ak.Array):
        def distance(self, other):
            return np.sqrt((self.x - other.x)**2 + (self.y - other.y)**2)

    ak.behavior[".", "point"] = PointArray

Now ``one[0]`` is a ``PointArray`` and can compute ``distance`` on arrays at a
time. Thanks to NumPy's
`universal function <https://docs.scipy.org/doc/numpy/reference/ufuncs.html>`__
(ufunc) syntax, the expression is the same (and could perhaps be implemented
once and used by both ``Point`` and ``PointArray``).

.. code-block:: python

    >>> one[0]
    <PointArray [{x: 1, y: 1.1}, ... {x: 3, y: 3.3}] type='3 * point["x": int64, "y"...'>
    >>> one[0].distance(two[0])
    <Array [0.141, 0, 0.316] type='3 * float64'>

But ``one`` itself is an ``Array`` of ``PointArrays``, and does not apply.

.. code-block:: python

    >>> one
    <Array [[{x: 1, y: 1.1}, ... x: 9, y: 9.9}]] type='5 * var * point["x": int64, "...'>
    >>> one.distance(two)
    AttributeError: no field named 'distance'

We can make the assignment work at all levels of list-depth by using a ``"*"``
instead of a ``"."``.

.. code-block:: python

    ak.behavior["*", "point"] = PointArray

One last caveat: our ``one`` array was created *before* this behavior was
assigned, so it needs to be recreated to be a member of the new class. The
normal :class:`ak.Array` constructor is sufficient for this. This is only
an issue if you're working interactively (but something to think about when
debugging!).

.. code-block:: python

    >>> one = ak.Array(one)
    >>> two = ak.Array(two)

Now it works, and again we're taking advantage of the fact that the expression
for ``distance`` based on ufuncs works equally well on Awkward Arrays.

.. code-block:: python

    >>> one
    <PointArray [[{x: 1, y: 1.1}, ... x: 9, y: 9.9}]] type='5 * var * point["x": int...'>
    >>> one.distance(two)
    <Array [[0.141, 0, 0.316, ... 0.707, 0, 0.906]] type='5 * var * float64'>

**In most cases, you want to apply array-of-records for all levels of list-depth:** use ``ak.behavior["*", record_name]``.

Overriding NumPy ufuncs and binary operators
============================================

The :class:`ak.Array` class overrides Python's binary operators with the
equivalent ufuncs, so ``__eq__`` actually calls :data:`numpy.equal`, for instance.
This is also true of other basic functions, like ``__abs__`` for overriding
:func:`abs` with :data:`numpy.absolute`. Each ufunc is then passed down to the leaves
(deepest sub-elements) of an Awkward data structure.

For example,

.. code-block:: python

    >>> ak.Array([[1, 2, 3], [], [4]]) == ak.Array([[3, 2, 1], [], [4]])
    <Array [[False, True, False], [], [True]] type='3 * var * bool'>


However, this does not apply to records or named types until they are explicitly
overridden:

.. code-block:: python

    >>> one == two
    Traceback (most recent call last):
      File "<stdin>", line 1, in <module>
    ...
    ValueError: no overloads for custom types: equal(point, point)

We might want to take an object-oriented view in which the ``==`` operation
applies to points, regardless of how deeply they are nested. If we try to do
it by adding ``__eq__`` as a method on ``PointArray``, it would work if the
``PointArray`` is the top of the data structure, but not if it's nested within
another structure.

Instead, we should override :data:`numpy.equal` itself. Custom ufunc overrides are
checked at every step in broadcasting, so the override would be applied if
point objects are discovered at any level.

.. code-block:: python

    def point_equal(left, right):
        return np.logical_and(left.x == right.x, left.y == right.y)

    ak.behavior[np.equal, "point", "point"] = point_equal

The above should be read as "override :data`np.equal` for cases in which both
arguments are ``"point"``."

.. code-block:: python

    >>> ak.to_list(one == two)
    [[False, True, False], [], [False, True], [False], [False, True, False]]

Similarly for overriding :func:`abs`

.. code-block:: python

    >>> def point_abs(point):
    ...     return np.sqrt(point.x**2 + point.y**2)
    ... 
    >>> ak.behavior[np.absolute, "point"] = point_abs
    >>> ak.to_list(abs(one))
    [[1.4866068747318506, 2.973213749463701, 4.459820624195552],
     [],
     [5.946427498927402, 7.433034373659253],
     [8.919641248391104],
     [10.406248123122953, 11.892854997854805, 13.379461872586655]]

and all other ufuncs.

If you need a placeholder for "any number," use :class:`numbers.Real`,
:class:`numbers.Integral`, etc. Non-arrays are resolved by type; builtin Python
numbers and NumPy numbers are subclasses of the generic number types in the
:mod:`numbers` library.

Also, for commutative operations, be sure to override both operator orders.
(Function signatures are matched to :data:`ak.behavior` using multiple dispatch.)

.. code-block:: python

    >>> import numbers
    >>> def point_lmult(point, scalar):
    ...     return ak.Array({"x": point.x * scalar, "y": point.y * scalar})
    ... 
    >>> def point_rmult(scalar, point):
    ...     return point_lmult(point, scalar)
    ... 
    >>> ak.behavior[np.multiply, "point", numbers.Real] = point_lmult
    >>> ak.behavior[np.multiply, numbers.Real, "point"] = point_rmult
    >>> ak.to_list(one * 10)
    [[{'x': 10, 'y': 11.0}, {'x': 20, 'y': 22.0}, {'x': 30, 'y': 33.0}],
     [],
     [{'x': 40, 'y': 44.0}, {'x': 50, 'y': 55.0}],
     [{'x': 60, 'y': 66.0}],
     [{'x': 70, 'y': 77.0}, {'x': 80, 'y': 88.0}, {'x': 90, 'y': 99.0}]]

If you need to override ufuncs in more generality, you can use the
:class:`numpy.ufunc` interface:

.. code-block:: python

    >>> def apply_ufunc(ufunc, method, args, kwargs):
    ...     if ufunc in (np.sin, np.cos, np.tan):
    ...         x = ufunc(args[0].x)
    ...         y = ufunc(args[0].y)
    ...         return ak.Array({"x": x, "y": y})
    ...     else:
    ...         return NotImplemented
    ... 
    >>> ak.behavior[np.ufunc, "point"] = apply_ufunc
    >>> ak.to_list(np.sin(one))
    [[{'x': 0.8414709848078965, 'y': 0.8912073600614354},
      {'x': 0.9092974268256817, 'y': 0.8084964038195901},
      {'x': 0.1411200080598672, 'y': -0.1577456941432482}],
     [],
     [{'x': -0.7568024953079282, 'y': -0.951602073889516},
      {'x': -0.9589242746631385, 'y': -0.7055403255703919}],
     [{'x': -0.27941549819892586, 'y': 0.31154136351337786}],
     [{'x': 0.6569865987187891, 'y': 0.9881682338770004},
      {'x': 0.9893582466233818, 'y': 0.5849171928917617},
      {'x': 0.4121184852417566, 'y': -0.45753589377532133}]]
    >>> np.sqrt(one)
    Traceback (most recent call last):
      File "<stdin>", line 1, in <module>
    ...
    ValueError: no overloads for custom types: sqrt(point)

But be forewarned: the ``ak.behavior[np.ufunc, name]`` syntax will match
*any* ufunc that has an array containing an array with type ``name``
*anywhere* in the argument list. The first array in the argument list
with type ``name`` will be matched instead of more detailed argument lists
with type ``name`` at a later spot in the list. The "apply_ufunc" interface
is *greedy*.

Mixin decorators
================
The pattern of adding additional properties and function overrides to records
and arrays of records is quite common, and can be nicely described by the "mixin"
idiom: a class with no constructor that is mixed with both the :class:`ak.Array` and :class:`ak.Record`
class as to create new derived classes. The :func:`ak.mixin_class` and :func:`ak.mixin_class_method`
python decorators assist with some of this boilerplate. Consider the ``Point`` class
from above; we can implement all the functionality so far described as follows:

.. code-block:: python

    @ak.mixin_class(ak.behavior)
    class Point:
        def distance(self, other):
            return np.sqrt((self.x - other.x) ** 2 + (self.y - other.y) ** 2)

        @ak.mixin_class_method(np.equal, {"Point"})
        def point_equal(self, other):
            return np.logical_and(self.x == other.x, self.y == other.y)

        @ak.mixin_class_method(np.abs)
        def point_abs(self):
            return np.sqrt(self.x ** 2 + self.y ** 2)

The behavior name is taken as the mixin class name, e.g. here it is ``Point`` (as opposed
to lowercase ``point`` previously). We can extend our implementation to allow ``Point`` types
to be added by overriding the ``np.add`` ufunc (appending to our class definition):

.. code-block:: python

    class Point:
        # ...

        @ak.mixin_class_method(np.add, {"Point"})
        def point_add(self, other):
            return ak.zip(
                {"x": self.x + other.x, "y": self.y + other.y}, with_name="Point",
            )

The real power of using mixin classes comes from the ability to inherit behaviors.
Consider a ``Point``-like record that also has a ``weight`` field. Suppose that we want
these ``WeightedPoint`` types to have the same distance and magnitude functionality, but
only be considered equal when they have the same weight. Also, suppose we want the addition
of two weighted points to give their weighted mean rather than a sum. We could implement
such a class as follows:

.. code-block:: python

    @ak.mixin_class(ak.behavior)
    class WeightedPoint(Point):
        @ak.mixin_class_method(np.equal, {"WeightedPoint"})
        def weighted_equal(self, other):
            return np.logical_and(self.point_equal(other), self.weight == other.weight)

        @ak.mixin_class_method(np.add, {"WeightedPoint"})
        def weighted_add(self, other):
            sumw = self.weight + other.weight
            return ak.zip(
                {
                    "x": (self.x * self.weight + other.x * other.weight) / sumw,
                    "y": (self.y * self.weight + other.y * other.weight) / sumw,
                    "weight": sumw,
                },
                with_name="WeightedPoint",
            )

A footnote: in this implementation, adding a WeightedPoint and a Point returns a Point.
One may wish to disable this by type-checking, since the functionalities are rather different.

Adding behavior to arrays
=========================

Occasionally, you may want to add behavior to an array that does not contain
records. A good example of this is to implement strings: strings are not a
special data type in Awkward Array as they are in many other libraries, they
are a behavior overlaid on arrays.

There are four predefined string behaviors:

* :class:`ak.CharBehavior`: an array of UTF-8 encoded characters;
* :class:`ak.ByteBehavior`: an array of unencoded characters;
* :class:`ak.StringBehavior`: an array of variable-length UTF-8 encoded strings;
* :class:`ak.ByteStringBehavior`: an array of variable-length unencoded bytestrings.

All four override the string representations (``__str__`` and ``__repr__``),
but the string behaviors additionally override equality:

.. code-block:: python

    >>> ak.Array(["one", "two", "three"]) == ak.Array(["1", "TWO", "three"])
    <Array [False, False, True] type='3 * bool'>

The only difference here is the parameter: instead of setting ``"__record__"``,
we set ``"__array__"``.

.. code-block:: python

    >>> ak.Array(["one", "two", "three"]).layout
    <ListOffsetArray64>
        <parameters>
            <param key="__array__">"string"</param>
        </parameters>
        <offsets><Index64 i="[0 3 6 11]" offset="0" length="4""/></offsets>
        <content><NumpyArray format="B" shape="11" data="0x 6f6e6574 776f7468 726565">
            <parameters>
                <param key="__array__">"char"</param>
            </parameters>
        </NumpyArray></content>
    </ListOffsetArray64>

In ``ak.behaviors.string``, string behaviors are assigned with lines like

.. code-block:: python

    ak.behavior["string"] = StringBehavior
    ak.behavior[np.equal, "string", "string"] = _string_equal

Custom type names
=================

To make the string type appear as ``string`` in type representations, a
``"__typestr__"`` behavior is overriden (in ``ak.behaviors.string``):

.. code-block:: python

    ak.behavior["__typestr__", "string"] = "string"

so that

.. code-block:: python

    >>> ak.type(ak.Array(["one", "two", "three"]))
    3 * string

Custom broadcasting
===================

In situations where we want to think about lists as objects, such as strings,
we may even need to override the broadcasting rules. For instance, given

.. code-block:: python

    ak.Array(["HAL"]) + ak.Array([[1, 1, 1, 1, 1]])

we might expect ``"HAL"`` to broadcast to each ``1``, like

.. code-block:: python

    [[[73, 66, 77], [73, 66, 77], [73, 66, 77], [73, 66, 77], [73, 66, 77]]]

but (without custom broadcasting) instead it raises a broadcasting for any
length of ``1`` list other than 3:

.. code-block:: python

    >>> # without custom broadcasting
    >>> print(ak.Array(["HAL"]) + ak.Array([[1, 1, 1, 1, 1]]))
    ValueError: in ListOffsetArray64, cannot broadcast nested list
    >>> print(ak.Array(["HAL"]) + ak.Array([[1, 1, 1]]))
    [[73, 66, 77]]

It's matching each character of ``"HAL"`` with a number from the list, but we
want the string to be taken as an object. That is fixed (in
``ak.behaviors.string``) with a custom broadcasting rule:

.. code-block:: python

    def _string_broadcast(layout, offsets):
        # layout:  an ak.layout.Content object
        # offsets: an ak.layout.Index of offsets to match
        # 
        # should return: an ak.layout.Content object of the broadcasted result
        ...

    awkward.behavior["__broadcast__", "string"] = _string_broadcast

Very few applications would need to do this, but the :data:`ak.behavior` object
provides a lot of room for customization hooks like this.

Overriding behavior in Numba
============================

Awkward Arrays can be arguments and return values of functions compiled with
`Numba <http://numba.pydata.org>`__. Since these functions run on low-level
objects, most functionality must be reimplemented, including behavioral
overrides.

The documentation on
`Extending Numba <https://numba.pydata.org/numba-doc/dev/extending/index.html>`__
introduces **typing**, **lowering**, and **models**, which are necessary for
reimplementing the behavior of a Python object in the compiled environment.
To apply the same to records and arrays from an Awkward data structure, we
use :data:`ak.behavior` hooks that start with ``"__numba_typer__"`` and
``"__numba_lower__"``.

**Case 1:** Adding a property, such as ``rec.property_name``.

.. code-block:: python

    ak.behavior["__numba_typer__", record_name, property_name] = typer
    ak.behavior["__numba_lower__", record_name, property_name] = lower

The ``typer`` function takes an
:func:`ak._connect._numba.arrayview.ArrayViewType` as its only argument
and returns the property's type.

The ``lower`` function takes the standard ``context, builder, sig, args``
arguments and returns the lowered value. Given a Python ``function`` that
takes one record and returns the property, the ``lower`` can be

.. code-block:: python

    def lower(context, builder, sig, args):
        return context.compile_internal(builder, function, sig, args)

**Case 2:** Adding a method, such as ``rec.method_name(arg0, arg1)``.

.. code-block:: python

    ak.behavior["__numba_typer__", record_name, method_name, ()] = typer
    ak.behavior["__numba_lower__", record_name, method_name, ()] = lower

The last item is an *empty* tuple, ``()`` (regardless of whether the method
takes any arguments).

In this case, the ``typer`` takes an
:func:`ak._connect._numba.arrayview.ArrayViewType` as well as any arguments
and returns the property's type, and the ``sig`` and ``args`` in ``lower``
include these arguments.

**Case 3:** Unary and binary operations, like ``-rec1`` and ``rec1 + rec2``.

.. code-block:: python

    ak.behavior["__numba_typer__", operator.neg, "rec1"] = typer
    ak.behavior["__numba_lower__", operator.neg, "rec1"] = lower

    ak.behavior["__numba_typer__", "rec1", operator.add, "rec2"] = typer
    ak.behavior["__numba_lower__", "rec1", operator.add, "rec2"] = lower

**Case 4:** Completely replacing the Awkward record with an object in Numba.

If a fully defined model for the object already exists and Numba, we can
have references to Awkward records or arrays simply *become* these objects,
which implies some overhead from copying data and a loss of the functionality
that Awkward would bring.

Strings, for instance, are replaced by Numba's built-in string model so that
all string operations will work, but Awkward operations like broadcasting
characters will not.

For this case, the signatures are

.. code-block:: python

    # parameters["__record__"] = record_name
    ak.behavior["__numba_typer__", record_name] = typer
    ak.behavior["__numba_lower__", record_name] = lower

    # for an array one-level deep
    ak.behavior["__numba_typer__", ".", record_name] = typer
    ak.behavior["__numba_lower__", ".", record_name] = lower

    # for an array any number of levels deep
    ak.behavior["__numba_typer__", "*", record_name] = typer
    ak.behavior["__numba_lower__", "*", record_name] = lower

    # parameters["__array__"] = array_name
    ak.behavior["__numba_typer__", array_name] = typer
    ak.behavior["__numba_lower__", array_name] = lower

The ``typer`` function takes an
:func:`ak._connect._numba.arrayview.ArrayViewType` as its only argument
and returns the Numba type of its replacement, while the ``lower``
function takes

* ``context``: Numba context
* ``builder``: Numba builder
* ``rettype``: the Numba type of its replacement
* ``viewtype``: an :func:`ak._connect._numba.arrayview.ArrayViewType`
* ``viewval``: a Numba value of the view
* ``viewproxy``: a Numba proxy (``context.make_helper``) of the view
* ``attype``: the Numba integer type of the index position
* ``atval``: the Numba value of the index position

.. Add back once https://github.com/scikit-hep/vector/issues/273 is completed
.. Complete example
.. ================

.. The
.. `Vector design prototype <https://vector.readthedocs.io/en/latest/usage/vector_design_prototype.html>`__
.. has a complete example, including Numba.

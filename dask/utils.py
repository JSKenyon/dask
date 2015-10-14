from __future__ import absolute_import, division, print_function

from collections import Iterator
from contextlib import contextmanager
from errno import ENOENT
import functools
import os
import sys
import shutil
import struct
import types
import gzip
import tempfile
import inspect
import codecs

from .compatibility import unicode, long, getargspec

def raises(err, lamda):
    try:
        lamda()
        return False
    except err:
        return True


def deepmap(func, *seqs):
    """ Apply function inside nested lists

    >>> inc = lambda x: x + 1
    >>> deepmap(inc, [[1, 2], [3, 4]])
    [[2, 3], [4, 5]]

    >>> add = lambda x, y: x + y
    >>> deepmap(add, [[1, 2], [3, 4]], [[10, 20], [30, 40]])
    [[11, 22], [33, 44]]
    """
    if isinstance(seqs[0], (list, Iterator)):
        return [deepmap(func, *items) for items in zip(*seqs)]
    else:
        return func(*seqs)


@contextmanager
def ignoring(*exceptions):
    try:
        yield
    except exceptions:
        pass


@contextmanager
def tmpfile(extension='', dir=None):
    extension = '.' + extension.lstrip('.')
    handle, filename = tempfile.mkstemp(extension, dir=dir)
    os.close(handle)
    os.remove(filename)

    try:
        yield filename
    finally:
        if os.path.exists(filename):
            if os.path.isdir(filename):
                shutil.rmtree(filename)
            else:
                os.remove(filename)


@contextmanager
def filetext(text, extension='', open=open, mode='w'):
    with tmpfile(extension=extension) as filename:
        f = open(filename, mode=mode)
        try:
            f.write(text)
        finally:
            try:
                f.close()
            except AttributeError:
                pass

        yield filename


def repr_long_list(seq):
    """

    >>> repr_long_list(list(range(100)))
    '[0, 1, 2, ..., 98, 99]'
    """
    if len(seq) < 8:
        return repr(seq)
    else:
        return repr(seq[:3])[:-1] + ', ..., ' + repr(seq[-2:])[1:]


class IndexCallable(object):
    """ Provide getitem syntax for functions

    >>> def inc(x):
    ...     return x + 1

    >>> I = IndexCallable(inc)
    >>> I[3]
    4
    """
    __slots__ = 'fn',
    def __init__(self, fn):
        self.fn = fn

    def __getitem__(self, key):
        return self.fn(key)


@contextmanager
def filetexts(d, open=open):
    """ Dumps a number of textfiles to disk

    d - dict
        a mapping from filename to text like {'a.csv': '1,1\n2,2'}
    """
    for filename, text in d.items():
        f = open(filename, 'wt')
        try:
            f.write(text)
        finally:
            try:
                f.close()
            except AttributeError:
                pass

    yield list(d)

    for filename in d:
        if os.path.exists(filename):
            os.remove(filename)


opens = {'gzip': gzip.open}


def get_bom(fn):
    """
    Get the Byte Order Mark (BOM) if it exists.
    """
    boms = set((codecs.BOM_UTF16, codecs.BOM_UTF16_BE, codecs.BOM_UTF16_LE))
    with open(fn, 'rb') as f:
        f.seek(0)
        bom = f.read(2)
        f.seek(0)
    if bom in boms:
        return bom
    else:
        return b''


def get_bin_linesep(encoding, linesep):
    """
    Simply doing `linesep.encode(encoding)` does not always give you
    *just* the linesep bytes, for some encodings this prefix's the
    linesep bytes with the BOM. This function ensures we just get the
    linesep bytes.
    """
    if encoding == 'utf-16':
        return linesep.encode('utf-16')[2:]  # [2:] strips bom
    else:
        return linesep.encode(encoding)


def next_linesep(fo, seek, encoding, linesep):
    bin_linesep = get_bin_linesep(encoding, linesep)
    data = b''
    data_len = 0

    while bin_linesep not in data:
        data_len += 1
        fo.seek(seek)
        data = fo.read(data_len)
        if len(data) < data_len:
            break  # eof

    stop = seek + data_len
    start = stop - len(bin_linesep)
    return start, stop


def textblock(file, start, stop, compression=None, encoding=None,
              linesep=None):
    """ Pull out a block of text from a file given start and stop bytes

    This gets data starting/ending from the next linesep delimiter

    Examples
    --------

    >> with open('myfile.txt', 'w') as f:
    ..     f.write('123\n456\n789\nabc')

    >> f = open('myfile.txt')

    In the example below, 1 and 10 don't line up with endlines

    >> textblock(f, 1, 10)
    '456\n789\n'
    """
    if isinstance(file, (str, unicode)):
        myopen = opens.get(compression, open)
        f = myopen(file, 'rb')
        try:
            result = textblock(f, start, stop, compression=None,
                               encoding=encoding, linesep=linesep)
        finally:
            f.close()
        return result

    if encoding is None:
        encoding = getattr(file, 'encoding', 'utf-8')
        if encoding is None:
            encoding = 'utf-8'

    if linesep is None:
        linesep = os.linesep

    if start:
        startstart, startstop = next_linesep(file, start, encoding, linesep)
    else:
        startstart = start
        startstop = start

    if stop is None:
        file.seek(start)
        return file.read()

    stopstart, stopstop = next_linesep(file, stop, encoding, linesep)

    file.seek(startstop)

    return file.read(stopstop - startstop)


def concrete(seq):
    """ Make nested iterators concrete lists

    >>> data = [[1, 2], [3, 4]]
    >>> seq = iter(map(iter, data))
    >>> concrete(seq)
    [[1, 2], [3, 4]]
    """
    if isinstance(seq, Iterator):
        seq = list(seq)
    if isinstance(seq, (tuple, list)):
        seq = list(map(concrete, seq))
    return seq


def skip(func):
    pass


def pseudorandom(n, p, random_state=None):
    """ Pseudorandom array of integer indexes

    >>> pseudorandom(5, [0.5, 0.5], random_state=123)
    array([1, 0, 0, 1, 1], dtype=int8)

    >>> pseudorandom(10, [0.5, 0.2, 0.2, 0.1], random_state=5)
    array([0, 2, 0, 3, 0, 1, 2, 1, 0, 0], dtype=int8)
    """
    import numpy as np
    p = list(p)
    cp = np.cumsum([0] + p)
    assert np.allclose(1, cp[-1])
    assert len(p) < 256

    if not isinstance(random_state, np.random.RandomState):
        random_state = np.random.RandomState(random_state)

    x = random_state.random_sample(n)
    out = np.empty(n, dtype='i1')

    for i, (low, high) in enumerate(zip(cp[:-1], cp[1:])):
        out[(x >= low) & (x < high)] = i
    return out


def different_seeds(n, random_state=None):
    """ A list of different 32 bit integer seeds

    Parameters
    ----------
    n: int
        Number of distinct seeds to return
    random_state: int or np.random.RandomState
        If int create a new RandomState with this as the seed
    Otherwise draw from the passed RandomState
    """
    import numpy as np

    if not isinstance(random_state, np.random.RandomState):
        random_state = np.random.RandomState(random_state)

    big_n = np.iinfo(np.int32).max

    seeds = set(random_state.randint(big_n, size=n))
    while len(seeds) < n:
        seeds.add(random_state.randint(big_n))

    # Sorting makes it easier to know what seeds are for what chunk
    return sorted(seeds)


def is_integer(i):
    """
    >>> is_integer(6)
    True
    >>> is_integer(42.0)
    True
    >>> is_integer('abc')
    False
    """
    import numpy as np
    if isinstance(i, (int, long)):
        return True
    if isinstance(i, float):
        return (i).is_integer()
    if issubclass(type(i), np.integer):
        return i
    else:
        return False


def file_size(fn, compression=None):
    """ Size of a file on disk

    If compressed then return the uncompressed file size
    """
    if compression == 'gzip':
        with open(fn, 'rb') as f:
            f.seek(-4, 2)
            result = struct.unpack('I', f.read(4))[0]
    else:
        result = os.stat(fn).st_size
    return result


ONE_ARITY_BUILTINS = set([abs, all, any, bool, bytearray, bytes, callable, chr,
    classmethod, complex, dict, dir, enumerate, eval, float, format, frozenset,
    hash, hex, id, int, iter, len, list, max, min, next, oct, open, ord, range,
    repr, reversed, round, set, slice, sorted, staticmethod, str, sum, tuple,
    type, vars, zip])
if sys.version_info[0] == 3: # Python 3
    ONE_ARITY_BUILTINS |= set([ascii])
if sys.version_info[:2] != (2, 6):
    ONE_ARITY_BUILTINS |= set([memoryview])
MULTI_ARITY_BUILTINS = set([compile, delattr, divmod, filter, getattr, hasattr,
    isinstance, issubclass, map, pow, setattr])

def takes_multiple_arguments(func):
    """ Does this function take multiple arguments?

    >>> def f(x, y): pass
    >>> takes_multiple_arguments(f)
    True

    >>> def f(x): pass
    >>> takes_multiple_arguments(f)
    False

    >>> def f(x, y=None): pass
    >>> takes_multiple_arguments(f)
    False

    >>> def f(*args): pass
    >>> takes_multiple_arguments(f)
    True

    >>> class Thing(object):
    ...     def __init__(self, a): pass
    >>> takes_multiple_arguments(Thing)
    False

    """
    if func in ONE_ARITY_BUILTINS:
        return False
    elif func in MULTI_ARITY_BUILTINS:
        return True

    try:
        spec = getargspec(func)
    except:
        return False

    try:
        is_constructor = spec.args[0] == 'self' and isinstance(func, type)
    except:
        is_constructor = False

    if spec.varargs:
        return True

    if spec.defaults is None:
        return len(spec.args) - is_constructor != 1
    return len(spec.args) - len(spec.defaults) - is_constructor > 1


class Dispatch(object):
    """Simple single dispatch."""
    def __init__(self):
        self._lookup = {}

    def register(self, type, func):
        """Register dispatch of `func` on arguments of type `type`"""
        if isinstance(type, tuple):
            for t in type:
                self.register(t, func)
        else:
            self._lookup[type] = func

    def __call__(self, arg):
        # We dispatch first on type(arg), and fall back to iterating through
        # the mro. This is significantly faster in the common case where
        # type(arg) is in the lookup, with only a small penalty on fall back.
        lk = self._lookup
        typ = type(arg)
        if typ in lk:
            return lk[typ](arg)
        for cls in inspect.getmro(typ)[1:]:
            if cls in lk:
                return lk[cls](arg)
        raise TypeError("No dispatch for {0} type".format(typ))


def ensure_not_exists(filename):
    """
    Ensure that a file does not exist.
    """
    try:
        os.unlink(filename)
    except OSError as e:
        if e.errno != ENOENT:
            raise


def _skip_doctest(line):
    if '>>>' in line:
        return line + '    # doctest: +SKIP'
    else:
        return line


def derived_from(original_klass, version=None, ua_args=[]):
    """Decorator to attach original class's docstring to the wrapped method.

    Parameters
    ----------
    original_klass: type
        Original class which the method is derived from
    version : str
        Original package version which supports the wrapped method
    ua_args : list
        List of keywords which Dask doesn't support. Keywords existing in
        original but not in Dask will automatically be added.
    """
    def wrapper(method):
        method_name = method.__name__

        try:
            # do not use wraps here, as it hides keyword arguments displayed
            # in the doc
            original_method = getattr(original_klass, method_name)
            doc = original_method.__doc__
            if doc is None:
                doc = ''

            method_args = getargspec(method).args
            original_args = getargspec(original_method).args

            not_supported = [m for m in original_args if m not in method_args]
            if len(ua_args) > 0:
                not_supported.extend(ua_args)

            if len(not_supported) > 0:
                note = ("\n        Notes\n        -----\n"
                        "        Dask doesn't supports following argument(s).\n\n")
                args = ''.join(['        * {0}\n'.format(a) for a in not_supported])
                doc = doc + note + args
            doc = '\n'.join([_skip_doctest(line) for line in doc.split('\n')])
            method.__doc__ = doc
            return method

        except AttributeError:
            module_name = original_klass.__module__.split('.')[0]
            @functools.wraps(method)
            def wrapped(*args, **kwargs):
                msg = "Base package doesn't support '{0}'.".format(method_name)
                if version is not None:
                    msg2 = " Use {0} {1} or later to use this method."
                    msg += msg2.format(module_name, version)
                raise NotImplementedError(msg)
            return wrapped
    return wrapper


def funcname(func):
    """Get the name of a function."""
    while hasattr(func, 'func'):
        func = func.func
    try:
        return func.__name__
    except:
        return str(func)

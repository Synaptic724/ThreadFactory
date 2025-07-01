import threading
import copy

class ConcurrentString:
    def __init__(self, initial: str = ""):
        self._value = initial
        self._lock = threading.RLock()

    def get(self) -> str:
        """Returns the current string value in a thread-safe way."""
        with self._lock:
            return self._value

    def set(self, new_value: str):
        """Sets the string value in a thread-safe way."""
        with self._lock:
            self._value = new_value

    def capitalize(self, *args, **kwargs):
        with self._lock:
            return self._value.capitalize(*args, **kwargs)

    def casefold(self, *args, **kwargs):
        with self._lock:
            return self._value.casefold(*args, **kwargs)

    def center(self, *args, **kwargs):
        with self._lock:
            return self._value.center(*args, **kwargs)

    def count(self, *args, **kwargs):
        with self._lock:
            return self._value.count(*args, **kwargs)

    def encode(self, *args, **kwargs):
        with self._lock:
            return self._value.encode(*args, **kwargs)

    def endswith(self, *args, **kwargs):
        with self._lock:
            return self._value.endswith(*args, **kwargs)

    def expandtabs(self, *args, **kwargs):
        with self._lock:
            return self._value.expandtabs(*args, **kwargs)

    def find(self, *args, **kwargs):
        with self._lock:
            return self._value.find(*args, **kwargs)

    def format(self, *args, **kwargs):
        with self._lock:
            return self._value.format(*args, **kwargs)

    def format_map(self, *args, **kwargs):
        with self._lock:
            return self._value.format_map(*args, **kwargs)

    def index(self, *args, **kwargs):
        with self._lock:
            return self._value.index(*args, **kwargs)

    def isalnum(self, *args, **kwargs):
        with self._lock:
            return self._value.isalnum(*args, **kwargs)

    def isalpha(self, *args, **kwargs):
        with self._lock:
            return self._value.isalpha(*args, **kwargs)

    def isascii(self, *args, **kwargs):
        with self._lock:
            return self._value.isascii(*args, **kwargs)

    def isdecimal(self, *args, **kwargs):
        with self._lock:
            return self._value.isdecimal(*args, **kwargs)

    def isdigit(self, *args, **kwargs):
        with self._lock:
            return self._value.isdigit(*args, **kwargs)

    def isidentifier(self, *args, **kwargs):
        with self._lock:
            return self._value.isidentifier(*args, **kwargs)

    def islower(self, *args, **kwargs):
        with self._lock:
            return self._value.islower(*args, **kwargs)

    def isnumeric(self, *args, **kwargs):
        with self._lock:
            return self._value.isnumeric(*args, **kwargs)

    def isprintable(self, *args, **kwargs):
        with self._lock:
            return self._value.isprintable(*args, **kwargs)

    def isspace(self, *args, **kwargs):
        with self._lock:
            return self._value.isspace(*args, **kwargs)

    def istitle(self, *args, **kwargs):
        with self._lock:
            return self._value.istitle(*args, **kwargs)

    def isupper(self, *args, **kwargs):
        with self._lock:
            return self._value.isupper(*args, **kwargs)

    def join(self, *args, **kwargs):
        with self._lock:
            return self._value.join(*args, **kwargs)

    def ljust(self, *args, **kwargs):
        with self._lock:
            return self._value.ljust(*args, **kwargs)

    def lower(self, *args, **kwargs):
        with self._lock:
            return self._value.lower(*args, **kwargs)

    def lstrip(self, *args, **kwargs):
        with self._lock:
            return self._value.lstrip(*args, **kwargs)

    def maketrans(self, *args, **kwargs):
        with self._lock:
            return self._value.maketrans(*args, **kwargs)

    def partition(self, *args, **kwargs):
        with self._lock:
            return self._value.partition(*args, **kwargs)

    def removeprefix(self, *args, **kwargs):
        with self._lock:
            return self._value.removeprefix(*args, **kwargs)

    def removesuffix(self, *args, **kwargs):
        with self._lock:
            return self._value.removesuffix(*args, **kwargs)

    def replace(self, *args, **kwargs):
        with self._lock:
            return self._value.replace(*args, **kwargs)

    def rfind(self, *args, **kwargs):
        with self._lock:
            return self._value.rfind(*args, **kwargs)

    def rindex(self, *args, **kwargs):
        with self._lock:
            return self._value.rindex(*args, **kwargs)

    def rjust(self, *args, **kwargs):
        with self._lock:
            return self._value.rjust(*args, **kwargs)

    def rpartition(self, *args, **kwargs):
        with self._lock:
            return self._value.rpartition(*args, **kwargs)

    def rsplit(self, *args, **kwargs):
        with self._lock:
            return self._value.rsplit(*args, **kwargs)

    def rstrip(self, *args, **kwargs):
        with self._lock:
            return self._value.rstrip(*args, **kwargs)

    def split(self, *args, **kwargs):
        with self._lock:
            return self._value.split(*args, **kwargs)

    def splitlines(self, *args, **kwargs):
        with self._lock:
            return self._value.splitlines(*args, **kwargs)

    def startswith(self, *args, **kwargs):
        with self._lock:
            return self._value.startswith(*args, **kwargs)

    def strip(self, *args, **kwargs):
        with self._lock:
            return self._value.strip(*args, **kwargs)

    def swapcase(self, *args, **kwargs):
        with self._lock:
            return self._value.swapcase(*args, **kwargs)

    def title(self, *args, **kwargs):
        with self._lock:
            return self._value.title(*args, **kwargs)

    def translate(self, *args, **kwargs):
        with self._lock:
            return self._value.translate(*args, **kwargs)

    def upper(self, *args, **kwargs):
        with self._lock:
            return self._value.upper(*args, **kwargs)

    def zfill(self, *args, **kwargs):
        with self._lock:
            return self._value.zfill(*args, **kwargs)

    def __str__(self):
        with self._lock:
            return str(self._value)

    def __repr__(self):
        with self._lock:
            return repr(self._value)

    def __eq__(self, other):
        with self._lock:
            return self._value == other

    def __ne__(self, other):
        with self._lock:
            return self._value != other

    def __lt__(self, other):
        with self._lock:
            return self._value < other

    def __le__(self, other):
        with self._lock:
            return self._value <= other

    def __gt__(self, other):
        with self._lock:
            return self._value > other

    def __ge__(self, other):
        with self._lock:
            return self._value >= other

    def __add__(self, other):
        with self._lock:
            return self._value + other

    def __radd__(self, other):
        with self._lock:
            return other + self._value

    def __mul__(self, n):
        with self._lock:
            return self._value * n

    def __rmul__(self, n):
        with self._lock:
            return n * self._value

    def __getitem__(self, index):
        with self._lock:
            return self._value[index]

    def __contains__(self, item):
        with self._lock:
            return item in self._value

    def __len__(self):
        with self._lock:
            return len(self._value)

    def __iter__(self):
        with self._lock:
            return iter(self._value[:])

    def __bool__(self):
        with self._lock:
            return bool(self._value)

    def __hash__(self):
        with self._lock:
            return hash(self._value)

    def __format__(self, format_spec):
        with self._lock:
            return format(self._value, format_spec)

    def __mod__(self, other):
        with self._lock:
            return self._value % other



    def __reduce__(self):
        with self._lock:
            return (self.__class__, (self._value,))

    def __reduce_ex__(self, protocol):
        with self._lock:
            return (self.__class__, (self._value,))

    def __getnewargs__(self):
        with self._lock:
            return (self._value,)

    def __copy__(self):
        with self._lock:
            return type(self)(self._value)

    def __deepcopy__(self, memo):
        with self._lock:
            return type(self)(copy.deepcopy(self._value, memo))

    def __dir__(self):
        with self._lock:
            return dir(self._value)

    @classmethod
    def __class_getitem__(cls, item):
        return cls

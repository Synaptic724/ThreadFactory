import threading
from array import array
import time
from typing import Type


class BitmapAllocator:
    """
    Bitmap-based ID allocator optimized for concurrent environments.

    Features:
    - Dynamically adjustable word size: 8, 16, 32, or 64 bits.
    - Allows custom lock type (Lock, RLock, or custom lock implementations).
    - Array of words (`array` module) used to represent the bitmap.
    - One lock per word to reduce contention in multi-threaded environments.
    - Randomized starting point to reduce thread contention hotspots.

    The allocator manages IDs using a bitmap where each bit represents one unique ID.
    """

    TYPE_CODES = {
        8:  ('B', 0xFF),                # Unsigned Char (8 bits)
        16: ('H', 0xFFFF),              # Unsigned Short (16 bits)
        32: ('I', 0xFFFFFFFF),          # Unsigned Int (32 bits)
        64: ('Q', 0xFFFFFFFFFFFFFFFF),  # Unsigned Long Long (64 bits)
    }

    def __init__(self, capacity: int, word_size: int = 32, lock_cls: Type[threading.Lock] = threading.Lock):
        """
        Initialize the BitmapAllocator.

        Args:
            capacity (int): The maximum number of IDs to allocate.
            word_size (int): The number of bits per word (choose from 8, 16, 32, 64).
            lock_cls (Type[threading.Lock]): The lock class to use (Lock, RLock, or custom).
        """
        if word_size not in self.TYPE_CODES:
            raise ValueError("word_size must be one of: 8, 16, 32, 64")

        # Assign word size and mask
        self._word_size = word_size
        self._typecode, self._full_mask = self.TYPE_CODES[word_size]

        # Compute how many words are needed
        self._num_words = (capacity + self._word_size - 1) // self._word_size

        # Create bitmap and per-word locks
        self._words = array(self._typecode, [0] * self._num_words)
        self._locks = [lock_cls() for _ in range(self._num_words)]

        self._capacity = capacity

    def _select_start_word_index(self) -> int:
        """
        Select a randomized starting word index to distribute contention.

        Returns:
            int: Index of the word to start searching for free bits.
        """
        ns = time.monotonic_ns()
        return ((ns >> 3) ^ ns) % self._num_words  # Mixed hash to spread load

    def acquire(self) -> int:
        """
        Acquire an available ID.

        Returns:
            int: The acquired ID.

        Raises:
            RuntimeError: If no IDs are available.
        """
        start_idx = self._select_start_word_index()

        # Search all words, wrapping around circularly
        for i in range(self._num_words):
            word_idx = (start_idx + i) % self._num_words
            lock = self._locks[word_idx]

            with lock:
                word = self._words[word_idx]

                # Skip if word is fully occupied
                if word == self._full_mask:
                    continue

                # Find first available bit
                free_bit = (~word) & (word + 1)  # Isolate the lowest available bit

                if free_bit == 0:
                    continue

                bit_idx = (free_bit - 1).bit_length()

                # Mark the bit as used
                self._words[word_idx] |= (1 << bit_idx)

                return word_idx * self._word_size + bit_idx

        raise RuntimeError("No IDs available (all slots are occupied).")

    def release(self, id_: int):
        """
        Release a previously acquired ID.

        Args:
            id_ (int): The ID to release.

        Raises:
            ValueError: If the ID is out of range.
            RuntimeError: If the ID is already free (double-free protection).
        """
        if not (0 <= id_ < self._capacity):
            raise ValueError(f"ID {id_} is out of range.")

        word_idx = id_ // self._word_size
        bit_idx = id_ % self._word_size

        lock = self._locks[word_idx]
        with lock:
            if (self._words[word_idx] & (1 << bit_idx)) == 0:
                raise RuntimeError(f"Double-free detected for ID {id_}.")

            self._words[word_idx] &= ~(1 << bit_idx)

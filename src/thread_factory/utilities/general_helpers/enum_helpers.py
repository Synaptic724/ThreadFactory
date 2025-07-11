#    Copyright [2025] [Mark Thomas Geleta]
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0

from enum import Enum
from functools import lru_cache
from typing import Any, Optional, Tuple, Union, TypeVar, Type


T = TypeVar("T", bound=Enum)

class EnumHelpers:
    @staticmethod
    @lru_cache(maxsize=256)
    def convert_enum_and_check(value: str | Enum, enum: Type[T]) -> T:
        """
        Converts a string input into the correct Enum member.
        Case-insensitive match is performed. Raises ValueError if the string doesn't match.

        If value is already an Enum member of the correct type, it is returned as-is.
        """
        if isinstance(value, enum):
            return value

        if isinstance(value, str):
            # Case-insensitive mapping
            lookup = {e.name.lower(): e for e in enum}
            result = lookup.get(value.lower())

            if result is not None:
                return result

            valid_options = [e.name for e in enum]
            raise ValueError(
                f"Invalid value '{value}' for enum {enum.__name__}. "
                f"Expected one of: {valid_options}."
            )

        raise ValueError(
            f"Expected a string or {enum.__name__} member, got {type(value).__name__}."
        )

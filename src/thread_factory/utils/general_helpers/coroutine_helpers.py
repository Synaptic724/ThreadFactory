import inspect

class CoroutineHelpers:
    @staticmethod
    def is_coroutine(func) -> bool:
        """
        Checks if a function (or callable) is a coroutine function (async def).
        Handles wrapped functions and callable objects.
        """
        while hasattr(func, "__wrapped__"):
            func = func.__wrapped__

        # Support callable objects
        if not callable(func):
            return False

        try:
            return inspect.iscoroutinefunction(func)
        except Exception:
            return False

    @staticmethod
    def is_async_function(func) -> bool:
        # Alias for clarity; same as is_coroutine
        return CoroutineHelpers.is_coroutine(func)
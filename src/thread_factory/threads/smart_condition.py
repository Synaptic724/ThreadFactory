from threading import Condition
from thread_factory.utils import Disposable


"""
This class is a subclass of the Condition class from the threading module.
It is a more advanced version of the Condition class that allows for more complex conditions.

It will allow for more advanced synchronization between threads. This targets a specific thread ID 
and then notifies specific that threadID to wake up by calling notify(threadID).

This will be used with the dynaphore to allow for more advanced synchronization between threads.
"""
class SmartCondition(Condition):
    pass
import threading, time
from thread_factory.synchronization.primitives.flow_regulator import FlowRegulator
from thread_factory.agent.command_center import CommandCenter
from thread_factory.utilities.coordination.package import Pack

def blocking_task(flow: FlowRegulator, duration: float = 1.0):
    """
    This function is used by agents. It tries to acquire the FlowRegulator,
    sleeps for a bit, and then releases it.
    """
    acquired = flow.acquire(timeout=5)
    if acquired:
        print(f"[{threading.current_thread().name}] Acquired flow!")
        time.sleep(duration)
        flow.release()
        print(f"[{threading.current_thread().name}] Released flow!")
    else:
        print(f"[{threading.current_thread().name}] Failed to acquire flow (timeout)")

# Set up the test
if __name__ == "__main__":
    flow = FlowRegulator(value=2)  # allow 2 permits
    center = CommandCenter(max_workers=10)

    # Create and start agents with the blocking task
    for _ in range(2):
        center.submit(
            target=Pack(blocking_task, flow, 2.0)
        )

    # Allow time for all to finish
    time.sleep(10)

    center.shutdown()
    flow.dispose()
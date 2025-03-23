import threading
import time


def thread_task():
    # This gets the current running thread (this instance of Thread)
    current = threading.current_thread()
    print(f"Test {threading.get_ident()}")

    # Access thread attributes
    print(f"[{current.name}] is running with ident: {current.ident}")

    # Simulate some work
    time.sleep(1)

    print(f"[{current.name}] is done!")


# Create and start 3 threads
threads = []
for i in range(3):
    t = threading.Thread(target=thread_task, name=f"Worker-{i}")
    t.start()
    threads.append(t)

# Wait for all threads to finish
for t in threads:
    t.join()

print("All threads completed.")
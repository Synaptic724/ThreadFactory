import unittest
import threading
import time
from thread_factory.dynamic_thread_pool.general_worker.general_worker import GeneralWorker

class TestGeneralWorker(unittest.TestCase):

    def test_factory_id_and_worker_type_binding(self):
        result = {}

        def check_identity():
            result["factory_id"] = getattr(threading.current_thread(), "factory_id", None)
            result["worker_type"] = getattr(threading.current_thread(), "worker_type", None)

        worker = GeneralWorker(on_run=check_identity)
        worker.start()
        worker.join(timeout=1)

        self.assertIsNotNone(result.get("factory_id"))
        self.assertEqual(result.get("worker_type"), "general")

    def test_on_run_callback_executes(self):
        flag = threading.Event()

        def task():
            flag.set()

        worker = GeneralWorker(on_run=task)
        worker.start()
        worker.join(timeout=1)

        self.assertTrue(flag.is_set(), "on_run did not execute")

    def test_shutdown_flag_triggers_exit(self):
        triggered = []

        def idle_loop():
            while not threading.current_thread().shutdown_flag.is_set():
                time.sleep(0.01)
            triggered.append(True)

        worker = GeneralWorker(on_run=idle_loop)
        worker.start()
        time.sleep(0.05)
        worker.stop()
        worker.join(timeout=1)

        self.assertTrue(triggered, "Shutdown flag didn't exit loop")

    def test_death_event_signaled_on_finish(self):
        worker = GeneralWorker(on_run=lambda: time.sleep(0.05))
        worker.start()
        worker.join(timeout=1)

        self.assertTrue(worker.death_event.is_set(), "Death event was not triggered")

if __name__ == "__main__":
    unittest.main()

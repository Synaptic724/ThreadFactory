import unittest
import threading
import time
import logging
from typing import List, Any, Dict
from thread_factory.synchronization.coordinators.conductor import Conductor
from thread_factory.synchronization.controllers.signal_controller import SignalController

def _spawn(n: int, fn: callable):
    threads = [threading.Thread(target=fn, daemon=True) for _ in range(n)]
    for t in threads:
        t.start()
    return threads

class TestConductorControllerIntegration(unittest.TestCase):

    def setUp(self):
        self.logger = logging.getLogger("test_controller")
        self.logger.setLevel(logging.CRITICAL)
        self.controller = SignalController(logger=self.logger)
        self.received_events: List[Dict[str, Any]] = []
        self.callback_hits = {"count": 0}
        self.callback_lock = threading.Lock()

    def tearDown(self):
        if self.controller and not self.controller.is_disposed:
            self.controller.dispose()

    def _event_recorder(self, obj_id: str, event_type: str, data: Any):
        self.received_events.append({"id": obj_id, "event": event_type, "data": data})

    def _counting_callback(self):
        with self.callback_lock:
            self.callback_hits["count"] += 1

    def test_successful_run_emits_correct_event_sequence(self):
        task_result = {"value": 0}
        task_lock = threading.Lock()
        def increment_task():
            with task_lock:
                task_result["value"] += 1
            return "DONE"

        c = Conductor(threshold=2, tasks=increment_task, controller=self.controller)
        self.controller.subscribe(c.id, "BARRIER_PASSED", self._event_recorder)
        self.controller.subscribe(c.id, "EXECUTION_STARTED", self._event_recorder)
        self.controller.subscribe(c.id, "EXECUTION_COMPLETED", self._event_recorder)

        threads = _spawn(2, c.start)
        for t in threads: t.join(timeout=2)

        self.assertEqual(task_result["value"], 2, "Task should be executed by BOTH threads.")
        self.assertIn("DONE", c.results)
        event_types = [e['event'] for e in self.received_events]
        expected_sequence = ["BARRIER_PASSED", "EXECUTION_STARTED", "EXECUTION_COMPLETED"]
        self.assertEqual(event_types, expected_sequence)
        self.assertEqual(len(self.controller.list_objects(name_filter="conductor")), 1)

    def test_timeout_emits_barrier_broken_event(self):
        c = Conductor(threshold=2, timeout=0.1, controller=self.controller)
        self.controller.subscribe(c.id, "BARRIER_BROKEN", self._event_recorder)
        _spawn(1, c.start)[0].join(timeout=1)
        self.assertTrue(c._broken)
        self.assertEqual(len(self.received_events), 1)
        self.assertEqual(self.received_events[0]['event'], "BARRIER_BROKEN")

    def test_controller_can_invoke_reset_on_reusable_conductor(self):
        c = Conductor(threshold=1, reusable=True, controller=self.controller)
        _spawn(1, c.start)[0].join(timeout=1)
        self.assertTrue(c._released)
        self.controller.invoke(c.id, 'reset')
        self.assertFalse(c._released)
        self.assertFalse(c._broken)
        _spawn(1, c.start)[0].join(timeout=1)
        self.assertTrue(c._released)

    def test_controller_invoke_on_all_resets_multiple_conductors(self):
        c1 = Conductor(threshold=1, reusable=True, controller=self.controller)
        c2 = Conductor(threshold=1, reusable=True, controller=self.controller)
        _spawn(1, c1.start)[0].join(timeout=1)
        _spawn(1, c2.start)[0].join(timeout=1)
        self.assertTrue(c1._released)
        self.assertTrue(c2._released)
        self.controller.invoke_on_all('reset', name_filter='conductor')
        self.assertFalse(c1._released)
        self.assertFalse(c2._released)

    def test_manual_release_blocks_threads_until_released(self):
        c = Conductor(threshold=2, manual_release=True, controller=self.controller)
        work_done_event = threading.Event()
        _spawn(2, lambda: (c.start(), work_done_event.set()))
        time.sleep(0.2)
        self.assertFalse(work_done_event.is_set())
        c.release()
        finished_in_time = work_done_event.wait(timeout=1)
        self.assertTrue(finished_in_time)

    def test_callback_is_fired_correctly_once_per_wave(self):
        def task_one(): return 1
        def task_two(): return 2
        c = Conductor(
            threshold=2,
            tasks=[task_one, task_two],
            callback=self._counting_callback,
            controller=self.controller
        )
        threads = _spawn(2, c.start)
        for t in threads: t.join(timeout=1)
        # FIX: The callback runs ONCE per task wave. 2 tasks = 2 hits.
        self.assertEqual(self.callback_hits["count"], 2)

    def test_conductor_disposal_cascades_from_controller_dispose(self):
        c = Conductor(threshold=1, controller=self.controller)
        self.assertFalse(c.is_disposed)
        self.controller.dispose()
        self.assertTrue(c.is_disposed)
        self.assertTrue(self.controller.is_disposed)

if __name__ == "__main__":
    unittest.main(verbosity=2)
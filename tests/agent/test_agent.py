import unittest
from unittest.mock import Mock, patch
import threading
import time

from thread_factory import ConcurrentDict
from thread_factory.runtime import WorkerState
from thread_factory.runtime.orchestrator.monitoring.records.records import WorkStatus
from thread_factory.agent.thread_pool.help_request import HelpRequest
from thread_factory.agent.thread_pool.agent import Agent
from thread_factory.utils.coordination.package import Pack


# Define a simple async function for testing coroutine checks
async def async_test_func():
    pass

# Define a simple sync function for testing
def sync_test_func():
    pass


class TestAgent(unittest.TestCase):

    def setUp(self):
        """
        Set up common mock objects and a fresh Agent instance before each test.
        """
        # Mock the factory that would typically manage this worker.
        self.mock_factory = Mock()
        # Initialize Agent with a specific factory_id and the mocked factory.
        self.worker = Agent(factory_id="worker1", factory=self.mock_factory)

        # Mock a HelpRequest instance to simulate bound work.
        self.mock_value_work = Mock(spec=HelpRequest)

        # Configure the mock HelpRequest's record and state behavior.
        self.mock_value_work.record = Mock()
        self.mock_value_work.get_record.return_value = self.mock_value_work.record
        self.mock_value_work.get_state.return_value = WorkStatus.PENDING

    def test_register_save_point(self):
        """Test registering a save point and its functionality with a synchronous callable."""
        save_point_name = "checkpoint"
        save_point_func = Mock()

        # Register save point
        self.worker.register_save_point(save_point_name, save_point_func)
        self.assertIn(save_point_name, self.worker.get_save_points_dict()) # Use getter

        # Call the registered save point function
        self.worker.get_save_points_dict()[save_point_name]() # Use getter
        save_point_func.assert_called_once()

    def test_register_save_point_coroutine_raises_type_error(self):
        """Test that registering a coroutine function as a save point raises TypeError."""
        save_point_name = "async_checkpoint"
        with self.assertRaisesRegex(TypeError, "Coroutine functions are not supported: async_test_func"):
            self.worker.register_save_point(save_point_name, async_test_func)
        self.assertNotIn(save_point_name, self.worker.get_save_points_dict())

    def test_get_save_points_dict(self):
        """Test retrieving the save points dictionary."""
        self.worker.register_save_point("test_point", sync_test_func)
        points = self.worker.get_save_points_dict()
        self.assertIsInstance(points, ConcurrentDict)
        self.assertIn("test_point", points)
        self.assertIsNot(points, self.worker._save_points) # Ensure it's a copy

    def test_register_location(self):
        """Test registering a location and its functionality with a synchronous callable."""
        location_name = "location1"
        location_func = Mock()

        # Register location
        self.worker.register_location(location_name, location_func)
        self.assertIn(location_name, self.worker.get_locations_dict()) # Use getter

        # Call the registered location function
        self.worker.get_locations_dict()[location_name]() # Use getter
        location_func.assert_called_once()

    def test_register_location_coroutine_raises_type_error(self):
        """Test that registering a coroutine function as a location raises TypeError."""
        location_name = "async_location"
        with self.assertRaisesRegex(TypeError, "Coroutine functions are not supported: async_test_func"):
            self.worker.register_location(location_name, async_test_func)
        self.assertNotIn(location_name, self.worker.get_locations_dict())

    def test_get_locations_dict(self):
        """Test retrieving the locations dictionary."""
        self.worker.register_location("test_location", sync_test_func)
        locations = self.worker.get_locations_dict()
        self.assertIsInstance(locations, ConcurrentDict)
        self.assertIn("test_location", locations)
        self.assertIsNot(locations, self.worker._locations) # Ensure it's a copy

    def test_set_home(self):
        """Test setting the home function with a synchronous callable."""
        home_func = Mock()
        self.worker.set_home(home_func)
        self.assertTrue(isinstance(self.worker._event_loop, Pack))


    def test_set_home_coroutine_raises_type_error(self):
        """Test that setting a coroutine function as home raises TypeError."""
        with self.assertRaisesRegex(TypeError, "Coroutine functions are not supported: async_test_func"):
            self.worker.set_home(async_test_func)
        self.assertIsNone(self.worker._event_loop) # Should not set it

    def test_run_with_home_set(self):
        """Test running the worker when home function is set."""
        home_func = Mock()
        self.worker.set_home(home_func)

        # Start the worker in a separate thread
        thread = threading.Thread(target=self.worker.run)
        thread.start()

        # Allow some time for the thread to execute
        time.sleep(0.1)

        # Check that home() was called
        home_func.assert_called_once() # Should only be called once by run()

        # Stop the worker gracefully
        self.worker.stop()
        thread.join()  # Ensure the thread has finished

    def test_run_without_home_set(self):
        """Test running the worker without a home function set."""
        with self.assertRaisesRegex(RuntimeError, "No home\(\) set before thread start."):
            self.worker.run()

    def test_stop(self):
        """Test stopping the worker."""
        self.worker.stop()
        self.assertTrue(self.worker.shutdown_flag.is_set())

    def test_dispose(self):
        """Test disposing the worker and proper cleanup of private attributes."""
        # Attach a mock HelpRequest to ensure dispose_work is called
        self.worker.set_value_work(self.mock_value_work) # Use setter

        # Register some save points and locations to ensure they are cleared
        self.worker.register_save_point("test_sp", sync_test_func)
        self.worker.register_location("test_loc", sync_test_func)

        self.worker.dispose()
        self.assertTrue(self.worker._disposed)
        self.assertIsNone(self.worker._save_points) # Check private attribute
        self.assertIsNone(self.worker._locations)   # Check private attribute
        self.assertIsNone(self.worker._event_loop)  # Check private attribute
        # Verify that dispose_work was called on the mock HelpRequest
        self.mock_value_work.dispose.assert_called_once()
        self.assertIsNone(self.worker._value_work) # _value_work should be cleared

    def test_dynamic_worker_repr(self):
        """Test the string representation of the worker."""
        self.worker.state = WorkerState.STARTING
        repr_str = repr(self.worker)
        self.assertIn("AgenticWorker", repr_str)
        self.assertIn("id=worker1", repr_str)
        self.assertIn("state=STARTING", repr_str)

    def test_worker_thread_lifecycle(self):
        """Test full worker lifecycle: start, run, stop, dispose."""
        self.worker.set_home(Mock())
        thread = threading.Thread(target=self.worker.run)

        # Start the worker
        thread.start()

        # Wait a bit and stop the worker
        time.sleep(0.1)
        self.worker.stop()

        # Ensure the thread stops properly and exits gracefully
        thread.join()

        # Now, dispose of the worker and check for proper cleanup
        self.worker.dispose()
        self.assertTrue(self.worker.disposed)
        # Assert that the final state is DISPOSED, as expected after disposal
        self.assertEqual(self.worker.state, WorkerState.DISPOSED)

    # --- Tests for ValueWork integration ---

    def test_get_value_work(self):
        """Test getting the bound ValueWork instance."""
        self.worker.set_value_work(self.mock_value_work) # Use setter
        retrieved_work = self.worker.get_value_work()
        self.assertIs(retrieved_work, self.mock_value_work)

    def test_set_value_work(self):
        """Test setting a ValueWork instance to the worker."""
        self.assertIsNone(self.worker.get_value_work()) # Initially None
        self.worker.set_value_work(self.mock_value_work)
        self.assertIs(self.worker.get_value_work(), self.mock_value_work)

    def test_set_work_state(self):
        """Test setting the state of the bound ValueWork."""
        self.worker.set_value_work(self.mock_value_work)
        self.worker.set_work_state(WorkStatus.IN_PROGRESS)
        self.mock_value_work.set_state.assert_called_once_with(WorkStatus.IN_PROGRESS)

    def test_get_work_state(self):
        """Test getting the state of the bound ValueWork."""
        self.worker.set_value_work(self.mock_value_work)
        state = self.worker.get_work_state()
        self.assertEqual(state, WorkStatus.PENDING)
        self.mock_value_work.get_state.assert_called_once()

    def test_mark_work_in_progress(self):
        """Test marking the bound ValueWork as 'in progress'."""
        self.worker.set_value_work(self.mock_value_work)
        self.worker.mark_work_in_progress()
        self.mock_value_work.mark_in_progress.assert_called_once()

    def test_mark_work_completed(self):
        """Test marking the bound ValueWork as 'completed'."""
        self.worker.set_value_work(self.mock_value_work)
        self.worker.mark_work_completed()
        self.mock_value_work.mark_completed.assert_called_once()

    def test_mark_work_failed(self):
        """Test marking the bound ValueWork as 'failed'."""
        self.worker.set_value_work(self.mock_value_work)
        self.worker.mark_work_failed()
        self.mock_value_work.mark_failed.assert_called_once()

    def test_mark_work_cancelled(self):
        """Test marking the bound ValueWork as 'cancelled'."""
        self.worker.set_value_work(self.mock_value_work)
        self.worker.mark_work_cancelled()
        self.mock_value_work.mark_cancelled.assert_called_once()

    def test_reset_work(self):
        """Test resetting the bound ValueWork."""
        self.worker.set_value_work(self.mock_value_work)
        self.worker.reset_work()
        self.mock_value_work.reset.assert_called_once()

    def test_get_work_record(self):
        """Test getting the record from the bound ValueWork."""
        self.worker.set_value_work(self.mock_value_work)
        record = self.worker.get_work_record()
        self.assertIs(record, self.mock_value_work.record)
        self.mock_value_work.get_record.assert_called_once()

    def test_acquire_and_run_work(self):
        """Test acquiring and running the bound ValueWork."""
        self.worker.set_value_work(self.mock_value_work)
        self.worker.acquire_and_run_work()
        self.mock_value_work.acquire_work.assert_called_once()

    def test_cancel_bound_job(self):
        """Test canceling the bound ValueWork job."""
        self.worker.set_value_work(self.mock_value_work)
        self.worker.cancel_bound_job()
        self.mock_value_work.cancel_job.assert_called_once()

    def test_dispose_work(self):
        """Test disposing of the bound ValueWork."""
        self.worker.set_value_work(self.mock_value_work)
        self.worker.dispose_work()
        self.mock_value_work.dispose.assert_called_once()
        self.assertIsNone(self.worker.get_value_work()) # Use getter for assertion

    def test_multiple_thread_disposal(self):
        """Test that multiple worker threads can be started and disposed of."""
        workers = []
        threads = []
        num_workers = 5

        # Create and start multiple workers in threads
        for i in range(num_workers):
            worker = Agent(factory_id=f"worker_{i}", factory=None)
            worker.set_home(Mock())
            thread = threading.Thread(target=worker.run)
            thread.start()
            workers.append(worker)
            threads.append(thread)

        # Allow some time for threads to start
        time.sleep(0.2)

        # Stop all workers and join their threads
        for worker_instance in workers: # Renamed loop variable to avoid conflict with self.worker
            worker_instance.stop()
        for thread_instance in threads: # Renamed loop variable
            thread_instance.join()
            self.assertFalse(thread_instance.is_alive())  # Ensure thread is no longer alive

        # Dispose of all workers and check their state
        for worker_instance in workers:
            worker_instance.dispose()
            self.assertTrue(worker_instance.disposed)
            self.assertEqual(worker_instance.state, WorkerState.DISPOSED)

    # --- New tests for Inventory Management ---

    def test_bind_to_inventory(self):
        """Test binding a value to the worker's private inventory without ID enforcement."""
        self.worker.bind_to_inventory("test_key", "test_value")
        self.assertEqual(self.worker._inventory.data["test_key"], "test_value")

    def test_bind_to_inventory_enforce_id_match(self):
        """
        Test binding with `enforce_id=True` when the `factory_id` of the current
        thread matches the worker's ID (or specified ID).
        """
        with patch('threading.current_thread') as mock_current_thread:
            # Mock the current thread's factory_id to match "worker1"
            mock_current_thread.return_value.factory_id = "worker1"
            self.worker.bind_to_inventory("test_key_id", "test_value_id", enforce_id=True)
            self.assertEqual(self.worker._inventory.data["test_key_id"], "test_value_id")

    def test_bind_to_inventory_enforce_id_mismatch(self):
        """
        Test binding with `enforce_id=True` when the `factory_id` of the current
        thread mismatches the worker's ID, expecting a `PermissionError`.
        """
        with patch('threading.current_thread') as mock_current_thread:
            # Mock the current thread's factory_id to be different
            mock_current_thread.return_value.factory_id = "other_worker"
            with self.assertRaises(PermissionError) as cm:
                self.worker.bind_to_inventory("test_key_fail", "test_value_fail", enforce_id=True)
            self.assertIn("Access Denied", str(cm.exception))
            self.assertIn("worker1", str(cm.exception)) # Should mention the worker's ID

    def test_get_from_inventory(self):
        """Test retrieving a value from the worker's private inventory."""
        self.worker.bind_to_inventory("get_key", "get_value")
        self.assertEqual(self.worker.get_from_inventory("get_key"), "get_value")
        # Test retrieval of a non-existent key, expecting None
        self.assertIsNone(self.worker.get_from_inventory("non_existent_key"))
        # Test retrieval of a non-existent key with a default value
        self.assertEqual(self.worker.get_from_inventory("non_existent_key", default="default_val"), "default_val")

    def test_get_from_inventory_enforce_id_match(self):
        """
        Test retrieving with `enforce_id=True` when the `factory_id` of the current
        thread matches the worker's ID.
        """
        self.worker.bind_to_inventory("get_key_id", "get_value_id")
        with patch('threading.current_thread') as mock_current_thread:
            mock_current_thread.return_value.factory_id = "worker1"
            value = self.worker.get_from_inventory("get_key_id", enforce_id=True)
            self.assertEqual(value, "get_value_id")

    def test_get_from_inventory_enforce_id_mismatch(self):
        """
        Test retrieving with `enforce_id=True` when the `factory_id` of the current
        thread mismatches the worker's ID, expecting a `PermissionError`.
        """
        self.worker.bind_to_inventory("get_key_fail", "get_value_fail")
        with patch('threading.current_thread') as mock_current_thread:
            mock_current_thread.return_value.factory_id = "other_worker"
            with self.assertRaises(PermissionError) as cm:
                self.worker.get_from_inventory("get_key_fail", enforce_id=True)
            self.assertIn("Access Denied", str(cm.exception))
            self.assertIn("worker1", str(cm.exception))

    def test_set_shared_inventory_item(self):
        """Test setting an item in the shared inventory."""
        self.worker.set_shared_inventory_item("shared_key", "shared_value")
        self.assertEqual(self.worker._shared_inventory["shared_key"], "shared_value")

    def test_get_shared_inventory_item(self):
        """Test getting an item from the shared inventory."""
        self.worker.set_shared_inventory_item("get_shared_key", "get_shared_value")
        self.assertEqual(self.worker.get_shared_inventory_item("get_shared_key"), "get_shared_value")
        self.assertIsNone(self.worker.get_shared_inventory_item("non_existent_shared_key"))
        self.assertEqual(self.worker.get_shared_inventory_item("non_existent_shared_key", default="default_shared"), "default_shared")

    def test_get_shared_inventory(self):
        """Test retrieving the entire shared inventory dictionary."""
        self.worker.set_shared_inventory_item("item1", 1)
        self.worker.set_shared_inventory_item("item2", "value2")
        shared_inv = self.worker.get_shared_inventory()
        self.assertIsInstance(shared_inv, ConcurrentDict)
        self.assertEqual(shared_inv, {"item1": 1, "item2": "value2"})
        self.assertIs(shared_inv, self.worker._shared_inventory) # Ensure it's the direct reference

    def test_register_data_transfer(self):
        """Test registering a data transfer function with a synchronous callable."""
        transfer_name = "process_data"
        transfer_func = Mock()
        self.worker.register_data_transfer(transfer_name, transfer_func)
        self.assertIn(transfer_name, self.worker._data_transfer) # Check private attribute

    def test_register_data_transfer_coroutine_raises_type_error(self):
        """Test that registering a coroutine function for data transfer raises TypeError."""
        transfer_name = "async_transfer"
        with self.assertRaisesRegex(TypeError, "Coroutine functions are not supported: async_test_func"):
            self.worker.register_data_transfer(transfer_name, async_test_func)
        self.assertNotIn(transfer_name, self.worker._data_transfer)

    def test_get_data_transfer_dict(self):
        """Test retrieving the data transfer functions dictionary."""
        self.worker.register_data_transfer("test_transfer", sync_test_func)
        transfers = self.worker.get_data_transfer_dict()
        self.assertIsInstance(transfers, ConcurrentDict)
        self.assertIn("test_transfer", transfers)
        self.assertIsNot(transfers, self.worker._data_transfer) # Ensure it's a copy

    def test_execute_transfer_success(self):
        """Test successful execution of a registered data transfer function."""
        mock_transfer_func = Mock(return_value="transfer_result")
        self.worker.register_data_transfer("my_transfer", mock_transfer_func) # Use setter
        result = self.worker.execute_transfer("my_transfer")
        mock_transfer_func.assert_called_once()
        self.assertEqual(result, "transfer_result")

    def test_execute_transfer_key_error(self):
        """Test executing a non-existent data transfer function, expecting `KeyError`."""
        with self.assertRaises(KeyError) as cm:
            self.worker.execute_transfer("non_existent_transfer")
        self.assertIn("No data_transfer entry named 'non_existent_transfer'", str(cm.exception))

    def test_execute_transfer_enforce_id_match(self):
        """
        Test executing a transfer with `enforce_id=True` when the `factory_id` of the
        current thread matches the worker's ID.
        """
        mock_transfer_func = Mock(return_value="secured_result")
        self.worker.register_data_transfer("secured_transfer", mock_transfer_func)
        with patch('threading.current_thread') as mock_current_thread:
            mock_current_thread.return_value.factory_id = "worker1"
            result = self.worker.execute_transfer("secured_transfer", enforce_id=True)
            self.assertEqual(result, "secured_result")
            mock_transfer_func.assert_called_once()

    def test_execute_transfer_enforce_id_mismatch(self):
        """
        Test executing a transfer with `enforce_id=True` when the `factory_id` of the
        current thread mismatches the worker's ID, expecting a `PermissionError`.
        """
        mock_transfer_func = Mock()
        self.worker.register_data_transfer("secured_transfer_fail", mock_transfer_func)
        with patch('threading.current_thread') as mock_current_thread:
            mock_current_thread.return_value.factory_id = "intruder_worker"
            with self.assertRaises(PermissionError) as cm:
                self.worker.execute_transfer("secured_transfer_fail", enforce_id=True)
            self.assertIn("Access Denied", str(cm.exception))
            self.assertIn("worker1", str(cm.exception))
            mock_transfer_func.assert_not_called() # Ensure the function wasn't called

    # --- External Access (ID-Based) ---

    def test_get_factory_id(self):
        """Test retrieving the worker's factory ID."""
        self.assertEqual(self.worker.get_factory_id(), "worker1")

    def test_bind_to_inventory_by_id(self):
        """
        Test binding a value to another worker's inventory by its `factory_id`.
        This involves mocking the `factory` to return a mock target worker.
        """
        mock_target_worker = Mock(spec=Agent)
        self.mock_factory.get_worker_by_id.return_value = mock_target_worker

        self.worker.bind_to_inventory_by_id("target_worker_id", "external_key", "external_value")

        self.mock_factory.get_worker_by_id.assert_called_once_with("target_worker_id")
        mock_target_worker.bind_to_inventory.assert_called_once_with("external_key", "external_value")

    def test_bind_to_inventory_by_id_worker_not_found(self):
        """
        Test binding to inventory by ID when the target worker cannot be resolved
        (i.e., `_resolve_worker_by_id` returns `None`).
        """
        self.mock_factory.get_worker_by_id.return_value = None

        self.worker.bind_to_inventory_by_id("non_existent_worker", "key", "value")

        self.mock_factory.get_worker_by_id.assert_called_once_with("non_existent_worker")

    def test_get_from_inventory_by_id(self):
        """
        Test getting a value from another worker's inventory by its `factory_id`.
        This also involves mocking the `factory` to return a mock target worker.
        """
        mock_target_worker = Mock(spec=Agent)
        mock_target_worker.get_from_inventory.return_value = "retrieved_value"
        self.mock_factory.get_worker_by_id.return_value = mock_target_worker

        value = self.worker.get_from_inventory_by_id("target_worker_id", "query_key", default="fallback")

        self.mock_factory.get_worker_by_id.assert_called_once_with("target_worker_id")
        mock_target_worker.get_from_inventory.assert_called_once_with("query_key", "fallback")
        self.assertEqual(value, "retrieved_value")

    def test_get_from_inventory_by_id_worker_not_found(self):
        """
        Test getting from inventory by ID when the target worker cannot be resolved.
        It should return the specified default value.
        """
        self.mock_factory.get_worker_by_id.return_value = None

        value = self.worker.get_from_inventory_by_id("non_existent_worker", "key", default="fallback")

        self.mock_factory.get_worker_by_id.assert_called_once_with("non_existent_worker")
        self.assertEqual(value, "fallback")


if __name__ == "__main__":
    unittest.main()

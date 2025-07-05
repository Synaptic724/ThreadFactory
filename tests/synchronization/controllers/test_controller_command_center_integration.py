import unittest
import logging
from unittest.mock import MagicMock, patch

# Assuming the CommandCenter and its dependencies are in a reachable path.
# The following imports are based on the structure provided in the Canvas.
from thread_factory.agent.command_center import CommandCenter
from thread_factory.synchronization import SignalController
from thread_factory.agent.identity.types.agent import Agent

# Suppress logging output during tests for a cleaner console
logging.disable(logging.CRITICAL)


class TestCommandCenterSignalManagement(unittest.TestCase):
    """
    Test suite for managing internal SignalControllers within the CommandCenter.
    """

    def setUp(self):
        """
        Set up a new CommandCenter instance before each test.
        """
        # We patch the AgentBuilder to avoid dependency issues during CC initialization
        with patch('thread_factory.agent.identity.agent_builder.AgentBuilder'):
            self.cc = CommandCenter()

    def tearDown(self):
        """
        Clean up by disposing of the CommandCenter instance after each test.
        """
        if self.cc and not self.cc._disposed:
            self.cc.dispose()

    def test_add_signal_controller_creates_new(self):
        """
        Test that add_signal_controller creates a new controller if none is provided.
        """
        controller_name = "test_bus"
        self.assertEqual(len(self.cc.list_signal_controllers()), 0)

        new_controller = self.cc.add_signal_controller(controller_name)

        self.assertIsNotNone(new_controller)
        self.assertIsInstance(new_controller, SignalController)
        self.assertIn(controller_name, self.cc.list_signal_controllers())
        self.assertEqual(len(self.cc.list_signal_controllers()), 1)

    def test_add_existing_signal_controller(self):
        """
        Test that an existing SignalController instance can be added.
        """
        controller_name = "pre_existing_bus"
        existing_controller = SignalController()

        added_controller = self.cc.add_signal_controller(controller_name, controller=existing_controller)

        self.assertIs(added_controller, existing_controller)
        self.assertIn(controller_name, self.cc.list_signal_controllers())

    def test_add_duplicate_name_raises_error(self):
        """
        Test that adding a SignalController with a duplicate name raises a ValueError.
        """
        controller_name = "duplicate_bus"
        self.cc.add_signal_controller(controller_name)

        with self.assertRaises(ValueError):
            self.cc.add_signal_controller(controller_name)

    def test_get_signal_controller(self):
        """
        Test retrieving a SignalController by its name.
        """
        controller_name = "retrieval_bus"
        # Test getting a non-existent controller
        self.assertIsNone(self.cc.get_signal_controller(controller_name))

        # Add a controller and then get it
        added_controller = self.cc.add_signal_controller(controller_name)
        retrieved_controller = self.cc.get_signal_controller(controller_name)

        self.assertIsNotNone(retrieved_controller)
        self.assertIs(added_controller, retrieved_controller)

    def test_list_signal_controllers(self):
        """
        Test that list_signal_controllers returns the correct names.
        """
        self.assertEqual(self.cc.list_signal_controllers(), [])

        names = ["bus_alpha", "bus_beta", "bus_gamma"]
        for name in names:
            self.cc.add_signal_controller(name)

        listed_names = self.cc.list_signal_controllers()
        self.assertCountEqual(listed_names, names)

    def test_remove_signal_controller_with_dispose(self):
        """
        Test removing a controller and ensuring its dispose method is called by default.
        """
        controller_name = "disposable_bus"
        mock_controller = MagicMock(spec=SignalController)

        self.cc.add_signal_controller(controller_name, controller=mock_controller)
        self.assertIn(controller_name, self.cc.list_signal_controllers())

        was_removed = self.cc.remove_signal_controller(controller_name)

        self.assertTrue(was_removed)
        self.assertNotIn(controller_name, self.cc.list_signal_controllers())
        mock_controller.dispose.assert_called_once()

    def test_remove_signal_controller_without_dispose(self):
        """
        Test removing a controller with dispose=False.
        """
        controller_name = "non_disposable_bus"
        mock_controller = MagicMock(spec=SignalController)

        self.cc.add_signal_controller(controller_name, controller=mock_controller)

        was_removed = self.cc.remove_signal_controller(controller_name, dispose=False)

        self.assertTrue(was_removed)
        self.assertNotIn(controller_name, self.cc.list_signal_controllers())
        mock_controller.dispose.assert_not_called()

    def test_remove_non_existent_controller(self):
        """
        Test that attempting to remove a non-existent controller returns False.
        """
        was_removed = self.cc.remove_signal_controller("non_existent_bus")
        self.assertFalse(was_removed)

    def test_command_center_dispose_cascades_to_controllers(self):
        """
        Test that disposing the CommandCenter also disposes all its internal controllers.
        """
        mock_controller_1 = MagicMock(spec=SignalController)
        mock_controller_2 = MagicMock(spec=SignalController)

        self.cc.add_signal_controller("bus_1", controller=mock_controller_1)
        self.cc.add_signal_controller("bus_2", controller=mock_controller_2)

        # Dispose the main command center
        self.cc.dispose()

        # Check that each internal controller's dispose method was called
        mock_controller_1.dispose.assert_called_once()
        mock_controller_2.dispose.assert_called_once()


class TestCommandCenterExternalSignalIntegration(unittest.TestCase):
    """
    Test suite for the integration where an external SignalController
    controls the CommandCenter.
    """

    def setUp(self):
        """
        Set up a CommandCenter with a mocked external SignalController.
        """
        self.mock_external_controller = MagicMock(spec=SignalController)
        # Patch the AgentBuilder to avoid dependency issues during CC initialization
        with patch('thread_factory.agent.identity.agent_builder.AgentBuilder'):
            self.cc = CommandCenter(
                external_signal_controller=self.mock_external_controller
            )

    def tearDown(self):
        """
        Clean up by disposing of the CommandCenter instance after each test.
        """
        if self.cc and not self.cc._disposed:
            self.cc.dispose()

    def test_init_registers_with_external_controller(self):
        """
        Test that CommandCenter registers itself with the external controller on init.
        """
        self.mock_external_controller.register.assert_called_once_with(self.cc)

    def test_dispose_unregisters_from_external_controller(self):
        """
        Test that CommandCenter unregisters itself on dispose.
        """
        cc_id = self.cc.id
        self.cc.dispose()
        self.mock_external_controller.unregister.assert_called_once_with(cc_id, dispose_object=False)

    def test_get_object_details_returns_valid_contract(self):
        """
        Test that _get_object_details returns the correct structure for registration.
        """
        details = self.cc._get_object_details()
        self.assertIn("name", details)
        self.assertEqual(details["name"], "command_center")
        self.assertIn("commands", details)
        self.assertIsInstance(details["commands"], dict)
        # Check if a key command is correctly mapped
        self.assertIs(details["commands"]["create_agent"], self.cc.create_agent)

    @patch('thread_factory.agent.identity.agent_builder.AgentBuilder.create_agent')
    def test_notify_on_agent_created(self, mock_create_agent):
        """
        Test that AGENT_CREATED event is notified.
        """
        # We need a mock agent that has the necessary attributes
        mock_agent = MagicMock(spec=Agent)
        mock_agent.factory_id = "agent_123"
        # The agent's name property is used in the notification
        type(mock_agent).name = "test_template"
        mock_create_agent.return_value = mock_agent

        self.cc.register_template("test_template", MagicMock())
        agent = self.cc.create_agent("test_template")

        self.mock_external_controller.notify.assert_any_call(
            self.cc.id,
            'AGENT_CREATED',
            {'agent_id': 'agent_123', 'template_name': 'test_template'}
        )

    @patch('thread_factory.agent.identity.agent_builder.AgentBuilder.create_agent')
    def test_notify_on_agent_unregistered(self, mock_create_agent):
        """
        Test that AGENT_UNREGISTERED event is notified.
        """
        mock_agent = MagicMock(spec=Agent)
        mock_agent.factory_id = "agent_123"
        mock_create_agent.return_value = mock_agent

        self.cc.register_template("test_template", MagicMock())
        agent = self.cc.create_agent("test_template")

        # Reset mock to ignore notifications from creation
        self.mock_external_controller.notify.reset_mock()

        # Directly call the internal method that should trigger the notification
        self.cc._unregister_agent(agent)

        self.mock_external_controller.notify.assert_called_with(
            self.cc.id,
            'AGENT_UNREGISTERED',
            {'agent_id': 'agent_123'}
        )

    def test_notify_on_config_changed(self):
        """
        Test that CONFIG_CHANGED event is notified when max_workers is changed.
        """
        initial_workers = self.cc._max_workers
        self.cc.increase_max_workers(5)

        self.mock_external_controller.notify.assert_called_with(
            self.cc.id,
            'CONFIG_CHANGED',
            {'setting': 'max_workers', 'new_value': initial_workers + 5}
        )

        self.cc.decrease_max_workers(2)
        self.mock_external_controller.notify.assert_called_with(
            self.cc.id,
            'CONFIG_CHANGED',
            {'setting': 'max_workers', 'new_value': initial_workers + 3}
        )

    @patch('thread_factory.agent.identity.agent_builder.AgentBuilder.create_agent')
    def test_notify_on_worker_cap_reached(self, mock_create_agent):
        """
        Test that WORKER_CAP_REACHED event is notified.
        """
        self.cc._max_workers = 0
        self.cc.register_template("test", MagicMock())

        with self.assertRaises(RuntimeError):
            self.cc.create_agent("test")

        self.mock_external_controller.notify.assert_called_with(
            self.cc.id,
            'WORKER_CAP_REACHED',
            {'max_workers': 0}
        )

    def test_notify_on_template_management(self):
        """
        Test notifications for template registration and unregistration.
        """
        self.cc.register_template("new_template", MagicMock())
        self.mock_external_controller.notify.assert_called_with(
            self.cc.id,
            'TEMPLATE_REGISTERED',
            {'template_name': 'new_template'}
        )

        self.cc.unregister_template("new_template")
        self.mock_external_controller.notify.assert_called_with(
            self.cc.id,
            'TEMPLATE_UNREGISTERED',
            {'template_name': 'new_template'}
        )

    def test_notify_on_internal_controller_management(self):
        """
        Test notifications for internal signal controller management.
        """
        self.cc.add_signal_controller("internal_bus")
        self.mock_external_controller.notify.assert_called_with(
            self.cc.id,
            'SIGNAL_CONTROLLER_ADDED',
            {'controller_name': 'internal_bus'}
        )

        self.cc.remove_signal_controller("internal_bus")
        self.mock_external_controller.notify.assert_called_with(
            self.cc.id,
            'SIGNAL_CONTROLLER_REMOVED',
            {'controller_name': 'internal_bus'}
        )


if __name__ == '__main__':
    unittest.main(verbosity=2)

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from thread_factory.utils.disposable import Disposable

# TODO: Remember that this DAG system is not adapted for parallelization. It sequentially executes work.


class StateObject(Disposable):
    """
    Thread-safe state object that references a Directed Acyclic Graph (DAG)
    for dynamic modifications during execution.

    Inherits from 'Disposable' (presumably a base class for managing resource cleanup)
    to align with an existing disposal pattern in the codebase.

    This object acts as a central hub for recording the execution status of nodes
    in the DAG and allows for modifications to the DAG structure based on these statuses.
    """
    def __init__(self, dag):
        """
        Initializes the StateObject with a reference to the DAG.

        Args:
            dag: An instance of the DAG class that this StateObject will manage.
        """
        super().__init__()  # Initialize the Disposable base class
        self._dag = dag  # Store a reference to the DAG
        self._execution_data = {}  # Dictionary to store the execution status of each node (node_id: status)
        self._state_lock = threading.RLock()  # Reentrant lock for thread-safe access to the state
        self.disposed = False  # Flag indicating if the object has been disposed

    def register_node_result(self, node_id, success=True):
        """
        Records the execution result of a node.

        If a node fails, this method will also remove the node and its associated
        edges from the DAG, effectively preventing any further processing of that
        branch of the graph.

        Args:
            node_id: The unique identifier of the node.
            success: A boolean indicating whether the node execution was successful (True) or not (False).
        """
        with self._state_lock:  # Acquire the lock to ensure thread-safe modification of the state
            if success:
                self._execution_data[node_id] = "SUCCESS"  # Mark the node as successfully executed
            else:
                self._execution_data[node_id] = "FAILED"  # Mark the node as failed
                self.remove_node_and_edges(node_id)  # If it failed, remove it from the DAG

    def remove_node_and_edges(self, node_id):
        """
        Removes a node and all its incoming and outgoing edges from the DAG.

        This method is called when a node fails to execute, effectively 'cutting it off'
        from the rest of the DAG and preventing any dependent nodes from being processed.

        Args:
            node_id: The unique identifier of the node to remove.
        """
        node = self._dag.find_node_by_id(node_id)  # Find the node object in the DAG
        if node:
            self._dag.remove_node(node)  # Remove the node from the DAG
            print(f"[StateObject] Removed node {node_id} and its edges from the DAG.")

    def recalc_topological_order(self):
        """
        Recomputes the topological order of the nodes in the DAG.

        This method should be called if the DAG structure has been modified (e.g.,
        nodes or edges have been removed) and a fresh topological order is needed
        for subsequent scheduling or processing.

        Returns:
            A list of nodes in topological order.
        """
        with self._state_lock:  # Acquire the lock for thread-safe access to the DAG
            # Just recompute a new topological order on the DAG
            new_order = self._dag.topological_sort()
            return new_order

    def get_status(self, node_id):
        """
        Retrieves the current execution status of a specific node.

        Args:
            node_id: The unique identifier of the node.

        Returns:
            A string representing the status of the node ("SUCCESS", "FAILED", or "UNKNOWN" if not yet recorded).
        """
        with self._state_lock:  # Acquire the lock for thread-safe access to the execution data
            return self._execution_data.get(node_id, "UNKNOWN")  # Return the status or "UNKNOWN" if not found

    def get_all_statuses(self):
        """
        Returns a snapshot of the execution status of all nodes.

        Returns:
            A dictionary where keys are node IDs and values are their corresponding statuses.
        """
        with self._state_lock:  # Acquire the lock for thread-safe access to the execution data
            return dict(self._execution_data)  # Return a copy of the status dictionary

    def dispose(self):
        """
        Disposes of the StateObject, releasing any held resources.

        This method is part of the 'Disposable' pattern and is called to clean up
        the object when it is no longer needed. It clears the execution data and
        removes the reference to the DAG to prevent memory leaks.
        """
        if self.disposed:  # Prevent double disposal
            return
        with self._state_lock:  # Acquire the lock for thread-safe access during disposal
            self._execution_data.clear()  # Clear the dictionary of execution statuses
            self._dag = None  # Remove the reference to the DAG
            self.disposed = True  # Mark the object as disposed
        print("[StateObject] Disposal complete.")



class ExecutionContext(Disposable):
    """
    Abstract base class for defining the 'work to be done' within a Node.

    Each concrete subclass of ExecutionContext should implement the 'execute()'
    method, which contains the specific logic for the task associated with a node.

    An ExecutionContext has a reference to a shared 'state' (an instance of StateObject)
    which allows it to report its execution status or read global data related to
    the DAG execution.

    This class also adheres to the 'Disposable' pattern for resource management.
    """
    def __init__(self, state: StateObject):
        """
        Initializes the ExecutionContext with a reference to the shared StateObject.

        Args:
            state: The shared StateObject instance.
        """
        self.state = state  # Store a reference to the shared state object
        self.disposed = False  # Flag indicating if the object has been disposed
        self._dispose_lock = threading.RLock()  # Lock for thread-safe disposal

    def execute(self):
        """
        Abstract method that must be implemented by subclasses.

        This method contains the core logic of the task associated with a node.
        """
        raise NotImplementedError("Subclasses must override the execute() method.")

    def dispose(self):
        """
        Safely disposes of the ExecutionContext, releasing resources.

        This method ensures that the disposal logic is executed only once and
        that the reference to the StateObject is cleared.
        """
        with self._dispose_lock:  # Acquire the lock for thread-safe disposal
            if not self.disposed:  # Check if already disposed
                self.state = None  # Remove the reference to the StateObject
                self.disposed = True  # Mark as disposed

    def __enter__(self):
        """
        Allows the ExecutionContext to be used as a context manager (e.g., with statement).
        Returns the instance itself upon entering the context.
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Context manager exit method. Calls the dispose method when exiting the context,
        ensuring resources are cleaned up.
        """
        self.dispose()

    def __del__(self):
        """
        Fallback disposal method (destructor).

        In Python, __del__ is not guaranteed to be called reliably, but it's included
        for completeness as a last resort for resource cleanup.
        """
        self.dispose()


class Node(Disposable):
    """
    Represents a node in the Directed Acyclic Graph (DAG).

    Each node can have incoming and outgoing edges, representing dependencies
    and the flow of execution. A node can also have a list of tasks (simple
    callable objects) and an associated ExecutionContext that defines more
    complex execution logic.

    This class is thread-safe using a reentrant lock to protect its internal state.
    """
    def __init__(self, node_id):
        """
        Initializes a Node with a unique identifier.

        Args:
            node_id: The unique identifier for this node (e.g., a string).
        """
        super().__init__()  # Initialize the Disposable base class
        self.id = node_id  # Unique identifier of the node
        self.disposed = False  # Flag indicating if the node has been disposed
        self._lock = threading.RLock()  # Reentrant lock for thread-safe access to node data

        # Data structures to manage connections and tasks
        self._incoming_edges = []  # List of Edge objects pointing to this node
        self._outgoing_edges = []  # List of Edge objects originating from this node
        self._tasks = []  # List of callable objects (tasks) to be executed by this node
        self._execution_context = None  # Optional ExecutionContext for more complex logic

    def set_execution_context(self, context: ExecutionContext):
        """
        Sets the ExecutionContext for this node.

        Args:
            context: An instance of an ExecutionContext subclass.
        """
        with self._lock:  # Acquire the lock for thread-safe modification
            self._execution_context = context

    def get_execution_context(self):
        """
        Retrieves the current ExecutionContext of this node.

        Returns:
            The ExecutionContext instance associated with this node, or None if not set.
        """
        with self._lock:  # Acquire the lock for thread-safe access
            return self._execution_context

    def add_incoming_edge(self, edge):
        """
        Adds an incoming edge to this node.

        Args:
            edge: An instance of the Edge class pointing to this node.
        """
        with self._lock:  # Acquire the lock for thread-safe modification
            self._incoming_edges.append(edge)

    def remove_incoming_edge(self, edge):
        """
        Removes an incoming edge from this node.

        Args:
            edge: The Edge object to remove.
        """
        with self._lock:  # Acquire the lock for thread-safe modification
            if edge in self._incoming_edges:
                self._incoming_edges.remove(edge)

    def add_outgoing_edge(self, edge):
        """
        Adds an outgoing edge from this node.

        Args:
            edge: An instance of the Edge class originating from this node.
        """
        with self._lock:  # Acquire the lock for thread-safe modification
            self._outgoing_edges.append(edge)

    def remove_outgoing_edge(self, edge):
        """
        Removes an outgoing edge from this node.

        Args:
            edge: The Edge object to remove.
        """
        with self._lock:  # Acquire the lock for thread-safe modification
            if edge in self._outgoing_edges:
                self._outgoing_edges.remove(edge)

    def get_incoming_edges(self):
        """
        Retrieves a list of all incoming edges to this node.

        Returns:
            A new list containing the incoming Edge objects.
        """
        with self._lock:  # Acquire the lock for thread-safe access
            return list(self._incoming_edges)  # Return a copy to prevent external modification

    def get_outgoing_edges(self):
        """
        Retrieves a list of all outgoing edges from this node.

        Returns:
            A new list containing the outgoing Edge objects.
        """
        with self._lock:  # Acquire the lock for thread-safe access
            return list(self._outgoing_edges)  # Return a copy to prevent external modification

    def add_task(self, task):
        """
        Adds a simple task (a callable object) to be executed by this node.

        Args:
            task: A callable object (e.g., a function or a lambda).
        """
        with self._lock:  # Acquire the lock for thread-safe modification
            self._tasks.append(task)

    def execute_tasks(self):
        """
        Executes all the tasks associated with this node and its ExecutionContext.

        This method first executes all the simple tasks added via 'add_task' and
        then, if an ExecutionContext is set, it calls the 'execute()' method of the context.
        The simple tasks are executed without holding the lock to allow for potential
        parallelism or long-running operations within the tasks themselves. The
        ExecutionContext's execution happens after the simple tasks.
        """
        with self._lock:  # Acquire the lock to get a copy of the tasks and the context
            tasks_copy = list(self._tasks)  # Create a copy of the tasks to avoid issues if the list is modified during execution
            context = self._execution_context

        # First execute all tasks without holding the lock
        for task in tasks_copy:
            task()

        # Then execute context if present
        if context is not None:
            context.execute()

    def execute(self, execute_internally=False):
        """
        Executes the tasks and optionally triggers the execution of the next node
        in a simple sequential manner (if there is only one outgoing edge).

        Args:
            execute_internally: A boolean flag indicating whether to automatically
                                trigger the execution of the next node. This is a
                                basic form of sequential execution within the node.
        """
        self.execute_tasks()
        if execute_internally:
            next_node = self.get_next_node()
            if next_node:
                next_node.execute(execute_internally=True)

    def get_next_node(self):
        """
        Gets the next node in the sequence based on the outgoing edges.

        This method assumes a simple linear flow where a node has at most one
        outgoing edge. If there are multiple or no outgoing edges, it returns None.

        Returns:
            The next Node object in the sequence, or None if there isn't one.
        """
        with self._lock:  # Acquire the lock for thread-safe access
            return self._outgoing_edges[0].to_node if self._outgoing_edges else None

    def find_target_node(self, target_id):
        """
        Finds a directly connected target node based on its ID.

        This method iterates through the outgoing edges of the current node and
        returns the 'to_node' of the first edge that points to a node with the
        specified ID.

        Args:
            target_id: The ID of the target node to find.

        Returns:
            The target Node object if found, otherwise None.
        """
        with self._lock:  # Acquire the lock for thread-safe access to outgoing edges
            for edge in self._outgoing_edges:
                if edge.to_node.id == target_id:
                    return edge.to_node
        return None

    def dispose(self):
        """
        Disposes of the Node, releasing references to edges, tasks, and the
        execution context.
        """
        with self._lock:  # Acquire the lock for thread-safe disposal
            self._incoming_edges.clear()  # Clear the list of incoming edges
            self._outgoing_edges.clear()  # Clear the list of outgoing edges
            self._tasks.clear()  # Clear the list of tasks
            if self._execution_context is not None:
                self._execution_context.dispose()  # Dispose of the execution context if it exists
            self._execution_context = None  # Remove the reference to the execution context
            self.disposed = True  # Mark the node as disposed


class Edge(Disposable):
    """
    Represents a directed edge in the DAG, connecting two nodes.

    Each edge has a 'from_node' (the source) and a 'to_node' (the destination).
    It also adheres to the 'Disposable' pattern for resource management.
    """
    def __init__(self, from_node, to_node):
        """
        Initializes an Edge with references to the source and destination nodes.

        Args:
            from_node: The Node object where the edge originates.
            to_node: The Node object where the edge points to.
        """
        super().__init__()  # Initialize the Disposable base class
        self.disposed = False  # Flag indicating if the edge has been disposed
        self.from_node = from_node  # The source node of the edge
        self.to_node = to_node  # The destination node of the edge
        self._edge_lock = threading.RLock()  # Lock for thread-safe disposal

    def dispose(self):
        """
        Disposes of the Edge, releasing references to the connected nodes.
        """
        if self.dispose:  # Prevent double disposal (typo in original code, should be self.disposed)
            return
        with self._edge_lock:  # Acquire the lock for thread-safe disposal
            self.disposed = True  # Mark the edge as disposed
            self.from_node = None  # Remove the reference to the source node
            self.to_node = None  # Remove the reference to the destination node

class DirectedAcyclicWorkGraph(Disposable):
    """
    Represents a Directed Acyclic Graph (DAG) composed of nodes and edges.

    This class provides methods for adding, removing, and retrieving nodes and
    edges, as well as for performing a topological sort and executing the tasks
    within the nodes in different ways (sequentially or in parallel layers).

    It also implements the 'Disposable' pattern for cleaning up resources.
    """
    def __init__(self):
        """
        Initializes an empty DAG.
        """
        super().__init__()  # Initialize the Disposable base class
        # Data structures to store nodes and edges
        self._nodes = {}  # Dictionary to store nodes (node_id: Node object)
        self._edges = []  # List to store Edge objects
        self._lock = threading.RLock()  # Reentrant lock for thread-safe access to the DAG's data structures
        self.disposed = False  # Flag indicating if the DAG has been disposed

    def add_node(self, node):
        """
        Adds a node to the DAG.

        Args:
            node: An instance of the Node class to add.
        """
        with self._lock:  # Acquire the lock for thread-safe modification of the nodes dictionary
            if node.id not in self._nodes:
                self._nodes[node.id] = node

    def remove_node(self, node):
        """
        Removes a node and all its associated incoming and outgoing edges from the DAG.

        Args:
            node: The Node object to remove.
        """
        with self._lock:  # Acquire the lock for thread-safe modification of nodes and edges
            if node.id in self._nodes:
                # Remove edges connected to this node by filtering the edges list
                self._edges = [
                    e for e in self._edges
                    if e.from_node != node and e.to_node != node
                ]
                del self._nodes[node.id]

    def add_edge(self, edge):
        """
        Adds a directed edge to the DAG, connecting two nodes.

        Args:
            edge: An instance of the Edge class to add. The source and destination
                  nodes of the edge must already be present in the DAG.
        """
        with self._lock:  # Acquire the lock for thread-safe modification of edges and node connections
            if (edge.from_node.id in self._nodes and
                    edge.to_node.id in self._nodes):
                self._edges.append(edge)
                edge.from_node.add_outgoing_edge(edge)  # Update the outgoing edges of the source node
                edge.to_node.add_incoming_edge(edge)    # Update the incoming edges of the destination node

    def remove_edge(self, edge):
        """
        Removes a specific edge from the DAG.

        Args:
            edge: The Edge object to remove.
        """
        with self._lock:  # Acquire the lock for thread-safe modification of the edges list
            if edge in self._edges:
                self._edges.remove(edge)
        edge.from_node.remove_outgoing_edge(edge)  # Update the outgoing edges of the source node
        edge.to_node.remove_incoming_edge(edge)    # Update the incoming edges of the destination node

    def get_nodes(self):
        """
        Retrieves a list of all nodes in the DAG.

        Returns:
            A new list containing all Node objects in the DAG.
        """
        with self._lock:  # Acquire the lock for thread-safe access to the nodes dictionary
            return list(self._nodes.values())

    def get_edges(self):
        """
        Retrieves a list of all edges in the DAG.

        Returns:
            A new list containing all Edge objects in the DAG.
        """
        with self._lock:  # Acquire the lock for thread-safe access to the edges list
            return list(self._edges)

    def find_node_by_id(self, node_id):
        """
        Finds a node in the DAG based on its unique identifier.

        Args:
            node_id: The ID of the node to find.

        Returns:
            The Node object with the given ID, or None if not found.
        """
        with self._lock:  # Acquire the lock for thread-safe access to the nodes dictionary
            return self._nodes.get(node_id, None)

    def topological_sort(self):
        """
        Performs a topological sort of the nodes in the DAG.

        A topological sort produces a linear ordering of nodes such that for every
        directed edge from node A to node B, node A comes before node B in the
        ordering. This is useful for determining a valid execution order for the
        nodes in the DAG.

        Raises:
            ValueError: If the graph contains a cycle (and is therefore not a DAG).

        Returns:
            A list of Node objects in topological order.
        """
        with self._lock:  # Acquire the lock to get a copy of the nodes
            nodes_copy = list(self._nodes.values())

        sorted_list = []  # List to store the topologically sorted nodes
        visited = set()  # Set to keep track of visited nodes
        temp_marked = set()  # Set to detect cycles

        def visit(node):
            """
            Recursive helper function for the topological sort.
            """
            if node in temp_marked:
                raise ValueError("Graph is not a DAG (cycle detected).")
            if node not in visited:
                temp_marked.add(node)
                for edge in node.get_outgoing_edges():
                    visit(edge.to_node)
                temp_marked.remove(node)
                visited.add(node)
                sorted_list.append(node)

        for node in nodes_copy:
            if node not in visited:
                visit(node)

        sorted_list.reverse()  # Reverse the list to get the correct topological order
        return sorted_list

    def execute(self):
        """
        Executes all nodes in the DAG in a sequential manner based on their
        topological order.

        This method first performs a topological sort to determine the correct
        execution order and then iterates through the sorted nodes, calling the
        'execute_tasks()' method of each node.
        """
        sorted_nodes = self.topological_sort()  # Get the nodes in topological order
        for node in sorted_nodes:
            node.execute_tasks()  # Execute the tasks associated with each node

    def execute_layered(self, max_workers=4):
        """
        Executes the nodes in the DAG in parallel layers using a breadth-first search (BFS) approach.

        This method identifies nodes with no incoming dependencies (in-degree of 0) as the
        first layer. These nodes are executed in parallel using a thread pool. Once all
        nodes in a layer have finished, the method identifies the next layer of nodes
        whose dependencies have been met and executes them in parallel, and so on.

        Args:
            max_workers: The maximum number of threads to use for parallel execution.
        """
        # Build an in-degree map: how many incoming edges each node has
        with self._lock:  # Acquire the lock to get a list of nodes
            nodes_list = list(self._nodes.values())

        in_degree = {}  # Dictionary to store the in-degree of each node
        for node in nodes_list:
            # number of incoming edges
            in_degree[node] = len(node.get_incoming_edges())

        # Start with all nodes that have no dependencies (in-degree = 0)
        current_wave = [n for n in nodes_list if in_degree[n] == 0]

        # We'll use a BFS layering approach with a thread pool
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            while current_wave:
                # 1) Run current_wave in parallel
                futures = {executor.submit(n.execute_tasks): n for n in current_wave}

                # 2) Wait for all to finish
                for future in as_completed(futures):
                    finished_node = futures[future]
                    for edge in finished_node.get_outgoing_edges():
                        child = edge.to_node
                        in_degree[child] -= 1  # Decrement the in-degree of the child nodes

                # 3) Clear out the current wave from in_degree (or mark them as done)
                for node in current_wave:
                    if node in in_degree:
                        del in_degree[node]

                # 4) Build next_wave: find nodes whose in-degree has become 0
                next_wave = [n for (n, deg) in in_degree.items() if deg == 0]

                # 5) current_wave = next_wave
                current_wave = next_wave

    def generate_dot_file(self, file_path):
        """
        Generates a .dot file representation of the DAG for visualization using tools like Graphviz.

        The .dot file describes the nodes and edges of the graph in a format that can be
        rendered into a visual diagram.

        Args:
            file_path: The path to the file where the .dot representation will be written.
        """
        with self._lock:  # Acquire the lock to get a copy of the edges
            edges_copy = list(self._edges)

        with open(file_path, 'w') as writer:
            writer.write("digraph G {\n")  # Start of the .dot file content
            for edge in edges_copy:
                writer.write(f'    "{edge.from_node.id}" -> "{edge.to_node.id}";\n')  # Write an edge definition
            writer.write("}\n")  # End of the .dot file content

    def dispose(self):
        """
        Disposes of all nodes and edges in the DAG, releasing their resources.
        """
        if self.disposed:  # Prevent double disposal
            return
        with self._lock:  # Acquire the lock for thread-safe disposal
            for node in self._nodes.values():
                node.dispose()  # Dispose of each node
            self._nodes.clear()  # Clear the dictionary of nodes

            for edge in self._edges:
                edge.dispose()  # Dispose of each edge
            self._edges.clear()  # Clear the list of edges

            self.disposed = True  # Mark the DAG as disposed


# # Assume Node, Edge, ExecutionContext, etc. are defined
# def more_complex_usage():
#     # Create a DAG
#     dag = DAG()
#
#     # Create nodes
#     node_a = Node("A")
#     node_b = Node("B")
#     node_c = Node("C")
#     node_d = Node("D")
#     node_e = Node("E")
#     node_f = Node("F")
#
#     # Add them
#     dag.add_node(node_a)
#     dag.add_node(node_b)
#     dag.add_node(node_c)
#     dag.add_node(node_d)
#     dag.add_node(node_e)
#     dag.add_node(node_f)
#
#     # Add tasks (just simple print statements for illustration)
#     node_a.add_task(lambda: print("[A] Doing A's work"))
#     node_b.add_task(lambda: print("[B] Doing B's work"))
#     node_c.add_task(lambda: print("[C] Doing C's work (depends on A, B)"))
#     node_d.add_task(lambda: print("[D] Doing D's work (depends on C)"))
#     node_e.add_task(lambda: print("[E] Doing E's work (depends on B)"))
#     node_f.add_task(lambda: print("[F] Doing F's work (depends on D and E)"))
#
#     """
#     Dependencies:
#         A -> C
#         B -> C
#         C -> D
#         B -> E
#         D -> F
#         E -> F
#
#     Visually something like:
#
#          A      B
#           \    / \
#            \  /   \
#             C      E
#             |       \
#             D ------- F
#
#     Wave (layer) conceptually:
#     - Wave 0: A, B  (both have no incoming edges)
#     - Wave 1: C, E  (C depends on A & B, E depends on B)
#     - Wave 2: D     (depends on C)
#     - Wave 3: F     (depends on D & E)
#     """
#
#     # Add edges
#     dag.add_edge(Edge(node_a, node_c))  # A->C
#     dag.add_edge(Edge(node_b, node_c))  # B->C
#     dag.add_edge(Edge(node_c, node_d))  # C->D
#     dag.add_edge(Edge(node_b, node_e))  # B->E
#     dag.add_edge(Edge(node_d, node_f))  # D->F
#     dag.add_edge(Edge(node_e, node_f))  # E->F
#
#     print("=== Sequential Run on Larger DAG ===")
#     dag.execute()  # Sequential topological run
#
#     print("\n=== Parallel BFS Layering Run on Larger DAG ===")
#     dag.execute_layered(max_workers=3)  # Up to 3 tasks can run in parallel
#
#
#
#
# more_complex_usage()
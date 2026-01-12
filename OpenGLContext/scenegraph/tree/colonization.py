"""Space colonization algorithm for procedural tree generation

Implements the space colonization algorithm as described in:
"Modeling Trees with a Space Colonization Algorithm" by Runions et al.

The algorithm works by:
1. Distributing attractor points in a crown volume
2. Growing branches toward attractors
3. Removing attractors when branches get close enough
4. Computing branch radii based on child branches
"""
import random
import math
import numpy as np

from vrml.vrml97 import tree as tree_nodes


class SpaceColonizationTree:
    """Generate tree structure using space colonization algorithm

    Uses VRML nodes (TreeNode, TreeAttractor, TreeParameters) for
    all data storage, allowing trees to be saved/loaded from VRML files.
    """

    def __init__(self, parameters=None):
        """Initialize tree generator

        Args:
            parameters: TreeParameters node, or None for defaults
        """
        if parameters is None:
            parameters = tree_nodes.TreeParameters()
        self.params = parameters
        self.nodes = []  # List of TreeNode nodes
        self.attractors = []  # List of TreeAttractor nodes
        self.root = None  # Root TreeNode

    def generate(self, max_iterations=500, seed=None):
        """Generate complete tree structure

        Args:
            max_iterations: Maximum growth iterations
            seed: Random seed (None for random)

        Returns:
            List of TreeNode nodes forming the tree skeleton
        """
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)

        self._initialize_trunk()
        self._distribute_attractors()

        for iteration in range(max_iterations):
            if not self._grow_step():
                break

        self._calculate_radii()
        return self.nodes

    def _initialize_trunk(self):
        """Create initial trunk segment(s) leading to crown"""
        base_pos = np.array(self.params.basePosition, dtype=np.float32)
        trunk_dir = np.array(self.params.trunkDirection, dtype=np.float32)
        trunk_dir = trunk_dir / np.linalg.norm(trunk_dir)

        crown_offset = float(self.params.crownOffset)
        segment_length = float(self.params.segmentLength)

        # Create root node
        self.root = tree_nodes.TreeNode()
        self.root.position = base_pos.tolist()
        self.root.depth = 0
        self.nodes.append(self.root)

        # Grow trunk up to crown
        current = self.root
        distance = 0.0
        depth = 0

        while distance < crown_offset:
            depth += 1
            new_pos = base_pos + trunk_dir * (distance + segment_length)

            new_node = tree_nodes.TreeNode()
            new_node.position = new_pos.tolist()
            new_node.parent = current
            new_node.depth = depth

            # Add as child of current
            children = list(current.children)
            children.append(new_node)
            current.children = children

            self.nodes.append(new_node)
            current = new_node
            distance += segment_length

    def _distribute_attractors(self):
        """Distribute attractor points in crown volume"""
        base_pos = np.array(self.params.basePosition, dtype=np.float32)
        trunk_dir = np.array(self.params.trunkDirection, dtype=np.float32)
        trunk_dir = trunk_dir / np.linalg.norm(trunk_dir)

        crown_offset = float(self.params.crownOffset)
        crown_radius = float(self.params.crownRadius)
        crown_shape = str(self.params.crownShape)
        attractor_count = int(self.params.attractorCount)
        bounding_size = np.array(self.params.boundingSize, dtype=np.float32)

        # Crown center
        crown_center = base_pos + trunk_dir * (crown_offset + crown_radius)

        self.attractors = []

        for _ in range(attractor_count):
            # Generate point in crown shape
            if crown_shape == 'sphere':
                point = self._random_point_in_sphere(crown_center, crown_radius)
            elif crown_shape == 'cone':
                point = self._random_point_in_cone(
                    crown_center - trunk_dir * crown_radius,
                    trunk_dir,
                    crown_radius * 2,
                    crown_radius
                )
            elif crown_shape == 'cylinder':
                point = self._random_point_in_cylinder(
                    crown_center,
                    trunk_dir,
                    crown_radius * 2,
                    crown_radius
                )
            elif crown_shape == 'ellipsoid':
                # Use bounding size for ellipsoid radii
                point = self._random_point_in_ellipsoid(
                    crown_center,
                    bounding_size / 2
                )
            else:
                point = self._random_point_in_sphere(crown_center, crown_radius)

            attractor = tree_nodes.TreeAttractor()
            attractor.position = point.tolist()
            attractor.active = True
            self.attractors.append(attractor)

    def _random_point_in_sphere(self, center, radius):
        """Generate random point uniformly distributed in sphere"""
        # Use rejection sampling for uniform distribution
        while True:
            point = np.random.uniform(-1, 1, 3)
            if np.linalg.norm(point) <= 1:
                return center + point * radius

    def _random_point_in_cone(self, apex, direction, height, base_radius):
        """Generate random point in cone volume"""
        direction = direction / np.linalg.norm(direction)

        # Random height along cone
        h = random.random() ** (1/3) * height  # Cube root for uniform volume

        # Radius at this height
        r = (h / height) * base_radius

        # Random angle and distance from axis
        theta = random.random() * 2 * math.pi
        dist = math.sqrt(random.random()) * r

        # Build orthonormal basis
        up = np.array([0, 1, 0])
        if abs(np.dot(direction, up)) > 0.9:
            up = np.array([1, 0, 0])
        right = np.cross(direction, up)
        right = right / np.linalg.norm(right)
        forward = np.cross(right, direction)

        offset = right * math.cos(theta) * dist + forward * math.sin(theta) * dist
        return apex + direction * h + offset

    def _random_point_in_cylinder(self, center, direction, height, radius):
        """Generate random point in cylinder volume"""
        direction = direction / np.linalg.norm(direction)

        # Random height
        h = (random.random() - 0.5) * height

        # Random position in circular cross-section
        theta = random.random() * 2 * math.pi
        dist = math.sqrt(random.random()) * radius

        # Build orthonormal basis
        up = np.array([0, 1, 0])
        if abs(np.dot(direction, up)) > 0.9:
            up = np.array([1, 0, 0])
        right = np.cross(direction, up)
        right = right / np.linalg.norm(right)
        forward = np.cross(right, direction)

        offset = right * math.cos(theta) * dist + forward * math.sin(theta) * dist
        return center + direction * h + offset

    def _random_point_in_ellipsoid(self, center, radii):
        """Generate random point in ellipsoid volume"""
        # Generate point in unit sphere, then scale
        while True:
            point = np.random.uniform(-1, 1, 3)
            if np.linalg.norm(point) <= 1:
                return center + point * radii

    def _grow_step(self):
        """Perform one growth iteration using vectorized numpy operations

        The algorithm:
        1. For each active attractor, find the closest node within attraction distance
        2. Each attractor influences only its closest node
        3. Each node that has influencing attractors grows one new branch toward
           the average direction of those attractors
        4. Kill attractors when any node gets within kill distance

        Returns:
            True if growth occurred, False if done
        """
        attraction_dist = float(self.params.attractionDistance)
        kill_dist = float(self.params.killDistance)
        segment_length = float(self.params.segmentLength)

        # Get active attractors as numpy array for vectorized operations
        active_mask = np.array([a.active for a in self.attractors])
        if not np.any(active_mask):
            return False

        active_indices = np.where(active_mask)[0]
        attractor_positions = np.array(
            [self.attractors[i].position for i in active_indices],
            dtype=np.float32
        )

        # Get all node positions as numpy array
        node_positions = np.array(
            [node.position for node in self.nodes],
            dtype=np.float32
        )

        # Compute all pairwise distances: nodes x attractors
        # Using broadcasting: (N, 1, 3) - (1, M, 3) = (N, M, 3)
        diff = node_positions[:, np.newaxis, :] - attractor_positions[np.newaxis, :, :]
        distances = np.linalg.norm(diff, axis=2)  # (N, M)

        # Find attractors to kill (any node within kill distance)
        min_dist_per_attractor = distances.min(axis=0)
        kill_mask = min_dist_per_attractor < kill_dist
        for i, idx in enumerate(active_indices):
            if kill_mask[i]:
                self.attractors[idx].active = False

        # For each attractor, find the closest node within attraction distance
        # Each attractor influences only ONE node - the closest one
        closest_node_per_attractor = distances.argmin(axis=0)  # (M,)

        # Only consider attractors within attraction distance of their closest node
        min_distances = distances[closest_node_per_attractor, np.arange(len(active_indices))]
        valid_attractors = (min_distances < attraction_dist) & ~kill_mask

        if not np.any(valid_attractors):
            return False

        # Group attractors by which node they influence
        node_to_attractors = {}  # node_idx -> list of attractor indices
        for attr_idx in np.where(valid_attractors)[0]:
            node_idx = closest_node_per_attractor[attr_idx]
            if node_idx not in node_to_attractors:
                node_to_attractors[node_idx] = []
            node_to_attractors[node_idx].append(attr_idx)

        # Grow new branches
        new_nodes = []

        for node_idx, attr_indices in node_to_attractors.items():
            node = self.nodes[node_idx]
            node_pos = node_positions[node_idx]

            # Compute directions to influencing attractors
            influencing_positions = attractor_positions[attr_indices]
            directions = influencing_positions - node_pos
            dir_lengths = np.linalg.norm(directions, axis=1, keepdims=True)
            dir_lengths = np.maximum(dir_lengths, 1e-6)  # Avoid division by zero
            normalized_directions = directions / dir_lengths

            # Average direction
            avg_direction = np.mean(normalized_directions, axis=0)
            avg_length = np.linalg.norm(avg_direction)
            if avg_length < 1e-6:
                continue
            avg_direction = avg_direction / avg_length

            # Create new node
            new_pos = node_pos + avg_direction * segment_length

            new_node = tree_nodes.TreeNode()
            new_node.position = new_pos.tolist()
            new_node.parent = node
            new_node.depth = node.depth + 1

            # Add as child
            children = list(node.children)
            children.append(new_node)
            node.children = children

            new_nodes.append(new_node)

        if new_nodes:
            self.nodes.extend(new_nodes)
            return True
        return False

    def _calculate_radii(self):
        """Calculate branch radii using pipe model

        Uses Leonardo da Vinci's rule: cross-sectional area of parent
        equals sum of children's cross-sectional areas.
        """
        initial_radius = float(self.params.initialRadius)
        radius_decay = float(self.params.radiusDecay)
        min_radius = float(self.params.minRadius)

        # Process nodes from leaves to root (reverse depth order)
        nodes_by_depth = {}
        for node in self.nodes:
            depth = node.depth
            if depth not in nodes_by_depth:
                nodes_by_depth[depth] = []
            nodes_by_depth[depth].append(node)

        max_depth = max(nodes_by_depth.keys()) if nodes_by_depth else 0

        # Start from leaves
        for depth in range(max_depth, -1, -1):
            if depth not in nodes_by_depth:
                continue
            for node in nodes_by_depth[depth]:
                children = list(node.children)
                if not children:
                    # Leaf node
                    node.radius = min_radius
                else:
                    # Sum of children's cross-sectional areas
                    child_area = sum(
                        math.pi * (child.radius ** 2)
                        for child in children
                    )
                    # Parent radius from area
                    node.radius = min(
                        initial_radius,
                        max(min_radius, math.sqrt(child_area / math.pi))
                    )

        # Apply decay from root
        if self.root:
            self.root.radius = initial_radius
            self._apply_radius_decay(self.root, radius_decay, min_radius)

    def _apply_radius_decay(self, node, decay, min_radius):
        """Recursively apply radius decay from parent to children"""
        parent_radius = node.radius
        for child in node.children:
            child.radius = max(min_radius, parent_radius * decay)
            self._apply_radius_decay(child, decay, min_radius)


def generate_tree(parameters=None, seed=None):
    """Convenience function to generate a tree

    Args:
        parameters: TreeParameters node or None for defaults
        seed: Random seed or None

    Returns:
        List of TreeNode nodes
    """
    generator = SpaceColonizationTree(parameters)
    return generator.generate(seed=seed)

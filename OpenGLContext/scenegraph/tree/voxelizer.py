"""Convert tree skeleton to 3D voxel texture

Takes a list of TreeNode nodes and generates a 3D numpy array
suitable for use as an OpenGL 3D texture for ray-marching.
"""
import numpy as np


class TreeVoxelizer:
    """Convert tree skeleton to 3D voxel volume

    The output volume contains:
    - R channel: branch/wood density (0-255)
    - G channel: leaf density (0-255)
    - B channel: distance from branch center (for shading)
    - A channel: combined density for ray-marching
    """

    def __init__(self, resolution=64):
        """Initialize voxelizer

        Args:
            resolution: Size of cubic volume (resolution^3 voxels)
        """
        self.resolution = resolution
        self.volume = None
        self.bounds_min = None
        self.bounds_max = None
        self.voxel_size = None

    def voxelize(self, nodes, leaf_density=0.3, leaf_cluster_size=0.4):
        """Convert tree nodes to voxel volume

        Args:
            nodes: List of TreeNode nodes
            leaf_density: Density of leaves at branch tips (0-1)
            leaf_cluster_size: Size of leaf clusters relative to voxel grid

        Returns:
            numpy array of shape (resolution, resolution, resolution, 4)
            with dtype uint8 (RGBA)
        """
        if not nodes:
            return np.zeros(
                (self.resolution, self.resolution, self.resolution, 4),
                dtype=np.uint8
            )

        # Calculate bounding box
        self._calculate_bounds(nodes)

        # Create empty volume
        self.volume = np.zeros(
            (self.resolution, self.resolution, self.resolution, 4),
            dtype=np.float32
        )

        # Voxelize each branch segment
        for node in nodes:
            # Check if parent exists and has position attribute
            # (pyvrml97 uses NullNode for default SFNode values)
            if node.parent and hasattr(node.parent, 'position'):
                self._voxelize_segment(node)

        # Add leaves at branch tips
        self._add_leaves(nodes, leaf_density, leaf_cluster_size)

        # Normalize and convert to uint8
        # R = wood, G = leaves, B = distance info, A = combined
        result = np.zeros_like(self.volume, dtype=np.uint8)

        # Clamp and scale wood density
        wood = np.clip(self.volume[:, :, :, 0], 0, 1)
        result[:, :, :, 0] = (wood * 255).astype(np.uint8)

        # Clamp and scale leaf density
        leaves = np.clip(self.volume[:, :, :, 1], 0, 1)
        result[:, :, :, 1] = (leaves * 255).astype(np.uint8)

        # Distance field (B channel) - normalized
        dist = np.clip(self.volume[:, :, :, 2], 0, 1)
        result[:, :, :, 2] = (dist * 255).astype(np.uint8)

        # Combined alpha - wood fully opaque, leaves moderately opaque
        combined = np.maximum(wood, leaves * 0.6)
        result[:, :, :, 3] = (combined * 255).astype(np.uint8)

        return result

    def _calculate_bounds(self, nodes):
        """Calculate bounding box of tree with padding"""
        positions = np.array([node.position for node in nodes])

        # Get max radius for padding
        max_radius = max(node.radius for node in nodes)

        # Bounds with padding
        padding = max_radius * 2 + 0.5  # Extra padding for leaves
        self.bounds_min = positions.min(axis=0) - padding
        self.bounds_max = positions.max(axis=0) + padding

        # Make bounds cubic (largest dimension)
        size = self.bounds_max - self.bounds_min
        max_size = max(size)

        # Center the bounds
        center = (self.bounds_min + self.bounds_max) / 2
        self.bounds_min = center - max_size / 2
        self.bounds_max = center + max_size / 2

        self.voxel_size = max_size / self.resolution

    def _world_to_voxel(self, position):
        """Convert world position to voxel coordinates"""
        normalized = (position - self.bounds_min) / (self.bounds_max - self.bounds_min)
        voxel = normalized * self.resolution
        return voxel

    def _voxelize_segment(self, node):
        """Voxelize a single branch segment from parent to node"""
        parent = node.parent
        if not parent or not hasattr(parent, 'position'):
            return

        start = np.array(parent.position, dtype=np.float32)
        end = np.array(node.position, dtype=np.float32)

        # Radii at start and end
        r_start = parent.radius
        r_end = node.radius

        # Convert to voxel space
        start_v = self._world_to_voxel(start)
        end_v = self._world_to_voxel(end)

        # Radius in voxel units
        r_start_v = r_start / self.voxel_size
        r_end_v = r_end / self.voxel_size

        # Rasterize cylinder using 3D line algorithm with varying radius
        self._rasterize_tapered_cylinder(start_v, end_v, r_start_v, r_end_v)

    def _rasterize_tapered_cylinder(self, start, end, r_start, r_end):
        """Rasterize a tapered cylinder into the volume"""
        direction = end - start
        length = np.linalg.norm(direction)

        if length < 0.001:
            return

        direction = direction / length

        # Sample along cylinder
        num_samples = max(int(length * 2), 3)

        for i in range(num_samples + 1):
            t = i / num_samples
            pos = start + direction * (t * length)
            radius = r_start + (r_end - r_start) * t

            # Get voxels within radius
            self._fill_sphere(pos, radius, 0)  # Channel 0 = wood

    def _fill_sphere(self, center, radius, channel):
        """Fill a sphere in the volume"""
        # Bounding box in voxel coords
        min_v = np.floor(center - radius - 1).astype(int)
        max_v = np.ceil(center + radius + 1).astype(int)

        # Clamp to volume bounds
        min_v = np.maximum(min_v, 0)
        max_v = np.minimum(max_v, self.resolution)

        # Fill voxels
        for x in range(min_v[0], max_v[0]):
            for y in range(min_v[1], max_v[1]):
                for z in range(min_v[2], max_v[2]):
                    voxel_center = np.array([x + 0.5, y + 0.5, z + 0.5])
                    dist = np.linalg.norm(voxel_center - center)

                    if dist <= radius:
                        # Smooth falloff at edges
                        falloff = 1.0 - (dist / radius) ** 2
                        falloff = max(0, falloff)

                        # Accumulate density
                        current = self.volume[x, y, z, channel]
                        self.volume[x, y, z, channel] = min(1.0, current + falloff)

                        # Store distance info in B channel
                        norm_dist = dist / max(radius, 0.001)
                        self.volume[x, y, z, 2] = max(
                            self.volume[x, y, z, 2],
                            1.0 - norm_dist
                        )

    def _add_leaves(self, nodes, density, cluster_size):
        """Add leaf clusters at branch tips only"""
        if density <= 0:
            return

        # Only add leaves to actual tip nodes (no children)
        # This prevents overlapping clusters that fill the crown
        tip_nodes = [node for node in nodes if len(list(node.children)) == 0]

        for node in tip_nodes:
            self._add_leaf_cluster(node, density, cluster_size)

    def _add_leaf_cluster(self, node, density, cluster_size):
        """Add a cluster of leaves around a node"""
        pos = np.array(node.position, dtype=np.float32)
        pos_v = self._world_to_voxel(pos)

        # Cluster radius in voxels - keep small to avoid overlap
        cluster_radius_world = cluster_size * (self.bounds_max[0] - self.bounds_min[0])
        cluster_radius_v = cluster_radius_world / self.voxel_size

        # Moderate cluster size - not too big (overlap) or too small (sparse)
        cluster_radius_v = max(1.5, min(cluster_radius_v, 4.0))

        # Bounding box
        min_v = np.floor(pos_v - cluster_radius_v - 1).astype(int)
        max_v = np.ceil(pos_v + cluster_radius_v + 1).astype(int)

        min_v = np.maximum(min_v, 0)
        max_v = np.minimum(max_v, self.resolution)

        # Fill leaf density with strong noise to create gaps
        for x in range(min_v[0], max_v[0]):
            for y in range(min_v[1], max_v[1]):
                for z in range(min_v[2], max_v[2]):
                    voxel_center = np.array([x + 0.5, y + 0.5, z + 0.5])
                    dist = np.linalg.norm(voxel_center - pos_v)

                    if dist <= cluster_radius_v:
                        # Sharper falloff at edges for more defined clusters
                        falloff = max(0, 1.0 - (dist / cluster_radius_v) ** 1.5)

                        # Noise for variation but not heavy filtering
                        noise = (
                            np.sin(x * 5.7) * np.cos(y * 4.3) * np.sin(z * 6.1) + 1
                        ) / 2

                        # Lower threshold so more leaf voxels are filled
                        if noise > 0.15:
                            # Scale noise to [0.5, 1.0] range for more consistent density
                            scaled_noise = 0.5 + noise * 0.5
                            leaf_value = falloff * density * scaled_noise

                            # Channel 1 = leaves
                            current = self.volume[x, y, z, 1]
                            self.volume[x, y, z, 1] = min(1.0, current + leaf_value)

    def get_bounds(self):
        """Get world-space bounds of the voxel volume

        Returns:
            (bounds_min, bounds_max) as numpy arrays
        """
        return self.bounds_min.copy(), self.bounds_max.copy()


def voxelize_tree(nodes, resolution=64, leaf_density=0.3, leaf_cluster_size=0.4):
    """Convenience function to voxelize a tree

    Args:
        nodes: List of TreeNode nodes
        resolution: Voxel grid resolution
        leaf_density: Leaf density at tips
        leaf_cluster_size: Size of leaf clusters

    Returns:
        (volume, bounds_min, bounds_max) tuple
    """
    voxelizer = TreeVoxelizer(resolution)
    volume = voxelizer.voxelize(nodes, leaf_density, leaf_cluster_size)
    bounds_min, bounds_max = voxelizer.get_bounds()
    return volume, bounds_min, bounds_max

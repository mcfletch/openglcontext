"""Volumetric tree rendering package

Provides procedural tree generation using space colonization algorithm
and volumetric rendering via ray-marching through 3D textures.

Main components:
- VolumetricTree: The renderable tree node (use this in scenes)
- SpaceColonizationTree: Tree generation algorithm
- TreeVoxelizer: Converts tree skeleton to 3D texture
- VRML nodes: TreeNode, TreeAttractor, TreeParameters (from vrml.vrml97.tree)

Example usage:
    from OpenGLContext.scenegraph.tree import VolumetricTree

    tree = VolumetricTree(
        crownShape='sphere',
        crownRadius=2.0,
        seed=42,
    )
"""

from OpenGLContext.scenegraph.tree.volumetrictree import VolumetricTree
from OpenGLContext.scenegraph.tree.colonization import SpaceColonizationTree
from OpenGLContext.scenegraph.tree.voxelizer import TreeVoxelizer, voxelize_tree

# Re-export VRML node types for convenience
from vrml.vrml97.tree import TreeNode, TreeAttractor, TreeParameters

__all__ = [
    'VolumetricTree',
    'SpaceColonizationTree',
    'TreeVoxelizer',
    'voxelize_tree',
    'TreeNode',
    'TreeAttractor',
    'TreeParameters',
]

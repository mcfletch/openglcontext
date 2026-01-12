"""OpenGL renderer for volumetric trees

Renders a procedurally generated tree using ray-marching through
a 3D voxel texture. The tree skeleton is generated using space
colonization algorithm and stored as VRML nodes for serialization.
"""
import numpy as np
from OpenGL.GL import *
from OpenGL.GL import shaders as GL_shaders
from OpenGL.arrays import vbo

from vrml.vrml97 import nodetypes, tree as tree_nodes
from vrml import node, field

from OpenGLContext.scenegraph import boundingvolume
from OpenGLContext.scenegraph.tree import colonization, voxelizer
from OpenGLContext.scenegraph.tree import shaders as tree_shaders

import logging

log = logging.getLogger(__name__)


class VolumetricTree(tree_nodes.VolumetricTree):
    """Renderable volumetric tree geometry

    Generates a tree using space colonization, voxelizes it into
    a 3D texture, and renders via ray-marching in a fragment shader.

    Can be used as geometry in a Shape node, or rendered standalone.
    """

    def __init__(self, **named):
        super(VolumetricTree, self).__init__(**named)
        self._compiled = False
        self._shader_program = None
        self._texture_3d = None
        self._vao = None
        self._vbo = None
        self._bounds_min = None
        self._bounds_max = None

    def compile(self, mode=None):
        """Compile the tree - generate skeleton, voxelize, create GPU resources"""
        if self._compiled:
            return True

        log.info("Compiling volumetric tree...")

        # Get parameters (use node fields or embedded parameters node)
        params = self._get_parameters()

        # Generate tree skeleton if not already present
        if not list(self.skeleton):
            seed = int(self.seed) if self.seed else None
            generator = colonization.SpaceColonizationTree(params)
            nodes = generator.generate(seed=seed)
            self.skeleton = nodes
            log.info("Generated tree with %d nodes", len(nodes))
        else:
            nodes = list(self.skeleton)
            log.info("Using existing skeleton with %d nodes", len(nodes))

        # Voxelize the tree
        resolution = int(self.volumeResolution)
        leaf_density = float(self.leafDensity)
        leaf_cluster_size = float(self.leafClusterSize)

        volume, bounds_min, bounds_max = voxelizer.voxelize_tree(
            nodes,
            resolution=resolution,
            leaf_density=leaf_density,
            leaf_cluster_size=leaf_cluster_size
        )

        self._bounds_min = bounds_min
        self._bounds_max = bounds_max

        log.info("Voxelized tree: bounds %s to %s", bounds_min, bounds_max)

        # Create 3D texture
        self._create_texture(volume, resolution)

        # Create shader program
        self._create_shader()

        # Create bounding box geometry for ray-marching
        self._create_bounding_box()

        self._compiled = True
        log.info("Volumetric tree compilation complete")
        return True

    def _get_parameters(self):
        """Get TreeParameters, creating from node fields if needed"""
        if self.parameters:
            return self.parameters

        # Create parameters from our convenience fields
        params = tree_nodes.TreeParameters()
        params.basePosition = list(self.basePosition)
        params.trunkDirection = list(self.trunkDirection)
        params.boundingSize = list(self.boundingSize)
        params.crownShape = str(self.crownShape)
        params.crownRadius = float(self.crownRadius)
        params.crownOffset = float(self.crownOffset)
        params.attractorCount = int(self.attractorCount)
        return params

    def _create_texture(self, volume, resolution):
        """Create OpenGL 3D texture from voxel data"""
        if self._texture_3d is not None:
            glDeleteTextures([self._texture_3d])

        self._texture_3d = glGenTextures(1)
        glBindTexture(GL_TEXTURE_3D, self._texture_3d)

        # Set texture parameters
        glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_WRAP_R, GL_CLAMP_TO_EDGE)

        # Upload texture data
        glTexImage3D(
            GL_TEXTURE_3D,
            0,  # level
            GL_RGBA,  # internal format
            resolution, resolution, resolution,
            0,  # border
            GL_RGBA,
            GL_UNSIGNED_BYTE,
            volume
        )

        glBindTexture(GL_TEXTURE_3D, 0)

    def _create_shader(self):
        """Compile and link shader program"""
        if self._shader_program is not None:
            glDeleteProgram(self._shader_program)

        vertex_src = tree_shaders.get_vertex_shader()
        fragment_src = tree_shaders.get_fragment_shader()

        try:
            vertex_shader = GL_shaders.compileShader(vertex_src, GL_VERTEX_SHADER)
            fragment_shader = GL_shaders.compileShader(fragment_src, GL_FRAGMENT_SHADER)
            self._shader_program = GL_shaders.compileProgram(vertex_shader, fragment_shader)
        except RuntimeError as e:
            log.error("Shader compilation failed: %s", e)
            raise

    def _create_bounding_box(self):
        """Create VAO/VBO for bounding box geometry"""
        # Bounding box vertices
        min_v = self._bounds_min
        max_v = self._bounds_max

        # 8 corners of the box
        vertices = np.array([
            # Front face
            [min_v[0], min_v[1], max_v[2]],
            [max_v[0], min_v[1], max_v[2]],
            [max_v[0], max_v[1], max_v[2]],
            [min_v[0], max_v[1], max_v[2]],
            # Back face
            [min_v[0], min_v[1], min_v[2]],
            [max_v[0], min_v[1], min_v[2]],
            [max_v[0], max_v[1], min_v[2]],
            [min_v[0], max_v[1], min_v[2]],
        ], dtype=np.float32)

        # Indices for 12 triangles (6 faces * 2)
        indices = np.array([
            # Front
            0, 1, 2, 0, 2, 3,
            # Back
            5, 4, 7, 5, 7, 6,
            # Left
            4, 0, 3, 4, 3, 7,
            # Right
            1, 5, 6, 1, 6, 2,
            # Top
            3, 2, 6, 3, 6, 7,
            # Bottom
            4, 5, 1, 4, 1, 0,
        ], dtype=np.uint32)

        # Expand to full vertex array
        full_vertices = vertices[indices]

        # Create VAO
        self._vao = glGenVertexArrays(1)
        glBindVertexArray(self._vao)

        # Create VBO
        self._vbo = vbo.VBO(full_vertices)
        self._vbo.bind()

        # Set up vertex attribute
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, None)

        glBindVertexArray(0)
        self._vbo.unbind()

    def render(
            self,
            visible=1,
            lit=1,
            textured=1,
            transparent=0,
            mode=None,
    ):
        """Render the volumetric tree"""
        if not self.compile(mode):
            return

        if self._shader_program is None:
            return

        # Get matrices from OpenGL state
        # OpenGL returns matrices in column-major order as a 4x4 numpy array
        modelview_matrix = glGetFloatv(GL_MODELVIEW_MATRIX)
        proj_matrix = glGetFloatv(GL_PROJECTION_MATRIX)

        # Extract camera position from inverse of modelview matrix
        # The modelview matrix transforms world coords to eye coords
        # Its inverse transforms eye coords to world coords
        # Camera is at origin in eye space, so camera_world = inv(MV) * (0,0,0,1)
        try:
            inv_modelview = np.linalg.inv(modelview_matrix)
            # OpenGL stores matrices in column-major order, but numpy sees it
            # as row-major. The translation components in OpenGL's column-major
            # layout are at indices [12], [13], [14] in the flat array, which
            # numpy sees as row 3 (the last row) when reshaped to 4x4.
            # So we extract from row 3, columns 0-2
            camera_pos = np.array([
                inv_modelview[3, 0],
                inv_modelview[3, 1],
                inv_modelview[3, 2]
            ], dtype=np.float32)
        except np.linalg.LinAlgError:
            camera_pos = np.array([0, 5, 15], dtype=np.float32)

        # Use shader
        glUseProgram(self._shader_program)

        # Set uniforms - use combined modelview matrix
        glUniformMatrix4fv(
            glGetUniformLocation(self._shader_program, "modelViewMatrix"),
            1, GL_FALSE, modelview_matrix
        )
        glUniformMatrix4fv(
            glGetUniformLocation(self._shader_program, "projectionMatrix"),
            1, GL_FALSE, proj_matrix
        )
        glUniform3fv(
            glGetUniformLocation(self._shader_program, "cameraPosition"),
            1, camera_pos
        )

        # Volume bounds
        glUniform3fv(
            glGetUniformLocation(self._shader_program, "boundsMin"),
            1, self._bounds_min.astype(np.float32)
        )
        glUniform3fv(
            glGetUniformLocation(self._shader_program, "boundsMax"),
            1, self._bounds_max.astype(np.float32)
        )

        # Material colors
        bark_color = np.array(self.barkColor, dtype=np.float32)
        leaf_color = np.array(self.leafColor, dtype=np.float32)
        glUniform3fv(
            glGetUniformLocation(self._shader_program, "barkColor"),
            1, bark_color
        )
        glUniform3fv(
            glGetUniformLocation(self._shader_program, "leafColor"),
            1, leaf_color
        )

        # Rendering parameters
        glUniform1f(
            glGetUniformLocation(self._shader_program, "densityScale"),
            float(self.densityScale)
        )
        glUniform1i(
            glGetUniformLocation(self._shader_program, "maxSteps"),
            int(self.maxRaySteps)
        )
        glUniform1f(
            glGetUniformLocation(self._shader_program, "stepSize"),
            float(self.rayStepSize)
        )

        # Light direction (from above-right)
        light_dir = np.array([0.5, 1.0, 0.3], dtype=np.float32)
        light_dir = light_dir / np.linalg.norm(light_dir)
        glUniform3fv(
            glGetUniformLocation(self._shader_program, "lightDir"),
            1, light_dir
        )

        # Bind 3D texture
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_3D, self._texture_3d)
        glUniform1i(
            glGetUniformLocation(self._shader_program, "volumeTexture"),
            0
        )

        # Enable blending and depth test
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glEnable(GL_DEPTH_TEST)
        glDepthMask(GL_TRUE)

        # Draw bounding box (triggers fragment shader ray-marching)
        glBindVertexArray(self._vao)
        glDrawArrays(GL_TRIANGLES, 0, 36)
        glBindVertexArray(0)

        # Cleanup
        glBindTexture(GL_TEXTURE_3D, 0)
        glUseProgram(0)

    def boundingVolume(self, mode):
        """Create a bounding-volume object for this node"""
        current = boundingvolume.getCachedVolume(self)
        if current:
            return current

        # Compile to get bounds
        if not self._compiled:
            self.compile(mode)

        if self._bounds_min is not None and self._bounds_max is not None:
            size = self._bounds_max - self._bounds_min
            center = (self._bounds_min + self._bounds_max) / 2
            return boundingvolume.cacheVolume(
                self,
                boundingvolume.AABoundingBox(
                    size=size.tolist(),
                    center=center.tolist(),
                ),
                ((self, 'boundingSize'),),
            )

        # Fallback to unbounded
        return boundingvolume.UnboundedVolume()

    def visible(self, frustum=None, matrix=None, occlusion=0, mode=None):
        """Check whether this renderable node intersects frustum"""
        return self.boundingVolume(mode).visible(
            frustum, matrix, occlusion=occlusion, mode=mode
        )

    def __del__(self):
        """Cleanup OpenGL resources"""
        # Note: This may not work correctly if called after context is destroyed
        try:
            if self._texture_3d is not None:
                glDeleteTextures([self._texture_3d])
            if self._shader_program is not None:
                glDeleteProgram(self._shader_program)
            if self._vao is not None:
                glDeleteVertexArrays(1, [self._vao])
        except Exception:
            pass  # Context may be gone

#! /usr/bin/env python
"""Volumetric Forest Demo

Creates a forest by instancing multiple procedurally generated trees
with random positions, rotations, and scales.

Note: Uses manual GL transforms for instancing since pyvrml97's scenegraph
doesn't support having the same node as a child of multiple parents.
"""
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from OpenGL.GL import *
from OpenGLContext.scenegraph.tree import VolumetricTree
import numpy as np
import math
import random
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


class ForestContext(BaseContext):
    """Demo context for volumetric forest rendering"""

    initialPosition = (0, 8, 40)  # Camera further back to see forest

    def OnInit(self):
        """Initialize the scene with multiple trees"""
        log.info("Initializing volumetric forest demo...")

        # Create a few different tree templates with different characteristics
        self.tree_templates = []

        # Template 1: Standard spherical oak-like tree
        log.info("Creating tree template 1 (sphere crown)...")
        self.tree_templates.append({
            'tree': VolumetricTree(
                crownShape='sphere',
                crownRadius=2.0,
                crownOffset=2.5,
                attractorCount=800,
                barkColor=[0.45, 0.28, 0.12],
                leafColor=[0.2, 0.5, 0.15],
                leafDensity=0.5,
                leafClusterSize=0.12,
                volumeResolution=64,
                maxRaySteps=150,
                rayStepSize=0.01,
                densityScale=1.2,
                seed=42,
            ),
            'base_radius': 4.0,  # Approximate crown diameter / 2
        })

        # Template 2: Tall conical pine tree
        log.info("Creating tree template 2 (cone crown)...")
        self.tree_templates.append({
            'tree': VolumetricTree(
                crownShape='cone',
                crownRadius=1.5,
                crownOffset=1.5,
                attractorCount=600,
                barkColor=[0.35, 0.22, 0.08],
                leafColor=[0.15, 0.4, 0.12],
                leafDensity=0.6,
                leafClusterSize=0.1,
                volumeResolution=64,
                maxRaySteps=150,
                rayStepSize=0.01,
                densityScale=1.3,
                seed=123,
            ),
            'base_radius': 2.5,  # Narrower cone shape
        })

        # Template 3: Wide spreading oak
        log.info("Creating tree template 3 (ellipsoid crown)...")
        self.tree_templates.append({
            'tree': VolumetricTree(
                crownShape='ellipsoid',
                crownRadius=2.5,
                crownOffset=2.0,
                boundingSize=[5.0, 4.0, 5.0],
                attractorCount=900,
                barkColor=[0.5, 0.3, 0.15],
                leafColor=[0.25, 0.55, 0.18],
                leafDensity=0.45,
                leafClusterSize=0.14,
                volumeResolution=64,
                maxRaySteps=150,
                rayStepSize=0.01,
                densityScale=1.1,
                seed=456,
            ),
            'base_radius': 5.0,  # Wide spreading crown
        })

        # Template 4: Small bushy tree
        log.info("Creating tree template 4 (small sphere)...")
        self.tree_templates.append({
            'tree': VolumetricTree(
                crownShape='sphere',
                crownRadius=1.2,
                crownOffset=1.0,
                attractorCount=400,
                barkColor=[0.4, 0.25, 0.1],
                leafColor=[0.3, 0.55, 0.2],
                leafDensity=0.55,
                leafClusterSize=0.1,
                volumeResolution=48,
                maxRaySteps=120,
                rayStepSize=0.012,
                densityScale=1.3,
                seed=789,
            ),
            'base_radius': 2.0,
        })

        # Template 5: Tall narrow cypress-like
        log.info("Creating tree template 5 (tall cylinder)...")
        self.tree_templates.append({
            'tree': VolumetricTree(
                crownShape='cylinder',
                crownRadius=1.0,
                crownOffset=1.0,
                attractorCount=500,
                barkColor=[0.3, 0.2, 0.08],
                leafColor=[0.12, 0.35, 0.1],
                leafDensity=0.65,
                leafClusterSize=0.08,
                volumeResolution=48,
                maxRaySteps=120,
                rayStepSize=0.012,
                densityScale=1.4,
                seed=321,
            ),
            'base_radius': 1.8,
        })

        # Pre-compile all templates
        for i, template in enumerate(self.tree_templates):
            log.info("Compiling tree template %d...", i + 1)
            template['tree'].compile()

        # Generate random instances with minimum spacing
        random.seed(999)  # Reproducible forest layout
        self.instances = []

        # Forest layout parameters - dense forest
        forest_radius = 30.0
        target_instances = 160  # Double density
        max_attempts = 1600

        attempts = 0
        while len(self.instances) < target_instances and attempts < max_attempts:
            attempts += 1

            # Random position in circular area
            angle = random.uniform(0, 2 * math.pi)
            distance = random.uniform(3.0, forest_radius) * math.sqrt(random.random())
            x = math.cos(angle) * distance
            z = math.sin(angle) * distance

            # Random template with weighted distribution
            weights = [0.3, 0.25, 0.15, 0.2, 0.1]
            template_idx = random.choices(range(len(self.tree_templates)), weights=weights)[0]
            template = self.tree_templates[template_idx]

            # Size variation
            scale = random.uniform(0.5, 1.6)

            # Calculate effective radius for this instance
            effective_radius = template['base_radius'] * scale

            # Check minimum spacing - allow significant crown overlap for dense forest
            # 0.4 factor means crowns can overlap up to 60%
            too_close = False

            for existing in self.instances:
                ex, _, ez = existing['position']
                dx = x - ex
                dz = z - ez
                dist = math.sqrt(dx * dx + dz * dz)

                # Get existing tree's effective radius
                ex_template = self.tree_templates[existing['template']]
                ex_radius = ex_template['base_radius'] * existing['scale']

                # Minimum distance: sum of radii with overlap factor
                # 0.4 allows crowns to significantly overlap for dense forest
                min_dist = (effective_radius + ex_radius) * 0.4
                if dist < min_dist:
                    too_close = True
                    break

            if too_close:
                continue

            # Random rotation around Y axis (in degrees for glRotatef)
            rotation = random.uniform(0, 360)

            self.instances.append({
                'template': template_idx,
                'position': (x, 0, z),
                'scale': scale,
                'rotation': rotation,
            })

        log.info("Created %d tree instances (after %d attempts)", len(self.instances), attempts)

    def _get_camera_position(self):
        """Extract camera position from current modelview matrix"""
        modelview = glGetFloatv(GL_MODELVIEW_MATRIX)
        try:
            inv_mv = np.linalg.inv(modelview)
            # Camera position is translation component of inverse modelview
            return np.array([inv_mv[3, 0], inv_mv[3, 1], inv_mv[3, 2]])
        except np.linalg.LinAlgError:
            return np.array([0, 8, 40])

    def Render(self, mode=None):
        """Render the forest"""
        BaseContext.Render(self, mode)

        # Clear with sky blue background
        glClearColor(0.5, 0.7, 0.9, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        glEnable(GL_DEPTH_TEST)
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glLightfv(GL_LIGHT0, GL_POSITION, [0.5, 1.0, 0.3, 0.0])

        # Draw ground first (opaque)
        self._draw_ground()

        # Get camera position for sorting
        camera_pos = self._get_camera_position()

        # Sort instances back-to-front for correct transparency blending
        def distance_to_camera(instance):
            pos = instance['position']
            dx = pos[0] - camera_pos[0]
            dy = pos[1] - camera_pos[1]
            dz = pos[2] - camera_pos[2]
            return -(dx * dx + dy * dy + dz * dz)  # Negative for back-to-front

        sorted_instances = sorted(self.instances, key=distance_to_camera)

        # Render trees back-to-front
        for instance in sorted_instances:
            template = self.tree_templates[instance['template']]
            tree = template['tree']
            x, y, z = instance['position']
            scale = instance['scale']
            rotation = instance['rotation']

            glPushMatrix()
            glTranslatef(x, y, z)
            glRotatef(rotation, 0, 1, 0)
            glScalef(scale, scale, scale)

            tree.render(mode=mode)

            glPopMatrix()

    def _draw_ground(self):
        """Draw a simple ground plane"""
        glDisable(GL_LIGHTING)
        glColor3f(0.25, 0.4, 0.15)  # Forest floor green

        glBegin(GL_QUADS)
        size = 50.0
        glNormal3f(0, 1, 0)
        glVertex3f(-size, -0.1, -size)
        glVertex3f(size, -0.1, -size)
        glVertex3f(size, -0.1, size)
        glVertex3f(-size, -0.1, size)
        glEnd()

        glEnable(GL_LIGHTING)


if __name__ == "__main__":
    ForestContext.ContextMainLoop()

#version 330 core
/* An X3D volume's box (volume.frag marches the rays through it).
 *
 * The unit cube, scaled to the volume's dimensions and centred on its
 * origin. The pass draws its back faces with the depth test off, so a
 * fragment is made wherever the box covers the view, the camera inside it or
 * not; the fragment stage clips the ray to the box and to the opaque scene.
 */

layout(location = 2) in vec3 aPosition;   // required: the unit cube's corners, -0.5 .. 0.5

uniform mat4 uModelView;
uniform mat4 uProjection;
uniform vec3 uDimensions;                 // the box's size in the volume's own units

void main() {
    gl_Position = uProjection * uModelView * vec4(aPosition * uDimensions, 1.0);
}

"""GLSL shaders for volumetric tree rendering

Contains vertex and fragment shader source code for ray-marching
through a 3D voxel texture representing tree geometry.
"""

# Vertex shader - transforms bounding box and passes world position to fragment
VERTEX_SHADER = """
#version 330 core

layout(location = 0) in vec3 position;

uniform mat4 modelViewMatrix;
uniform mat4 projectionMatrix;

out vec3 vWorldPos;

void main() {
    // Position is already in world space (bounding box vertices)
    vWorldPos = position;

    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
"""

# Fragment shader - ray-marches through 3D texture
FRAGMENT_SHADER = """
#version 330 core

in vec3 vWorldPos;

uniform sampler3D volumeTexture;
uniform vec3 boundsMin;
uniform vec3 boundsMax;
uniform vec3 barkColor;
uniform vec3 leafColor;
uniform float densityScale;
uniform int maxSteps;
uniform float stepSize;
uniform vec3 lightDir;
uniform vec3 cameraPosition;
uniform mat4 modelViewMatrix;
uniform mat4 projectionMatrix;

out vec4 fragColor;

// Ray-box intersection using slab method
vec2 intersectBox(vec3 origin, vec3 dir, vec3 boxMin, vec3 boxMax) {
    vec3 invDir = 1.0 / dir;
    vec3 t0 = (boxMin - origin) * invDir;
    vec3 t1 = (boxMax - origin) * invDir;
    vec3 tmin = min(t0, t1);
    vec3 tmax = max(t0, t1);
    float tNear = max(max(tmin.x, tmin.y), tmin.z);
    float tFar = min(min(tmax.x, tmax.y), tmax.z);
    return vec2(tNear, tFar);
}

// Convert world position to texture coordinates [0,1]
vec3 worldToTex(vec3 pos) {
    return (pos - boundsMin) / (boundsMax - boundsMin);
}

// Gradient-based normal estimation from density field
vec3 estimateNormal(vec3 texCoord, float delta) {
    float dx = texture(volumeTexture, texCoord + vec3(delta, 0, 0)).a
             - texture(volumeTexture, texCoord - vec3(delta, 0, 0)).a;
    float dy = texture(volumeTexture, texCoord + vec3(0, delta, 0)).a
             - texture(volumeTexture, texCoord - vec3(0, delta, 0)).a;
    float dz = texture(volumeTexture, texCoord + vec3(0, 0, delta)).a
             - texture(volumeTexture, texCoord - vec3(0, 0, delta)).a;
    vec3 grad = vec3(dx, dy, dz);
    float len = length(grad);
    if (len < 0.001) return vec3(0, 1, 0);  // Default up normal
    return -grad / len;
}

void main() {
    // Compute ray direction per-fragment for correct perspective
    vec3 rayOrigin = cameraPosition;
    vec3 rayDir = normalize(vWorldPos - cameraPosition);

    // Find ray intersection with bounding box
    vec2 tHit = intersectBox(rayOrigin, rayDir, boundsMin, boundsMax);

    if (tHit.x > tHit.y || tHit.y < 0.0) {
        discard;
    }

    // Start from box entry (or camera if inside box)
    float tStart = max(tHit.x, 0.0);
    float tEnd = tHit.y;

    // Calculate step size based on box diagonal
    vec3 boxSize = boundsMax - boundsMin;
    float boxDiagonal = length(boxSize);
    float actualStepSize = stepSize * boxDiagonal;

    // Ray marching with front-to-back compositing
    vec3 accumColor = vec3(0.0);
    float accumAlpha = 0.0;
    float t = tStart;
    float firstHitT = -1.0;

    // Normal estimation delta based on texture resolution
    float normalDelta = 1.0 / 32.0;

    for (int i = 0; i < maxSteps && t < tEnd && accumAlpha < 0.95; i++) {
        vec3 pos = rayOrigin + rayDir * t;
        vec3 texCoord = worldToTex(pos);

        // Check bounds
        if (all(greaterThanEqual(texCoord, vec3(0.0))) &&
            all(lessThanEqual(texCoord, vec3(1.0)))) {

            vec4 sampleVal = texture(volumeTexture, texCoord);

            // R = wood density, G = leaf density, A = combined
            float woodDensity = sampleVal.r * densityScale;
            float leafDensity = sampleVal.g * densityScale * 0.5;
            float totalDensity = sampleVal.a * densityScale;

            if (totalDensity > 0.005) {
                // Record first hit for depth
                if (firstHitT < 0.0) {
                    firstHitT = t;
                }

                // Estimate surface normal from density gradient
                vec3 normal = estimateNormal(texCoord, normalDelta);
                float diffuse = max(dot(normal, normalize(lightDir)), 0.0);

                // Composite wood and leaves separately, then blend
                // Wood: solid, darker, higher opacity
                if (woodDensity > 0.01) {
                    float woodAlpha = 1.0 - exp(-woodDensity * actualStepSize * 25.0);
                    vec3 woodLit = barkColor * (0.25 + diffuse * 0.5);
                    accumColor += (1.0 - accumAlpha) * woodAlpha * woodLit;
                    accumAlpha += (1.0 - accumAlpha) * woodAlpha;
                }

                // Leaves: more opaque to actually occlude
                if (leafDensity > 0.01 && accumAlpha < 0.95) {
                    float leafAlpha = 1.0 - exp(-leafDensity * actualStepSize * 20.0);
                    vec3 leafLit = leafColor * (0.4 + diffuse * 0.5);
                    accumColor += (1.0 - accumAlpha) * leafAlpha * leafLit;
                    accumAlpha += (1.0 - accumAlpha) * leafAlpha;
                }
            }
        }

        t += actualStepSize;
    }

    if (accumAlpha < 0.01) {
        discard;
    }

    fragColor = vec4(accumColor, accumAlpha);

    // Set depth from first hit point
    if (firstHitT > 0.0) {
        vec3 hitPos = rayOrigin + rayDir * firstHitT;
        vec4 clipPos = projectionMatrix * modelViewMatrix * vec4(hitPos, 1.0);
        float ndcDepth = clipPos.z / clipPos.w;
        gl_FragDepth = (ndcDepth + 1.0) * 0.5;
    } else {
        gl_FragDepth = 1.0;
    }
}
"""


def get_vertex_shader():
    """Get vertex shader source"""
    return VERTEX_SHADER


def get_fragment_shader():
    """Get fragment shader source"""
    return FRAGMENT_SHADER

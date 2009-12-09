// Vertex-shader pre-calculation for blinn-phong lighting
void phong_preCalc( 
    in vec3 vertex_position,
    in vec4 light_position,
    out float light_distance,
    out vec3 ec_light_location,
    out vec3 ec_light_half
) {
    // This is the core setup for a phong lighting pass as a reusable fragment of code.
    
    // vertex_position -- un-transformed vertex position (world-space)
    // light_position -- un-transformed light location (direction)
    // light_distance -- output giving world-space distance-to-light 
    // ec_light_location -- output giving location of light in eye coords 
    // ec_light_half -- output giving the half-vector optimization
    
    if (light_position.w == 0.0) {
        // directional rather than positional light...
        ec_light_location = normalize(
            gl_NormalMatrix *
            light_position.xyz
        );
        light_distance = 0.0;
    } else {
        // positional light, we calculate distance in 
        // model-view space here, so we take a partial 
        // solution...
        vec3 ms_vec = (
            light_position.xyz -
            vertex_position
        );
        vec3 light_direction = gl_NormalMatrix * ms_vec;
        ec_light_location = normalize( light_direction );
        light_distance = abs(length( ms_vec ));
    }
    // half-vector calculation 
    ec_light_half = normalize(
        ec_light_location - vec3( 0,0,-1 )
    );
}

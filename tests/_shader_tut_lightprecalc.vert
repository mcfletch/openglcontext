void light_preCalc( in vec3 vertex_position ) {
    // This function is dependent on the uniforms and 
    // varying values we've been using in our shader tutorial,
    // it basically just iterates over the phong_lightCalc passing in 
    // the appropriate pointers...
    vec3 light_direction;
    for (int i = 0; i< LIGHT_COUNT; i++ ) {
        int j = i * LIGHT_SIZE;
        phong_preCalc(
            vertex_position,
            lights[j+POSITION],
            // following are the values to fill in...
            Light_distance[i],
            EC_Light_location[i],
            EC_Light_half[i]
        );
    }
}

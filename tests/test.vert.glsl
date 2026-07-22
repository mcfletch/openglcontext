#version 120

attribute vec3 vtx_position;
                        attribute vec3 vtx_normal;
                        attribute vec2 vtx_texcoord_0;
                        
                        // modelview matrix and inverse...
                        uniform mat4 mat_modelview; 
                        uniform mat4 inv_modelview;
                        uniform mat4 tps_modelview;
                        uniform mat4 itp_modelview;
                        
                        // projection matrix and inverse...
                        uniform mat4 mat_projection;
                        uniform mat4 inv_projection;
                        uniform mat4 tps_projection;
                        uniform mat4 itp_projection;
                        
                        // combined matrices and inverse
                        uniform mat4 mat_modelproj;
                        uniform mat4 inv_modelproj;
                        uniform mat4 tps_modelproj;
                        uniform mat4 itp_modelproj; // a.k.a. gl_NormalMatrix
                        
                        void main() {
                            mat4 combined = mat_modelproj;
                            //mat4 mat_normal = transpose(inverse(mat_modelview));
                            //mat4 mat_normal = transpose(inv_modelview);
                            mat4 mat_normal = transpose(inv_modelview);
                            vec4 position = combined * vec4(
                                vtx_position, 1.0
                            );
                            //baseNormal = normalize( gl_NormalMatrix * vtx_normal);
                            baseNormal = normalize( mat_normal * vec4(vtx_normal,0.0)).xyz;
                            light_preCalc(vtx_position);
                            vtx_texcoord_0_var = vtx_texcoord_0;
                            gl_Position = position;
                        }

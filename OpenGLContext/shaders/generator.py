

class ShaderGenerator( object ):
    def shader( self, mode, geometry ):
        """Create/lookup appropriate shader for given geometry
        
        geometry -- collection of uniforms, attributes, animations, etc.
        material -- base material object connected to the geometry
        mode.lights -- array of light meta-information
        mode.modelView, mode.projection -- etc...
        """
class DefaultShaderGenerator( ShaderGenerator ):
    def shader( self, mode, geometry ):
        definitions = [self.MODE_MATRIX_DEF]
        template = []
        if geometry.material:
            definitions.append( self.MATERIAL_DEF )
        lights = mode.lights
        definitions.append( self.LIGHT_DEF%{'light_size': len(lights) })
        
    MODE_MATRIX_DEF = '''uniform mat4 mat_modelview; uniform mat4 mat_projection;'''
    MATERIAL_DEF = '''struct Material {
            vec4 ambient;
            vec4 diffuse;
            vec4 specular;
            float shininess;
        };
        uniform Material material;'''
    LIGHT_DEF = '''uniform vec4 lights[ %(light_count)s*LIGHT_SIZE ];

        varying vec3 EC_Light_half[%(light_count)s];
        varying vec3 EC_Light_location[%(light_count)s];
        varying float Light_distance[%(light_count)s];'''

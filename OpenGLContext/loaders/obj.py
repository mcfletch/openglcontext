"""Implements OBJ loading into OpenGLContext scenegraph nodes

Based on the Pyglet OBJ loader in the contrib files section which is
licensed under the following license:

    Copyright (c) 2006-2008 Alex Holkner
    All rights reserved.

    Redistribution and use in source and binary forms, with or without
    modification, are permitted provided that the following conditions are met:

      * Redistributions of source code must retain the above copyright
        notice, this list of conditions and the following disclaimer.
      * Redistributions in binary form must reproduce the above copyright 
        notice, this list of conditions and the following disclaimer in
        the documentation and/or other materials provided with the
        distribution.
      * Neither the name of pyglet nor the names of its
        contributors may be used to endorse or promote products
        derived from this software without specific prior written
        permission.

    THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
    "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
    LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
    FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
    COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
    INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
    BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
    LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
    CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
    LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
    ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
    POSSIBILITY OF SUCH DAMAGE.

        From the pyglet svn:
        http://pyglet.googlecode.com/svn/trunk/contrib/model/model/obj.py
        Last revised on March 7, 2008 by Alex Holkner (revision 1884)

        Additions/changes by Jim Getzen on June 2, 2008:
        Fixed a bug in the OBJ.load_material_library method:
        'emissive' changed to 'emission'

        Added a color argument to the OBJ.draw method.
        Added a color argument to the Mesh.draw method.
        Added code the Mesh.draw method to enable glColorMaterial
        capability (allowing objects to be temporarily recolored).

        Added OBJ.compile convenience method to compile all of an
        OBJ's meshes.

        Commented out the glDisable(GL_TEXTURE_2D) in the 'apply'
        method of Material. It interfered with the shadow mapping
        OpenGL state settings.

Note:

    This is only a tiny fraction of the OBJ file format, for an idea of how much 
    is left out, see:
    
        http://people.scs.fsu.edu/~burkardt/txt/obj_format.txt
    
"""
import logging 
log = logging.getLogger( __name__ )
from OpenGLContext.loaders import base, loader
from OpenGLContext.scenegraph import basenodes
import urllib
try:
    from hashlib import md5 
except ImportError, err:
    from md5 import md5

class OBJHandler( base.BaseHandler ):
    """Scenegraph loader which loads individual OBJ files as scenegraphs"""
    filename_extensions = ['.obj','.obj.gz']
    def defaultMaterial( self ):
        return basenodes.Appearance(
            material = basenodes.Material( diffuseColor = [.9,.9,.9 ]),
        )
        
    def parse( self, data, baseURL, *args, **named ):
        """Parse the loaded data (with the provided meta-information)
        
        This implementation simply creates VRML97 scenegraph nodes out 
        of the .obj format data. 
        """
        sg = basenodes.sceneGraph(
        )
        
        # these three are shared among all shapes
        hash = md5( baseURL ).hexdigest()
        coord = basenodes.Coordinate( DEF='Coord-%s'%(hash,) )
        normal = basenodes.Normal(DEF='Norm-%s'%(hash,))
        texCoord = basenodes.TextureCoordinate(DEF='TexCoord-%s'%(hash,))

        mesh = None # transforms
        group = None # shape
        material = None # appearance, material, texture
        
        materials = {}
        
        # indices are 1-based, the first values are never used...
        vertices = [[0., 0., 0.]] 
        normals = [[0., 0., 0.]]
        tex_coords = [[0., 0.]]
        
        current_vertex_indices = []
        current_normal_indices = []
        current_texcoord_indices = []

        for line in data.splitlines():
            if line.startswith('#'): 
                continue
            values = line.split()
            if not values: 
                continue

            if values[0] == 'v':
                vertices.append(map(float, values[1:4]))
            elif values[0] == 'vn':
                normals.append(map(float, values[1:4]))
            elif values[0] == 'vt':
                tex_coords.append(map(float, values[1:3]))
            elif values[0] == 'mtllib':
                self.load_material_library(values[1], materials, baseURL)
            elif values[0] in ('usemtl', 'usemat'):
                material = materials.get(values[1], None)
                if material is None:
                    log.warn('Unknown material: %s', values[1])
                    material = self.defaultMaterial()
                if mesh is not None:
                    if group and current_vertex_indices:
                        group.geometry.coordIndex = current_vertex_indices
                        group.geometry.texCoordIndex = current_texcoord_indices
                        group.geometry.normalIndex = current_normal_indices
                        current_vertex_indices = []
                        current_texcoord_indices = []
                        current_normal_indices = []
                    group = basenodes.Shape(
                        geometry = basenodes.IndexedFaceSet(
                            coord = coord,
                            normal = normal,
                            texCoord = texCoord,
                            solid=False,
                        ),
                        appearance = material,
                    )
                    mesh.children.append(group)
            elif values[0] == 'o':
                mesh = basenodes.Transform( DEF = values[1] )
                sg.children.append( mesh )
                sg.regDefName( values[1], mesh )
                # previous shape is no longer current...
                group = None
            elif values[0] == 's':
                # a smoothing-group definition...
                # not currently supported...
                pass
            elif values[0] == 'f':
                # adds a single face
                if mesh is None:
                    # anonymous transform
                    mesh = basenodes.Transform()
                    sg.children.append(mesh)
                if material is None:
                    material = self.defaultMaterial()
                if group is None:
                    group = basenodes.Shape( 
                        geometry = basenodes.IndexedFaceSet(
                            coord = coord,
                            normal = normal,
                            texCoord = texCoord,
                            solid=False,
                        ),
                        appearance = material,
                    )
                    mesh.children.append(group)

                for i, v in enumerate(values[1:]):
                    v_index, t_index, n_index = self._cleanIndex( v )
                    current_vertex_indices.append( v_index )
                    current_texcoord_indices.append( t_index )
                    current_normal_indices.append( n_index )
                current_vertex_indices.append( -1 )
                current_texcoord_indices.append( -1 )
                current_normal_indices.append( -1 )
            else:
                log.warn( """Unrecognized operation: %r""", values )
        if group and current_vertex_indices:
            group.geometry.coordIndex = current_vertex_indices
            group.geometry.texCoordIndex = current_texcoord_indices
            group.geometry.normalIndex = current_normal_indices
        coord.point = vertices
        normal.normal = normals
        texCoord.texCoord = tex_coords
        return True,sg
    
    
        # this creates a pointset-only version of the geometry...
#		sg.children = [
#			basenodes.Transform(
#				children = [
#					basenodes.Shape(
#						geometry = basenodes.PointSet( 
#							coord=coord,
#							color = [1,1,1]*len(coord.point)
#						),
#						appearance = basenodes.Appearance(
#							material = basenodes.Material(
#								diffuseColor = [1,0,0],
#							),
#						)
#					),
#				],
#			),
#			basenodes.PointLight( location = [0,0,10 ] ),
#			basenodes.Background( skyColor=[1,1,1] ),
#		]
    

    def _cleanIndex( self, v ):
        """Indices are in the format:
        
        ci/ti/ni where ti and ni can be null
        """
        return (
            map(int, [j or 0 for j in v.split('/')]) + [0, 0]
        )[:3]
    def load_material_library( self, url, materials, baseURL=None ):
        """Load the materials in resource into the materials set"""
        #( resolvedURL, os.path.abspath(filename), file, headers )
        try:
            finalURL, filename, file, headers = loader.Loader( url, baseURL )
        except IOError, err:
            if '/' in url:
                possible = url.split( '/' )[-1]
                try:
                    finalURL, filename, file, headers = loader.Loader( 
                        possible, baseURL 
                    )
                except IOError, err:
                    log.warn(
                        """Unable to load material library: %s""",
                        url,
                    )
                    return False
                
        material = None
        for line in file.read().splitlines():
            if line.startswith('#'):
                continue
            values = line.split()
            if not values:
                continue

            if values[0] == 'newmtl':
                material = self.defaultMaterial()
                materials[values[1]] = material
            elif material is None:
                log.warn('Expected "newmtl" in %s', url)
                continue

            try:
                if values[0] == 'Kd':
                    material.material.diffuseColor = map(float, values[1:])
                elif values[0] == 'Ka':
                    material.material.ambientColor = map(float, values[1:])
                elif values[0] == 'Ks':
                    material.material.specularColor = map(float, values[1:])
                elif values[0] == 'Ke':
                    material.material.emissiveColor = map(float, values[1:])
                elif values[0] == 'Ns':
                    material.material.shininess = float(values[1])
                elif values[0] == 'd':
                    material.material.opacity = float(values[1])
                elif values[0] == 'map_Kd':
                    if '/' in values[1]:
                        img_url = [ values[1], values[1].split('/')[-1] ]
                    else:
                        img_url = [ values[1] ]
                    img_url = [
                        urllib.basejoin(baseURL, u )
                        for u in img_url
                    ]
                    texture = basenodes.ImageTexture(url=img_url)
                    material.texture = texture
            except:
                log.warn('Parse error in %s.', url)

def defaultHandler( ):
    """Default handler instance used for loading standard obj files"""
    return OBJHandler()

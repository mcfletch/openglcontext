#version 330 core
in vec3 vEyePos;
in vec3 vWorldPos;
in vec3 vWorldNormal;

uniform sampler2DArray layerColor;   // N detail albedo layers (sRGB)
uniform sampler2DArray layerNormal;  // N detail normal-GL layers
uniform sampler2DArray layerRough;   // N detail roughness layers
uniform sampler2D      controlMap;   // RGBA splat weights over the whole terrain
uniform sampler2D      sunShadow;     // baked sun shadow (1 lit, 0 shadowed)
uniform int   numLayers;
uniform vec2  worldMin;              // terrain XZ origin
uniform vec2  worldSize;            // terrain XZ size
uniform float detailScale;         // detail-texture repeats per world unit
uniform float macroScale;          // second, larger tiling to break repetition
uniform float normalStrength;
uniform mat3  uNormalMatrix;

uniform vec3  sunDirEye;            // normalized, eye space (points FROM surface TO sun is -this)
uniform vec3  sunColor;
uniform vec3  skyColor;            // hemispheric ambient (up)
uniform vec3  groundAmbient;      // hemispheric ambient (down)
uniform float fogDensity;
uniform vec3  fogColor;

out vec4 fragColor;

vec3 sRGBToLinear(vec3 c){ return pow(c, vec3(2.2)); }
vec3 linearToSRGB(vec3 c){ return pow(c, vec3(1.0/2.2)); }
vec3 aces(vec3 x){
    const float a=2.51,b=0.03,c=2.43,d=0.59,e=0.14;
    return clamp((x*(a*x+b))/(x*(c*x+d)+e),0.0,1.0);
}

void main(){
    vec4 w = texture(controlMap, (vWorldPos.xz - worldMin)/worldSize);
    float wt[4] = float[4](w.r,w.g,w.b,w.a);
    // Normalise over the *active* layers only: a control map whose unused
    // channels still carry weight would otherwise dilute (darken) the blend.
    float wsum = 0.0;
    for(int k=0;k<4;k++){ if(k<numLayers) wsum += wt[k]; }
    float inv = 1.0/max(wsum,1e-4);
    for(int k=0;k<4;k++){ wt[k] *= inv; }

    vec2 uvD = vWorldPos.xz * detailScale;
    vec2 uvM = vWorldPos.xz * macroScale;

    vec3 albedo = vec3(0.0);
    vec3 nts = vec3(0.0);
    for(int k=0;k<4;k++){
        if(k>=numLayers) break;
        float f = wt[k];
        if(f<=0.001) continue;
        // detail + macro blend hides obvious tiling
        vec3 cD = texture(layerColor, vec3(uvD,float(k))).rgb;
        vec3 cM = texture(layerColor, vec3(uvM,float(k))).rgb;
        albedo += f * sRGBToLinear(mix(cD,cM,0.5));
        vec3 nD = texture(layerNormal, vec3(uvD,float(k))).rgb*2.0-1.0;
        nts += f * nD;
    }

    // top-down tangent frame (T=+X, B=+Z), perturb the world normal by detail normal
    vec3 Nw = normalize(vWorldNormal + (vec3(1,0,0)*nts.x + vec3(0,0,1)*nts.y)*normalStrength);
    vec3 N = normalize(uNormalMatrix * Nw);

    vec3 L = -sunDirEye;
    float NdotL = max(dot(N,L),0.0);
    float sh = texture(sunShadow, (vWorldPos.xz - worldMin)/worldSize).r;   // 1 lit, 0 shadowed
    vec3 direct = albedo * sunColor * NdotL * sh;
    float up = clamp(Nw.y*0.5+0.5, 0.0, 1.0);
    vec3 ambient = albedo * mix(groundAmbient, skyColor, up) * (0.55 + 0.45*sh);
    vec3 color = direct + ambient;

    if(fogDensity>0.0){
        float fog = 1.0-exp(-fogDensity*length(vEyePos));
        color = mix(color, fogColor, clamp(fog,0.0,1.0));
    }
    color = aces(color);
    fragColor = vec4(linearToSRGB(color), 1.0);
}

// X3D's Phong lighting for one light (ISO/IEC 19775-1, 17.2.2.5) -- the
// attenuation, the spot cone and a light's diffuse and specular terms, on the
// colour values as given. Shared by the VRML97 pass's lit shaders and the PBR
// shader's Phong mode. Needs _lights_inc (the light uniforms) and declares no
// uniform of its own.

// X3D's 1 / max(c0 + c1 d + c2 d^2, floor): the floor is 1 for X3D's lights,
// which never light more than their intensity, and near 0 for glTF's.
float calcAttenuation(int lightIndex, float distance) {
    if (lightRadius[lightIndex] > 0.0 && distance > lightRadius[lightIndex]) {
        return 0.0;
    }
    vec3 atten = lightAttenuation[lightIndex];
    return 1.0 / max(atten.x + atten.y * distance + atten.z * distance * distance,
                     max(lightAttenuationFloor[lightIndex], 1e-4));
}

// Spot cone falloff: a LINEAR ramp in cos-angle from the outer cutoff to the
// inner beamWidth -- the VRML97 SpotLight model (pbr.frag's smoothstep cone is
// glTF/KHR_lights_punctual; the divergence is intentional, do NOT "unify" them).
float calcSpotEffect(int lightIndex, vec3 lightDir) {
    vec3 spotDir = normalize(lightDirection[lightIndex]);
    float cosAngle = dot(-lightDir, spotDir);
    float cutoff = cos(lightCutOffAngle[lightIndex]);
    float beamWidth = cos(lightBeamWidth[lightIndex]);

    if (cosAngle < cutoff) {
        return 0.0;
    } else if (cosAngle > beamWidth) {
        return 1.0;
    } else {
        return (cosAngle - cutoff) / (beamWidth - cutoff);
    }
}

// The ambient, diffuse and specular light one light gives a fragment at the
// eye-space `position`, scaled by its shadow factor (1.0 = fully lit).
// `matAmbient` is the Material's ambientIntensity times its diffuse colour;
// `shininess` is X3D's, 0 to 1, the exponent 128 times it.
vec3 phongLight(int lightIndex, vec3 normal, vec3 viewDir, vec3 position,
                vec3 matDiffuse, vec3 matAmbient, vec3 matSpecular, float shininess,
                float shadowFactor) {
    if (lightType[lightIndex] == LIGHT_OFF) {
        return vec3(0.0);
    }

    vec3 lightDir;
    float attenuation = 1.0;

    if (lightType[lightIndex] == LIGHT_DIRECTIONAL) {
        // VRML direction is where the light POINTS (toward surface); N·L needs the
        // direction FROM surface TO light, so negate.
        lightDir = normalize(-lightDirection[lightIndex]);
    } else {
        vec3 lightVec = lightPosition[lightIndex].xyz - position;
        float distance = length(lightVec);
        lightDir = lightVec / max(distance, 1e-4);
        attenuation = calcAttenuation(lightIndex, distance);

        if (lightType[lightIndex] == LIGHT_SPOT) {
            attenuation *= calcSpotEffect(lightIndex, lightDir);
        }
    }

    if (attenuation <= 0.0) {
        return vec3(0.0);
    }

    vec3 color = lightColor[lightIndex] * lightIntensity[lightIndex];
    vec3 ambient = lightColor[lightIndex] * lightAmbientIntensity[lightIndex] * matAmbient;

    // Diffuse (Lambert)
    float nDotL = max(dot(normal, lightDir), 0.0);
    vec3 diffuse = matDiffuse * color * nDotL;

    // Specular (Blinn-Phong)
    vec3 specular = vec3(0.0);
    if (nDotL > 0.0 && shininess > 0.0) {
        vec3 halfDir = normalize(lightDir + viewDir);
        float nDotH = max(dot(normal, halfDir), 0.0);
        specular = matSpecular * color * pow(nDotH, shininess * 128.0);
    }

    return shadowFactor * attenuation * (ambient + diffuse + specular);
}

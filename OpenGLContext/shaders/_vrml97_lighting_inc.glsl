// Shared VRML97 lighting math -- the attenuation, spot-cone and per-light
// contribution functions -- included by both vrml97_lighting.frag (material
// diffuse) and vrml97_vertex_color.frag (per-vertex diffuse) so the two stay in
// lock-step (finding 2a). The including shader must first pull in _lights_inc
// (the light-uniform block + enums) and declare the `vPosition` varying and the
// `shininess` uniform. calcLight takes a per-light shadowFactor, so a shader that
// resolves shadows passes it through and one that doesn't passes 1.0.

// Attenuation for point/spot lights. Clamp the denominator (as pbr.frag does) so
// a zero-constant light near a fragment can't divide by zero into Inf/NaN.
float calcAttenuation(int lightIndex, float distance) {
    vec3 atten = lightAttenuation[lightIndex];
    return 1.0 / max(atten.x + atten.y * distance + atten.z * distance * distance, 1e-4);
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

// Contribution of a single light, scaled by its shadow factor (1.0 = fully lit).
vec3 calcLight(int lightIndex, vec3 normal, vec3 viewDir,
               vec3 matDiffuse, vec3 matSpecular, float shadowFactor) {
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
        vec3 lightVec = lightPosition[lightIndex].xyz - vPosition;
        float distance = length(lightVec);
        lightDir = lightVec / distance;
        attenuation = calcAttenuation(lightIndex, distance);

        if (lightType[lightIndex] == LIGHT_SPOT) {
            attenuation *= calcSpotEffect(lightIndex, lightDir);
        }
    }

    if (attenuation <= 0.0) {
        return vec3(0.0);
    }

    vec3 color = lightColor[lightIndex] * lightIntensity[lightIndex];

    // Diffuse (Lambert)
    float nDotL = max(dot(normal, lightDir), 0.0);
    vec3 diffuse = matDiffuse * color * nDotL;

    // Specular (Blinn-Phong). VRML97 shininess is 0-1, mapped to a 0..128 exponent.
    vec3 specular = vec3(0.0);
    if (nDotL > 0.0 && shininess > 0.0) {
        vec3 halfDir = normalize(lightDir + viewDir);
        float nDotH = max(dot(normal, halfDir), 0.0);
        specular = matSpecular * color * pow(nDotH, shininess * 128.0);
    }

    return shadowFactor * attenuation * (diffuse + specular);
}

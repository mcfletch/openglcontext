// Order-independent transparency (OpenGLContext.passes.oit): with oitPass
// the fragment's colour and opacity, already written, become what the two
// weighted-blended targets accumulate. The weight is X_ITE 16.4.3's OIT2
// (MIT licence, see license.txt). Included after the fragColor and
// fragObjectId outputs are declared; main() calls oitAccumulate() last.

uniform bool oitPass;   // the transparent surfaces of a view drawn into the OIT targets

void oitAccumulate() {
    if (!oitPass) return;
    float a = fragColor.a;
    float w = clamp(pow(min(1.0, a * 10.0) + 0.01, 3.0) * 1e8
                    * pow(1.0 - gl_FragCoord.z * 0.9, 3.0), 1e-2, 3e3);
    fragColor = vec4(fragColor.rgb * a * w, a);
    fragObjectId = vec4(a * w);
}

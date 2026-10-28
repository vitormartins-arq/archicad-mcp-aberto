#pragma once

// Get3DProjectionSets returns degrees; API_CameraID stores these angles in radians.
// A camera element cannot keep two-point perspective (AC30 reads it back as false, live
// test 28/10/2026), so the flag is cleared and read-back compares like with like.
// Keep coordinates, distances and sun settings untouched.
template<class Perspective>
constexpr Perspective CameraPerspective (const Perspective& projection)
{
    auto camera = projection;
    constexpr double radiansPerDegree = 3.14159265358979323846 / 180.0;
    camera.viewCone *= radiansPerDegree;
    camera.rollAngle *= radiansPerDegree;
    camera.azimuth *= radiansPerDegree;
    camera.isTwoPointPersp = false;
    return camera;
}

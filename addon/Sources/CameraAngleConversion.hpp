#pragma once

// Get3DProjectionSets returns degrees; API_CameraID stores these angles in radians.
// Keep coordinates, distances, two-point perspective and sun settings untouched.
template<class Perspective>
constexpr Perspective CameraPerspective (const Perspective& projection)
{
    auto camera = projection;
    constexpr double radiansPerDegree = 3.14159265358979323846 / 180.0;
    camera.viewCone *= radiansPerDegree;
    camera.rollAngle *= radiansPerDegree;
    camera.azimuth *= radiansPerDegree;
    return camera;
}

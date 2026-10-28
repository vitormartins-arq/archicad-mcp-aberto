#include "../Sources/CameraAngleConversion.hpp"
#include <cassert>
#include <cmath>

struct PerspectiveFixture {
    double viewCone, rollAngle, azimuth, distance, cameraZ;
    bool isTwoPointPersp;
    double sunAltitude;
};

int main ()
{
    // Regression from AC30: copying 75 degrees directly clamped the camera to 120.
    const PerspectiveFixture source {75.0, -30.0, 261.821744124, 37.445907827, 1.161563224, true, 45.0};
    const auto camera = CameraPerspective (source);
    assert (std::abs (camera.viewCone - 1.3089969389957472) < 1e-12);
    assert (std::abs (camera.rollAngle + 0.5235987755982988) < 1e-12);
    assert (std::abs (camera.azimuth - 4.569651488434038) < 1e-9);
    assert (camera.distance == source.distance && camera.cameraZ == source.cameraZ);
    assert (camera.isTwoPointPersp && camera.sunAltitude == source.sunAltitude);
    assert (source.viewCone == 75.0);
}

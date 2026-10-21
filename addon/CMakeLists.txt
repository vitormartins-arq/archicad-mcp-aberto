cmake_minimum_required (VERSION 3.17)

# Build tooling copied from Tapir (MIT, Enzyme APD); see Tools/LICENSE-Tapir.
include (Tools/CMakeCommon.cmake)

set_property (GLOBAL PROPERTY USE_FOLDERS ON)

set (CMAKE_CONFIGURATION_TYPES Debug;Release;RelWithDebInfo)
set (AC_API_DEVKIT_DIR ${AC_API_DEVKIT_DIR} CACHE PATH "API DevKit directory.")
set (AC_VERSION ${API_AC_VERSION} CACHE STRING "Archicad version.")
# MDID issued by Graphisoft for "Archicad MCP Aberto" (registered 21/10/2026). A fork
# that ships its own build registers its own Local ID and passes it here.
set (AC_MDID_DEVELOPER_ID 1110659426 CACHE STRING "MDID Developer ID issued by Graphisoft.")
set (AC_MDID_LOCAL_ID 287719994 CACHE STRING "MDID Local ID issued by Graphisoft for this add-on.")

SetGlobalCompilerDefinitions (${AC_VERSION})

if (WIN32)
	set (NamePostFix Win)
else ()
	set (NamePostFix Mac)
endif ()
set (AddOnName "ArchicadMcpAberto_AC${AC_VERSION}_${NamePostFix}")

project (${AddOnName})

# The resource compiler reads ResourceObjects, so the MDID header goes there.
configure_file (Sources/DeveloperIds.hpp.in ${CMAKE_BINARY_DIR}/ResourceObjects/DeveloperIds.hpp @ONLY)

set (AddOnSourcesFolder Sources)
set (AddOnResourcesFolder Sources)
GenerateAddOnProject (AddOn ${AC_VERSION} ${AC_API_DEVKIT_DIR} ${AddOnName} ${AddOnSourcesFolder} ${AddOnResourcesFolder} INT)

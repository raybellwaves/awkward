cmake_minimum_required(VERSION 3.15...3.26)

project(
  ${SKBUILD_PROJECT_NAME}
  LANGUAGES CXX
  VERSION ${SKBUILD_PROJECT_VERSION})

# Set required standards
set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Download headers
include(FetchContent)
set(AWKWARD_VERSION "v2.0.10")
FetchContent_Declare(
  awkward-headers
  URL https://github.com/scikit-hep/awkward/releases/download/${AWKWARD_VERSION}/header-only.zip)
# Instead of using `FetchContent_MakeAvailable(awkward-headers)`, we manually load the target so
# that we can EXCLUDE_FROM_ALL
FetchContent_GetProperties(awkward-headers)
if(NOT awkward-headers_POPULATED)
  FetchContent_Populate(awkward-headers)
  add_subdirectory(${awkward-headers_SOURCE_DIR} ${awkward-headers_BINARY_DIR} EXCLUDE_FROM_ALL)
endif()

# Load interpreter & pybind11
find_package(Python COMPONENTS Interpreter Development.Module)
find_package(pybind11 CONFIG)

# Build demo module
pybind11_add_module(demo demo.cpp)
target_link_libraries(demo PRIVATE awkward::layout-builder)

# Install into wheel
install(TARGETS demo DESTINATION .)

cmake_minimum_required(VERSION 3.10)
project(DisasterReliefSystem CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include_directories(${CMAKE_SOURCE_DIR}/include)

file(GLOB SOURCES "${CMAKE_SOURCE_DIR}/src/*.cpp")

add_executable(drras ${SOURCES})

# Needed on some GCC/MinGW setups for <filesystem>
if (CMAKE_CXX_COMPILER_ID MATCHES "GNU")
    target_link_libraries(drras stdc++fs)
endif()
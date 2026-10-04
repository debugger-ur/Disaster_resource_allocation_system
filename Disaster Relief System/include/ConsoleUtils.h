#pragma once
#include <string>
#include <climits>

namespace drras {

// Small set of validated console-input helpers -> keeps UI code in App.cpp
// free from repetitive cin-error-handling boilerplate.
int readInt(const std::string &prompt, int minVal = INT_MIN, int maxVal = INT_MAX);
double readDouble(const std::string &prompt, double minVal = -1e18, double maxVal = 1e18);
std::string readLine(const std::string &prompt);
char readChoiceChar(const std::string &prompt);

} // namespace drras
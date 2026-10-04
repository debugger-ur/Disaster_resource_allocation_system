#include "ConsoleUtils.h"
#include <iostream>
#include <sstream>

namespace drras {

static std::string trim(const std::string &s) {
    size_t start = s.find_first_not_of(" \t\r\n");
    size_t end = s.find_last_not_of(" \t\r\n");
    if (start == std::string::npos) return "";
    return s.substr(start, end - start + 1);
}

int readInt(const std::string &prompt, int minVal, int maxVal) {
    while (true) {
        std::cout << prompt;
        std::string line;
        std::getline(std::cin, line);
        line = trim(line);
        try {
            size_t pos = 0;
            int val = std::stoi(line, &pos);
            if (pos != line.size()) throw std::invalid_argument("trailing");
            if (val < minVal || val > maxVal) {
                std::cout << "Please enter a value between " << minVal << " and " << maxVal << ".\n";
                continue;
            }
            return val;
        } catch (...) {
            std::cout << "Invalid integer input. Please try again.\n";
        }
    }
}

double readDouble(const std::string &prompt, double minVal, double maxVal) {
    while (true) {
        std::cout << prompt;
        std::string line;
        std::getline(std::cin, line);
        line = trim(line);
        try {
            size_t pos = 0;
            double val = std::stod(line, &pos);
            if (pos != line.size()) throw std::invalid_argument("trailing");
            if (val < minVal || val > maxVal) {
                std::cout << "Please enter a value between " << minVal << " and " << maxVal << ".\n";
                continue;
            }
            return val;
        } catch (...) {
            std::cout << "Invalid number input. Please try again.\n";
        }
    }
}

std::string readLine(const std::string &prompt) {
    std::cout << prompt;
    std::string line;
    std::getline(std::cin, line);
    return trim(line);
}

char readChoiceChar(const std::string &prompt) {
    std::string line = readLine(prompt);
    return line.empty() ? '\0' : line[0];
}

} // namespace drras
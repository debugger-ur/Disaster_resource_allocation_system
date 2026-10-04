#include "App.h"
#include <iostream>

int main() {
    try {
        drras::App app;
        app.run();
    } catch (const std::exception &e) {
        std::cerr << "Fatal error: " << e.what() << std::endl;
        return 1;
    }
    return 0;
}
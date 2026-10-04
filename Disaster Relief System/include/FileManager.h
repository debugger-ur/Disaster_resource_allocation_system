#pragma once
#include <string>
#include <vector>

namespace drras {

// Generic CSV / file persistence helper shared by every manager.
class FileManager {
public:
    FileManager() = delete;

    static bool fileExists(const std::string &path);
    static void ensureFile(const std::string &path, const std::string &header);

    static std::vector<std::vector<std::string>> readCSV(const std::string &path, bool skipHeader = true);
    static void appendCSVRow(const std::string &path, const std::vector<std::string> &fields);
    static void writeCSVAll(const std::string &path, const std::string &header,
                              const std::vector<std::vector<std::string>> &rows);

    static std::vector<std::string> splitLine(const std::string &line, char delim = ',');
    static std::string joinFields(const std::vector<std::string> &fields, char delim = ',');

    static void logMessage(const std::string &message, const std::string &logFile = "data/logs.txt");
};

} // namespace drras
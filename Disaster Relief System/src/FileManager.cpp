#include "FileManager.h"
#include "Exceptions.h"
#include "Common.h"
#include <fstream>
#include <sstream>
#include <filesystem>

namespace drras {
namespace fs = std::filesystem;

bool FileManager::fileExists(const std::string &path) {
    return fs::exists(path);
}

void FileManager::ensureFile(const std::string &path, const std::string &header) {
    fs::path p(path);
    if (p.has_parent_path() && !fs::exists(p.parent_path())) {
        fs::create_directories(p.parent_path());
    }
    if (!fs::exists(path)) {
        std::ofstream out(path);
        if (!header.empty()) out << header << "\n";
    }
}

std::vector<std::string> FileManager::splitLine(const std::string &line, char delim) {
    std::vector<std::string> fields;
    std::stringstream ss(line);
    std::string field;
    while (std::getline(ss, field, delim)) fields.push_back(field);
    if (!line.empty() && line.back() == delim) fields.push_back("");
    return fields;
}

std::string FileManager::joinFields(const std::vector<std::string> &fields, char delim) {
    std::string result;
    for (size_t i = 0; i < fields.size(); ++i) {
        result += fields[i];
        if (i + 1 < fields.size()) result += delim;
    }
    return result;
}

std::vector<std::vector<std::string>> FileManager::readCSV(const std::string &path, bool skipHeader) {
    std::vector<std::vector<std::string>> rows;
    std::ifstream in(path);
    if (!in.is_open()) return rows; // missing file -> treat as empty dataset

    std::string line;
    bool first = true;
    while (std::getline(in, line)) {
        if (line.empty()) continue;
        if (first && skipHeader) { first = false; continue; }
        first = false;
        rows.push_back(splitLine(line));
    }
    return rows;
}

void FileManager::appendCSVRow(const std::string &path, const std::vector<std::string> &fields) {
    std::ofstream out(path, std::ios::app);
    if (!out.is_open()) throw FileIOException("Unable to open file for writing: " + path);
    out << joinFields(fields) << "\n";
}

void FileManager::writeCSVAll(const std::string &path, const std::string &header,
                                const std::vector<std::vector<std::string>> &rows) {
    std::ofstream out(path, std::ios::trunc);
    if (!out.is_open()) throw FileIOException("Unable to open file for writing: " + path);
    out << header << "\n";
    for (const auto &row : rows) out << joinFields(row) << "\n";
}

void FileManager::logMessage(const std::string &message, const std::string &logFile) {
    ensureFile(logFile, "");
    std::ofstream out(logFile, std::ios::app);
    out << currentTimestamp() << " - " << message << "\n";
}

} // namespace drras
#pragma once
#include <stdexcept>
#include <string>

namespace drras {

class DRRASException : public std::runtime_error {
public:
    explicit DRRASException(const std::string &msg) : std::runtime_error(msg) {}
};

class InvalidInputException   : public DRRASException { public: using DRRASException::DRRASException; };
class DuplicateIDException    : public DRRASException { public: using DRRASException::DRRASException; };
class RecordNotFoundException : public DRRASException { public: using DRRASException::DRRASException; };
class FileIOException         : public DRRASException { public: using DRRASException::DRRASException; };

} // namespace drras
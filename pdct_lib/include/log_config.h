#ifndef LOG_CONFIG_H
#define LOG_CONFIG_H

// Log levels
enum class LogLevel {
    OUT,
    INFO,
    WARNING,
    ERROR,
    NUM_LEVEL
};

// Default configuration
#define ENABLE_LOG 1
#define DEFAULT_LOG_LEVEL LogLevel::INFO
#define LOG_FILE_PATH "pdct.log"

#endif // LOG_CONFIG_H

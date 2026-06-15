"""
Logging utilities for the ma_aos multi-agent system.

Provides centralized logging functions for file-based and console output.
"""

import time

# Global log file handle
log_file = None


def setup_logging(filename='logs_run.txt', episode_type="EPISODE"):
    """
    Initialize logging to file with timestamp.
    
    Args:
        filename (str): Path to log file. Default: 'logs_run.txt'
        episode_type (str): Type of episode for logging header. Default: "EPISODE"
    """
    global log_file
    log_file = open(filename, 'w', buffering=1)  # Line buffering for immediate write
    log_message(f"{'='*80}")
    log_message(f"{episode_type} START - {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log_message(f"{'='*80}\n")


def log_message(msg):
    """
    Write message to both console and file.
    
    Args:
        msg (str): Message to log
    """
    global log_file
    print(msg)
    if log_file:
        log_file.write(msg + '\n')
        log_file.flush()


def close_logging():
    """Close log file."""
    global log_file
    if log_file:
        log_file.close()
        log_file = None

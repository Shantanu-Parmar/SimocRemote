import os

class Config:
    """Application configuration."""
    LOG_DIR = os.environ.get('SIMOC_LOG_DIR', '/home/pi/logs')
    BLOCKED_SENSOR_SUBSTRINGS = ["mock", "test", "dummy"]
    DEBUG = False
    THREADED = True
    HOST = '0.0.0.0'
    PORT = 5000

# Load config
config = Config()
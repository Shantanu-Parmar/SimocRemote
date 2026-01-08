# app.py
import logging
from flask import Flask
from config import config
from utils import discover_sensors
from routes import register_routes

app = Flask(__name__, template_folder='templates', static_folder='static')

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Discover sensors at startup
sensors = discover_sensors(config.LOG_DIR, config.BLOCKED_SENSOR_SUBSTRINGS)

# Register all routes (including the main / route)
register_routes(app, sensors, config.LOG_DIR)

if __name__ == '__main__':
    app.run(
        host=config.HOST,
        port=config.PORT,
        debug=config.DEBUG,
        threaded=config.THREADED
    )

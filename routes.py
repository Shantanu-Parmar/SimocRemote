# simoc_dashboard/routes.py
from flask import render_template, request, jsonify, send_file, abort
import io
import datetime
import pandas as pd
import os
import json
#from .utils import get_data_in_range, get_decimated_data, get_last_data
from utils import get_data_in_range, get_decimated_data, get_last_data
from utils import find_start_offset, find_end_offset  # Import missing functions
def register_routes(app, sensors, log_dir):
    """
    Register all Flask routes for the dashboard.

    Args:
        app (Flask): The Flask application instance.
        sensors (dict): Discovered sensors dictionary.
        log_dir (str): Path to log directory.
    """

    @app.route('/decimated_data/<sensor>')
    def decimated_data_route(sensor):
        """API endpoint: decimated full history."""
        if sensor not in sensors:
            return jsonify([]), 404
        filepath = os.path.join(log_dir, sensors[sensor]['file'])
        data = get_decimated_data(filepath)
        return jsonify(data)

    @app.route('/last_2h_data/<sensor>')
    def last_2h_data_route(sensor):
        """API endpoint: last 2 hours of data."""
        if sensor not in sensors:
            return jsonify([]), 404
        filepath = os.path.join(log_dir, sensors[sensor]['file'])
        end = datetime.datetime.now()
        start = end - datetime.timedelta(hours=2)
        data = get_data_in_range(filepath, start, end)
        return jsonify(data)

    @app.route('/last_data/<sensor>')
    def last_data_route(sensor):
        """API endpoint: most recent entry."""
        if sensor not in sensors:
            return jsonify({}), 404
        filepath = os.path.join(log_dir, sensors[sensor]['file'])
        entry = get_last_data(filepath)
        return jsonify(entry or {})

    @app.route('/range_data/<sensor>')
    def range_data_route(sensor):
        """Get data in a custom range for a sensor. If no range, return all data."""
        if sensor not in sensors:
            return jsonify([]), 404

        start_str = request.args.get('start')
        end_str = request.args.get('end')

        filepath = os.path.join(log_dir, sensors[sensor]['file'])

        if not os.path.exists(filepath):
            return jsonify([]), 404

        data = []
        try:
            with open(filepath, 'r') as f:
                if start_str and end_str:
                    start = datetime.datetime.strptime(start_str, '%Y-%m-%d %H:%M:%S')
                    end = datetime.datetime.strptime(end_str, '%Y-%m-%d %H:%M:%S')
                    start_offset = find_start_offset(f, start)
                    end_offset = find_end_offset(f, end, lo=start_offset)
                    f.seek(start_offset)
                    while f.tell() < end_offset:
                        line = f.readline()
                        if not line.strip():
                            continue

                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue  # skip corrupted line safely

                        ts_str = entry.get("timestamp")
                        if not ts_str:
                            continue

                        try:
                            ts = datetime.datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S.%f')
                        except ValueError:
                            continue

                        if start <= ts <= end:
                            data.append(entry)
                else:
                    # No range: read all
                    for line in f:
                        if not line.strip():
                            continue

                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        data.append(entry)

        except Exception as e:
            app.logger.error(f"Error fetching range data for {sensor}: {e}")
            return jsonify([]), 500

        return jsonify(data)

    @app.route('/')
    def index():
        num_sensors = len(sensors)
        if num_sensors == 1:
            live_col_class = "col-12"
        elif num_sensors == 2:
            live_col_class = "col-lg-6 col-md-6 col-sm-12"
        elif num_sensors == 3:
            live_col_class = "col-lg-4 col-md-6 col-sm-12"
        elif num_sensors <= 6:
            live_col_class = "col-lg-4 col-md-6 col-sm-12"
        else:
            live_col_class = "col-lg-3 col-md-4 col-sm-6"
        
        return render_template(
            'dashboard.html',
            sensors=sensors,
            live_col_class=live_col_class
        )

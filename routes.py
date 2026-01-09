# simoc_dashboard/routes.py
from flask import render_template, request, jsonify, send_file, abort, Response
import io
import datetime
import pandas as pd
import os
import json
import csv
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
                        
    @app.route('/sensor_range/<sensor>')
    def sensor_range(sensor):
        """Fast endpoint: returns min/max timestamp and approx count for a sensor."""
        if sensor not in sensors:
            return jsonify({"error": "Sensor not found"}), 404

        filepath = os.path.join(log_dir, sensors[sensor]['file'])

        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            return jsonify({"start": None, "end": None, "count": 0})

        try:
            with open(filepath, 'r') as f:
                # First line
                first_line = f.readline().strip()
                if not first_line:
                    return jsonify({"start": None, "end": None, "count": 0})

                first = json.loads(first_line)
                start_ts = first.get('timestamp')

                # Last line (efficient backward seek)
                f.seek(0, os.SEEK_END)
                pos = f.tell() - 1
                while pos > 0:
                    pos -= 1
                    f.seek(pos)
                    if f.read(1) == '\n':
                        break
                last_line = f.readline().strip()
                last = json.loads(last_line) if last_line else first
                end_ts = last.get('timestamp')

                # Rough line count (fast approximation)
                count = sum(1 for _ in open(filepath)) if start_ts else 0

            return jsonify({
                "start": start_ts,
                "end": end_ts,
                "count": count
            })

        except Exception as e:
            app.logger.error(f"Error getting range for {sensor}: {e}")
            return jsonify({"error": str(e)}), 500
        

    @app.route('/download_full/<sensor>')
    def download_full(sensor):
        """Download full CSV for a sensor - all parameters, missing as 'NA'"""
        if sensor not in sensors:
            abort(404)

        filepath = os.path.join(log_dir, sensors[sensor]['file'])

        if not os.path.exists(filepath):
            abort(404, "Sensor file not found")

        output = io.StringIO()
        writer = csv.writer(output)

        # Header: timestamp + all params
        params = sensors[sensor]['params']
        headers = ['timestamp'] + params
        writer.writerow(headers)

        try:
            with open(filepath, 'r') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)
                        row = [entry.get('timestamp', '')]
                        for p in params:
                            row.append(entry.get(p, 'NA'))  # ← NA for missing
                        writer.writerow(row)
                    except json.JSONDecodeError:
                        continue  # skip bad lines
        except Exception as e:
            app.logger.error(f"CSV download error for {sensor}: {e}")
            abort(500)

        output.seek(0)

        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={
                "Content-Disposition": f"attachment; filename={sensor}_full_data.csv"
            }
        )


    @app.route('/download_range/<sensor>')
    def download_range(sensor):
        if sensor not in sensors:
            abort(404)

        start_str = request.args.get('start')
        end_str   = request.args.get('end')

        if not start_str or not end_str:
            abort(400, "Missing start or end parameter")

        try:
            start = datetime.datetime.strptime(start_str, '%Y-%m-%d %H:%M:%S')
            end   = datetime.datetime.strptime(end_str, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            abort(400, "Invalid date format")

        filepath = os.path.join(log_dir, sensors[sensor]['file'])

        output = io.StringIO()
        writer = csv.writer(output)

        # Header: timestamp + all params
        params = sensors[sensor]['params']
        writer.writerow(['timestamp'] + params)

        try:
            data = get_data_in_range(filepath, start, end)  # Reuse your existing function!
            for entry in data:
                row = [entry.get('timestamp', '')]
                for p in params:
                    row.append(entry.get(p, 'NA'))  # Or '' / None — your choice
                writer.writerow(row)
        except Exception as e:
            app.logger.error(f"CSV error for {sensor}: {e}")
            abort(500)

        output.seek(0)

        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={"Content-Disposition": f"attachment; filename={sensor}_data_{start_str}_to_{end_str}.csv"}
        )

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

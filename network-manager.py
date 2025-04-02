from flask import Flask, render_template, request, flash, redirect, url_for, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix
from logging.handlers import RotatingFileHandler
from datetime import datetime
from pathlib import Path
import subprocess
import scan_devices
import platform
import database
import ipaddress
import logging
import os
import re

base_dir = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'c5521ab2e51b07b079aad5258ffb8ff719f40e6925f19e8d184c059b1f25bd68')

# Configure logging
if not os.path.exists('logs'):
    os.makedirs('logs')

file_handler = RotatingFileHandler('logs/network_manager.log', maxBytes=10240, backupCount=10)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
file_handler.setLevel(logging.INFO)
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)
app.logger.info('Network Manager startup')

def get_db():
    conn = database.create_connection()
    if conn is None:
        app.logger.error("Database connection failed")
        raise Exception("Database connection failed")
    return conn

def init_db():
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Create tables if they don't exist - MariaDB syntax
        c.execute('''
            CREATE TABLE IF NOT EXISTS devices (
                id INT PRIMARY KEY AUTO_INCREMENT,
                ip_address VARCHAR(45),
                hostname VARCHAR(255) NOT NULL,
                mac_address VARCHAR(17) UNIQUE NOT NULL,
                device_type VARCHAR(50),
                notes TEXT,
                last_seen DATETIME
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS leases (
                id INT PRIMARY KEY AUTO_INCREMENT,
                device_id INT,
                ip_address VARCHAR(45) NOT NULL,
                active BOOLEAN DEFAULT 1,
                FOREIGN KEY (device_id) REFERENCES devices (id) ON DELETE CASCADE
            )
        ''')
        
        conn.commit()
    except Exception as e:
        app.logger.error(f"Database initialization failed: {e}")
        raise
    finally:
        if conn:
            database.close_connection(conn)

@app.route('/')
def index():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''
            SELECT d.*, l.ip_address
            FROM devices d 
            LEFT JOIN leases l ON d.id = l.device_id AND l.active = 1
            ORDER BY d.ip_address
        ''')
        devices = c.fetchall()
        return render_template('index.html', devices=devices)
    except Exception as e:
        app.logger.error(f"Error in index route: {e}")
        flash('An error occurred while loading devices', 'error')
        return redirect(url_for('index'))
    finally:
        if conn:
            database.close_connection(conn)

@app.route('/add_device', methods=['GET', 'POST'])
def add_device():
    if request.method == 'POST':
        ip_address = request.form['ip_address']
        hostname = request.form['hostname']
        mac_address = request.form['mac_address']
        device_type = request.form['device_type']
        notes = request.form['notes']
        
        if not validate_mac(mac_address):
            flash('Invalid MAC address format')
            return redirect(url_for('add_device'))
        
        mac_address = format_mac(mac_address)
        
        if not validate_ip(ip_address):
            flash('Invalid IP address format')
            return redirect(url_for('add_device'))
        
        ip_address = format_ip(ip_address)
        
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute('''
                INSERT INTO devices (ip_address, hostname, mac_address, device_type, notes, last_seen)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (ip_address, hostname, mac_address, device_type, notes, datetime.now()))
            conn.commit()
            flash('Device added successfully')
            return redirect(url_for('index'))
        except database.mysql.connector.IntegrityError:
            flash('MAC address already exists')
            return redirect(url_for('add_device'))
        except Exception as e:
            app.logger.error(f"Error adding device: {e}")
            flash('An error occurred while adding the device')
            return redirect(url_for('add_device'))
        finally:
            if conn:
                database.close_connection(conn)
    
    return render_template('add_device.html')

@app.route('/edit_device/<int:device_id>', methods=['GET', 'POST'])
def edit_device(device_id):
    conn = None
    try:
        conn = get_db()
        c = conn.cursor()
        
        if request.method == 'POST':
            ip_address = format_ip(request.form['ip_address'])
            hostname = request.form['hostname']
            mac_address = format_mac(request.form['mac_address'])
            device_type = request.form['device_type']
            notes = request.form['notes']
            
            c.execute('''
                UPDATE devices 
                SET ip_address = %s, hostname = %s, mac_address = %s, 
                    device_type = %s, notes = %s, last_seen = %s
                WHERE id = %s
            ''', (ip_address, hostname, mac_address, device_type, notes, datetime.now(), device_id))
            conn.commit()
            flash('Device updated successfully')
            return redirect(url_for('index'))
        
        c.execute('SELECT * FROM devices WHERE id = %s', (device_id,))
        device = c.fetchone()
        if device is None:
            flash('Device not found')
            return redirect(url_for('index'))
            
        return render_template('edit_device.html', device=device)
    
    except Exception as e:
        app.logger.error(f"Error in edit_device: {e}")
        flash('An error occurred while processing your request')
        return redirect(url_for('index'))
    finally:
        if conn:
            database.close_connection(conn)

@app.route('/remove_device/<int:device_id>')
def remove_device(device_id):
    conn = None
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM devices WHERE id = %s', (device_id,))
        conn.commit()
        flash('Device removed successfully')
    except Exception as e:
        app.logger.error(f"Error removing device: {e}")
        flash('An error occurred while removing the device')
    finally:
        if conn:
            database.close_connection(conn)
    return redirect(url_for('index'))

@app.route('/remove_devices', methods=['POST'])
def remove_devices():
    if request.form.getlist('device_ids[]'):
        conn = None
        try:
            conn = get_db()
            c = conn.cursor()
            device_ids = request.form.getlist('device_ids[]')
            placeholders = ','.join(['%s'] * len(device_ids))
            c.execute(f'DELETE FROM devices WHERE id IN ({placeholders})', device_ids)
            conn.commit()
            flash(f'{len(device_ids)} devices removed successfully')
        except Exception as e:
            app.logger.error(f"Error removing multiple devices: {e}")
            flash('An error occurred while removing devices')
        finally:
            if conn:
                database.close_connection(conn)
    return redirect(url_for('index'))

def validate_mac(mac):
    """Validate MAC address format"""
    mac = mac.replace(':', '').replace('-', '').replace('_', '')
    return len(mac) == 12 and all(c in '0123456789ABCDEFabcdef' for c in mac)

def format_mac(mac):
    """Format MAC address to XX:XX:XX:XX:XX:XX"""
    mac = mac.replace(':', '').replace('-', '').replace('_', '').upper()
    return ':'.join([mac[i:i+2] for i in range(0, 12, 2)])

def validate_ip(ip):
    """Validate IP address format"""
    import re
    ip = ip.replace('_', '.').replace('-', '.')
    return bool(re.match(r'^(\d{1,3}\.){3}\d{1,3}$', ip))

def format_ip(ip):
    """Format IP address to XXX.XXX.XXX.XXX"""
    ip = ip.replace('_', '.').replace('-', '.')
    parts = ip.split('.')
    return '.'.join(parts)

@app.route('/setup_nui', methods=['GET', 'POST'])
def setup_nui():
    conn = None
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Create settings table if it doesn't exist
        c.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                id INT PRIMARY KEY AUTO_INCREMENT,
                `key` VARCHAR(50) UNIQUE NOT NULL,
                value TEXT
            )
        ''')
        conn.commit()
        
        if request.method == 'POST':
            subnet = request.form['subnet']
            try:
                # Validate subnet format
                ipaddress.ip_network(subnet)
                c.execute('''
                    INSERT INTO settings (`key`, value) 
                    VALUES ('scan_subnet', %s)
                    ON DUPLICATE KEY UPDATE value = %s
                ''', (subnet, subnet))
                conn.commit()
                flash('Settings saved successfully')
                return redirect(url_for('index'))
            except ValueError:
                flash('Invalid subnet format')
                return redirect(url_for('setup_nui'))
        
        # Get current subnet
        c.execute('SELECT value FROM settings WHERE `key` = "scan_subnet"')
        result = c.fetchone()
        subnet = result[0] if result else '192.168.1.0/24'
        
        return render_template('setup_nui.html', subnet=subnet)
    except Exception as e:
        app.logger.error(f"Error in setup_nui: {e}")
        flash('An error occurred')
        return redirect(url_for('index'))
    finally:
        if conn:
            database.close_connection(conn)

@app.route('/scan_devices', methods=['POST'])
def scan_devices():
    try:
        conn = get_db()
        # Import the NetworkScanner class correctly
        from scan_devices import NetworkScanner
        
        # Create an instance of NetworkScanner with the connection
        scanner = NetworkScanner(conn)
        
        # Start the scan
        if scanner.start_scan():
            flash('Network scan started')
            return render_template('scan_devices.html')
        else:
            flash('A scan is already in progress')
            return redirect(url_for('index'))
    except Exception as e:
        app.logger.error(f"Error starting network scan: {e}")
        flash(f'Failed to start network scan: {str(e)}')
        return redirect(url_for('index'))

@app.route('/check_scan_complete')
def check_scan_complete():
    try:
        conn = get_db()
        scanner = scan_devices.NetworkScanner(conn)
        status = scanner.get_scan_status()
        if not status['in_progress']:
            return jsonify({'complete': True, 'devices': status['devices_found']})
        return jsonify({'complete': False})
    except Exception as e:
        app.logger.error(f"Error checking scan status: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/scan_status')
def scan_status():
    try:
        conn = get_db()
        c = conn.cursor()
        scanner = NetworkScanner(conn)
        return jsonify(scanner.get_scan_status())
    except Exception as e:
        app.logger.error(f"Error getting scan status: {e}")
        return jsonify({'error': str(e)}), 500

# In init_db() function, add this table:
#conn = get_db()
#c = conn.cursor()

#c.execute('''
#    INSERT INTO settings (
#        id INT PRIMARY KEY AUTO_INCREMENT,
#        key VARCHAR(50) UNIQUE NOT NULL,
#        value TEXT
#    )
#''')

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('FLASK_PORT', 5000))
    bind_address = os.environ.get('FLASK_BIND_ADDRESS', '0.0.0.0')
    
    app.run(host=bind_address, port=port, debug=False)
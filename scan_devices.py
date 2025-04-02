import ipaddress
import subprocess
import platform
import threading
import queue
import socket
from datetime import datetime
from flask import current_app

class NetworkScanner:
    def __init__(self, db_connection):
        self.db = db_connection
        self.scan_in_progress = False
        self.active_hosts = []

    def ping_host(self, ip):
        """Ping a single host and return if it's online"""
        param = '-n' if platform.system().lower() == 'windows' else '-c'
        command = ['ping', param, '1', ip]
        return subprocess.call(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0

    def worker(self, work_queue, result_queue):
        """Worker thread to process IPs from queue"""
        while True:
            ip = work_queue.get()
            if ip is None:
                break
            if self.ping_host(ip):
                result_queue.put(ip)
            work_queue.task_done()

    def get_subnet_from_db(self):
        """Get configured subnet from database"""
        try:
            cursor = self.db.cursor()
            cursor.execute('SELECT value FROM settings WHERE key = "scan_subnet"')
            result = cursor.fetchone()
            return result[0] if result else '192.168.14.0/23'
        except Exception as e:
            current_app.logger.error(f"Error getting subnet: {e}")
            return '192.168.14.0/23'

    def save_results_to_db(self, active_ips):
        """Save scan results to database"""
        try:
            cursor = self.db.cursor()
            for ip in active_ips:
                try:
                    hostname = socket.gethostbyaddr(ip)[0]
                except:
                    hostname = "Unknown"

                cursor.execute('''
                    INSERT INTO devices (hostname, ip_address, last_seen)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE 
                        hostname = VALUES(hostname),
                        last_seen = VALUES(last_seen)
                ''', (hostname, ip, datetime.now()))
            
            self.db.commit()
        except Exception as e:
            current_app.logger.error(f"Error saving scan results: {e}")
            self.db.rollback()

    def start_scan(self):
        """Start network scan in background thread"""
        if self.scan_in_progress:
            return False

        self.scan_in_progress = True
        self.active_hosts = []
        
        thread = threading.Thread(target=self._run_scan)
        thread.daemon = True
        thread.start()
        return True

    def _run_scan(self, num_threads=10):
        """Run the actual network scan"""
        try:
            subnet = self.get_subnet_from_db()
            network = ipaddress.ip_network(subnet)
            
            work_queue = queue.Queue()
            result_queue = queue.Queue()
            
            # Start worker threads
            threads = []
            for _ in range(num_threads):
                t = threading.Thread(target=self.worker, args=(work_queue, result_queue))
                t.daemon = True
                t.start()
                threads.append(t)
            
            # Add IPs to work queue
            for ip in network.hosts():
                work_queue.put(str(ip))
                
            # Add thread termination signals
            for _ in range(num_threads):
                work_queue.put(None)
                
            # Wait for all threads to complete
            for t in threads:
                t.join()
                
            # Collect and save results
            active_ips = []
            while not result_queue.empty():
                active_ips.append(result_queue.get())
            
            self.active_hosts = sorted(active_ips, key=lambda ip: [int(i) for i in ip.split('.')])
            self.save_results_to_db(self.active_hosts)
            
        except Exception as e:
            current_app.logger.error(f"Error during network scan: {e}")
        finally:
            self.scan_in_progress = False

    def get_scan_status(self):
        """Return current scan status"""
        return {
            'in_progress': self.scan_in_progress,
            'devices_found': len(self.active_hosts)
        }
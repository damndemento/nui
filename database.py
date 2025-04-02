
import mysql.connector
import logging
import sys
from pathlib import Path

# Add parent directory to Python path to import db_config
sys.path.append(str(Path(__file__).parent.parent))
from db_config import DB_CONFIG

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_connection():
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        if connection.is_connected():
            db_info = connection.get_server_info()
            logger.info(f"Connected to MariaDB Server version {db_info}")
            cursor = connection.cursor()
            cursor.execute("select database();")
            db_name = cursor.fetchone()[0]
            logger.info(f"Connected to database: {db_name}")
            return connection
    except mysql.connector.Error as err:
        logger.error(f"Error: {err}")
        return None

def close_connection(connection):
    if connection is not None and connection.is_connected():
        connection.close()
        logger.info("Database connection closed.")

if __name__ == "__main__":
    conn = create_connection()


import schedule
import time
import subprocess
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)

def run_flight_check():
    """Run the flight checker script"""
    try:
        logging.info(f"Starting flight check at {datetime.now()}")
        result = subprocess.run(['python', 'flight_checker.py'], 
                              capture_output=True, text=True)
        
        if result.returncode == 0:
            logging.info("Flight check completed successfully")
        else:
            logging.error(f"Flight check failed: {result.stderr}")
    except Exception as e:
        logging.error(f"Error running flight check: {e}")

# Schedule daily at 9 AM
schedule.every().day.at("09:00").do(run_flight_check)

if __name__ == "__main__":
    logging.info("Scheduler started")
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute

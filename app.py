from flask import Flask, render_template, jsonify, request, redirect, url_for, flash
from database import FlightDatabase
from flight_checker import run_flight_check
import threading
import traceback
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'flight-tracker-secret-key-change-in-production'

db = FlightDatabase()

# Global search status
search_status = {
    'running': False,
    'last_run': None,
    'progress': 0,
    'current_route': '',
    'error': None
}

def run_search_background():
    """Run flight search in background thread"""
    global search_status
    try:
        print("🚀 Background flight search starting...")
        search_status['running'] = True
        search_status['error'] = None
        search_status['progress'] = 0
        search_status['current_route'] = 'Initializing...'
        
        # Run the flight check
        run_flight_check()
        
        search_status['last_run'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        search_status['progress'] = 100
        search_status['current_route'] = 'Completed!'
        print("✅ Background flight search completed!")
        
    except Exception as e:
        error_msg = str(e)
        search_status['error'] = error_msg
        print(f"❌ Background search error: {error_msg}")
        print(f"❌ Traceback: {traceback.format_exc()}")
    finally:
        search_status['running'] = False

@app.route('/')
def dashboard():
    """Main dashboard page"""
    try:
        latest_results = db.get_latest_results()
        job_runs = db.get_job_runs()
        
        return render_template('index.html', 
                             results=latest_results, 
                             job_runs=job_runs,
                             search_status=search_status)
    except Exception as e:
        print(f"❌ Dashboard error: {e}")
        return f"Dashboard Error: {e}", 500

@app.route('/trigger-search', methods=['POST'])
def trigger_search():
    """Trigger immediate flight search"""
    global search_status
    
    print("🔘 Search button clicked!")
    
    if search_status['running']:
        flash('⚠️ Search already in progress! Please wait...', 'warning')
        return redirect(url_for('dashboard'))
    
    try:
        # Start search in background thread
        search_thread = threading.Thread(target=run_search_background, daemon=True)
        search_thread.start()
        
        flash('🚀 Flight search started! Page will auto-refresh when complete.', 'info')
        return redirect(url_for('dashboard'))
        
    except Exception as e:
        error_msg = f"Failed to start search: {e}"
        print(f"❌ {error_msg}")
        flash(f'❌ Error starting search: {error_msg}', 'error')
        return redirect(url_for('dashboard'))

@app.route('/history')
def search_history():
    """Search history page"""
    try:
        all_runs = db.get_all_job_runs_with_details()
        search_dates = db.get_search_dates()
        stats = db.get_search_statistics()
        
        return render_template('history.html',
                             job_runs=all_runs,
                             search_dates=search_dates,
                             stats=stats,
                             search_status=search_status)
    except Exception as e:
        print(f"History page error: {e}")
        return f"Error loading history: {e}", 500

@app.route('/history/<search_date>')
def search_details(search_date):
    """Show details for a specific search date"""
    try:
        results = db.get_results_by_date(search_date)
        job_run = None
        
        # Get job run info for this date
        job_runs = db.get_job_runs()
        for run in job_runs:
            if run['run_date'] == search_date:
                job_run = run
                break
        
        return render_template('search_details.html',
                             results=results,
                             job_run=job_run,
                             search_date=search_date,
                             search_status=search_status)
    except Exception as e:
        print(f"Search details error: {e}")
        return f"Error loading search details: {e}", 500

# API Routes
@app.route('/api/search-status')
def api_search_status():
    """API endpoint for search status"""
    return jsonify(search_status)

@app.route('/api/results')
def api_results():
    """API endpoint for latest results"""
    return jsonify(db.get_latest_results())

@app.route('/api/history/<origin>/<destination>')
def api_history(origin, destination):
    """API endpoint for price history"""
    return jsonify(db.get_price_history(origin, destination))

@app.route('/api/job-runs')
def api_job_runs():
    """API endpoint for job run history"""
    return jsonify(db.get_job_runs())

if __name__ == '__main__':
    print("🌐 Starting Flight Price Tracker...")
    print("📍 Dashboard: http://localhost:5000")
    print("📊 History: http://localhost:5000/history")
    app.run(host='0.0.0.0', port=5000, debug=True)

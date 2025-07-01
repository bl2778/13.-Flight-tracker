import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Any, Optional

class FlightDatabase:
    def __init__(self, db_path: str = "flight_data.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize database tables"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS flight_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    price TEXT,
                    segments TEXT,
                    currency TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS job_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_date TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total_routes INTEGER,
                    successful_routes INTEGER,
                    min_price REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
    
    def save_flight_results(self, results: Dict[str, Dict[str, tuple]], 
                          currency: str, min_price: Optional[float] = None):
        """Save flight search results to database"""
        with sqlite3.connect(self.db_path) as conn:
            date_str = datetime.now().strftime('%Y-%m-%d')
            
            # Clear existing results for today
            conn.execute("DELETE FROM flight_results WHERE date = ?", (date_str,))
            
            # Save individual results
            for origin in results:
                for dest in results[origin]:
                    price, segments = results[origin][dest]
                    conn.execute("""
                        INSERT INTO flight_results 
                        (date, origin, destination, price, segments, currency)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (date_str, origin, dest, price, segments, currency))
            
            # Save job run summary
            total_routes = sum(len(dests) for dests in results.values())
            successful_routes = sum(
                1 for origin in results 
                for dest in results[origin] 
                if results[origin][dest][0] not in ["N/A", None]
            )
            
            conn.execute("""
                INSERT INTO job_runs 
                (run_date, status, total_routes, successful_routes, min_price)
                VALUES (?, ?, ?, ?, ?)
            """, (date_str, "completed", total_routes, successful_routes, min_price))
    
    def get_latest_results(self) -> List[Dict[str, Any]]:
        """Get latest flight results"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM flight_results 
                WHERE date = (SELECT MAX(date) FROM flight_results)
                ORDER BY origin, destination
            """)
            return [dict(row) for row in cursor.fetchall()]
    
    def get_price_history(self, origin: str, destination: str) -> List[Dict[str, Any]]:
        """Get price history for a specific route"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT date, price, currency FROM flight_results 
                WHERE origin = ? AND destination = ? 
                AND price != 'N/A'
                ORDER BY date DESC LIMIT 30
            """, (origin, destination))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_job_runs(self) -> List[Dict[str, Any]]:
        """Get job run history"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM job_runs 
                ORDER BY created_at DESC LIMIT 30
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_all_job_runs_with_details(self) -> List[Dict[str, Any]]:
        """Get all job runs with details"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT 
                    jr.*,
                    COUNT(fr.id) as total_flights_found,
                    COUNT(CASE WHEN fr.price != 'N/A' THEN 1 END) as successful_flights
                FROM job_runs jr
                LEFT JOIN flight_results fr ON jr.run_date = fr.date
                GROUP BY jr.id
                ORDER BY jr.created_at DESC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_results_by_date(self, search_date: str) -> List[Dict[str, Any]]:
        """Get all flight results for a specific date"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM flight_results 
                WHERE date = ?
                ORDER BY origin, destination
            """, (search_date,))
            return [dict(row) for row in cursor.fetchall()]

    def get_search_dates(self) -> List[str]:
        """Get all unique search dates"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT DISTINCT run_date 
                FROM job_runs 
                ORDER BY run_date DESC
            """)
            return [row[0] for row in cursor.fetchall()]

    def get_search_statistics(self) -> Dict[str, Any]:
        """Get overall search statistics"""
        with sqlite3.connect(self.db_path) as conn:
            # Total searches
            total_searches = conn.execute("SELECT COUNT(*) FROM job_runs").fetchone()[0]
            
            # Average success rate
            avg_success = conn.execute("""
                SELECT AVG(CAST(successful_routes AS FLOAT) / total_routes * 100) 
                FROM job_runs WHERE total_routes > 0
            """).fetchone()[0] or 0
            
            # Best price ever
            best_price = conn.execute("""
                SELECT MIN(min_price) FROM job_runs WHERE min_price IS NOT NULL
            """).fetchone()[0]
            
            # Total routes checked
            total_routes = conn.execute("""
                SELECT SUM(total_routes) FROM job_runs
            """).fetchone()[0] or 0
            
            return {
                'total_searches': total_searches,
                'avg_success_rate': round(avg_success, 1) if avg_success else 0,
                'best_price_ever': best_price,
                'total_routes_checked': total_routes
            }

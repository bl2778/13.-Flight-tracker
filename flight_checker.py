#!/usr/bin/env python3
"""
Automated flight-price checker + database storage.
Modified to use environment variables and save results to SQLite database.
WITH PROGRESS REPORTING
"""

# ─── Imports ────────────────────────────────────────────────────────────────
import os
import logging
import smtplib
import socket
import tempfile
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from typing import Optional, Dict, Tuple

from dotenv import load_dotenv
from amadeus import Client, ResponseError
from database import FlightDatabase
# ❌ REMOVED: from scheduler import run_flight_check

# ─── Config ────────────────────────────────────────────────────────────────
load_dotenv()

# Environment variables (secure)
AMADEUS_CLIENT_ID = os.getenv('AMADEUS_CLIENT_ID')
AMADEUS_CLIENT_SECRET = os.getenv('AMADEUS_CLIENT_SECRET')
SENDER_EMAIL = os.getenv('SENDER_EMAIL')
SENDER_EMAIL_PASSWORD = os.getenv('SENDER_EMAIL_PASSWORD')
RECIPIENT_EMAIL = os.getenv('RECIPIENT_EMAIL')
SEND_EMAIL = os.getenv('SEND_EMAIL', 'false').lower() == 'true'

# Flight search configuration
FLIGHT_CONFIG = {
    "origins": ["SHA", "NKG"],
    "destinations": ["DXB", "YVR"],  # Reduced for testing
    "trip_type": "W",
    "departure_date": "2025-10-01", 
    "return_date": "2025-10-06",
    "cabin_class": "B",
    "currency": "CNY",
    "adults": 1,
    "max_offers": 1,
    "non_stop": False,
}

CLASS_MAP = {
    "E": "ECONOMY",
    "W": "PREMIUM_ECONOMY", 
    "B": "BUSINESS", 
    "F": "FIRST",
}

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# ✅ FIXED: Windows-compatible logging (no emojis in log file)
LOG_FILE = os.path.join(tempfile.gettempdir(), "flight_checker.log")

# Create file handler without emojis for Windows compatibility
file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
file_handler.setFormatter(file_formatter)

# Create console handler (emojis OK in console)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
console_handler.setFormatter(console_formatter)

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    handlers=[file_handler, console_handler]
)

# Set network timeout
socket.setdefaulttimeout(30)

# ─── Progress Reporting Class ──────────────────────────────────────────────
class ProgressReporter:
    def __init__(self, total_routes: int):
        self.total_routes = total_routes
        self.current_route = 0
        self.successful_routes = 0
        self.failed_routes = 0
        self.start_time = datetime.now()

    def update(self, origin: str, destination: str, success: bool, price: Optional[str] = None):
        """Update progress and display status"""
        self.current_route += 1
        if success:
            self.successful_routes += 1
        else:
            self.failed_routes += 1
            
        # Calculate progress
        progress_pct = (self.current_route / self.total_routes) * 100
        elapsed_time = datetime.now() - self.start_time
        
        # ... rest of existing code ...
        
        # 🆕 UPDATE: Also update the global search_status for web interface
        try:
            # Import here to avoid circular imports
            import app
            app.search_status['progress'] = int(progress_pct)
            app.search_status['current_route'] = f"{origin} → {destination}"
        except ImportError:
            pass  # In case we're running standalone
        
        # Also log to file
        logging.info(f"Route {self.current_route}/{self.total_routes}: {origin}→{destination} - {status_log}")

    def update(self, origin: str, destination: str, success: bool, price: Optional[str] = None):
        """Update progress and display status"""
        self.current_route += 1
        if success:
            self.successful_routes += 1
        else:
            self.failed_routes += 1
            
        # Calculate progress
        progress_pct = (self.current_route / self.total_routes) * 100
        elapsed_time = datetime.now() - self.start_time
        
        # Estimate remaining time
        if self.current_route > 0:
            avg_time_per_route = elapsed_time.total_seconds() / self.current_route
            remaining_routes = self.total_routes - self.current_route
            eta_seconds = remaining_routes * avg_time_per_route
            eta = timedelta(seconds=int(eta_seconds))
        else:
            eta = timedelta(0)
        
        # Progress bar
        bar_length = 30
        filled_length = int(bar_length * self.current_route // self.total_routes)
        bar = '█' * filled_length + '░' * (bar_length - filled_length)
        
        # Status message (emojis for console display)
        status_display = "✅ SUCCESS" if success else "❌ FAILED"
        status_log = "SUCCESS" if success else "FAILED"  # ✅ No emojis for logging
        price_info = f" | Price: {price}" if price and price != "N/A" else ""
        
        print(f"\n{'='*80}")
        print(f"🛫 ROUTE {self.current_route:2d}/{self.total_routes}: {origin} → {destination}")
        print(f"📊 PROGRESS: [{bar}] {progress_pct:.1f}%")
        print(f"⏱️  STATUS: {status_display}{price_info}")
        print(f"📈 SUCCESS RATE: {self.successful_routes}/{self.current_route} ({self.successful_routes/self.current_route*100:.1f}%)")
        print(f"⏰ ELAPSED: {str(elapsed_time).split('.')[0]} | ETA: {str(eta).split('.')[0]}")
        print(f"{'='*80}")
        
        # ✅ FIXED: Log without emojis for Windows compatibility
        logging.info(f"Route {self.current_route}/{self.total_routes}: {origin}->{destination} - {status_log}")


# ─── Amadeus client ────────────────────────────────────────────────────────
amadeus_client: Optional[Client] = None

def initialize_amadeus_client() -> bool:
    """Initialize Amadeus API client without test call"""
    global amadeus_client
    
    if not (AMADEUS_CLIENT_ID and AMADEUS_CLIENT_SECRET):
        print("❌ Amadeus credentials missing")
        return False
        
    try:
        amadeus_client = Client(
            client_id=AMADEUS_CLIENT_ID,
            client_secret=AMADEUS_CLIENT_SECRET,
        )
        print("✅ Amadeus client created (skipping test call)")
        return True
        
    except Exception as exc:
        print(f"❌ Amadeus error: {exc}")
        return False

# ─── Flight-search helper ──────────────────────────────────────────────────
def get_flight_offer_details(
    origin_code: str,
    destination_code: str,
    departure_date: str,
    return_date: Optional[str],
    travel_class: str,
    adults: int,
    currency_code: str,
    max_offers: int,
    non_stop: bool,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Fetch flight offers from Amadeus API with comprehensive error handling.
    """
    if amadeus_client is None:
        logging.error("Amadeus client not ready.")
        return None, None

    params = {
        "originLocationCode": origin_code,
        "destinationLocationCode": destination_code,
        "departureDate": departure_date,
        "returnDate": return_date,
        "adults": adults,
        "travelClass": travel_class,
        "nonStop": str(non_stop).lower(),
        "currencyCode": currency_code,
        "max": max_offers,
    }
    params = {k: v for k, v in params.items() if v is not None}

    try:
        print(f"🔍 Searching {origin_code} → {destination_code}... ", end="", flush=True)
        
        response = amadeus_client.shopping.flight_offers_search.get(**params)

        if not response.data:
            print("❌ No offers found")
            logging.info("No offers for %s -> %s", origin_code, destination_code)
            return None, None

        offer = response.data[0]
        price = offer["price"]["grandTotal"]
        segs = [
            " / ".join(f"{s['carrierCode']}{s['number']}"
                      for s in it["segments"])
            for it in offer["itineraries"]
        ]
        print(f"✅ Found: {currency_code} {price}")
        return price, " <-> ".join(segs)

    except socket.timeout:
        print("⏰ TIMEOUT")
        logging.error("Timeout connecting to Amadeus API for %s -> %s", 
                     origin_code, destination_code)
        return None, None
    except socket.error as err:
        print(f"🌐 NETWORK ERROR: {err}")
        logging.error("Network error for %s -> %s: %s", 
                     origin_code, destination_code, err)
        return None, None
    except ResponseError as err:
        status = getattr(err.response, "status_code", "???")
        print(f"🚫 API ERROR [{status}]")
        logging.error("Amadeus API error %s -> %s [%s]: %s",
                      origin_code, destination_code, status, str(err))
        return None, None
    except Exception as exc:
        print(f"💥 UNEXPECTED ERROR: {exc}")
        logging.error("Unexpected error for %s -> %s: %s",
                      origin_code, destination_code, exc)
        return None, None

# ─── HTML & PDF helpers ────────────────────────────────────────────────────
def build_html_table(origins, destinations, results, currency):
    """Return a prettified HTML table + lowest price value."""
    # Find the numeric minimum to highlight it later
    min_price_val = None
    for o in origins:
        for d in destinations:
            price_str = results[o][d][0]
            if price_str and price_str != "N/A":
                try:
                    val = float(str(price_str).replace(currency, '').replace(',', '').strip())
                    if min_price_val is None or val < min_price_val:
                        min_price_val = val
                except (ValueError, AttributeError):
                    continue

    # Table header
    html = [
        '<table style="border-collapse:collapse;width:100%;font-family:Arial,Helvetica,sans-serif;">',
        '<tr>',
        '<th style="background:#004472;color:#fff;border:1px solid #ddd;padding:8px;">Destination</th>'
    ]
    for o in origins:
        html.append(f'<th style="background:#004472;color:#fff;border:1px solid #ddd;padding:8px;">{o}</th>')
    html.append('</tr>')

    # Rows
    for idx, dest in enumerate(destinations):
        bg = '#f7f7f7' if idx % 2 else '#ffffff'
        html.append(f'<tr style="background:{bg};">')
        html.append(f'<td style="border:1px solid #ddd;padding:8px;">{dest}</td>')
        for o in origins:
            price, segs = results[o][dest]
            # Highlight best fare
            if price and price != "N/A":
                try:
                    price_val = float(str(price).replace(currency, '').replace(',', '').strip())
                    if min_price_val and price_val == min_price_val:
                        price_html = f'<span style="color:#2e8b57;font-weight:bold;">{price}</span>'
                    else:
                        price_html = str(price)
                except (ValueError, AttributeError):
                    price_html = str(price)
            else:
                price_html = "N/A"
            
            cell = (f'{price_html}<br>'
                    f'<span style="font-size:12px;color:#555;">{segs}</span>')
            html.append(f'<td style="border:1px solid #ddd;padding:8px;text-align:center;">{cell}</td>')
        html.append('</tr>')
    html.append('</table>')
    return '\n'.join(html), min_price_val

def html_to_pdf(html: str, pdf_path: str) -> bool:
    """Convert HTML to PDF using xhtml2pdf; return True on success or False if unavailable."""
    try:
        from xhtml2pdf import pisa
    except ImportError:
        logging.warning("xhtml2pdf not installed – PDF attachment skipped.")
        return False
    try:
        with open(pdf_path, "w+b") as f:
            pisa_status = pisa.CreatePDF(html, dest=f, encoding='utf-8')
        return not pisa_status.err
    except Exception as exc:
        logging.error("PDF generation failed: %s", exc)
        return False

# ─── E-mail helper ────────────────────────────────────────────────────────
def send_email(subject: str, html_body: str, pdf_path: Optional[str] = None) -> None:
    """Send email with optional PDF attachment."""
    if not SEND_EMAIL:
        print("📧 Email sending disabled via SEND_EMAIL environment variable.")
        logging.info("Email sending disabled via SEND_EMAIL environment variable.")
        return
        
    if not all([RECIPIENT_EMAIL, SENDER_EMAIL, SENDER_EMAIL_PASSWORD]):
        print("❌ E-mail credentials incomplete – message not sent.")
        logging.error("E-mail credentials incomplete – message not sent.")
        return

    print("📧 Preparing email...")
    print(f"   From: {SENDER_EMAIL}")
    print(f"   To: {RECIPIENT_EMAIL}")
    print(f"   Server: {SMTP_SERVER}:{SMTP_PORT}")
    
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECIPIENT_EMAIL

    # Plain (fallback) and HTML parts
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText("Your e-mail client does not support HTML.", "plain"))
    alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt)

    # Optional PDF attachment
    if pdf_path and os.path.exists(pdf_path):
        with open(pdf_path, "rb") as f:
            attach = MIMEApplication(f.read(), _subtype="pdf")
        attach.add_header("Content-Disposition",
                          "attachment", filename=os.path.basename(pdf_path))
        msg.attach(attach)
        print("📎 PDF attachment added")

    try:
        print("📤 Connecting to Gmail SMTP...")
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
            print("🔐 Starting TLS...")
            server.starttls()
            print("🔑 Logging in...")
            server.login(SENDER_EMAIL, SENDER_EMAIL_PASSWORD)
            print("📬 Sending message...")
            server.send_message(msg)
        print(f"✅ E-mail sent successfully to {RECIPIENT_EMAIL}")
        logging.info("E-mail sent to %s", RECIPIENT_EMAIL)
    except smtplib.SMTPAuthenticationError as exc:
        print(f"❌ Gmail authentication failed: {exc}")
        print("💡 Check if you're using an App Password, not your regular password")
        logging.error("Gmail authentication failed: %s", exc)
    except (OSError, smtplib.SMTPException) as exc:
        print(f"❌ E-mail connection failed: {exc}")
        print("💡 This might be due to firewall/network restrictions")
        logging.error("E-mail failed: %s", exc)


# ─── Main workflow ────────────────────────────────────────────────────────
def run_flight_check():
    """Main flight checking workflow with database storage."""
    print("\n" + "="*80)
    print("🛫 FLIGHT PRICE CHECKER STARTING")
    print("="*80)
    
    start_time = datetime.now()
    logging.info("─── Flight-check script starting ───")

    # Initialize database
    print("🗄️  Initializing database...")
    db = FlightDatabase()
    print("✅ Database ready!")

    if not initialize_amadeus_client():
        error_msg = "Could not authenticate with the Amadeus API."
        logging.error(error_msg)
        if SEND_EMAIL:
            send_email("Flight Checker ❌  Amadeus init failed",
                       f"<p>{error_msg}</p>")
        return

    origins = FLIGHT_CONFIG["origins"]
    destinations = FLIGHT_CONFIG["destinations"]
    dep_date = FLIGHT_CONFIG["departure_date"]
    ret_date = FLIGHT_CONFIG["return_date"] if FLIGHT_CONFIG["trip_type"] == "W" else None
    travel_class = CLASS_MAP.get(FLIGHT_CONFIG["cabin_class"], "ECONOMY")
    currency = FLIGHT_CONFIG["currency"]
    adults = FLIGHT_CONFIG["adults"]
    max_offers = FLIGHT_CONFIG["max_offers"]
    non_stop = FLIGHT_CONFIG["non_stop"]

    total_routes = len(origins) * len(destinations)
    print(f"\n📋 FLIGHT SEARCH CONFIGURATION:")
    print(f"   Origins: {', '.join(origins)} ({len(origins)} airports)")
    print(f"   Destinations: {', '.join(destinations)} ({len(destinations)} airports)")
    print(f"   Total Routes: {total_routes}")
    print(f"   Departure: {dep_date} | Return: {ret_date}")
    print(f"   Class: {travel_class} | Currency: {currency}")
    print(f"   Estimated Time: ~{total_routes * 2} seconds")
    
    # Initialize progress reporter
    progress = ProgressReporter(total_routes)
    
    results: Dict[str, Dict[str, Tuple[str, str]]] = {}
    logging.info("Querying %d routes", total_routes)

    for o in origins:
        results[o] = {}
        for d in destinations:
            if o == d:
                results[o][d] = ("N/A", "Same origin & destination")
                progress.update(o, d, False, "N/A")
                continue
                
            # Add small delay between API calls to be respectful
            time.sleep(1)
            
            price, segs = get_flight_offer_details(
                o, d, dep_date, ret_date,
                travel_class, adults, currency, max_offers, non_stop,
            )
            
            success = price is not None
            results[o][d] = (price if price else "N/A",
                             segs if segs else "Not found")
            progress.update(o, d, success, price)

    # ─── Final Summary ───
    total_time = datetime.now() - start_time
    print(f"\n" + "="*80)
    print("🎉 FLIGHT SEARCH COMPLETED!")
    print(f"⏱️  Total Time: {str(total_time).split('.')[0]}")
    print(f"📊 Success Rate: {progress.successful_routes}/{total_routes} ({progress.successful_routes/total_routes*100:.1f}%)")
    print("="*80)

    # ─── Save to database ───
    print("💾 Saving results to database...")
    table_html, best_price = build_html_table(origins, destinations, results, currency)
    db.save_flight_results(results, currency, best_price)
    print(f"✅ Results saved! Best price found: {currency} {best_price}")
    logging.info("Results saved to database. Best price: %s", best_price)

    # ─── Optional email sending ───
    if SEND_EMAIL:
        print("\n📧 Preparing email report...")
        summary_block = (
            f'<p style="font-size:16px;">📉 <strong>Lowest fare found:</strong> '
            f'<span style="color:#2e8b57;font-size:18px;">{currency} {best_price:,.0f}</span></p>'
            if best_price is not None else
            '<p>No numeric fares were returned.</p>'
        )
        generated_on = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        html_body = f"""
        <html>
          <body style="font-family:Arial,Helvetica,sans-serif;">
            <h2 style="color:#004472;">Flight Price Report</h2>
            <p><strong>Search completed:</strong> {generated_on}</p>
            <p><strong>Success rate:</strong> {progress.successful_routes}/{total_routes} routes</p>
            {summary_block}
            {table_html}
            <p style="font-size:12px;color:#777;">Generated on {generated_on}</p>
          </body>
        </html>
        """

        # Optional PDF
        pdf_path = os.path.join(tempfile.gettempdir(), "flight_report.pdf")
        pdf_ok = html_to_pdf(html_body, pdf_path)
        if not pdf_ok:
            pdf_path = None

        # Send email
        subject = f"Daily Flight Price Report – {datetime.now():%Y-%m-%d}"
        send_email(subject, html_body, pdf_path)

    print(f"\n🎯 SCRIPT COMPLETED SUCCESSFULLY!")
    print(f"📝 Log file: {LOG_FILE}")
    logging.info("─── Flight-check script finished ───")

# ✅ FIXED: Proper main execution
if __name__ == "__main__":
    run_flight_check()

from flask import Flask, request, jsonify, send_from_directory
import sqlite3
import logging
from openai import OpenAI
import os
import re
from werkzeug.utils import secure_filename
from functools import lru_cache
from dotenv import load_dotenv
from Levenshtein import distance as levenshtein_distance
import pytesseract  # For OCR
from PyPDF2 import PdfReader  # For PDF text extraction
import math
from datetime import datetime
import shutil

# Initialize Flask app
app = Flask(__name__)
load_dotenv()

# Configurations
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB file limit
app.config['DATABASE'] = 'copbot.db'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Database setup
def get_db_connection():
    conn = sqlite3.connect(app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    return conn

# Initialize database tables
def init_db():
    with get_db_connection() as conn:
        # Create new tables with enhanced schema
        conn.execute('''
            CREATE TABLE IF NOT EXISTS laws (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                reference TEXT,
                last_updated DATE
            )
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS emergency_contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_name TEXT NOT NULL,
                contact_number TEXT NOT NULL,
                alternate_number TEXT,
                jurisdiction TEXT,
                available_hours TEXT DEFAULT '24/7',
                description TEXT
            )
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS fir_procedures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                method TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                steps TEXT NOT NULL,
                required_documents TEXT,
                url TEXT,
                notes TEXT
            )
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS police_stations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                district TEXT NOT NULL,
                station_name TEXT NOT NULL,
                address TEXT NOT NULL,
                phone TEXT,
                email TEXT,
                jurisdiction TEXT,
                latitude REAL,
                longitude REAL
            )
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS uploads (
                id INTEGER PRIMARY KEY,
                filename TEXT,
                user_ip TEXT,
                upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Insert comprehensive data
        insert_initial_data(conn)
        conn.commit()

def insert_initial_data(conn):
    # Check if tables are empty before inserting
    if not conn.execute('SELECT 1 FROM laws LIMIT 1').fetchone():
        conn.executemany(
            "INSERT INTO laws (category, title, description, reference, last_updated) VALUES (?, ?, ?, ?, ?)",
            [
                ('Public Safety', 'Tamil Nadu Prohibition Act, 1937', 
                 'Regulates the manufacture, possession, and consumption of alcohol in the state', 
                 'Act No. 10 of 1937', '2023-01-01'),
                ('Traffic', 'Tamil Nadu Motor Vehicles Rules', 
                 'Rules governing vehicle registration, licensing, and traffic regulations', 
                 'G.O. Ms. No. 123, Transport Dept', '2022-06-15'),
                ('Women Safety', 'Tamil Nadu Prohibition of Harassment of Woman Act, 1998', 
                 'Provides protection against sexual harassment of women', 
                 'Act No. 56 of 1998', '2021-12-01'),
                ('Cyber Crime', 'Tamil Nadu Cyber Crime Regulations', 
                 'Procedures for reporting and investigating cyber crimes in the state', 
                 'G.O. Ms. No. 345, Home Dept', '2023-03-10'),
                ('Property', 'Tamil Nadu Land Reforms Act', 
                 'Regulates land ownership and tenancy in the state', 
                 'Act No. 58 of 1961', '2020-11-20')
            ]
        )
    
    if not conn.execute('SELECT 1 FROM emergency_contacts LIMIT 1').fetchone():
        conn.executemany(
            "INSERT INTO emergency_contacts (service_name, contact_number, description) VALUES (?, ?, ?)",
            [
                ('Police Emergency', '100', 'General police emergency number'),
                ('Women Helpline', '1091', '24/7 helpline for women in distress'),
                ('Child Helpline', '1098', 'Child protection and emergency services'),
                ('Fire & Rescue', '101', 'Fire department emergency number'),
                ('Ambulance', '108', 'Emergency medical services'),
                ('Crime Stopper', '1090', 'Anonymous crime reporting'),
                ('Traffic Police', '103', 'Traffic-related emergencies'),
                ('Anti Corruption', '1064', 'Corruption complaints'),
                ('Disaster Management', '1070', 'Natural disaster response'),
                ('Railway Police', '1512', 'Railway-related emergencies'),
                ('Highway Patrol', '9842299888', 'Highway emergency assistance'),
                ('Cyber Crime', '1930', 'Cyber crime complaints'),
                ('Senior Citizen Helpline', '1253', 'Elderly assistance'),
                ('Coastal Security', '1093', 'Maritime security emergencies'),
                ('Drug Abuse', '14446', 'Narcotics control and rehabilitation'),
                ('Mental Health', '104', 'Mental health crisis support'),
                ('Poison Control', '18004250169', 'Poison information center'),
                ('Tourist Police', '1363', 'Assistance for tourists'),
                ('HIV/AIDS Helpline', '1097', 'HIV/AIDS support services'),
                ('Electricity Emergency', '1912', 'Power outage and electrical emergencies'),
                ('Gas Leak Emergency', '1906', 'LPG gas leak emergencies')
            ]
        )
    
    if not conn.execute('SELECT 1 FROM fir_procedures LIMIT 1').fetchone():
        conn.executemany(
            "INSERT INTO fir_procedures (method, title, description, steps, url) VALUES (?, ?, ?, ?, ?)",
            [
                ('online', 'Online FIR Filing', 'File an FIR through the Tamil Nadu Police Citizen Portal',
                 '1. Visit eservices.tnpolice.gov.in\n2. Locate "Register Online Complaint"\n3. Fill the form\n4. Submit',
                 'https://eservices.tnpolice.gov.in'),
                ('offline', 'In-Person FIR Filing', 'File an FIR at your local police station',
                 '1. Visit nearest police station\n2. Provide incident details\n3. Verify FIR before signing',
                 None)
            ]
        )
    
    if not conn.execute('SELECT 1 FROM police_stations LIMIT 1').fetchone():
        conn.executemany(
            "INSERT INTO police_stations (district, station_name, address, phone, latitude, longitude) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ('Chennai', 'T. Nagar Police Station', 'Parthasarathy Koil St, T. Nagar', '044-24342522', 13.0344, 80.2206),
                ('Chennai', 'Anna Nagar Police Station', 'H Block, 2nd Ave, Anna Nagar', '044-26214455', 13.0860, 80.2100),
                ('Chennai', 'Adyar Police Station', '1st Main Road, Adyar', '044-24410999', 13.0067, 80.2566),
                ('Coimbatore', 'Peelamedu Police Station', 'Avanish Nagar, Peelamedu', '0422-2571111', 11.0168, 76.9558),
                ('Madurai', 'Tallakulam Police Station', 'West Marret St, Tallakulam', '0452-2533333', 9.9252, 78.1198)
            ]
        )

init_db()

# Helper functions
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in {'pdf', 'png', 'jpg', 'jpeg'}

def get_closest_match(user_input):
    with get_db_connection() as conn:
        cursor = conn.execute("SELECT keyword FROM responses")
        keywords = [row['keyword'] for row in cursor.fetchall()]
    
    closest = min(keywords, key=lambda x: levenshtein_distance(user_input.lower(), x.lower()))
    if levenshtein_distance(user_input.lower(), closest.lower()) <= len(user_input) * 0.3:
        return closest
    return None

def extract_text_from_file(filepath):
    try:
        if filepath.endswith('.pdf'):
            with open(filepath, 'rb') as f:
                reader = PdfReader(f)
                text = "\n".join([page.extract_text() for page in reader.pages])
        else:
            text = pytesseract.image_to_string(filepath)
        return text
    except Exception as e:
        logger.error(f"OCR Error: {str(e)}")
        return None

def haversine_distance(lat1, lon1, lat2, lon2):
    # Calculate distance between two coordinates in kilometers
    R = 6371  # Earth radius in km
    dLat = math.radians(lat2 - lat1)
    dLon = math.radians(lon2 - lon1)
    a = (math.sin(dLat/2) * math.sin(dLat/2) + \
        math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * \
        math.sin(dLon/2) * math.sin(dLon/2))
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

# AI Functions
@lru_cache(maxsize=100)
def get_gpt_response(prompt, context=""):
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant for Tamil Nadu Police. Provide concise answers."},
                {"role": "user", "content": context + prompt}
            ],
            temperature=0.5
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"GPT Error: {str(e)}")
        return None

def enhance_with_ai(db_response, user_input):
    if not db_response:
        ai_suggestions = get_gpt_response(
            "Generate 3 police-related follow-up questions about: " + user_input,
            "Provide only a numbered list without commentary"
        )
        return f"I couldn't find information about that.<br><br><b>You might ask:</b><br>{ai_suggestions}" if ai_suggestions else "Please contact your local police station."
    return db_response

# Routes
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

@app.route('/uploads/<filename>')
def serve_upload(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Empty filename'}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Extract text from file
        extracted_text = extract_text_from_file(filepath)
        text_preview = extracted_text[:200] + "..." if extracted_text else "No text extracted"
        
        # Store in database
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO uploads (filename, user_ip) VALUES (?, ?)",
                (filename, request.remote_addr)
            )
            conn.commit()
        
        return jsonify({
            'message': 'File uploaded successfully',
            'filename': filename,
            'text_preview': text_preview,
            'url': f'/uploads/{filename}'
        })
    
    return jsonify({'error': 'Invalid file type'}), 400

@app.route('/nearest-station', methods=['POST'])
def nearest_station():
    try:
        user_lat = request.json.get('lat')
        user_lng = request.json.get('lng')
        
        if not user_lat or not user_lng:
            return jsonify({'error': 'Location data missing'}), 400
        
        with get_db_connection() as conn:
            stations = conn.execute(
                "SELECT station_name, address, phone, latitude, longitude FROM police_stations"
            ).fetchall()
        
        if not stations:
            return jsonify({'error': 'No police stations found in database'}), 404
        
        # Find nearest station
        nearest = None
        min_distance = float('inf')
        
        for station in stations:
            distance = haversine_distance(
                user_lat, user_lng,
                station['latitude'], station['longitude']
            )
            
            if distance < min_distance:
                min_distance = distance
                nearest = station
        
        if not nearest:
            return jsonify({'error': 'Could not calculate nearest station'}), 500
        
        return jsonify({
            'station': f"{nearest['station_name']} ({nearest['address']})",
            'distance': f"{min_distance:.1f} km",
            'phone': nearest['phone'],
            'map_url': f"https://www.google.com/maps/dir/?api=1&destination={nearest['latitude']},{nearest['longitude']}"
        })
        
    except Exception as e:
        logger.error(f"Nearest station error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/laws', methods=['GET'])
def get_laws():
    category = request.args.get('category', '')
    query = request.args.get('query', '')
    
    with get_db_connection() as conn:
        if category:
            laws = conn.execute(
                "SELECT * FROM laws WHERE category LIKE ?", 
                (f'%{category}%',)
            ).fetchall()
        elif query:
            laws = conn.execute(
                "SELECT * FROM laws WHERE title LIKE ? OR description LIKE ?", 
                (f'%{query}%', f'%{query}%')
            ).fetchall()
        else:
            laws = conn.execute("SELECT * FROM laws").fetchall()
    
    return jsonify([dict(law) for law in laws])

@app.route('/api/fir-procedures', methods=['GET'])
def get_fir_procedures():
    method = request.args.get('method', '')
    
    with get_db_connection() as conn:
        if method:
            procedures = conn.execute(
                "SELECT * FROM fir_procedures WHERE method = ?", 
                (method,)
            ).fetchall()
        else:
            procedures = conn.execute("SELECT * FROM fir_procedures").fetchall()
    
    return jsonify([dict(proc) for proc in procedures])

@app.route('/api/emergency-contacts', methods=['GET'])
def get_emergency_contacts():
    service = request.args.get('service', '')
    
    with get_db_connection() as conn:
        if service:
            contacts = conn.execute(
                "SELECT * FROM emergency_contacts WHERE service_name LIKE ?", 
                (f'%{service}%',)
            ).fetchall()
        else:
            contacts = conn.execute("SELECT * FROM emergency_contacts").fetchall()
    
    return jsonify([dict(contact) for contact in contacts])

@app.route('/chat', methods=['POST'])
def chat():
    user_input = request.json.get('query', '').strip().lower()
    
    if not user_input:
        return jsonify({'response': 'Please enter a valid query.', 'type': 'text'})
    
    # Check for emergency keywords - expanded list
    emergency_keywords = ['emergency', 'help', 'danger', 'accident', 'crime', 'police', 'ambulance', 
                         'fire', 'rescue', 'murder', 'attack', 'violence', 'threat', 'harassment']
    
    if any(keyword in user_input for keyword in emergency_keywords):
        with get_db_connection() as conn:
            contacts = conn.execute(
                "SELECT service_name, contact_number, description FROM emergency_contacts "
                "ORDER BY CASE WHEN service_name LIKE '%Police%' THEN 1 "
                "WHEN service_name LIKE '%Ambulance%' THEN 2 "
                "WHEN service_name LIKE '%Women%' THEN 3 "
                "ELSE 4 END"
            ).fetchall()
        
        # Format contacts with HTML
        contacts_html = []
        for contact in contacts:
            contacts_html.append(
                f"<div class='emergency-contact'>"
                f"<div><b>{contact['service_name']}</b>: {contact['contact_number']}<br>"
                f"<small>{contact['description']}</small></div>"
                f"<a href='tel:{contact['contact_number']}' class='call-btn'>"
                f"<i class='fas fa-phone'></i> Call</a>"
                f"</div>"
            )
        
        response = "<b>🚨 Emergency Contacts:</b><br><br>" + "<br>".join(contacts_html)
        return jsonify({
            'response': response,
            'type': 'emergency_contacts'
        })
    
    # Check for law-related queries - improved matching
    law_keywords = ['law', 'act', 'regulation', 'rule', 'legal', 'offense', 'penalty', 
                   'prohibition', 'rights', 'duty', 'violation']
    
    if any(keyword in user_input for keyword in law_keywords):
        with get_db_connection() as conn:
            # Search in both title and description
            laws = conn.execute(
                "SELECT title, description FROM laws WHERE "
                "title LIKE ? OR description LIKE ? OR category LIKE ?",
                (f'%{user_input}%', f'%{user_input}%', f'%{user_input}%')
            ).fetchall()
        
        if laws:
            laws_html = []
            for law in laws:
                laws_html.append(
                    f"<div class='law-item'>"
                    f"<h4>{law['title']}</h4>"
                    f"<p>{law['description']}</p>"
                    f"</div>"
                )
            
            response = "<b>⚖️ Relevant Laws:</b><br><br>" + "<br><br>".join(laws_html)
            return jsonify({
                'response': response,
                'type': 'laws_info'
            })
    
    # Check for FIR-related queries
    fir_keywords = ['fir', 'file complaint', 'first information report', 'police complaint',
                   'register case', 'file case', 'complaint process']
    
    if any(keyword in user_input for keyword in fir_keywords):
        with get_db_connection() as conn:
            procedures = conn.execute(
                "SELECT method, title, steps, url FROM fir_procedures ORDER BY method DESC"
            ).fetchall()
        
        procedures_html = []
        for proc in procedures:
            steps = proc['steps'].replace('\n', '<br>')
            link = f"<a href='{proc['url']}' target='_blank'>Visit Portal</a>" if proc['url'] else ""
            procedures_html.append(
                f"<div class='fir-method'>"
                f"<h4>{proc['title']} ({proc['method']})</h4>"
                f"<p>{steps}</p>"
                f"{link}"
                f"</div>"
            )
        
        response = "<b>📝 FIR Filing Procedures:</b><br><br>" + "<br><br>".join(procedures_html)
        return jsonify({
            'response': response,
            'type': 'fir_info'
        })
    
    # Fallback to AI if no database matches
    ai_response = get_gpt_response(
        f"User asked about Tamil Nadu police services: {user_input}. "
        "Provide a concise answer with relevant contacts if needed. "
        "If asking about laws or procedures, mention they can ask specifically "
        "about 'emergency contacts', 'FIR process', or 'Tamil Nadu laws'."
    )
    
    return jsonify({
        'response': ai_response or "Please contact your local police station for more information.",
        'type': 'text'
    })

@app.route('/admin/backup', methods=['GET'])
def backup_db():
    if not os.path.exists(app.config['DATABASE']):
        return "Database not found", 404
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"backups/copbot_backup_{timestamp}.db"
    
    os.makedirs('backups', exist_ok=True)
    shutil.copy2(app.config['DATABASE'], backup_path)
    
    return jsonify({
        'status': 'success',
        'backup_path': backup_path
    })

if __name__ == '__main__':
    app.run(debug=True)
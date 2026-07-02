import os
import random
import hashlib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import psycopg2
import psycopg2.extras
import razorpay

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "super_secret_evidence_key_123!")

# Razorpay configuration (prefer environment variables)
# Set `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` in the environment for production/live keys.
RAZORPAY_KEY_ID = os.environ.get('RAZORPAY_KEY_ID', 'rzp_test_SSbOdDCw5ffIUk')
RAZORPAY_KEY_SECRET = os.environ.get('RAZORPAY_KEY_SECRET', 'l3GCUC0BDSHgU91Jg8tgY7Hz')

# Initialize Razorpay client safely and log initialization errors
razorpay_client = None
try:
    if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
        raise ValueError('Razorpay key id or secret not provided')
    razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
except Exception as e:
    print(f"Razorpay client initialization error: {e}")
    razorpay_client = None

# SMTP configuration for OTP emails
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_EMAIL = "evidencem2008@gmail.com"
SMTP_APP_PASSWORD = "upurmohkxhlescmh"

# Database configuration (Defaults for local testing)
DB_HOST = "localhost"
DB_NAME = "evidence_db"
DB_USER = "postgres"
DB_PASS = "123456789"

def get_db_connection():
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS
        )
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        return None

def hash_password(password):
    """Hash password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

def generate_otp():
    """Generate a 6-digit OTP"""
    return str(random.randint(100000, 999999))

def send_otp_email(recipient_email, otp_code, user_name):
    """Send OTP code to the user's email via Gmail SMTP"""
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_EMAIL
        msg['To'] = recipient_email
        msg['Subject'] = 'EPS Login - Your OTP Code'

        body = f"""Dear {user_name},

Your One-Time Password (OTP) for login is:

    {otp_code}

This OTP is valid for a single use. Do not share it with anyone.This code is valid for only 5 minutes.

Regards,
Evidence Management System"""
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_APP_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Error sending OTP email: {e}")
        return False

app.jinja_env.globals.update(hash_password=hash_password)

@app.route('/')
def landing():
    """Landing and login panel"""
    if 'user_id' in session:
        if session.get('role') == 'admin':
            return redirect(url_for('admin_dashboard'))
        elif session.get('role') == 'officer':
            return redirect(url_for('officer_dashboard'))
        elif session.get('role') == 'supervisor':
            return redirect(url_for('supervisor_dashboard'))
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        password = request.form.get('password')
        role = request.form.get('role')

        if not user_id or not password or not role:
            flash("Please provide all fields.", "danger")
            return redirect(url_for('landing'))

        hashed_password = hash_password(password)
        conn = get_db_connection()
        
        if not conn:
            flash("Database connection error.", "danger")
            return redirect(url_for('landing'))

        try:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                # Step 1: Check if user exists with correct credentials (ignore is_active)
                cur.execute(
                    "SELECT * FROM users WHERE user_id = %s AND role = %s",
                    (user_id, role)
                )
                user = cur.fetchone()

                if user and user['password_hash'] == hashed_password:
                    # Step 2: Check if account is active
                    if not user['is_active']:
                        flash("Your account has been deactivated. Please contact the administrator.", "danger")
                    else:
                        # Admin logs in directly (no OTP)
                        if role == 'admin':
                            session['user_id'] = user['user_id']
                            session['role'] = user['role']
                            session['name'] = user['name']
                            flash("Login successful.", "success")
                            return redirect(url_for('admin_dashboard'))

                        # Officer/Supervisor: require OTP verification
                        user_email = user.get('email')
                        if not user_email:
                            flash("No email on file. Contact admin to add your email for OTP verification.", "danger")
                            return redirect(url_for('landing'))

                        otp_code = generate_otp()
                        # Store pending login info in session
                        session['otp_pending'] = True
                        session['otp_code'] = otp_code
                        session['otp_user_id'] = user['user_id']
                        session['otp_role'] = user['role']
                        session['otp_name'] = user['name']
                        session['otp_email'] = user_email

                        if send_otp_email(user_email, otp_code, user['name']):
                            flash("OTP has been sent to your registered email.", "info")
                        else:
                            flash("Failed to send OTP. Please try again.", "danger")
                            session.pop('otp_pending', None)
                            return redirect(url_for('landing'))

                        return redirect(url_for('verify_otp'))
                else:
                    flash("Invalid User ID, password, or role.", "danger")
        except Exception as e:
            print(f"Login error: {e}")
            flash("An error occurred during login.", "danger")
        finally:
            conn.close()

    return redirect(url_for('landing'))

@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('landing'))

@app.route('/verify_otp', methods=['GET', 'POST'])
def verify_otp():
    # Only allow access if OTP is pending
    if not session.get('otp_pending'):
        flash("Please login first.", "warning")
        return redirect(url_for('landing'))

    if request.method == 'POST':
        entered_otp = request.form.get('otp', '').strip()
        stored_otp = session.get('otp_code')

        if entered_otp == stored_otp:
            # OTP matched — complete login
            session['user_id'] = session.pop('otp_user_id')
            session['role'] = session.pop('otp_role')
            session['name'] = session.pop('otp_name')
            session.pop('otp_code', None)
            session.pop('otp_pending', None)
            session.pop('otp_email', None)
            flash("Login successful.", "success")

            if session['role'] == 'officer':
                return redirect(url_for('officer_dashboard'))
            elif session['role'] == 'supervisor':
                return redirect(url_for('supervisor_dashboard'))
        else:
            flash("Invalid OTP. Please try again.", "danger")

    # Mask email for display (e.g. m***l@gmail.com)
    email = session.get('otp_email', '')
    if email and '@' in email:
        local, domain = email.split('@', 1)
        if len(local) > 2:
            masked_email = local[0] + '***' + local[-1] + '@' + domain
        else:
            masked_email = local[0] + '***@' + domain
    else:
        masked_email = '***'

    return render_template('verify_otp.html', masked_email=masked_email)

@app.route('/resend_otp', methods=['POST'])
def resend_otp():
    if not session.get('otp_pending'):
        flash("Please login first.", "warning")
        return redirect(url_for('landing'))

    otp_code = generate_otp()
    session['otp_code'] = otp_code

    email = session.get('otp_email')
    name = session.get('otp_name', 'User')

    if send_otp_email(email, otp_code, name):
        flash("A new OTP has been sent to your email.", "info")
    else:
        flash("Failed to resend OTP. Please try again.", "danger")

    return redirect(url_for('verify_otp'))


# ==========================================
# ADMIN PANEL
# ==========================================

@app.route('/admin')
@app.route('/admin/dashboard', methods=['GET', 'POST'])
def admin_dashboard():
    if session.get('role') != 'admin': return redirect(url_for('landing'))
    
    conn = get_db_connection()
    all_cases = []
    
    if request.method == 'POST' and request.form.get('action') == 'update_case_status':
        case_id = request.form.get('case_id')
        new_status = request.form.get('status')
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("UPDATE cases SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE case_id = %s", (new_status, case_id))
                conn.commit()
                flash(f"Case {case_id} status updated to {new_status}.", "success")
            except Exception as e:
                conn.rollback()
                flash(f"Error updating case status: {e}", "danger")
                
    if conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT * FROM cases WHERE status = 'Active' ORDER BY created_at DESC")
            all_cases = cur.fetchall()
        conn.close()
        
    return render_template('admin/dashboard.html', cases=all_cases)

@app.route('/admin/add_officer', methods=['GET', 'POST'])
def add_officer():
    if session.get('role') != 'admin': return redirect(url_for('landing'))

    conn = get_db_connection()
    next_officer_id = 'officer-1'  # default

    # Auto-generate next officer ID: officer-1, officer-2, ...
    if conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                "SELECT user_id FROM users WHERE role = 'officer' AND user_id LIKE 'officer-%' ORDER BY user_id DESC"
            )
            existing = cur.fetchall()
            if existing:
                nums = []
                for row in existing:
                    try:
                        nums.append(int(row['user_id'].split('-')[1]))
                    except (IndexError, ValueError):
                        pass
                next_num = max(nums) + 1 if nums else 1
            else:
                next_num = 1
            next_officer_id = f"officer-{next_num}"

    if request.method == 'POST':
        officer_id = request.form.get('officer_id')
        name = request.form.get('name')
        password = request.form.get('password')
        department = request.form.get('department')
        phone = request.form.get('phone')
        email = request.form.get('email')
        
        hashed_pw = hash_password(password)
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO users (user_id, name, role, password_hash, department, phone, email) VALUES (%s, %s, 'officer', %s, %s, %s, %s)",
                        (officer_id, name, hashed_pw, department, phone, email)
                    )
                conn.commit()
                flash("Officer added successfully.", "success")
            except Exception as e:
                conn.rollback()
                flash(f"Error adding officer: {e}", "danger")
            finally:
                conn.close()
            return redirect(url_for('add_officer'))

    if conn: conn.close()
    return render_template('admin/add_officer.html', next_officer_id=next_officer_id)


@app.route('/admin/view_evidence', methods=['GET', 'POST'])
def admin_view_evidence():
    if session.get('role') != 'admin': return redirect(url_for('landing'))
    
    evidence_list = []
    case_query = ""
    if request.method == 'POST':
        case_query = request.form.get('case_id')
        conn = get_db_connection()
        if conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("SELECT * FROM evidence WHERE case_id = %s", (case_query,))
                evidence_list = cur.fetchall()
            conn.close()
            
    return render_template('admin/view_evidence.html', evidence=evidence_list, case_query=case_query)

@app.route('/admin/create_case', methods=['GET', 'POST'])
def create_case():
    if session.get('role') != 'admin': return redirect(url_for('landing'))
    
    conn = get_db_connection()
    users = {'officers': [], 'supervisors': []}
    next_case_id = ''
    
    if conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT user_id, name FROM users WHERE role = 'officer' AND is_active = TRUE")
            users['officers'] = cur.fetchall()
            cur.execute("SELECT user_id, name FROM users WHERE role = 'supervisor' AND is_active = TRUE")
            users['supervisors'] = cur.fetchall()

            # Auto-generate next case ID: CASE-YYYY-NNN
            current_year = datetime.now().year
            year_prefix = f"CASE-{current_year}-"
            cur.execute(
                "SELECT case_id FROM cases WHERE case_id ILIKE %s ORDER BY case_id DESC LIMIT 1",
                (year_prefix + '%',)
            )
            last_case = cur.fetchone()
            if last_case:
                # Extract the numeric part and increment
                last_num = int(last_case['case_id'].split('-')[-1])
                next_num = last_num + 1
            else:
                next_num = 1
            next_case_id = f"CASE-{current_year}-{next_num:03d}"
            
    if request.method == 'POST':
        case_id = request.form.get('case_id')
        title = request.form.get('title')
        description = request.form.get('description')
        pol_station = request.form.get('police_station')
        alloc_officer = request.form.get('officer_id')
        alloc_super = request.form.get('supervisor_id')
        
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO cases (case_id, title, description, police_station, created_by) VALUES (%s, %s, %s, %s, %s)",
                        (case_id, title, description, pol_station, session['user_id'])
                    )
                    if alloc_officer:
                        cur.execute(
                            "INSERT INTO case_allocations (case_id, user_id, role, allocated_by) VALUES (%s, %s, 'officer', %s)",
                            (case_id, alloc_officer, session['user_id'])
                        )
                    if alloc_super:
                        cur.execute(
                            "INSERT INTO case_allocations (case_id, user_id, role, allocated_by) VALUES (%s, %s, 'supervisor', %s)",
                            (case_id, alloc_super, session['user_id'])
                        )
                conn.commit()
                flash("Case created successfully.", "success")
            except Exception as e:
                conn.rollback()
                flash(f"Error creating case: {e}", "danger")
            return redirect(url_for('create_case'))
            
    if conn: conn.close()
    return render_template('admin/create_case.html', users=users, next_case_id=next_case_id)

@app.route('/admin/chain_of_custody', methods=['GET', 'POST'])
def admin_coc():
    if session.get('role') != 'admin': return redirect(url_for('landing'))

    coc_list = []
    query = ""
    all_cases = []

    if request.method == 'POST':
        action = request.form.get('action')

        # ── Add new COC entry ──────────────────────────────────
        if action == 'add_coc':
            ev_id    = request.form.get('new_evidence_id')
            case_id  = request.form.get('new_case_id')
            from_usr = request.form.get('from_user')
            to_usr   = request.form.get('to_user')
            purpose  = request.form.get('purpose')
            notes    = request.form.get('notes') or None
            query    = ev_id  # keep search box pre-filled

            conn = get_db_connection()
            if conn:
                try:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO chain_of_custody
                                (evidence_id, case_id, from_user, to_user, purpose, notes)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (ev_id, case_id, from_usr, to_usr, purpose, notes))
                    conn.commit()
                    flash(f"COC entry added for Evidence {ev_id}.", "success")
                except Exception as e:
                    conn.rollback()
                    flash(f"Error adding COC entry: {e}", "danger")
                finally:
                    conn.close()

        # ── Search / View timeline ─────────────────────────────
        else:
            query = request.form.get('evidence_id', '')

        # Always reload timeline after any POST
        if query:
            conn = get_db_connection()
            if conn:
                with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                    cur.execute(
                        "SELECT * FROM chain_of_custody WHERE evidence_id = %s ORDER BY transfer_date ASC",
                        (query,)
                    )
                    coc_list = cur.fetchall()
                conn.close()

    # Fetch all cases and users for the dropdowns
    conn = get_db_connection()
    all_users = []
    if conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT case_id, title FROM cases ORDER BY case_id")
            all_cases = cur.fetchall()
            cur.execute("SELECT user_id, name, role FROM users WHERE role = 'officer' ORDER BY user_id")
            all_users = cur.fetchall()
        conn.close()

    return render_template('admin/chain_of_custody.html', coc=coc_list, query=query, all_cases=all_cases, all_users=all_users)

@app.route('/admin/get_evidence_by_case/<case_id>')
def get_evidence_by_case(case_id):
    if session.get('role') != 'admin': return jsonify([]), 403

    conn = get_db_connection()
    evidence_ids = []
    if conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT evidence_id FROM evidence WHERE case_id = %s ORDER BY evidence_id", (case_id,))
            evidence_ids = [row['evidence_id'] for row in cur.fetchall()]
        conn.close()

    return jsonify(evidence_ids)

@app.route('/admin/get_evidence_holder/<evidence_id>')
def get_evidence_holder(evidence_id):
    if session.get('role') != 'admin': return jsonify({'holder': None}), 403

    conn = get_db_connection()
    holder = None
    if conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("""
                SELECT to_user FROM chain_of_custody 
                WHERE evidence_id = %s 
                ORDER BY transfer_date DESC LIMIT 1
            """, (evidence_id,))
            row = cur.fetchone()
            if row:
                holder = row['to_user']
        conn.close()

    return jsonify({'holder': holder})


@app.route('/admin/add_supervisor', methods=['GET', 'POST'])
def add_supervisor():
    if session.get('role') != 'admin': return redirect(url_for('landing'))

    conn = get_db_connection()
    next_supervisor_id = 'supervisor-1'  # default

    # Auto-generate next supervisor ID: supervisor-1, supervisor-2, ...
    if conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                "SELECT user_id FROM users WHERE role = 'supervisor' AND user_id LIKE 'supervisor-%' ORDER BY user_id DESC"
            )
            existing = cur.fetchall()
            if existing:
                nums = []
                for row in existing:
                    try:
                        nums.append(int(row['user_id'].split('-')[1]))
                    except (IndexError, ValueError):
                        pass
                next_num = max(nums) + 1 if nums else 1
            else:
                next_num = 1
            next_supervisor_id = f"supervisor-{next_num}"

    if request.method == 'POST':
        supervisor_id = request.form.get('supervisor_id')
        name = request.form.get('name')
        password = request.form.get('password')
        department = request.form.get('department')
        phone = request.form.get('phone')
        email = request.form.get('email')
        
        hashed_pw = hash_password(password)
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO users (user_id, name, role, password_hash, department, phone, email) VALUES (%s, %s, 'supervisor', %s, %s, %s, %s)",
                        (supervisor_id, name, hashed_pw, department, phone, email)
                    )
                conn.commit()
                flash("Supervisor added successfully.", "success")
            except Exception as e:
                conn.rollback()
                flash(f"Error adding supervisor: {e}", "danger")
            finally:
                conn.close()
            return redirect(url_for('add_supervisor'))

    if conn: conn.close()
    return render_template('admin/add_supervisor.html', next_supervisor_id=next_supervisor_id)


@app.route('/admin/active_officer', methods=['GET', 'POST'])
def active_officer():
    if session.get('role') != 'admin': return redirect(url_for('landing'))

    conn = get_db_connection()

    if request.method == 'POST':
        officer_id = request.form.get('officer_id')
        new_status = request.form.get('status')  # 'Active' or 'Inactive'
        is_active = (new_status == 'Active')     # convert to boolean
        if conn and officer_id:
            try:
                with conn.cursor() as cur:
                    cur.execute("UPDATE users SET is_active = %s WHERE user_id = %s AND role = 'officer'",
                                (is_active, officer_id))
                conn.commit()
                flash(f"Officer {officer_id} status updated to {new_status}.", "success")
            except Exception as e:
                conn.rollback()
                flash(f"Error updating officer status: {e}", "danger")

    officers = []
    if conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT user_id AS officer_id, name, is_active AS status FROM users WHERE role = 'officer' ORDER BY officer_id")
            officers = cur.fetchall()
        conn.close()

    return render_template('admin/active_officer.html', officers=officers, razorpay_key=RAZORPAY_KEY_ID)

@app.route('/admin/pay_salary', methods=['POST'])
def pay_salary():
    if session.get('role') != 'admin': return jsonify({'error': 'Unauthorized'}), 403

    officer_id = request.form.get('officer_id')
    amount = request.form.get('amount')

    if not officer_id or not amount:
        return jsonify({'error': 'Officer ID and amount are required'}), 400

    try:
        amount_float = float(amount)
        amount_paise = int(amount_float * 100)  # Razorpay uses paise
    except ValueError:
        return jsonify({'error': 'Invalid amount'}), 400

    # Ensure Razorpay client is initialized
    if not razorpay_client:
        return jsonify({'error': 'Razorpay client not configured. Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET.'}), 500

    # Create Razorpay order
    order_data = {
        'amount': amount_paise,
        'currency': 'INR',
        'notes': {
            'officer_id': officer_id,
            'purpose': 'Salary Payment'
        }
    }

    try:
        order = razorpay_client.order.create(data=order_data)
    except Exception as e:
        print(f"Razorpay order creation error: {e}")
        return jsonify({'error': f'Razorpay order creation failed: {e}'}), 500

    # Save to DB
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO salary_payments (officer_id, amount, razorpay_order_id, status, paid_by)
                    VALUES (%s, %s, %s, 'created', %s)
                """, (officer_id, amount_float, order['id'], session['user_id']))
            conn.commit()
        except Exception as e:
            conn.rollback()
            return jsonify({'error': f'DB error: {e}'}), 500
        finally:
            conn.close()

    return jsonify({
        'order_id': order['id'],
        'amount': amount_paise,
        'currency': 'INR',
        'key': RAZORPAY_KEY_ID
    })


@app.route('/admin/razorpay_check')
def razorpay_check():
    """Admin-only endpoint that attempts a lightweight Razorpay order creation to validate keys."""
    if session.get('role') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403

    if not razorpay_client:
        return jsonify({'status': 'error', 'message': 'Razorpay client not configured. Check environment variables.'}), 500

    try:
        # create a small test order (won't be captured) to validate API auth
        test_order = razorpay_client.order.create(data={'amount': 100, 'currency': 'INR', 'notes': {'test': 'ping'}})
        return jsonify({'status': 'ok', 'order_id': test_order.get('id'), 'message': 'Razorpay keys appear valid (test order created).'})
    except Exception as e:
        print(f"Razorpay key validation error: {e}")
        return jsonify({'status': 'error', 'message': f'Razorpay API error: {e}'}), 500

@app.route('/admin/verify_salary_payment', methods=['POST'])
def verify_salary_payment():
    if session.get('role') != 'admin': return jsonify({'error': 'Unauthorized'}), 403

    payment_id = request.form.get('razorpay_payment_id')
    order_id = request.form.get('razorpay_order_id')
    signature = request.form.get('razorpay_signature')

    # Ensure Razorpay client available
    if not razorpay_client:
        return jsonify({'error': 'Razorpay client not configured. Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET.'}), 500

    # Verify signature
    try:
        razorpay_client.utility.verify_payment_signature({
            'razorpay_order_id': order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': signature
        })
    except razorpay.errors.SignatureVerificationError:
        # Update status to failed
        conn = get_db_connection()
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("UPDATE salary_payments SET status='failed' WHERE razorpay_order_id=%s", (order_id,))
                conn.commit()
            finally:
                conn.close()
        return jsonify({'error': 'Payment verification failed'}), 400

    # Update payment record as paid
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE salary_payments
                    SET razorpay_payment_id = %s, razorpay_signature = %s,
                        status = 'paid', paid_at = CURRENT_TIMESTAMP
                    WHERE razorpay_order_id = %s
                """, (payment_id, signature, order_id))
            conn.commit()
        except Exception as e:
            conn.rollback()
            return jsonify({'error': f'DB error: {e}'}), 500
        finally:
            conn.close()

    return jsonify({'status': 'success', 'message': 'Payment verified and recorded'})

@app.route('/admin/salary_history/<officer_id>')
def salary_history(officer_id):
    if session.get('role') != 'admin': return redirect(url_for('landing'))

    conn = get_db_connection()
    payments = []
    officer_name = officer_id

    if conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT name FROM users WHERE user_id = %s", (officer_id,))
            row = cur.fetchone()
            if row:
                officer_name = row['name']
            cur.execute("""
                SELECT * FROM salary_payments
                WHERE officer_id = %s ORDER BY created_at DESC
            """, (officer_id,))
            payments = cur.fetchall()
        conn.close()

    return render_template('admin/salary_history.html', payments=payments, officer_id=officer_id, officer_name=officer_name)

@app.route('/admin/active_supervisor', methods=['GET', 'POST'])
def active_supervisor():
    if session.get('role') != 'admin': return redirect(url_for('landing'))

    conn = get_db_connection()

    if request.method == 'POST':
        supervisor_id = request.form.get('supervisor_id')
        new_status = request.form.get('status')  # 'Active' or 'Inactive'
        is_active = (new_status == 'Active')     # convert to boolean
        if conn and supervisor_id:
            try:
                with conn.cursor() as cur:
                    cur.execute("UPDATE users SET is_active = %s WHERE user_id = %s AND role = 'supervisor'",
                                (is_active, supervisor_id))
                conn.commit()
                flash(f"Supervisor {supervisor_id} status updated to {new_status}.", "success")
            except Exception as e:
                conn.rollback()
                flash(f"Error updating supervisor status: {e}", "danger")

    supervisors = []
    if conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT user_id AS supervisor_id, name, is_active AS status FROM users WHERE role = 'supervisor' ORDER BY supervisor_id")
            supervisors = cur.fetchall()
        conn.close()

    return render_template('admin/active_supervisor.html', supervisors=supervisors)

@app.route('/admin/active_case', methods=['GET', 'POST'])
def active_case():
    if session.get('role') != 'admin': return redirect(url_for('landing'))

    conn = get_db_connection()

    if request.method == 'POST':
        case_id = request.form.get('case_id')
        new_status = request.form.get('status')
        if conn and case_id and new_status:
            try:
                with conn.cursor() as cur:
                    cur.execute("UPDATE cases SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE case_id = %s",
                                (new_status, case_id))
                conn.commit()
                flash(f"Case {case_id} status updated to {new_status}.", "success")
            except Exception as e:
                conn.rollback()
                flash(f"Error updating case status: {e}", "danger")

    cases = []
    # Support year-based search via GET param or form field
    search_year = request.args.get('search_year', '') or request.form.get('search_year', '')
    if conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            if search_year:
                cur.execute(
                    "SELECT * FROM cases WHERE case_id LIKE %s ORDER BY created_at DESC",
                    (f"CASE-{search_year}-%",)
                )
            else:
                cur.execute("SELECT * FROM cases ORDER BY created_at DESC")
            cases = cur.fetchall()
        conn.close()

    return render_template('admin/active_case.html', cases=cases, search_year=search_year)

# ==========================================
# OFFICER PANEL
# ==========================================

@app.route('/officer')
@app.route('/officer/dashboard')
def officer_dashboard():
    if session.get('role') != 'officer': return redirect(url_for('landing'))
    
    conn = get_db_connection()
    cases = []
    if conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("""
                SELECT c.* FROM cases c
                JOIN case_allocations ca ON c.case_id = ca.case_id
                WHERE ca.user_id = %s AND c.status = 'Active' ORDER BY c.created_at DESC
            """, (session['user_id'],))
            cases = cur.fetchall()
        conn.close()
        
    return render_template('officer/dashboard.html', cases=cases)

@app.route('/officer/upload_evidence', methods=['GET', 'POST'])
def upload_evidence():
    if session.get('role') != 'officer': return redirect(url_for('landing'))
    
    if request.method == 'POST':
        conn = get_db_connection()
        if conn:
            try:
                with conn.cursor() as cur:
                    # Validate allocation
                    cur.execute("SELECT 1 FROM case_allocations WHERE case_id=%s AND user_id=%s", 
                                (request.form.get('case_id'), session['user_id']))
                    if not cur.fetchone():
                        flash("You are not allocated to this case.", "danger")
                        return redirect(url_for('upload_evidence'))
                     # after  software_used remove hash_value,  
                    cur.execute("""
                        INSERT INTO evidence (
                            evidence_id, case_id, file_name, file_path, file_format, nature, date_creation, date_extraction,
                            device_type, device_make, serial_number, storage_capacity, operating_system, software_used, 
                           hash_value,  storage_media, storage_id_mark, uploaded_by, status
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,  'Pending')
                    """, (
                        request.form.get('evidence_id'), request.form.get('case_id'), 
                        request.form.get('file_name'), request.form.get('file_path'),
                        request.form.get('file_format'), request.form.get('nature'),
                        request.form.get('date_creation'), request.form.get('date_extraction'),
                        request.form.get('device_type'), request.form.get('device_make'),
                        request.form.get('serial_number'), request.form.get('storage_capacity'), 
                        request.form.get('operating_system'), request.form.get('software_used'),
                        request.form.get('hash_value'),
                        request.form.get('storage_media'), 
                        request.form.get('storage_id_mark'), session['user_id']
                    ))
                    
                    cur.execute("""
                        INSERT INTO chain_of_custody (evidence_id, case_id, from_user, to_user, purpose)
                        VALUES (%s, %s, %s, %s, 'Initial Upload')
                    """, (request.form.get('evidence_id'), request.form.get('case_id'), 
                          session['user_id'], session['user_id']))
                conn.commit()
                flash("Evidence uploaded successfully.", "success")
            except Exception as e:
                conn.rollback()
                flash(f"Error uploading evidence: {e}", "danger")
            finally:
                conn.close()
            return redirect(url_for('upload_evidence'))
            
    return render_template('officer/upload_evidence.html')

@app.route('/officer/verify_status', methods=['GET', 'POST'])
def officer_verify():
    if session.get('role') != 'officer': return redirect(url_for('landing'))
    
    ev_data = None
    if request.method == 'POST':
        query = request.form.get('evidence_id')
        conn = get_db_connection()
        if conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("SELECT status, notes, verified_by, verified_at FROM evidence WHERE evidence_id = %s", (query,))
                ev_data = cur.fetchone()
            conn.close()
            
    return render_template('officer/verify_status.html', data=ev_data)

@app.route('/officer/view_evidence', methods=['GET', 'POST'])
def officer_view_evidence():
    if session.get('role') != 'officer': return redirect(url_for('landing'))
    
    evidence_list = []
    query = ""
    if request.method == 'POST':
        query = request.form.get('case_id')
        conn = get_db_connection()
        if conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("SELECT 1 FROM case_allocations WHERE case_id=%s AND user_id=%s", (query, session['user_id']))
                if cur.fetchone():
                    cur.execute("SELECT * FROM evidence WHERE case_id = %s", (query,))
                    evidence_list = cur.fetchall()
                else:
                    flash("Not allocated to this case.", "warning")
            conn.close()
            
    return render_template('officer/view_evidence.html', evidence=evidence_list, query=query)


# ==========================================
# SUPERVISOR PANEL
# ==========================================

@app.route('/supervisor')
@app.route('/supervisor/dashboard')
def supervisor_dashboard():
    if session.get('role') != 'supervisor': return redirect(url_for('landing'))
    
    conn = get_db_connection()
    cases = []
    if conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("""
                SELECT c.* FROM cases c
                JOIN case_allocations ca ON c.case_id = ca.case_id
                WHERE ca.user_id = %s AND c.status = 'Active' ORDER BY c.created_at DESC
            """, (session['user_id'],))
            cases = cur.fetchall()
        conn.close()
        
    return render_template('supervisor/dashboard.html', cases=cases)

@app.route('/supervisor/view_coc', methods=['GET', 'POST'])
def supervisor_coc():
    if session.get('role') != 'supervisor': return redirect(url_for('landing'))
    
    coc_list = []
    if request.method == 'POST':
        query = request.form.get('evidence_id')
        conn = get_db_connection()
        if conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("SELECT * FROM chain_of_custody WHERE evidence_id = %s ORDER BY transfer_date ASC", (query,))
                coc_list = cur.fetchall()
            conn.close()
            
    return render_template('supervisor/view_coc.html', coc=coc_list)

@app.route('/supervisor/verify_evidence', methods=['GET', 'POST'])
def supervisor_verify():
    if session.get('role') != 'supervisor': return redirect(url_for('landing'))
    
    evidence_list = []
    case_query = request.args.get('case_id', "")
    
    conn = get_db_connection()
    if request.method == 'POST' and request.form.get('action') == 'update_status':
        ev_id = request.form.get('evidence_id')
        new_status = request.form.get('status')
        notes = request.form.get('notes')
        case_query = request.form.get('case_id')
        
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE evidence 
                        SET status = %s, notes = %s, verified_by = %s, verified_at = CURRENT_TIMESTAMP
                        WHERE evidence_id = %s
                    """, (new_status, notes, session['user_id'], ev_id))
                conn.commit()
                flash("Evidence status updated.", "success")
            except Exception as e:
                conn.rollback()
                flash(f"Error updating status: {e}", "danger")
            
    if case_query and conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT 1 FROM case_allocations WHERE case_id=%s AND user_id=%s", (case_query, session['user_id']))
            if cur.fetchone():
                cur.execute("SELECT * FROM evidence WHERE case_id = %s", (case_query,))
                evidence_list = cur.fetchall()
            else:
                flash("Not allocated to this case.", "warning")
                evidence_list = []
                
    if conn: conn.close()
    return render_template('supervisor/verify_evidence.html', evidence=evidence_list, case_query=case_query)

@app.route('/supervisor/section_63', methods=['GET', 'POST'])
def section_63_form():
    if session.get('role') != 'supervisor': return redirect(url_for('landing'))
    
    data = None
    form_format = "A"
    not_verified = False
    not_found = False
    
    if request.method == 'POST':
        ev_id = request.form.get('evidence_id')
        form_format = request.form.get('form_format', 'A')
        
        conn = get_db_connection()
        if conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("""
                    SELECT e.*, c.title as case_title, c.police_station 
                    FROM evidence e
                    JOIN cases c ON e.case_id = c.case_id
                    WHERE e.evidence_id = %s
                """, (ev_id,))
                row = cur.fetchone()
            conn.close()

            if row is None:
                not_found = True          # Evidence ID does not exist
            elif row['status'] != 'Verified':
                not_verified = True       # Exists but not yet verified
            else:
                data = row               # Verified — allow form generation
            
    return render_template('supervisor/section_63_form.html',
                           data=data, form_format=form_format,
                           not_verified=not_verified, not_found=not_found)


# ==========================================
# SHARED ROUTES
# ==========================================

@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if session.get('role') != 'admin': return redirect(url_for('landing'))
    
    if request.method == 'POST':
        old_pw = request.form.get('old_password')
        new_pw = request.form.get('new_password')
        
        conn = get_db_connection()
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT password_hash FROM users WHERE user_id = %s", (session['user_id'],))
                    row = cur.fetchone()
                    if row and row[0] == hash_password(old_pw):
                        cur.execute("UPDATE users SET password_hash = %s WHERE user_id = %s", 
                                  (hash_password(new_pw), session['user_id']))
                        conn.commit()
                        flash("Password updated successfully.", "success")
                    else:
                        flash("Incorrect old password.", "danger")
            except Exception as e:
                conn.rollback()
                flash(f"Error: {e}", "danger")
            finally:
                conn.close()
                
    return render_template('shared/change_password.html')

@app.route('/admin/change_user_password', methods=['POST'])
def change_user_password():
    if session.get('role') != 'admin': return redirect(url_for('landing'))

    user_id = request.form.get('user_id')
    new_password = request.form.get('new_password')
    redirect_to = request.form.get('redirect_to', 'active_officer')

    if not user_id or not new_password:
        flash("User ID and new password are required.", "danger")
        return redirect(url_for(redirect_to))

    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET password_hash = %s WHERE user_id = %s",
                            (hash_password(new_password), user_id))
            conn.commit()
            flash(f"Password for {user_id} updated successfully.", "success")
        except Exception as e:
            conn.rollback()
            flash(f"Error changing password: {e}", "danger")
        finally:
            conn.close()

    return redirect(url_for(redirect_to))

if __name__ == '__main__':
    app.run(debug=True, port=5000)

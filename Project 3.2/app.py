import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_mail import Mail, Message
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from collections import defaultdict

# --- 1. SETUP & CONFIGURATION ---
app = Flask(__name__)
app.secret_key = 'supersecretkey'

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///university_database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- EMAIL CONFIGURATION ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'officalinternet69@gmail.com'  
app.config['MAIL_PASSWORD'] = 'imfsqsknyusddefa'    
app.config['MAIL_DEFAULT_SENDER'] = 'officalinternet69@gmail.com' 
mail = Mail(app)

# --- 2. DATABASE MODELS ---
class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    usn = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    course = db.Column(db.String(50), nullable=True)
    semester = db.Column(db.String(10), nullable=True)
    subjects = db.Column(db.Text, nullable=True)

class Faculty(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

with app.app_context():
    db.create_all()

rooms_db, allocations_db, duty_db, qp_stats = [], [], [], {}

# --- 3. ADMIN ROUTES ---
@app.route('/')
def home():
    stats = {'students': Student.query.count(), 'faculty': Faculty.query.count(), 'rooms': len(rooms_db), 'allocations': len(allocations_db)}
    return render_template('index.html', stats=stats)

@app.route('/login_page')
def login_page(): return render_template('login.html')

@app.route('/login', methods=['POST'])
def perform_login():
    if request.form['username'] == "admin" and request.form['password'] == "admin@1234":
        return redirect(url_for('dashboard'))
    return "<h1>Wrong Password!</h1>"

@app.route('/dashboard')
def dashboard():
    students = Student.query.all()
    faculty = Faculty.query.all()
    
    all_subjects = set()
    for s in students:
        if s.subjects:
            for sub in s.subjects.split(', '):
                all_subjects.add(sub.strip())
    sorted_subjects = sorted(list(all_subjects))
    
    return render_template('dashboard.html', students=students, faculty=faculty, rooms=rooms_db, allocations_count=len(allocations_db), all_subjects=sorted_subjects)

@app.route('/add_room', methods=['POST'])
def add_room():
    rooms_db.append({'room_no': request.form['room_no'], 'capacity': int(request.form['capacity'])})
    flash(f"Room {request.form['room_no']} added successfully.", "success")
    return redirect(url_for('dashboard'))

# --- NEW DELETE ROUTES ---
@app.route('/delete_room/<room_no>', methods=['POST'])
def delete_room(room_no):
    global rooms_db
    # Rebuild the list without the deleted room
    rooms_db = [room for room in rooms_db if str(room['room_no']) != str(room_no)]
    flash(f"Room {room_no} deleted successfully.", "error") 
    return redirect(url_for('dashboard'))

@app.route('/delete_student/<usn>', methods=['POST'])
def delete_student(usn):
    student = Student.query.filter_by(usn=usn).first()
    if student:
        db.session.delete(student)
        db.session.commit()
        flash(f"Student {student.name} ({usn}) removed successfully.", "success")
    else:
        flash(f"Student not found.", "error")
    return redirect(url_for('dashboard'))

@app.route('/delete_faculty/<email>', methods=['POST'])
def delete_faculty(email):
    faculty = Faculty.query.filter_by(email=email).first()
    if faculty:
        db.session.delete(faculty)
        db.session.commit()
        flash(f"Prof. {faculty.name} removed successfully.", "success")
    else:
        flash(f"Faculty not found.", "error")
    return redirect(url_for('dashboard'))


# --- MASTER TIMETABLE ALGORITHM ---
@app.route('/generate', methods=['POST'])
def generate():
    global allocations_db, duty_db, qp_stats
    allocations_db, duty_db, qp_stats = [], [], {}
    
    selected_subjects = request.form.getlist('subjects')
    if not selected_subjects:
        flash("Please select at least one subject to generate the plan.", "error")
        return redirect(url_for('dashboard'))

    timeslot_groups = defaultdict(list)
    for subj in selected_subjects:
        date_val = request.form.get(f'date_{subj}')
        time_val = request.form.get(f'time_{subj}')
        date = date_val if date_val else 'TBA'
        time = time_val if time_val else 'TBA'
        timeslot_groups[(date, time)].append(subj)

    active_faculty = [{'Name': f.name, 'Email': f.email} for f in Faculty.query.all()]
    f_idx = 0

    for (exam_date, exam_time), subs_in_slot in timeslot_groups.items():
        students_to_seat = []
        for s in Student.query.all():
            if s.subjects:
                enrolled_subs = [sub.strip() for sub in s.subjects.split(',')]
                for sel_sub in subs_in_slot:
                    if sel_sub in enrolled_subs:
                        students_to_seat.append({'Name': s.name.strip(), 'USN': s.usn.strip(), 'Subject': sel_sub, 'Email': s.email.strip()})
                        break 

        subject_groups = {}
        for st in students_to_seat:
            subj = st['Subject']
            if subj not in subject_groups:
                subject_groups[subj] = []
            subject_groups[subj].append(st)

        for room in rooms_db:
            r_name, cap = room['room_no'], room['capacity']
            
            if sum(len(v) for v in subject_groups.values()) == 0:
                break
                
            if active_faculty:
                fac = active_faculty[f_idx % len(active_faculty)]
                duty_db.append({'Date': exam_date, 'Time': exam_time, 'Room': r_name, 'Faculty': fac['Name'], 'Email': fac['Email']})
                f_idx += 1
                
            if r_name not in qp_stats: qp_stats[r_name] = {}
            prev_subject = None

            for seat in range(1, cap + 1):
                if sum(len(v) for v in subject_groups.values()) == 0:
                    break
                
                valid_subjects = [subj for subj, students in subject_groups.items() if len(students) > 0 and subj != prev_subject]
                
                if valid_subjects:
                    valid_subjects.sort(key=lambda s: len(subject_groups[s]), reverse=True)
                    chosen_subject = valid_subjects[0]
                    student = subject_groups[chosen_subject].pop(0)
                    
                    allocations_db.append({
                        'Date': exam_date, 'Time': exam_time,
                        'Room': r_name, 'Seat': seat, 'USN': student['USN'], 
                        'Name': student['Name'], 'Subject': student['Subject'], 'Email': student['Email']
                    })
                    
                    qp_stats[r_name][chosen_subject] = qp_stats[r_name].get(chosen_subject, 0) + 1
                    prev_subject = chosen_subject
                else:
                    allocations_db.append({
                        'Date': exam_date, 'Time': exam_time,
                        'Room': r_name, 'Seat': seat, 'USN': '-', 
                        'Name': '--- EMPTY SEAT (SPACING) ---', 'Subject': '-', 'Email': ''
                    })
                    prev_subject = None 

    return render_template('seating.html', allocations=allocations_db, qp_stats=qp_stats, duties=duty_db)

# --- BEAUTIFUL COLUMN-FORMAT EMAIL DISPATCH ---
@app.route('/send_emails', methods=['POST'])
def send_emails():
    count = 0
    with mail.connect() as conn:
        
        student_schedules = defaultdict(list)
        for alloc in allocations_db:
            if alloc.get('Email') and alloc.get('Email') != '':
                if alloc['Subject'] != '-':
                    student_schedules[alloc['Email']].append(alloc)

        for email, exams in student_schedules.items():
            name = exams[0]['Name']
            cards_html = ""
            for ex in exams:
                cards_html += f"""
                <table border="0" cellpadding="12" cellspacing="0" style="width: 100%; border-collapse: collapse; margin-bottom: 20px; border: 1px solid #e0e0e0; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); background-color: #ffffff;">
                    <tr><td style="width: 35%; background-color: #f8f9fa; font-weight: bold; color: #555555; border-bottom: 1px solid #eeeeee; border-right: 1px solid #eeeeee;">Subject</td><td style="border-bottom: 1px solid #eeeeee; color: #333333; font-weight: bold;">{ex['Subject']}</td></tr>
                    <tr><td style="background-color: #f8f9fa; font-weight: bold; color: #555555; border-bottom: 1px solid #eeeeee; border-right: 1px solid #eeeeee;">Date</td><td style="border-bottom: 1px solid #eeeeee; color: #333333;">{ex['Date']}</td></tr>
                    <tr><td style="background-color: #f8f9fa; font-weight: bold; color: #555555; border-bottom: 1px solid #eeeeee; border-right: 1px solid #eeeeee;">Time</td><td style="border-bottom: 1px solid #eeeeee; color: #333333;">{ex['Time']}</td></tr>
                    <tr><td style="background-color: #f8f9fa; font-weight: bold; color: #555555; border-bottom: 1px solid #eeeeee; border-right: 1px solid #eeeeee;">Room</td><td style="border-bottom: 1px solid #eeeeee; color: #6c5ce7; font-weight: bold; font-size: 16px;">{ex['Room']}</td></tr>
                    <tr><td style="background-color: #f8f9fa; font-weight: bold; color: #555555; border-right: 1px solid #eeeeee;">Seat No.</td><td style="color: #00cec9; font-weight: bold; font-size: 16px;">{ex['Seat']}</td></tr>
                </table>
                """
            student_html = f"""
            <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #e0e0e0; border-radius: 12px; overflow: hidden; background-color: #fcfcfc;">
                <div style="background: linear-gradient(135deg, #6c5ce7, #00cec9); padding: 25px; text-align: center; color: white;"><h2 style="margin: 0; font-size: 26px; font-weight: bold; letter-spacing: 1px;">AEW Master Hall Ticket</h2></div>
                <div style="padding: 30px; color: #333333;">
                    <p style="font-size: 16px; margin-top: 0;">Hello <strong>{name}</strong>,</p>
                    <p style="font-size: 15px; color: #555555; margin-bottom: 25px;">Your complete examination schedule has been finalized. Please find your official seating details below:</p>
                    {cards_html}
                    <p style="font-size: 13px; color: #888888; text-align: center; margin-top: 30px; border-top: 1px solid #dddddd; padding-top: 20px;">Best of luck with your examinations!<br><strong>AEW Administration System</strong></p>
                </div>
            </div>
            """
            try:
                conn.send(Message(subject="Your Complete AEW Hall Ticket", recipients=[email], html=student_html))
                count += 1
            except: pass

        faculty_schedules = defaultdict(list)
        for duty in duty_db:
            if duty.get('Email') and duty.get('Email') != '':
                faculty_schedules[duty['Email']].append(duty)

        for email, duties in faculty_schedules.items():
            name = duties[0]['Faculty']
            cards_html = ""
            for d in duties:
                cards_html += f"""
                <table border="0" cellpadding="12" cellspacing="0" style="width: 100%; border-collapse: collapse; margin-bottom: 20px; border: 1px solid #e0e0e0; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); background-color: #ffffff;">
                    <tr><td style="width: 35%; background-color: #f8f9fa; font-weight: bold; color: #555555; border-bottom: 1px solid #eeeeee; border-right: 1px solid #eeeeee;">Date</td><td style="border-bottom: 1px solid #eeeeee; color: #333333;">{d['Date']}</td></tr>
                    <tr><td style="background-color: #f8f9fa; font-weight: bold; color: #555555; border-bottom: 1px solid #eeeeee; border-right: 1px solid #eeeeee;">Time</td><td style="border-bottom: 1px solid #eeeeee; color: #333333;">{d['Time']}</td></tr>
                    <tr><td style="background-color: #f8f9fa; font-weight: bold; color: #555555; border-right: 1px solid #eeeeee;">Room Assigned</td><td style="color: #e84393; font-weight: bold; font-size: 16px;">{d['Room']}</td></tr>
                </table>
                """
            faculty_html = f"""
            <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #e0e0e0; border-radius: 12px; overflow: hidden; background-color: #fcfcfc;">
                <div style="background: linear-gradient(135deg, #e84393, #6c5ce7); padding: 25px; text-align: center; color: white;"><h2 style="margin: 0; font-size: 26px; font-weight: bold; letter-spacing: 1px;">Master Invigilation Duty</h2></div>
                <div style="padding: 30px; color: #333333;">
                    <p style="font-size: 16px; margin-top: 0;">Hello Prof. <strong>{name}</strong>,</p>
                    <p style="font-size: 15px; color: #555555; margin-bottom: 25px;">You have been assigned to invigilation duty. Please find your complete schedule below:</p>
                    {cards_html}
                    <p style="font-size: 13px; color: #888888; text-align: center; margin-top: 30px; border-top: 1px solid #dddddd; padding-top: 20px;">Thank you for your cooperation.<br><strong>AEW Administration System</strong></p>
                </div>
            </div>
            """
            try:
                conn.send(Message(subject="Master Invigilation Schedule", recipients=[email], html=faculty_html))
                count += 1
            except: pass

    flash(f"Successfully transmitted {count} Master Schedule Emails!", "success")
    return redirect(url_for('dashboard'))

# --- 4. STUDENT ROUTES (FIXED CURRICULUM MAPPING) ---
@app.route('/student_login', methods=['GET', 'POST'])
def student_login():
    error = None
    if request.method == 'POST':
        student = Student.query.filter_by(email=request.form['email']).first()
        if student and check_password_hash(student.password, request.form['password']):
            session['student_usn'] = student.usn  
            session['student_name'] = student.name
            return redirect(url_for('student_select'))
        else: error = "Invalid Credentials!"
    return render_template('student_login.html', error=error)

@app.route('/student_register', methods=['GET', 'POST'])
def student_register():
    error = None
    if request.method == 'POST':
        if Student.query.filter_by(usn=request.form['usn'].strip().upper()).first() or Student.query.filter_by(email=request.form['email']).first():
            error = "USN or Email already exists."
        else:
            new_student = Student(name=request.form['name'], usn=request.form['usn'].strip().upper(), email=request.form['email'], password=generate_password_hash(request.form['password']))
            db.session.add(new_student)
            db.session.commit()
            flash("Account successfully created! You can now login.", "success")
            return redirect(url_for('student_login'))
    return render_template('student_register.html', error=error)

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    error = None
    if request.method == 'POST':
        student = Student.query.filter_by(email=request.form['email'], usn=request.form['usn'].strip().upper()).first()
        if student:
            student.password = generate_password_hash(request.form['new_password'])
            db.session.commit()
            flash("Password reset successfully! Please login.", "success")
            return redirect(url_for('student_login'))
        else: error = "Verification failed. USN and Email do not match."
    return render_template('forgot_password.html', error=error)

@app.route('/student_select', methods=['GET', 'POST'])
def student_select():
    if 'student_usn' not in session: return redirect(url_for('student_login'))
    student = Student.query.filter_by(usn=session['student_usn']).first()
    
    if request.method == 'POST':
        course = request.form.get('course')
        semester = request.form.get('semester')
        
        curriculum_map = {
            'MCA': {
                '1': 'TOC, Data Structure, Discrete Mathematics',
                '3': 'Web programming, RM, ML'
            },
            'MBA': {
                '1': 'Marketing Management, Financial Management, HRM',
                '3': 'Business communication, Operational management, Psychology'
            }
        }
        
        assigned_subjects = curriculum_map.get(course, {}).get(semester, '')
        
        student.course = course
        student.semester = semester
        student.subjects = assigned_subjects
        db.session.commit()
        
        flash(f"Successfully registered for {course} Semester {semester}! Your assigned subjects are: {assigned_subjects}", "success")
        
    return render_template('student_select.html', student=student)

# --- 5. FACULTY ROUTES ---
@app.route('/faculty_login', methods=['GET', 'POST'])
def faculty_login():
    error = None
    if request.method == 'POST':
        fac = Faculty.query.filter_by(email=request.form['email']).first()
        if fac and check_password_hash(fac.password, request.form['password']):
            session['faculty_name'] = fac.name
            flash(f"Welcome back, Prof. {fac.name}! You will receive your duty schedule via email.", "success")
            return redirect(url_for('home'))
        else: error = "Invalid Credentials!"
    return render_template('faculty_login.html', error=error)

@app.route('/faculty_register', methods=['GET', 'POST'])
def faculty_register():
    error = None
    if request.method == 'POST':
        if Faculty.query.filter_by(email=request.form['email']).first():
            error = "Email already registered."
        else:
            db.session.add(Faculty(name=request.form['name'], email=request.form['email'], password=generate_password_hash(request.form['password'])))
            db.session.commit()
            flash("Faculty account created! Please login.", "success")
            return redirect(url_for('faculty_login'))
    return render_template('faculty_register.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

if __name__ == "__main__":
    app.run(debug=True, port=5001)
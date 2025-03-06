from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
import stripe
import openai
import os

# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'your_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'your_email@gmail.com'
app.config['MAIL_PASSWORD'] = 'your_email_password'

# Initialize extensions
db = SQLAlchemy(app)
mail = Mail(app)

# Stripe configuration
stripe.api_key = 'your_stripe_secret_key'

# OpenAI configuration
openai.api_key = 'your_openai_api_key'

# Database Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(10), nullable=False)  # 'customer' or 'labourer'

class Labourer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    skills = db.Column(db.String(200), nullable=False)
    phone_number = db.Column(db.String(15), nullable=False)
    experience = db.Column(db.String(100), nullable=False)
    availability = db.Column(db.String(100), nullable=False)
    hourly_rate = db.Column(db.Float, nullable=False)

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    labourer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')  # 'pending', 'accepted', 'rejected'

# Routes
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']

        hashed_password = generate_password_hash(password, method='sha256')
        new_user = User(username=username, password=hashed_password, role=role)
        db.session.add(new_user)
        db.session.commit()

        flash('Account created successfully! Please login.')
        return redirect(url_for('login'))

    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['role'] = user.role
            flash('Logged in successfully!')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password.')

    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    role = session['role']

    if role == 'customer':
        labourers = Labourer.query.all()
        return render_template('customer_dashboard.html', labourers=labourers)
    elif role == 'labourer':
        bookings = Booking.query.filter_by(labourer_id=user_id).all()
        return render_template('labourer_dashboard.html', bookings=bookings)

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session or session['role'] != 'labourer':
        return redirect(url_for('login'))

    user_id = session['user_id']
    labourer = Labourer.query.filter_by(user_id=user_id).first()

    if request.method == 'POST':
        labourer.skills = request.form['skills']
        labourer.phone_number = request.form['phone_number']
        labourer.experience = request.form['experience']
        labourer.availability = request.form['availability']
        labourer.hourly_rate = request.form['hourly_rate']
        db.session.commit()
        flash('Profile updated successfully!')
        return redirect(url_for('dashboard'))

    return render_template('profile.html', labourer=labourer)

@app.route('/search', methods=['GET'])
def search():
    if 'user_id' not in session or session['role'] != 'customer':
        return redirect(url_for('login'))

    service = request.args.get('service')
    location = request.args.get('location')

    results = Labourer.query.filter(
        Labourer.skills.ilike(f'%{service}%'),
        Labourer.availability.ilike(f'%{location}%')
    ).all()

    return render_template('search.html', results=results)

@app.route('/book/<int:labourer_id>', methods=['POST'])
def book(labourer_id):
    if 'user_id' not in session or session['role'] != 'customer':
        return redirect(url_for('login'))

    customer_id = session['user_id']
    new_booking = Booking(customer_id=customer_id, labourer_id=labourer_id)
    db.session.add(new_booking)
    db.session.commit()

    # Send email to labourer
    labourer = Labourer.query.get(labourer_id)
    customer = User.query.get(customer_id)
    send_email(
        to=labourer.user.username,  # Assuming email is stored as username
        subject='New Booking Request',
        body=f'You have a new booking request from {customer.username}.'
    )

    flash('Booking request sent!')
    return redirect(url_for('dashboard'))

@app.route('/update_booking/<int:booking_id>/<status>')
def update_booking(booking_id, status):
    if 'user_id' not in session or session['role'] != 'labourer':
        return redirect(url_for('login'))

    booking = Booking.query.get(booking_id)
    booking.status = status
    db.session.commit()

    flash(f'Booking {status}!')
    return redirect(url_for('dashboard'))

@app.route('/chat', methods=['POST'])
def chat():
    if 'user_id' not in session or session['role'] != 'customer':
        return jsonify({'error': 'Unauthorized'}), 401

    user_input = request.json.get('message')
    if not user_input:
        return jsonify({'error': 'No message provided'}), 400

    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a helpful assistant that helps customers choose the right labourer based on their needs."},
            {"role": "user", "content": user_input}
        ]
    )

    ai_response = response['choices'][0]['message']['content']
    return jsonify({'response': ai_response})

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully!')
    return redirect(url_for('home'))

# Helper functions
def send_email(to, subject, body):
    msg = Message(subject, sender='your_email@gmail.com', recipients=[to])
    msg.body = body
    mail.send(msg)

# Run the app
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)
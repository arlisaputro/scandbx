from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import boto3
from botocore.exceptions import ClientError
import easyocr
import io
from PIL import Image

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'
app.config['S3_BUCKET'] = 'scandbx-file-bucket'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Create uploads directory if it doesn't exist
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Initialize S3 client (optional)
try:
    s3_client = boto3.client('s3', region_name='us-east-1')
    s3_available = True
except Exception as e:
    print(f"Warning: S3 not available: {e}")
    s3_client = None
    s3_available = False

# Initialize EasyOCR reader with Indonesian and English support
try:
    ocr_reader = easyocr.Reader(['id', 'en'])
except Exception as e:
    print(f"Warning: Could not initialize EasyOCR: {e}")
    ocr_reader = None

# Simple user storage (use database in production)
users = {
    'admin': generate_password_hash('password123'),
    'guest': generate_password_hash('guest123')
}

ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('menu.html')

@app.route('/upload_page')
def upload_page():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('upload.html', s3_available=s3_available)

@app.route('/file_list')
def file_list():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    filter_type = request.args.get('filter', 'all')
    if not filter_type:
        filter_type = 'all'
    files = []
    
    # Get S3 files
    if filter_type in ['all', 's3'] and s3_available:
        try:
            response = s3_client.list_objects_v2(Bucket=app.config['S3_BUCKET'])
            s3_files = [{'name': obj['Key'], 'storage': 's3'} for obj in response.get('Contents', [])]
            files.extend(s3_files)
        except Exception as e:
            if filter_type == 's3':
                flash('S3 not available. Please configure AWS credentials.')
    
    # Get local files
    if filter_type in ['all', 'local']:
        try:
            local_files = os.listdir(app.config['UPLOAD_FOLDER'])
            local_files = [{'name': f, 'storage': 'local'} for f in local_files if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
            files.extend(local_files)
        except OSError:
            pass
    
    return render_template('file_list.html', files=files, current_filter=filter_type or 'all', s3_available=s3_available)

@app.route('/extract_text/<storage>/<filename>')
def extract_text(storage, filename):
    if 'username' not in session:
        return redirect(url_for('login'))
    
    if ocr_reader is None:
        flash('OCR service is not available. Please install EasyOCR.')
        return redirect(url_for('file_list'))
    
    try:
        if storage == 's3' and s3_available:
            # Download image from S3
            response = s3_client.get_object(Bucket=app.config['S3_BUCKET'], Key=filename)
            image_data = response['Body'].read()
        elif storage == 's3':
            flash('S3 not available for text extraction.')
            return redirect(url_for('file_list'))
        else:
            # Read local file
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            with open(file_path, 'rb') as f:
                image_data = f.read()
        
        # Extract text using EasyOCR
        results = ocr_reader.readtext(image_data)
        text = '\n'.join([result[1] for result in results])
        
        return render_template('extracted_text.html', filename=filename, text=text)
    except Exception as e:
        flash(f'Error extracting text: {str(e)}')
        return redirect(url_for('file_list'))

@app.route('/delete_file/<storage>/<filename>', methods=['POST'])
def delete_file(storage, filename):
    if 'username' not in session:
        return redirect(url_for('login'))
    if session['username'] != 'admin':
        flash('Access denied. Admin only.')
        return redirect(url_for('file_list'))
    
    try:
        if storage == 's3' and s3_available:
            s3_client.delete_object(Bucket=app.config['S3_BUCKET'], Key=filename)
        elif storage == 's3':
            flash('S3 not available for deletion.')
            return redirect(url_for('file_list'))
        else:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            os.remove(file_path)
        flash(f'File {filename} deleted successfully!')
    except Exception as e:
        flash(f'Error deleting file: {str(e)}')
    return redirect(url_for('file_list'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        if username in users and check_password_hash(users[username], password):
            session['username'] = username
            return redirect(url_for('index'))
        flash('Invalid credentials')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    if 'file' not in request.files:
        flash('No file selected')
        return redirect(url_for('upload_page'))
    
    file = request.files['file']
    storage = request.form.get('storage', 's3')
    
    if file.filename == '':
        flash('No file selected')
        return redirect(url_for('upload_page'))
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        try:
            if storage == 's3' and s3_available:
                s3_client.upload_fileobj(file, app.config['S3_BUCKET'], filename)
                flash(f'File {filename} uploaded to S3 successfully!')
            elif storage == 's3':
                flash('S3 not available. Uploading to local folder instead.')
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                flash(f'File {filename} uploaded to local folder successfully!')
            else:
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                flash(f'File {filename} uploaded to local folder successfully!')
        except Exception as e:
            flash(f'Error uploading file: {str(e)}')
        return redirect(url_for('upload_page'))
    
    flash('Invalid file type. Only JPG, JPEG, PNG allowed.')
    return redirect(url_for('upload_page'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001, ssl_context='adhoc')
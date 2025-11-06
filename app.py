from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import boto3
from botocore.exceptions import ClientError

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'
app.config['S3_BUCKET'] = 'scandbx-file-bucket'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Initialize S3 client
s3_client = boto3.client('s3', region_name='ap-southeast-3')

# Simple user storage (use database in production)
users = {
    'admin': generate_password_hash('password123'),
    'guest': generate_password_hash('guest123')
}

ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png'}

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
    return render_template('upload.html')

@app.route('/file_list')
def file_list():
    if 'username' not in session:
        return redirect(url_for('login'))
    try:
        response = s3_client.list_objects_v2(Bucket=app.config['S3_BUCKET'])
        files = [obj['Key'] for obj in response.get('Contents', [])]
    except ClientError:
        files = []
        flash('Error accessing S3 bucket')
    return render_template('file_list.html', files=files)

@app.route('/view_file/<filename>')
def view_file(filename):
    if 'username' not in session:
        return redirect(url_for('login'))
    try:
        url = s3_client.generate_presigned_url('get_object',
                                               Params={'Bucket': app.config['S3_BUCKET'], 'Key': filename},
                                               ExpiresIn=3600,
                                               Config=boto3.session.Config(region_name='ap-southeast-3'))
        return redirect(url)
    except ClientError:
        flash('File not found')
        return redirect(url_for('file_list'))

@app.route('/delete_file/<filename>', methods=['POST'])
def delete_file(filename):
    if 'username' not in session:
        return redirect(url_for('login'))
    if session['username'] != 'admin':
        flash('Access denied. Admin only.')
        return redirect(url_for('file_list'))
    
    try:
        s3_client.delete_object(Bucket=app.config['S3_BUCKET'], Key=filename)
        flash(f'File {filename} deleted successfully!')
    except ClientError:
        flash('Error deleting file')
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
        return redirect(url_for('index'))
    
    file = request.files['file']
    if file.filename == '':
        flash('No file selected')
        return redirect(url_for('index'))
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        try:
            s3_client.upload_fileobj(file, app.config['S3_BUCKET'], filename)
            flash(f'File {filename} uploaded successfully!')
        except ClientError:
            flash('Error uploading file to S3')
        return redirect(url_for('upload_page'))
    
    flash('Invalid file type. Only PDF, JPG, JPEG, PNG allowed.')
    return redirect(url_for('upload_page'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001, ssl_context='adhoc')
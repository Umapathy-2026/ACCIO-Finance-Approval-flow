import os
import uuid
from flask import current_app
from werkzeug.utils import secure_filename


ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'xlsx', 'xls', 'doc', 'docx', 'eml', 'msg'}

ALLOWED_MIMES = {
    'application/pdf',
    'image/png',
    'image/jpeg',
    'image/gif',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-excel',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'message/rfc822',
    'application/vnd.ms-outlook',
}


def allowed_file(file):
    """Validate file extension and optionally MIME type. Returns (is_valid, error_msg)."""
    filename = secure_filename(file.filename)
    if '.' not in filename:
        return False, 'File must have an extension.'

    ext = filename.rsplit('.', 1).lower()[1]
    if ext not in ALLOWED_EXTENSIONS:
        return False, f'File type .{ext} is not allowed.'

    try:
        import magic
        header = file.read(2048)
        file.seek(0)
        mime = magic.from_buffer(header, mime=True)
        if mime not in ALLOWED_MIMES:
            return False, f'File content type {mime} is not permitted.'
    except ImportError:
        pass

    return True, None


def save_file(file):
    """Save an uploaded file to the local filesystem."""
    if file and file.filename:
        original_filename = secure_filename(file.filename)
        ext = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else ''
        unique_name = f"{uuid.uuid4().hex}_{original_filename}"
        upload_folder = current_app.config['UPLOAD_FOLDER']
        filepath = os.path.join(upload_folder, unique_name)
        file.save(filepath)
        return original_filename, unique_name
    return None, None


def get_file_path(filename):
    """Get the full path of a stored file."""
    return os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
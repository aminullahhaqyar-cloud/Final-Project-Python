"""
Library Management System
Flask + sqlite3 (no SQLAlchemy dependency)
"""

import sqlite3
import os
from datetime import datetime, date, timedelta
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask import (Flask, render_template, request, redirect,
                   url_for, flash, session, g)

# ─────────────────────────────────────────────
# App setup
# ─────────────────────────────────────────────

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.dirname(__file__), 'library.sqlite'))


# ─────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def query(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rv = cur.fetchall()
    return (rv[0] if rv else None) if one else rv


def execute(sql, args=()):
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    return cur.lastrowid


# sqlite3 type converters for date/datetime
sqlite3.register_adapter(date, lambda d: d.isoformat())
sqlite3.register_converter('DATE', lambda s: date.fromisoformat(s.decode()))
sqlite3.register_adapter(datetime, lambda dt: dt.isoformat(sep=' '))
sqlite3.register_converter('DATETIME', lambda s: datetime.fromisoformat(s.decode()))


# ─────────────────────────────────────────────
# Lightweight model wrappers
# ─────────────────────────────────────────────

class User:
    def __init__(self, row):
        self.id = row['id']
        self.name = row['name']
        self.email = row['email']
        self.password_hash = row['password_hash']
        self.role = row['role']
        self.is_active = bool(row['is_active'])
        self.created_at = row['created_at']

    @property
    def is_staff(self):
        return self.role in ('admin', 'librarian')

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @staticmethod
    def get(user_id):
        row = query('SELECT * FROM users WHERE id=?', (user_id,), one=True)
        return User(row) if row else None

    @staticmethod
    def get_by_email(email):
        row = query('SELECT * FROM users WHERE email=?', (email,), one=True)
        return User(row) if row else None


class Book:
    def __init__(self, row):
        self.id = row['id']
        self.title = row['title']
        self.author = row['author']
        self.language = row['language']
        self.publication_year = row['publication_year']
        self.isbn = row['isbn']
        self.genre = row['genre']
        self.description = row['description']
        self.available = bool(row['available'])
        self.added_at = row['added_at']

    @staticmethod
    def get(book_id):
        row = query('SELECT * FROM books WHERE id=?', (book_id,), one=True)
        return Book(row) if row else None

    @property
    def current_checkout(self):
        row = query('SELECT * FROM checkouts WHERE book_id=? AND returned=0', (self.id,), one=True)
        return Checkout(row) if row else None


class Checkout:
    def __init__(self, row):
        self.id = row['id']
        self.user_id = row['user_id']
        self.book_id = row['book_id']
        self.checked_out_at = row['checked_out_at']
        self.due_date = row['due_date']
        self.returned = bool(row['returned'])
        self.returned_at = row['returned_at']

    @property
    def is_overdue(self):
        if self.returned or not self.due_date:
            return False
        due = self.due_date if isinstance(self.due_date, date) else date.fromisoformat(str(self.due_date))
        return date.today() > due

    @property
    def user(self):
        return User.get(self.user_id)

    @property
    def book(self):
        return Book.get(self.book_id)


# ─────────────────────────────────────────────
# DB init
# ─────────────────────────────────────────────

def init_db():
    with app.app_context():
        db = get_db()
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    NOT NULL,
                email         TEXT    NOT NULL UNIQUE,
                password_hash TEXT    NOT NULL,
                role          TEXT    NOT NULL DEFAULT 'member',
                is_active     INTEGER NOT NULL DEFAULT 1,
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS books (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                title            TEXT NOT NULL,
                author           TEXT NOT NULL,
                language         TEXT NOT NULL,
                publication_year INTEGER,
                isbn             TEXT UNIQUE,
                genre            TEXT,
                description      TEXT,
                available        INTEGER NOT NULL DEFAULT 1,
                added_at         DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS checkouts (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id        INTEGER NOT NULL REFERENCES users(id),
                book_id        INTEGER NOT NULL REFERENCES books(id),
                checked_out_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                due_date       DATE,
                returned       INTEGER NOT NULL DEFAULT 0,
                returned_at    DATETIME
            );
        """)
        db.commit()
        seed_data(db)


def seed_data(db):
    if db.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0:
        db.execute(
            'INSERT INTO users (name, email, password_hash, role) VALUES (?,?,?,?)',
            ('Admin', 'admin@library.com', generate_password_hash('admin123'), 'admin')
        )

    if db.execute('SELECT COUNT(*) FROM books').fetchone()[0] == 0:
        books = [
            ('The Great Gatsby', 'F. Scott Fitzgerald', 'English', 1925, '9780743273565', 'Fiction',
             'A story of wealth, love, and the American Dream set in the 1920s.'),
            ('To Kill a Mockingbird', 'Harper Lee', 'English', 1960, '9780061935466', 'Fiction',
             'A lawyer defends a Black man accused of a crime in the American South.'),
            ('1984', 'George Orwell', 'English', 1949, '9780451524935', 'Dystopian',
             'A chilling vision of a totalitarian future society under constant surveillance.'),
            ('Don Quixote', 'Miguel de Cervantes', 'Spanish', 1605, '9780060934347', 'Classic',
             'The story of a man who believes himself to be a knight-errant.'),
            ('The Little Prince', 'Antoine de Saint-Exupéry', 'French', 1943, '9780156012195', 'Children',
             'A poetic tale of a young prince who visits various planets.'),
            ('Crime and Punishment', 'Fyodor Dostoevsky', 'Russian', 1866, '9780486415871', 'Classic',
             'A student commits a crime and wrestles with guilt and redemption.'),
        ]
        db.executemany(
            'INSERT INTO books (title,author,language,publication_year,isbn,genre,description) VALUES (?,?,?,?,?,?,?)',
            books
        )
    db.commit()


# ─────────────────────────────────────────────
# Auth helpers
# ─────────────────────────────────────────────

def current_user():
    if 'user_id' in session:
        return User.get(session['user_id'])
    return None


app.jinja_env.globals['current_user'] = current_user


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def staff_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in.', 'warning')
            return redirect(url_for('login'))
        user = current_user()
        if not user or not user.is_staff:
            flash('Staff access required.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in.', 'warning')
            return redirect(url_for('login'))
        user = current_user()
        if not user or user.role != 'admin':
            flash('Admin access required.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated


def get_book_or_404(book_id):
    book = Book.get(book_id)
    if not book:
        from flask import abort
        abort(404)
    return book


def get_checkout_or_404(checkout_id):
    row = query('SELECT * FROM checkouts WHERE id=?', (checkout_id,), one=True)
    if not row:
        from flask import abort
        abort(404)
    return Checkout(row)


def get_user_or_404(user_id):
    user = User.get(user_id)
    if not user:
        from flask import abort
        abort(404)
    return user


# ─────────────────────────────────────────────
# Routes — Public / Auth
# ─────────────────────────────────────────────

@app.route('/')
def index():
    recent = [Book(r) for r in query(
        'SELECT * FROM books ORDER BY added_at DESC LIMIT 6')]
    total_books = query('SELECT COUNT(*) FROM books', one=True)[0]
    available_books = query('SELECT COUNT(*) FROM books WHERE available=1', one=True)[0]
    total_members = query("SELECT COUNT(*) FROM users WHERE role='member' AND is_active=1", one=True)[0]
    return render_template('index.html', recent_books=recent,
                           total_books=total_books,
                           available_books=available_books,
                           total_members=total_members)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        if not all([name, email, password]):
            flash('All fields are required.', 'danger')
        elif password != confirm:
            flash('Passwords do not match.', 'danger')
        elif len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
        elif User.get_by_email(email):
            flash('Email already registered.', 'danger')
        else:
            execute('INSERT INTO users (name,email,password_hash,role) VALUES (?,?,?,?)',
                    (name, email, generate_password_hash(password), 'member'))
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.get_by_email(email)

        if user and user.check_password(password) and user.is_active:
            session['user_id'] = user.id
            flash(f'Welcome back, {user.name}!', 'success')
            return redirect(url_for('index'))
        flash('Invalid email or password.', 'danger')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))


# ─────────────────────────────────────────────
# Routes — Books
# ─────────────────────────────────────────────

@app.route('/books')
def books():
    q = request.args.get('q', '').strip()
    language = request.args.get('language', '').strip()
    available_only = request.args.get('available_only') == 'on'

    sql = 'SELECT * FROM books WHERE 1=1'
    args = []
    if q:
        like = f'%{q}%'
        sql += ' AND (title LIKE ? OR author LIKE ? OR genre LIKE ? OR isbn LIKE ?)'
        args += [like, like, like, like]
    if language:
        sql += ' AND language=?'
        args.append(language)
    if available_only:
        sql += ' AND available=1'
    sql += ' ORDER BY title'

    all_books = [Book(r) for r in query(sql, args)]
    languages = [r[0] for r in query('SELECT DISTINCT language FROM books ORDER BY language')]

    return render_template('books.html', books=all_books, query=q,
                           language=language, available_only=available_only,
                           languages=languages)


@app.route('/books/<int:book_id>')
def book_detail(book_id):
    book = get_book_or_404(book_id)
    history = [Checkout(r) for r in query(
        'SELECT * FROM checkouts WHERE book_id=? ORDER BY checked_out_at DESC', (book_id,))]
    today = date.today().isoformat()
    return render_template('book_detail.html', book=book, history=history, today=today)


@app.route('/books/add', methods=['GET', 'POST'])
@staff_required
def add_book():
    if request.method == 'POST':
        isbn = request.form.get('isbn', '').strip() or None
        if isbn and query('SELECT id FROM books WHERE isbn=?', (isbn,), one=True):
            flash('A book with this ISBN already exists.', 'danger')
            return render_template('book_form.html', action='Add', book=None)

        title = request.form.get('title', '').strip()
        author = request.form.get('author', '').strip()
        language = request.form.get('language', '').strip()
        year = request.form.get('publication_year') or None
        genre = request.form.get('genre', '').strip() or None
        description = request.form.get('description', '').strip() or None

        if not all([title, author, language]):
            flash('Title, author and language are required.', 'danger')
            return render_template('book_form.html', action='Add', book=None)

        book_id = execute(
            'INSERT INTO books (title,author,language,publication_year,isbn,genre,description) VALUES (?,?,?,?,?,?,?)',
            (title, author, language, year, isbn, genre, description)
        )
        flash(f'"{title}" added successfully.', 'success')
        return redirect(url_for('book_detail', book_id=book_id))

    return render_template('book_form.html', action='Add', book=None)


@app.route('/books/<int:book_id>/edit', methods=['GET', 'POST'])
@staff_required
def edit_book(book_id):
    book = get_book_or_404(book_id)

    if request.method == 'POST':
        isbn = request.form.get('isbn', '').strip() or None
        existing = query('SELECT id FROM books WHERE isbn=? AND id!=?', (isbn, book_id), one=True) if isbn else None
        if existing:
            flash('Another book already uses this ISBN.', 'danger')
            return render_template('book_form.html', action='Edit', book=book)

        execute(
            '''UPDATE books SET title=?,author=?,language=?,publication_year=?,
               isbn=?,genre=?,description=? WHERE id=?''',
            (request.form.get('title', '').strip(),
             request.form.get('author', '').strip(),
             request.form.get('language', '').strip(),
             request.form.get('publication_year') or None,
             isbn,
             request.form.get('genre', '').strip() or None,
             request.form.get('description', '').strip() or None,
             book_id)
        )
        flash('Book updated successfully.', 'success')
        return redirect(url_for('book_detail', book_id=book_id))

    return render_template('book_form.html', action='Edit', book=book)


@app.route('/books/<int:book_id>/delete', methods=['POST'])
@admin_required
def delete_book(book_id):
    book = get_book_or_404(book_id)
    if not book.available:
        flash('Cannot delete a checked-out book.', 'danger')
        return redirect(url_for('book_detail', book_id=book_id))
    execute('DELETE FROM books WHERE id=?', (book_id,))
    flash('Book deleted.', 'info')
    return redirect(url_for('books'))


# ─────────────────────────────────────────────
# Routes — Checkouts
# ─────────────────────────────────────────────

@app.route('/books/<int:book_id>/checkout', methods=['POST'])
@login_required
def checkout_book(book_id):
    book = get_book_or_404(book_id)
    user = current_user()

    if not book.available:
        flash('This book is not available.', 'danger')
        return redirect(url_for('book_detail', book_id=book_id))

    target_user_id = request.form.get('user_id')
    if target_user_id and user.is_staff:
        target_uid = int(target_user_id)
    else:
        target_uid = user.id

    due_date_str = request.form.get('due_date')
    due_date = due_date_str if due_date_str else (date.today() + timedelta(days=14)).isoformat()

    execute(
        'INSERT INTO checkouts (user_id,book_id,due_date) VALUES (?,?,?)',
        (target_uid, book_id, due_date)
    )
    execute('UPDATE books SET available=0 WHERE id=?', (book_id,))
    flash(f'"{book.title}" checked out successfully.', 'success')
    return redirect(url_for('book_detail', book_id=book_id))


@app.route('/checkouts/<int:checkout_id>/return', methods=['POST'])
@login_required
def return_book(checkout_id):
    co = get_checkout_or_404(checkout_id)
    user = current_user()

    if not user.is_staff and co.user_id != user.id:
        flash('Not authorized.', 'danger')
        return redirect(url_for('index'))

    now = datetime.now().isoformat(sep=' ')
    execute('UPDATE checkouts SET returned=1, returned_at=? WHERE id=?', (now, checkout_id))
    execute('UPDATE books SET available=1 WHERE id=?', (co.book_id,))
    book = Book.get(co.book_id)
    flash(f'"{book.title}" returned successfully.', 'success')
    return redirect(url_for('book_detail', book_id=co.book_id))


@app.route('/history')
@login_required
def checkout_history():
    user = current_user()
    if user.is_staff:
        rows = query('SELECT * FROM checkouts ORDER BY checked_out_at DESC')
    else:
        rows = query('SELECT * FROM checkouts WHERE user_id=? ORDER BY checked_out_at DESC', (user.id,))
    checkouts = [Checkout(r) for r in rows]
    return render_template('history.html', checkouts=checkouts)


# ─────────────────────────────────────────────
# Routes — Users
# ─────────────────────────────────────────────

@app.route('/users')
@staff_required
def users():
    all_users = [User(r) for r in query('SELECT * FROM users ORDER BY name')]
    return render_template('users.html', users=all_users)


@app.route('/users/<int:user_id>')
@staff_required
def user_detail(user_id):
    member = get_user_or_404(user_id)
    checkouts = [Checkout(r) for r in query(
        'SELECT * FROM checkouts WHERE user_id=? ORDER BY checked_out_at DESC', (user_id,))]
    return render_template('user_detail.html', member=member, checkouts=checkouts)


@app.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_user(user_id):
    member = get_user_or_404(user_id)

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        role = request.form.get('role', 'member')
        is_active = 1 if request.form.get('is_active') == 'on' else 0
        new_password = request.form.get('new_password', '')

        if new_password:
            execute('UPDATE users SET name=?,email=?,role=?,is_active=?,password_hash=? WHERE id=?',
                    (name, email, role, is_active, generate_password_hash(new_password), user_id))
        else:
            execute('UPDATE users SET name=?,email=?,role=?,is_active=? WHERE id=?',
                    (name, email, role, is_active, user_id))
        flash('User updated.', 'success')
        return redirect(url_for('user_detail', user_id=user_id))

    return render_template('user_form.html', member=member)


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user = current_user()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        new_password = request.form.get('new_password', '')
        if new_password:
            if len(new_password) < 6:
                flash('Password must be at least 6 characters.', 'danger')
                checkouts = [Checkout(r) for r in query(
                    'SELECT * FROM checkouts WHERE user_id=? ORDER BY checked_out_at DESC', (user.id,))]
                return render_template('profile.html', user=user, checkouts=checkouts)
            execute('UPDATE users SET name=?,password_hash=? WHERE id=?',
                    (name, generate_password_hash(new_password), user.id))
        else:
            execute('UPDATE users SET name=? WHERE id=?', (name, user.id))
        flash('Profile updated.', 'success')
        return redirect(url_for('profile'))

    checkouts = [Checkout(r) for r in query(
        'SELECT * FROM checkouts WHERE user_id=? ORDER BY checked_out_at DESC', (user.id,))]
    # Refresh user object after possible name change
    user = current_user()
    return render_template('profile.html', user=user, checkouts=checkouts)


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    app.run(debug=True)

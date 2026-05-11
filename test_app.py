"""
Tests for the Library Management System (sqlite3 version).
Run with:  python3 test_app.py
Or with pytest if available:  python -m pytest test_app.py -v
"""

import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

# ── Bootstrap ──────────────────────────────────────────────────────────────────
# Point the app at a temp DB so tests never touch the real one.
_db_fd, _db_path = tempfile.mkstemp(suffix='.sqlite')
os.environ['DB_PATH'] = _db_path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import app, init_db, query, execute, User, Book, Checkout
from werkzeug.security import generate_password_hash


# ── Helpers ────────────────────────────────────────────────────────────────────

def login(client, email, password):
    return client.post('/login',
                       data={'email': email, 'password': password},
                       follow_redirects=True)


def logout(client):
    return client.get('/logout', follow_redirects=True)


# ── Base test case ─────────────────────────────────────────────────────────────

class BaseTestCase(unittest.TestCase):

    def setUp(self):
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret'
        # Wipe and recreate schema before every test
        with app.test_request_context():
            db = app.extensions  # not used; just ensure context
        from app import get_db
        with app.app_context():
            conn = __import__('sqlite3').connect(_db_path)
            conn.executescript("""
                DROP TABLE IF EXISTS checkouts;
                DROP TABLE IF EXISTS books;
                DROP TABLE IF EXISTS users;
            """)
            conn.commit()
            conn.close()
        init_db()
        self.client = app.test_client()

    # ── Seed helpers ──────────────────────────────────────────────────────────

    def _make_admin(self):
        with app.test_request_context():
            execute('INSERT INTO users (name,email,password_hash,role) VALUES (?,?,?,?)',
                    ('Admin', 'admin@test.com', generate_password_hash('password123'), 'admin'))
            return query('SELECT id FROM users WHERE email=?', ('admin@test.com',), one=True)[0]

    def _make_member(self, name='Alice', email='alice@test.com'):
        with app.test_request_context():
            execute('INSERT INTO users (name,email,password_hash,role) VALUES (?,?,?,?)',
                    (name, email, generate_password_hash('password123'), 'member'))
            return query('SELECT id FROM users WHERE email=?', (email,), one=True)[0]

    def _make_book(self):
        with app.test_request_context():
            bid = execute(
                'INSERT INTO books (title,author,language,publication_year,isbn) VALUES (?,?,?,?,?)',
                ('Test Book', 'Test Author', 'English', 2020, '1234567890')
            )
            return bid


# ── Auth tests ─────────────────────────────────────────────────────────────────

class TestAuthentication(BaseTestCase):

    def test_register_new_user(self):
        r = self.client.post('/register', data={
            'name': 'Bob', 'email': 'bob@test.com',
            'password': 'pass123', 'confirm_password': 'pass123'
        }, follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'log in', r.data.lower())
        with app.test_request_context():
            u = User.get_by_email('bob@test.com')
        self.assertIsNotNone(u)
        self.assertEqual(u.name, 'Bob')
        self.assertEqual(u.role, 'member')

    def test_register_duplicate_email(self):
        self._make_member()
        r = self.client.post('/register', data={
            'name': 'Alice 2', 'email': 'alice@test.com',
            'password': 'pass123', 'confirm_password': 'pass123'
        }, follow_redirects=True)
        self.assertIn(b'already registered', r.data.lower())

    def test_register_password_mismatch(self):
        r = self.client.post('/register', data={
            'name': 'Bob', 'email': 'bob@test.com',
            'password': 'pass123', 'confirm_password': 'different'
        }, follow_redirects=True)
        self.assertIn(b'do not match', r.data.lower())

    def test_login_valid(self):
        self._make_member()
        r = login(self.client, 'alice@test.com', 'password123')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Welcome back', r.data)

    def test_login_invalid_password(self):
        self._make_member()
        r = login(self.client, 'alice@test.com', 'wrongpassword')
        self.assertIn(b'Invalid email or password', r.data)

    def test_login_nonexistent_user(self):
        r = login(self.client, 'nobody@test.com', 'pass')
        self.assertIn(b'Invalid', r.data)

    def test_logout(self):
        self._make_member()
        login(self.client, 'alice@test.com', 'password123')
        r = logout(self.client)
        self.assertEqual(r.status_code, 200)


# ── Book tests ─────────────────────────────────────────────────────────────────

class TestBooks(BaseTestCase):

    def test_books_page_loads(self):
        r = self.client.get('/books')
        self.assertEqual(r.status_code, 200)

    def test_book_search(self):
        self._make_book()
        r = self.client.get('/books?q=Test+Book')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Test Book', r.data)

    def test_book_search_no_results(self):
        r = self.client.get('/books?q=zzznomatch')
        self.assertIn(b'0 books found', r.data)

    def test_add_book_requires_staff(self):
        self._make_member()
        login(self.client, 'alice@test.com', 'password123')
        r = self.client.get('/books/add', follow_redirects=True)
        self.assertIn(b'Staff access required', r.data)

    def test_admin_can_add_book(self):
        self._make_admin()
        login(self.client, 'admin@test.com', 'password123')
        r = self.client.post('/books/add', data={
            'title': 'New Book', 'author': 'New Author',
            'language': 'English', 'publication_year': '2024',
            'isbn': '9999999999', 'genre': 'Fiction', 'description': ''
        }, follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        with app.test_request_context():
            row = query('SELECT * FROM books WHERE isbn=?', ('9999999999',), one=True)
        self.assertIsNotNone(row)
        self.assertEqual(row['title'], 'New Book')

    def test_book_detail_page(self):
        bid = self._make_book()
        r = self.client.get(f'/books/{bid}')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Test Book', r.data)

    def test_edit_book_admin(self):
        self._make_admin()
        bid = self._make_book()
        login(self.client, 'admin@test.com', 'password123')
        r = self.client.post(f'/books/{bid}/edit', data={
            'title': 'Updated Title', 'author': 'Test Author',
            'language': 'English', 'publication_year': '2020',
            'isbn': '1234567890', 'genre': 'Fiction', 'description': ''
        }, follow_redirects=True)
        self.assertIn(b'Updated Title', r.data)

    def test_delete_book_admin(self):
        self._make_admin()
        bid = self._make_book()
        login(self.client, 'admin@test.com', 'password123')
        r = self.client.post(f'/books/{bid}/delete', follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        with app.test_request_context():
            row = query('SELECT * FROM books WHERE id=?', (bid,), one=True)
        self.assertIsNone(row)

    def test_delete_book_member_forbidden(self):
        self._make_member()
        bid = self._make_book()
        login(self.client, 'alice@test.com', 'password123')
        r = self.client.post(f'/books/{bid}/delete', follow_redirects=True)
        self.assertIn(b'Admin access required', r.data)


# ── Checkout tests ─────────────────────────────────────────────────────────────

class TestCheckouts(BaseTestCase):

    def test_checkout_book(self):
        self._make_member()
        bid = self._make_book()
        login(self.client, 'alice@test.com', 'password123')
        due = (date.today() + timedelta(days=14)).isoformat()
        r = self.client.post(f'/books/{bid}/checkout',
                             data={'due_date': due}, follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        with app.test_request_context():
            book = query('SELECT available FROM books WHERE id=?', (bid,), one=True)
        self.assertEqual(book['available'], 0)

    def test_checkout_unavailable_book(self):
        self._make_member()
        bid = self._make_book()
        login(self.client, 'alice@test.com', 'password123')
        due = (date.today() + timedelta(days=14)).isoformat()
        self.client.post(f'/books/{bid}/checkout', data={'due_date': due}, follow_redirects=True)
        r = self.client.post(f'/books/{bid}/checkout', data={'due_date': due}, follow_redirects=True)
        self.assertIn(b'not available', r.data.lower())

    def test_return_book(self):
        self._make_member()
        bid = self._make_book()
        login(self.client, 'alice@test.com', 'password123')
        due = (date.today() + timedelta(days=14)).isoformat()
        self.client.post(f'/books/{bid}/checkout', data={'due_date': due}, follow_redirects=True)

        with app.test_request_context():
            co_row = query('SELECT id FROM checkouts WHERE book_id=?', (bid,), one=True)
            co_id = co_row[0]

        r = self.client.post(f'/checkouts/{co_id}/return', follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        with app.test_request_context():
            co = query('SELECT returned FROM checkouts WHERE id=?', (co_id,), one=True)
            book = query('SELECT available FROM books WHERE id=?', (bid,), one=True)
        self.assertEqual(co['returned'], 1)
        self.assertEqual(book['available'], 1)

    def test_history_visible_to_logged_in_user(self):
        self._make_member()
        login(self.client, 'alice@test.com', 'password123')
        r = self.client.get('/history')
        self.assertEqual(r.status_code, 200)

    def test_history_requires_login(self):
        r = self.client.get('/history', follow_redirects=True)
        self.assertIn(b'log in', r.data.lower())


# ── User management tests ──────────────────────────────────────────────────────

class TestUserManagement(BaseTestCase):

    def test_users_list_staff_only(self):
        self._make_member()
        login(self.client, 'alice@test.com', 'password123')
        r = self.client.get('/users', follow_redirects=True)
        self.assertIn(b'Staff access required', r.data)

    def test_users_list_visible_to_admin(self):
        self._make_admin()
        login(self.client, 'admin@test.com', 'password123')
        r = self.client.get('/users')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Admin', r.data)

    def test_profile_update(self):
        self._make_member()
        login(self.client, 'alice@test.com', 'password123')
        r = self.client.post('/profile',
                             data={'name': 'Alice Updated', 'new_password': ''},
                             follow_redirects=True)
        self.assertIn(b'Profile updated', r.data)


# ── Model / logic unit tests ───────────────────────────────────────────────────

class TestModels(BaseTestCase):

    def test_user_password_hashing(self):
        with app.test_request_context():
            uid = execute(
                'INSERT INTO users (name,email,password_hash,role) VALUES (?,?,?,?)',
                ('Test', 't@t.com', generate_password_hash('secret'), 'member')
            )
            u = User.get(uid)
        self.assertTrue(u.check_password('secret'))
        self.assertFalse(u.check_password('wrong'))

    def test_checkout_is_overdue(self):
        self._make_member()
        bid = self._make_book()
        with app.test_request_context():
            uid = query('SELECT id FROM users WHERE email=?', ('alice@test.com',), one=True)[0]
            past = (date.today() - timedelta(days=1)).isoformat()
            co_id = execute(
                'INSERT INTO checkouts (user_id,book_id,due_date,returned) VALUES (?,?,?,0)',
                (uid, bid, past)
            )
            row = query('SELECT * FROM checkouts WHERE id=?', (co_id,), one=True)
            co = Checkout(row)
        self.assertTrue(co.is_overdue)

    def test_checkout_not_overdue_if_returned(self):
        self._make_member()
        bid = self._make_book()
        with app.test_request_context():
            uid = query('SELECT id FROM users WHERE email=?', ('alice@test.com',), one=True)[0]
            past = (date.today() - timedelta(days=1)).isoformat()
            co_id = execute(
                'INSERT INTO checkouts (user_id,book_id,due_date,returned) VALUES (?,?,?,1)',
                (uid, bid, past)
            )
            row = query('SELECT * FROM checkouts WHERE id=?', (co_id,), one=True)
            co = Checkout(row)
        self.assertFalse(co.is_overdue)

    def test_user_is_staff(self):
        with app.test_request_context():
            for name, email, role in [('A','a@a.com','admin'),('L','l@l.com','librarian'),('M','m@m.com','member')]:
                execute('INSERT INTO users (name,email,password_hash,role) VALUES (?,?,?,?)',
                        (name, email, generate_password_hash('x'), role))
            admin = User.get_by_email('a@a.com')
            librarian = User.get_by_email('l@l.com')
            member = User.get_by_email('m@m.com')
        self.assertTrue(admin.is_staff)
        self.assertTrue(librarian.is_staff)
        self.assertFalse(member.is_staff)


# ── Run ────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    unittest.main(verbosity=2)

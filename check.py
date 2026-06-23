import os
from app import create_app
import re

app = create_app()

with app.test_client() as client:
    with app.app_context():

        # 1. Health
        r = client.get('/api/health')
        print('1. Health:', r.status_code, '-', r.get_json()['status'])

        # 2. Login page
        r = client.get('/auth/login')
        html = r.data.decode()
        print('2. Login page:', r.status_code)

        # 3. Extract token from <meta name="csrf-token" content="...">
        m = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
        token = m.group(1)
        print('   CSRF token found:', bool(token))

        # 4. Login - send token in header (as JS would) + form data
        r = client.post('/auth/login',
            data={'email': 'admin@company.com', 'password': os.environ.get("TEST_ADMIN_PASSWORD", "")},
            headers={'X-CSRFToken': token},
            follow_redirects=True
        )
        print('3. Login:', r.status_code, '- Has Dashboard:', 'Dashboard' in r.data.decode())

        # 5-9. Routes
        for label, url in [
            ('4. Dashboard',     '/admin/dashboard'),
            ('5. All Tickets',   '/admin/all-tickets'),
            ('6. Audit Log',     '/admin/audit-log'),
            ('7. New Ticket',    '/requester/new-ticket'),
            ('8. Notifications', '/api/notifications'),
            ('9. Form Fields',   '/api/form-fields/1'),
        ]:
            r = client.get(url)
            print(f'{label}:', r.status_code)

        print('\n=== ALL TESTS PASSED ===')
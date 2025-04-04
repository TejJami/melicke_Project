# Bookkeeping App

This is a Django-based project for managing bookkeeping, properties, tenants, leases, income, and expense profiles. The project is integrated with TailwindCSS and daisyUI for frontend styling.

## Overview
This project enables users to manage:
- Real estate properties
- Tenants and landlords
- Leases for units within properties
- Income and expense profiles
- Bank transactions through PDF uploads and parsing

## Key Technologies
- **Backend**: Django 4.x
- **Frontend**: TailwindCSS, daisyUI
- **Database**: PostgreSQL
- **PDF Parsing**: PyPDF2, pdfplumber, PyMuPDF
- **JavaScript**: Custom logic and dashboard interactions

## Prerequisites
- Python 3.8+
- Node.js 14+
- npm (Node Package Manager)
- PostgreSQL
- virtualenv (optional but recommended)

---

## Project Setup

### 1. Clone the Repository
```bash
git clone https://github.com/username/repository-name.git
cd repository-name
```

### 2. Create and Activate Virtual Environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows use `venv\Scripts\activate`
```

### 3. Install Python Requirements
```bash
pip install -r requirements.txt
```

### 4. Set Up Environment Variables
Create a `.env` file in the root directory with the following template:

```env
DJANGO_SECRET_KEY=your-secret-key
DJANGO_DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost
DB_NAME=your-db-name
DB_USER=your-db-user
DB_PASSWORD=your-db-password
DB_HOST=localhost
DB_PORT=5432
```

### 5. Apply Migrations and Create Superuser
```bash
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
```

### 6. Install JavaScript Dependencies
```bash
cd jstoolchains
npm install
```

---

## Running the Project

### 1. Start the Django Development Server
```bash
python manage.py runserver
```
- Open http://127.0.0.1:8000 in your browser to access the application.

### 2. Run TailwindCSS in Watch Mode
In a separate terminal, run the following to compile TailwindCSS:
```bash
cd jstoolchains
npm run tailwind-watch
```
- This command watches for changes in CSS and recompiles automatically.

---

## Testing
Run unit tests to ensure models and views are working as expected:
```bash
python manage.py test bookkeeping
```

---

## Uploading Bank Statements (PDF Parsing)
1. Navigate to the **Dashboard** section.
2. Upload the bank statement PDF by clicking "Upload Bank Statement".
3. Parsed transactions will appear under **Earmarked Transactions**.

---

## Common Management Commands
- **Apply Migrations**:
  ```bash
  python manage.py migrate
  ```
- **Create Migration**:
  ```bash
  python manage.py makemigrations
  ```
- **Run Tests**:
  ```bash
  python manage.py test
  ```
- **Collect Static Files**:
  ```bash
  python manage.py collectstatic
  ```

---

## Structure Overview
```
repository-name/
├── README.md
├── manage.py
├── requirements.txt
├── blogProject/
│   ├── settings.py
│   └── urls.py
├── bookkeeping/
│   ├── models.py
│   ├── views.py
│   ├── templates/
│   ├── static/
│   └── signals.py
├── jstoolchains/
│   ├── package.json
│   └── tailwind.config.js
└── media/
    └── property_images/
```

- **bookkeeping/**: Core application for managing properties, tenants, and leases.
- **static/**: JavaScript and CSS files, including Tailwind output.
- **templates/**: HTML templates for frontend rendering.
- **media/**: Property images uploaded by users.
- **jstoolchains/**: TailwindCSS and npm configuration.

---

## Notes
- Ensure PostgreSQL is running before starting the Django server.
- Always activate the virtual environment before running any management commands.
- Run migrations regularly to keep the database schema updated.

---

## Troubleshooting
- **Django Not Found Error**:
  ```bash
  source venv/bin/activate  # or venv\Scripts\activate on Windows
  ```
- **Static Files Not Loading**:
  ```bash
  python manage.py collectstatic
  ```
- **Database Connection Issues**:
  - Verify `.env` database credentials.
  - Ensure PostgreSQL service is running.

---



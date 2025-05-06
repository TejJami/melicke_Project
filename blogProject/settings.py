from pathlib import Path
import os
from dotenv import load_dotenv
import django_heroku
import os
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Static files settings for Whitenoise
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

load_dotenv()  # Load environment variables from .env

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DJANGO_DEBUG')

ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '').split(',')


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_browser_reload',
    'bookkeeping',
    'django.contrib.humanize',  # Enables intcomma filter
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # Required for serving static files on Heroku
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]


ROOT_URLCONF = 'blogProject.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'blogProject.wsgi.application'


# Database
# https://docs.djangoproject.com/en/4.0/ref/settings/#databases

import dj_database_url

# DATABASES = {
#     'default': dj_database_url.config(default=os.environ.get('DATABASE_URL'))
# }

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME'),
        'USER': os.getenv('DB_USER'),
        'PASSWORD': os.getenv('DB_PASSWORD'),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '5432'),
    }
}


# Password validation
# https://docs.djangoproject.com/en/4.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/4.0/topics/i18n/

LANGUAGE_CODE = 'de'
USE_L10N = True
USE_THOUSAND_SEPARATOR = True

TIME_ZONE = 'UTC'



USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.0/howto/static-files/

STATIC_URL = '/static/'


# Default primary key field type
# https://docs.djangoproject.com/en/4.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'


# Redirects after login/logout
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'  
LOGIN_URL = '/login/'

django_heroku.settings(locals(), test_runner=False)


COMMERZBANK_CLIENT_ID=os.getenv('COMMERZBANK_CLIENT_ID')
COMMERZBANK_CLIENT_SECRET= os.getenv('COMMERZBANK_CLIENT_SECRET')
COMMERZBANK_API_BASE=os.getenv('COMMERZBANK_API_BASE')

ONEDRIVE_CLIENT_ID = os.getenv('ONEDRIVE_CLIENT_ID')
ONEDRIVE_CLIENT_SECRET = os.getenv('ONEDRIVE_CLIENT_SECRET')
ONEDRIVE_REDIRECT_URI = os.getenv('ONEDRIVE_REDIRECT_URI')
ONEDRIVE_SCOPES = ['offline_access', 'Files.ReadWrite.All', 'User.Read']

import os
import base64

# Load Base64-encoded certificate from environment variable
COMMERZBANK_CERT_BASE64 = os.getenv("COMMERZBANK_CERT", "")

# Decode and write certificate to a temporary file if available
if COMMERZBANK_CERT_BASE64:
    cert_path = "/tmp/commerzbank_cert.pem"  # Temporary file for Heroku
    with open(cert_path, "wb") as cert_file:
        cert_file.write(base64.b64decode(COMMERZBANK_CERT_BASE64))
else:
    cert_path = None  # No certificate available

# Store certificate path in settings
COMMERZBANK_CERT_PATH = cert_path

COMMERZBANK_REDIRECT_URI = "https://bookkeeping-mei-02eece815857.herokuapp.com/commerzbank/callback/"
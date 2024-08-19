"""
Django settings specific for glamr test site on alpena
"""
from os import environ
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from mibios.glamr.settings import *


# Set to True for development but never in production deployment
DEBUG = False

# Yes, show internal stuff
INTERNAL_DEPLOYMENT = True

# Set this to False when running the runserver command on localhost
SECURE_SSL_REDIRECT = False

# Add additional apps here:
INSTALLED_APPS.append('django_extensions')  # noqa:F405

# User switch magic: needs the remote user injection middleware and set
# ASSUME_IDENTIY = ('alice', 'bob') so when user bob logs in through the web
# server the middleware will make it look as if alice is authenticated.  In
# development, e.g. when using the shell or runserver commands let
# ASSUME_IDENTITY = ('', 'bob') assume bob's identity.
#
#MIDDLEWARE = ['mibios.ops.utils.RemoteUserInjection'] + MIDDLEWARE
#ASSUME_IDENTITY = ('', 'heinro')

# List of contacts for site adminitrators
ADMINS = [("Robert", "heinro@umich.edu")]

# For production, set STATIC_ROOT to the directory containing static files,
# relative to your instance's base directory
STATIC_ROOT = 'static'

KRONA_CACHE_DIR = 'krona-cache/'

# URL for static files
STATIC_URL = '/glamr/static/'

# Direcorty relative to the base where download files get stored
MEDIA_ROOT = 'media/'

# URL path for downloads
MEDIA_URL = '/glamr/media/'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'glamr',
        'USER': 'glamr_django',
        'HOST': 'database',
        'PORT': '5432',
    },
}

# Allowed host settings:
ALLOWED_HOSTS.append('127.0.0.1')  # noqa:F405
ALLOWED_HOSTS.append('webapp')  # noqa:F405
ALLOWED_HOSTS.append('vondamm.earth.lsa.umich.edu')  # noqa:F405

# Uncomment this do disable caching, for testing/debugging only
# CACHES['default']['BACKEND'] = 'django.core.cache.backends.dummy.DummyCache'
CACHES['default'] = {  # noqa:F405
    'BACKEND': 'django.core.cache.backends.memcached.PyMemcacheCache',
    'LOCATION': '127.0.0.1:11211',
    'OPTIONS': {
        'default_noreply': True,
    },
}

SITE_NAME = 'GLAMR'
SITE_NAME_VERBOSE = 'GLAMR DB testing'

SCHEMA_PLOT_APPS = ['mibios_omics']

STATICFILES_DIRS = ['static_var']
FORCE_SCRIPT_NAME = '/glamr'

LOGGING['loggers']['django.template'] = {'handlers': ['null'], 'propagate': False, }

GLOBUS_DIRECT_URL_BASE = 'https://g-61d4a3.a1bfb5.bd7c.data.globus.org'
GLOBUS_FILE_APP_URL_BASE = 'https://app.globus.org/file-manager?origin_id=d16258fe-0228-449f-a70c-ae92e52b1464&origin_path=%2F'  # noqa:E501

# env override
if environ.get('DJANGO_ENABLE_TEST_VIEWS') == 'true':
    ENABLE_TEST_VIEWS = True
if environ.get('DJANGO_DEBUG') == 'true':
    DEBUG = True

try:
    PUBLIC_DATA_ROOT = Path(environ['DJANGO_PUBLIC_DATA_ROOT'])
except KeyError as e:
    raise ImproperlyConfigured(str(e)) from e

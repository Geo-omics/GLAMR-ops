"""
Django settings specific for glarm test site on alpena
"""
from os import environ
from mibios.glamr.settings import *


# Set to True for development but never in production deployment
DEBUG = False

# Set this to False when running the runserver command on localhost
SECURE_SSL_REDIRECT = False

# Add additional apps here:
INSTALLED_APPS.append('django_extensions')

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

# storing krona files on the static volume, must be created/maintained manually
KRONA_CACHE_DIR = 'static/krona-cache/'

# URL for static files
STATIC_URL = '/static/'

# Direcorty relative to the base where download files get stored
MEDIA_ROOT = 'media/'

# URL path for downloads
MEDIA_URL = '/media/'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': environ.get('GLAMR_DB_NAME', 'glamr-public'),
        'USER': 'glamr_django',
        'HOST': 'database.gdick-web-app.svc.cluster.local',
        'PORT': '5432',
    },
}

# Allowed host settings:
ALLOWED_HOSTS.append('127.0.0.1')
ALLOWED_HOSTS.append('webapp')
ALLOWED_HOSTS.append('www-gdick-web-app.apps.gnosis.lsa.umich.edu')
ALLOWED_HOSTS.append('glamr.earth.lsa.umich.edu')
ALLOWED_HOSTS.append('greatlakesomics.org')

# Uncomment this do disable caching, for testing/debugging only
# CACHES['default']['BACKEND'] = 'django.core.cache.backends.dummy.DummyCache'
CACHES['default'] = {
    'BACKEND': 'django.core.cache.backends.memcached.PyMemcacheCache',
    'LOCATION': '127.0.0.1:11211',
    'OPTIONS': {
        'default_noreply': True,
    },
}

SITE_NAME = 'GLAMR'
SITE_NAME_VERBOSE = 'GLAMR DB'

SCHEMA_PLOT_APPS = ['mibios_omics']

STATICFILES_DIRS = ['static_var']
LOGGING['loggers']['django.template'] = {'handlers': ['null'], 'propagate': False, }

# env override
if environ.get('DJANGO_ENABLE_TEST_VIEWS') == 'true':
    ENABLE_TEST_VIEWS = True

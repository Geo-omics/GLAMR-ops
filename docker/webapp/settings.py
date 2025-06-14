"""
Django settings specific for glamr test site on alpena
"""
from os import environ

from mibios.glamr.settings import *  # noqa:F403


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
AUTHENTICATION_BACKENDS = ['django.contrib.auth.backends.ModelBackend']

# List of contacts for site adminitrators
ADMINS = [("Robert", "heinro@umich.edu")]

# For production, set STATIC_ROOT to the directory containing static files,
# relative to your instance's base directory
STATIC_ROOT = 'static'

# storing krona files on the static volume, may/should be created/maintained
# manually
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
ALLOWED_HOSTS.append('alpena.earth.lsa.umich.edu')  # noqa:F405
CSRF_TRUSTED_ORIGINS = ['https://alpena.earth.lsa.umich.edu']

# To make glamr.views.AddUserEmailView.get_email() get the our domain right:
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True
# And get proto right, too:
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Uncomment this do disable caching, for testing/debugging only
# CACHES['default']['BACKEND'] = 'django.core.cache.backends.dummy.DummyCache'
CACHES['default'] = {  # noqa:F405
    'BACKEND': 'django.core.cache.backends.memcached.PyMemcacheCache',
    'LOCATION': '127.0.0.1:11211',
    'OPTIONS': {
        'default_noreply': True,
    },
}
MIDDLEWARE.insert(0, 'django.middleware.cache.UpdateCacheMiddleware')  # noqa:F405,E501
MIDDLEWARE.append('django.middleware.cache.FetchFromCacheMiddleware')  # noqa:F405,E501

SITE_NAME = 'GLAMR'
SITE_NAME_VERBOSE = 'GLAMR DB testing'

SCHEMA_PLOT_APPS = ['mibios_omics']

STATICFILES_DIRS = ['static_var']
FORCE_SCRIPT_NAME = '/glamr'

LOGGING['handlers']['console']['formatter'] = 'verbose'  # noqa:F405

GLOBUS_DIRECT_URL_BASE = 'https://g-61d4a3.a1bfb5.bd7c.data.globus.org'
GLOBUS_FILE_APP_URL_BASE = 'https://app.globus.org/file-manager?origin_id=d16258fe-0228-449f-a70c-ae92e52b1464&origin_path=%2F'  # noqa:E501
HTTPD_FILESTORAGE_ROOT = '/storage-local'

# env override
if environ.get('DJANGO_ENABLE_TEST_VIEWS') == 'true':
    ENABLE_TEST_VIEWS = True
if environ.get('DJANGO_DEBUG') == 'true':
    DEBUG = True

# MIDDLEWARE = ['mibios.ops.utils.TraceMalloc'] + MIDDLEWARE

web: python manage.py migrate --noinput && python manage.py collectstatic --noinput && python manage.py sync_scheduled_jobs && gunicorn keel_site.wsgi --bind 0.0.0.0:$PORT --workers 2 --timeout 120

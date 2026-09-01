web: gunicorn app:app --bind 0.0.0.0:$PORT --workers ${WEB_CONCURRENCY:-1} --threads ${WEB_THREADS:-4} --timeout ${GUNICORN_TIMEOUT:-120} --graceful-timeout 30 --access-logfile - --error-logfile -

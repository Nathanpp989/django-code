.PHONY: run test migrate static certs nginx

run:
	ollama serve & python -m gunicorn --workers 3 newsite.wsgi:application

dev:
	ollama serve & python manage.py runserver

test:
	python manage.py test django_llm -v 2

pytest:
	pytest --cov=django_llm

migrate:
	python manage.py makemigrations && python manage.py migrate

static:
	python manage.py collectstatic --noinput

certs:
	chmod +x generate_certs.sh && ./generate_certs.sh

nginx:
	sudo cp nginx.conf /etc/nginx/sites-available/django_llm && sudo nginx -t && sudo service nginx restart

superuser:
	python manage.py createsuperuser

shell:
	python manage.py shell
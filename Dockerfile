FROM python:3.12-slim

# Evita archivos .pyc y buffering
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Directorio de trabajo
WORKDIR /Buzzy-project

# Copiamos requirements primero (mejor cache)
COPY requerimens.txt .

RUN pip install psycopg2-binary
RUN pip install --upgrade pip \
    && pip install -r requerimens.txt

# Copiamos el proyecto
COPY . .

RUN chmod +x entrypoint.sh


# Migraciones y superuser
# RUN python3 manage.py makemigrations --noinput
# RUN python3 manage.py migrate --noinput
# RUN python3 manage.py createsuperuser --noinput --username admin --email admin@example.com
# RUN python3 manage.py changepassword --noinput admin <<< 'reymanuel010899'

# Exponemos el puerto
EXPOSE 8000
ENTRYPOINT ["/Buzzy-project/entrypoint.sh"]
CMD ["python3", "manage.py", "runserver", "0.0.0.0:8000"]

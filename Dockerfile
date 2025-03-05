<<<<<<< HEAD
FROM python:3.12
 
RUN mkdir /Buzzy-project

COPY requerimens.txt ./Buzzy-project/

COPY . ./Buzzy-project/

WORKDIR ./Buzzy-project	

RUN python3 -m venv venv

RUN python -m pip install -r requirements.txt

RUN python3 manage.py runserver 0.0.0.0:8000

CMD ['python3', 'manage.py', 'runserver', '0.0.0.0:8000']
=======
FROM python3.10

ENV PYTHONUNBUFFERED 1

RUN mkdir /buzzy-backend

# COPY requerimens.txt ./buzzy-backend/

COPY . ./buzzy-backend/

RUN python3 -m venv venv

RUN pip install -r requerimens.txt

>>>>>>> f506f38 (cambios)

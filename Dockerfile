FROM python:3.12
 
RUN mkdir /Buzzy-project

COPY requerimens.txt ./Buzzy-project/

COPY . ./Buzzy-project/

WORKDIR ./Buzzy-project	

RUN python3 -m venv venv

RUN python -m pip install -r requirements.txt

RUN python3 manage.py runserver 0.0.0.0:8000

CMD ['python3', 'manage.py', 'runserver', '0.0.0.0:8000']

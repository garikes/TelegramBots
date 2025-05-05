FROM python:3.11
WORKDIR /tmp
ADD requirements.txt ./
RUN /usr/local/bin/python -m pip install --upgrade pip && pip install -r requirements.txt
ENV APP_HOME ./
WORKDIR $APP_HOME
COPY . $APP_HOME
RUN mkdir -p /app/logs
ENV NAME World
CMD ["python", "main.py"]

FROM python:3.7
WORKDIR /tmp

RUN mkdir /src

RUN apt-get update -y
RUN apt-get install curl -y

# pip
RUN curl --silent --location https://bootstrap.pypa.io/get-pip.py | python3 -

RUN adduser --disabled-password --gecos "" mitodl


# Install project packages
COPY requirements.txt /tmp/requirements.txt
COPY test_requirements.txt /tmp/test_requirements.txt
RUN pip install -r requirements.txt -r test_requirements.txt

USER mitodl

FROM centos:8
RUN yum install -y python3
RUN yum group install -y "Development Tools"
RUN git clone https://github.com/commanderka/frvt.git
RUN git clone https://github.com/commanderka/frvtMovieMaker.git
WORKDIR /frvtMovieMaker
RUN git pull
RUN pip3 install --upgrade pip
RUN yum install -y libglvnd-glx-1:1.2.0-6.el8.i686
RUN pip3 install -r requirements.txt
WORKDIR /frvt/1N/frvtPlainCWrapper
RUN mkdir build
WORKDIR /frvt/1N/frvtPlainCWrapper/build
RUN yum install -y cmake
RUN cmake ..
RUN make
ENV LD_LIBRARY_PATH=/frvt/1N/frvtPlainCWrapper/build
ENV PYTHONPATH=/frvt/1N/frvtPythonWrapper
WORKDIR /frvtMovieMaker

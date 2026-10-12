FROM python:3.10-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG TORCH_INDEX_URL=https://mirrors.aliyun.com/pytorch-wheels/cpu/
ARG TORCH_SPEC=torch==2.9.1+cpu

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir ${TORCH_SPEC} \
      --index-url ${TORCH_INDEX_URL} \
 && pip install --no-cache-dir -r requirements.txt \
      --index-url ${PIP_INDEX_URL} \
 && python -c "import torch; assert not torch.cuda.is_available(), torch.__version__"

COPY . ./backend/

EXPOSE 8897
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8897"]
